"""Duplicate-response guard (field 2026-10-15, founder's laptop logs).

velona/GLM returns finish_reason=tool_calls with an EMPTY tool_calls array
on nearly every reply, and weak models re-issue an identical read call
inside one turn. Two mechanisms glued 2-3 full answers into one bubble:

1. ai_node's dropped-toolcall re-prompt re-generated while attempt 1's
   text was already painted -> now the painted chars are retracted first
   (message.agent.retract -> token_retract frame -> panel truncates).
2. The identical list_files executed 3x per turn, each loop streaming a
   fresh answer variant -> repeated read-only calls are dropped at
   ai_node's return, the single chokepoint every call passes.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.graphs import chat_graph as cg


def _turn_with_executed(call_id="c1", name="list_files", args=None, result="a.py\nb.py"):
    args = {"path": "."} if args is None else args
    return [
        HumanMessage(content="list the files"),
        AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args, "type": "tool_call"}]),
        ToolMessage(content=result, tool_call_id=call_id, name=name),
    ]


def _result_with(name="list_files", args=None, call_id="c2"):
    args = {"path": "."} if args is None else args
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args, "type": "tool_call"}])


def test_identical_read_call_is_dropped():
    state = {"messages": _turn_with_executed()}
    out = cg._drop_repeated_read_calls(_result_with(), state)
    assert (out.tool_calls or []) == [], "the 3x list_files loop dies at ai_node"


def test_doom_ask_means_repeats_pass_through():
    """Field 2026-10-17: this guard silently ate three identical
    reads, so the doom_loop permission ask never fired. When the
    permission layer would ask/deny about the loop, repeats must
    survive to SafeToolNode's doom counter."""
    state = {"messages": _turn_with_executed(call_id="c1", name="read_file",
                                            args={"path": "notes.py"}, result="x=1")}
    result = _result_with(name="read_file", args={"path": "notes.py"})
    out = cg._drop_repeated_read_calls(result, state, doom_defers=True)
    assert len(out.tool_calls or []) == 1, "the repeat is the permission layer's business now"
    out = cg._drop_repeated_read_calls(result, state, doom_defers=False)
    assert (out.tool_calls or []) == [], "under doom_loop=allow the silent drop stands"


def test_read_after_intervening_write_is_kept():
    messages = _turn_with_executed()
    messages += [
        AIMessage(content="", tool_calls=[{"id": "c9", "name": "write_file", "args": {"path": "a.py"}, "type": "tool_call"}]),
        ToolMessage(content="ok", tool_call_id="c9", name="write_file"),
    ]
    out = cg._drop_repeated_read_calls(_result_with(), {"messages": messages})
    assert len(out.tool_calls or []) == 1, "a write in between makes the re-read legitimate"


def test_different_args_are_kept():
    state = {"messages": _turn_with_executed()}
    out = cg._drop_repeated_read_calls(_result_with(args={"path": "src"}), state)
    assert len(out.tool_calls or []) == 1


def test_mutating_repeat_is_never_dropped():
    state = {"messages": _turn_with_executed(call_id="c1", name="run_terminal", args={"command": "ls"}, result="ok")}
    out = cg._drop_repeated_read_calls(
        _result_with(name="run_terminal", args={"command": "ls"}), state)
    assert len(out.tool_calls or []) == 1, "shell retries after a fix are legitimate"


def test_repeat_from_a_previous_turn_is_kept():
    messages = _turn_with_executed() + [HumanMessage(content="list them again")]
    out = cg._drop_repeated_read_calls(_result_with(), {"messages": messages})
    assert len(out.tool_calls or []) == 1, "a NEW user turn may re-list"


def test_retract_emits_exact_char_count(monkeypatch):
    seen = []
    monkeypatch.setattr(cg.event_bus, "emit", lambda kind, payload: seen.append((kind, payload)))
    cg._TURN_LAST_CALL_TEXT["t1"] = 42
    cg._retract_streamed_answer("t1")
    assert seen == [("message.agent.retract", {"chars": 42, "thread_id": "t1"})]
    cg._retract_streamed_answer("t1")  # already withdrawn -> silent
    assert len(seen) == 1


def test_bridge_projects_retract_frames(tmp_path):
    from src.bridge.__main__ import BridgeServer, TurnIdentity

    identity = TurnIdentity.create(session_id="s1", workspace=str(tmp_path))
    frame = BridgeServer._project_event(
        {"type": "message.agent.retract", "event_id": "e9", "payload": {"chars": 17}},
        identity,
    )
    assert frame["type"] == "token_retract" and frame["chars"] == 17
    stored = BridgeServer._project_stored_event(
        {"type": "message.agent.retract", "payload": {"chars": 5}}
    )
    assert stored["type"] == "token_retract" and stored["chars"] == 5


def _capture_bus(monkeypatch):
    seen = []
    monkeypatch.setattr(
        cg.event_bus, "emit", lambda kind, payload: seen.append((kind, payload)))
    return seen


def test_held_answer_paints_once_on_release(monkeypatch):
    """The greeting case (field 2026-10-15): a short tools-bound answer is
    held, then released whole -- it never spawns-and-vanishes."""
    seen = _capture_bus(monkeypatch)
    pump = cg._AgentTokenPump("t-hold", hold_text=True)
    pump._emit_text("Hi! How can I help you today?")
    assert seen == [], "nothing paints while the attempt's fate is undecided"
    assert pump.painted_chars == 0
    pump.release_held()
    assert seen == [("message.agent.chunk",
                     {"chunk": "Hi! How can I help you today?", "thread_id": "t-hold"})]
    assert pump.painted_chars == len("Hi! How can I help you today?")


def test_discarded_attempt_never_paints(monkeypatch):
    seen = _capture_bus(monkeypatch)
    pump = cg._AgentTokenPump("t-discard", hold_text=True)
    pump._emit_text("Hello! How can I help you today?")
    pump.discard_held()
    assert seen == [], "a re-prompted attempt leaves no trace on screen"


def test_long_answer_breaks_the_hold_and_streams(monkeypatch):
    seen = _capture_bus(monkeypatch)
    pump = cg._AgentTokenPump("t-live", hold_text=True)
    pump._emit_text("x" * 200)
    assert seen and pump.painted_chars == 200, "past the cap the answer streams live"


def test_discard_retracts_only_what_was_painted(monkeypatch):
    seen = _capture_bus(monkeypatch)
    pump = cg._AgentTokenPump("t-mix", hold_text=True)
    pump._emit_text("y" * 200)          # went live (over cap)
    pump._emit_text("held-tail")        # live now too (post-release)
    cg._TURN_PUMPS["t-mix"] = pump
    cg._TURN_LAST_CALL_TEXT["t-mix"] = pump.painted_chars
    seen.clear()
    cg._discard_held_answer("t-mix")
    assert seen == [("message.agent.retract",
                     {"chars": 209, "thread_id": "t-mix"})]


def test_reprompt_only_for_genuinely_dropped_calls():
    """velona/GLM mislabels text answers finish_reason=tool_calls; a
    delivered answer must NOT re-prompt (double billing per step), while
    an empty dropped call still must."""
    dropped = AIMessage(content="", response_metadata={"finish_reason": "tool_calls"})
    assert cg._should_reprompt_dropped_toolcall(dropped, tools_bound=True, retries=0)
    answered = AIMessage(
        content="Hi! How can I help you today?",
        response_metadata={"finish_reason": "tool_calls"},
    )
    assert not cg._should_reprompt_dropped_toolcall(answered, tools_bound=True, retries=0)
    assert not cg._should_reprompt_dropped_toolcall(dropped, tools_bound=False, retries=0)
    assert not cg._should_reprompt_dropped_toolcall(dropped, tools_bound=True, retries=3)
    with_calls = AIMessage(
        content="",
        tool_calls=[{"id": "x", "name": "list_files", "args": {}, "type": "tool_call"}],
        response_metadata={"finish_reason": "tool_calls"},
    )
    assert not cg._should_reprompt_dropped_toolcall(with_calls, tools_bound=True, retries=0)

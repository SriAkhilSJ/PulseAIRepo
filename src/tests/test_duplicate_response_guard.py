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

"""D40 inclusive provider-call budget and tool-free final response.

The last configured call is reserved for text so a bound of N never requires
an N+1 farewell request. Legacy already-exhausted checkpoints retain one
compatibility grace call; both paths disable tools and then finalize.
"""

from langchain_core.messages import AIMessage, SystemMessage

import src.graphs.chat_graph as cg
from src.graphs import budget as bg  # P0-D: budget funcs moved to their own module
from src.context.token_tracker import TokenUsage


def test_iteration_budget_default_clamps_and_tolerates_garbage(monkeypatch):
    monkeypatch.delenv("AGENT_ITERATION_BUDGET", raising=False)
    assert bg._iteration_budget() == bg._ITERATION_BUDGET_DEFAULT

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "5")
    assert bg._iteration_budget() == 5

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "999")
    assert bg._iteration_budget() == bg._ITERATION_BUDGET_CLAMP, "must clamp"

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "abc")
    assert bg._iteration_budget() == bg._ITERATION_BUDGET_DEFAULT


def test_budget_exhausted_boundary(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "3")
    assert bg._budget_exhausted({"iteration_used": 2}) is False
    assert bg._budget_exhausted({"iteration_used": 3}) is True
    assert bg._budget_exhausted({}) is False


def test_final_response_reserve_is_the_last_inclusive_slot(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "3")
    assert bg._final_response_reserve_reached({"iteration_used": 1}) is False
    assert bg._final_response_reserve_reached({"iteration_used": 2}) is True
    assert bg._final_response_reserve_reached({"iteration_used": 3}) is False

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "1")
    assert bg._final_response_reserve_reached({"iteration_used": 0}) is True


def _message_state(last, **extra):
    state = {"messages": [SystemMessage(content="SYS"), last]}
    state.update(extra)
    return state


def test_should_continue_finalizes_when_exhausted(monkeypatch):
    """Hermes loop law (agent/iteration_budget.py + turn_iteration_prep.py:108
    'the budget-crossing request completes first'): a pending BOUND tool call
    executes even at the cap — field 2026-09-08 dropped the model's
    start_terminal (the dev server the whole task was for) and finalized.
    The budget still concludes the run: the NEXT call is the unbound grace
    call (see the text-only finalize pins in test_budget_crossing_dispatch)."""
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "1")
    last = AIMessage(content="", tool_calls=[{"id": "c1", "name": "read_file", "args": {}}])
    state = _message_state(last, iteration_used=1)
    assert cg.should_continue(state) == "tools"


def test_should_continue_still_routes_tools_when_under_budget(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "10")
    last = AIMessage(content="", tool_calls=[{"id": "c1", "name": "read_file", "args": {}}])
    state = _message_state(last, iteration_used=3)
    assert cg.should_continue(state) == "tools"


class _FakeLLM:
    def __init__(self, reply="ok", model="m"):
        self.reply = reply
        self.model = model
        self.bound = None
        self.sent_messages = None

    def bind_tools(self, tools):
        b = _FakeLLM(reply=self.reply, model=self.model)
        self.bound = b
        return b

    def invoke(self, messages, **kwargs):
        self.sent_messages = messages
        return AIMessage(content=self.reply, id="r1")


class _FakeEngine:
    def build_ai_messages(self, state, system_message):
        return [SystemMessage(content="PERSONA"), SystemMessage(content="LAYER")]


def _patch_env(monkeypatch, budget):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", str(budget))
    llm = _FakeLLM(reply="final text")
    monkeypatch.setattr(cg, "get_llm", lambda provider, model, reasoning_config=None, **kw: llm)
    monkeypatch.setattr(cg, "get_context_engine", lambda config: _FakeEngine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))
    return llm


def _config():
    return {"configurable": {"thread_id": "t", "provider": "groq", "model": "m"}}


def test_ai_node_grace_call_when_exhausted(monkeypatch):
    llm = _patch_env(monkeypatch, budget=1)
    state = {
        "iteration_used": 1,     # already at budget -> exhausted on entry
        "current_task": "fix bug",
        "messages": [],
    }
    out = cg.ai_node(state, _config())
    # bind was prepared, but the UNBOUND proxy must have served the call —
    # the model was never offered tools on the grace path.
    assert llm.bound is not None, "bind_tools still prepared a bound client"
    assert llm.sent_messages is not None, "unbound proxy served the grace call"
    assert llm.bound.sent_messages is None, "bound client must NOT have been invoked"
    # Hermes shape (handle_max_iterations :2119): the summary request rides
    # as a USER message appended to the history — the system stays one fused
    # block, and the model can SEE its work.
    assert any("PERSONA" in str(m.content) for m in llm.sent_messages), "persona survives the fuse"
    summary_requests = [
        m for m in llm.sent_messages
        if m.type == "human" and "maximum number of tool-calling iterations" in str(m.content)
    ]
    assert summary_requests, "hermes' user-role summary request must ride the grace call"
    assert len([m for m in llm.sent_messages if m.type == "system"]) == 1, "one system block out the door"
    assert out["iteration_used"] == 2
    assert out["grace_done"] == 1
    assert "token_usage" in out


def test_ai_node_reserves_last_slot_for_tool_free_final_response(monkeypatch):
    llm = _patch_env(monkeypatch, budget=3)
    state = {
        "iteration_used": 2,
        "current_task": "fix bug",
        "messages": [],
    }
    out = cg.ai_node(state, _config())

    assert llm.sent_messages is not None, "unbound model must serve the final slot"
    assert llm.bound.sent_messages is None, "tools must be disabled in the final slot"
    assert str(llm.sent_messages[-1].content) == bg._FINAL_RESPONSE_RESERVE_REQUEST
    assert out["iteration_used"] == 3
    assert out["grace_done"] == 1
    assert out["wrap_summary"] == 0, "missing evidence remains a budget cut"


def test_ai_node_marks_evidence_ready_final_slot_as_clean_wrap(monkeypatch):
    llm = _patch_env(monkeypatch, budget=3)
    monkeypatch.setattr(cg, "_completion_evidence_ready", lambda state: True)
    events = []
    monkeypatch.setattr(cg.event_bus, "emit", lambda kind, payload: events.append((kind, payload)))

    out = cg.ai_node(
        {"iteration_used": 2, "current_task": "fix bug", "messages": []},
        _config(),
    )

    assert llm.sent_messages is not None
    assert out["wrap_summary"] == 1
    assert out["grace_done"] == 1
    status = [payload for kind, payload in events if kind == "context.status"]
    assert status and status[-1]["phase"] == "final_response_reserve"
    assert status[-1]["completion_evidence_ready"] is True


def test_ai_node_normal_path_binds_tools_and_increments(monkeypatch):
    llm = _patch_env(monkeypatch, budget=10)
    state = {
        "iteration_used": 0,
        "current_task": "fix bug",
        "messages": [],
    }
    out = cg.ai_node(state, _config())
    assert llm.bound is not None, "normal path binds tools"
    assert llm.bound.sent_messages is not None, "bound client served the call"
    assert llm.sent_messages is None, "unbound proxy unused on the normal path"
    assert not any("iteration budget" in m.content for m in llm.bound.sent_messages)
    assert out["iteration_used"] == 1
    assert out["grace_done"] == 0


def _patch_env_tool_reply(monkeypatch, budget, tool_names):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", str(budget))
    llm = _FakeToolLLM(tool_names)
    monkeypatch.setattr(cg, "get_llm", lambda provider, model, reasoning_config=None, **kw: llm)
    monkeypatch.setattr(cg, "get_context_engine", lambda config: _FakeEngine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))
    return llm


class _FakeToolLLM:
    """Fake LLM whose reply carries tool calls (exercises the refund)."""

    def __init__(self, tool_names):
        self.tool_names = tool_names
        self.model = "m"
        self.bound = None
        self.sent_messages = None

    def bind_tools(self, tools):
        b = _FakeToolLLM(self.tool_names)
        self.bound = b
        return b

    def invoke(self, messages, **kwargs):
        self.sent_messages = messages
        return AIMessage(content="", id="r1", tool_calls=[
            {"id": f"c{i}", "name": name, "args": {}}
            for i, name in enumerate(self.tool_names)
        ])


def test_ai_node_counts_execute_code_only_turn(monkeypatch):
    """Test5-6 regression: PTC is efficient only when it batches work; each
    provider request still counts toward Crusor's bounded paid turn. A mechanical
    Hermes refund let repeated os.walk scripts evade forced delivery."""
    _patch_env_tool_reply(monkeypatch, budget=10, tool_names=["execute_code"])
    state = {"iteration_used": 3, "current_task": "fix bug", "messages": []}
    out = cg.ai_node(state, _config())
    assert out["iteration_used"] == 4


def test_ai_node_no_refund_for_mixed_turns(monkeypatch):
    """Mixed execute_code/direct-tool turns also consume an iteration."""
    _patch_env_tool_reply(
        monkeypatch, budget=10, tool_names=["execute_code", "copy_file"])
    state = {"iteration_used": 3, "current_task": "fix bug", "messages": []}
    out = cg.ai_node(state, _config())
    assert out["iteration_used"] == 4, "mixed turn consumes an iteration"


def test_ai_node_no_refund_on_grace_path(monkeypatch):
    """The grace call may not refund — budget is flat-out spent there."""
    _patch_env_tool_reply(monkeypatch, budget=5, tool_names=["execute_code"])
    state = {"iteration_used": 5, "current_task": "fix bug", "messages": []}
    out = cg.ai_node(state, _config())
    assert out["iteration_used"] == 6, "grace call consumes, never refunds"
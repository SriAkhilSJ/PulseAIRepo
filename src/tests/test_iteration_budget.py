"""D40 agent iteration budget + grace call on exhaustion.

hermes conversation_loop.py:1558 / agent_init.py:902: the agent loop runs
while the iteration budget has remaining calls, then performs one final
grace call so the run concludes with text instead of being cut off. Here the
budget gates ai_node: once exhausted, tools are hidden and a no-tools grace
call produces the closing summary; should_continue then finalizes.
"""

from langchain_core.messages import AIMessage, SystemMessage

import src.graphs.chat_graph as cg
from src.context.token_tracker import TokenUsage


def test_iteration_budget_default_clamps_and_tolerates_garbage(monkeypatch):
    monkeypatch.delenv("AGENT_ITERATION_BUDGET", raising=False)
    assert cg._iteration_budget() == cg._ITERATION_BUDGET_DEFAULT

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "5")
    assert cg._iteration_budget() == 5

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "999")
    assert cg._iteration_budget() == cg._ITERATION_BUDGET_CLAMP, "must clamp"

    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "abc")
    assert cg._iteration_budget() == cg._ITERATION_BUDGET_DEFAULT


def test_budget_exhausted_boundary(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "3")
    assert cg._budget_exhausted({"iteration_used": 2}) is False
    assert cg._budget_exhausted({"iteration_used": 3}) is True
    assert cg._budget_exhausted({}) is False


def _message_state(last, **extra):
    state = {"messages": [SystemMessage(content="SYS"), last]}
    state.update(extra)
    return state


def test_should_continue_finalizes_when_exhausted(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "1")
    last = AIMessage(content="", tool_calls=[{"id": "c1", "name": "read_file", "args": {}}])
    state = _message_state(last, iteration_used=1)
    assert cg.should_continue(state) == "finalize"


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
    monkeypatch.setattr(cg, "get_llm", lambda provider, model: llm)
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
    assert "PERSONA" in [m.content for m in llm.sent_messages]
    assert any("iteration budget" in m.content for m in llm.sent_messages), "grace nudge"
    assert out["iteration_used"] == 2
    assert out["grace_done"] == 1
    assert "token_usage" in out


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
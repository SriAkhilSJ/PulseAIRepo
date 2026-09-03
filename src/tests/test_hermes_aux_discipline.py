"""Hermes auxiliary discipline for the task classifier + terminal output knob.

Owner constraint: we are TESTING PERFORMANCE, not hardcoding behavior -- no
message-text shortcuts. The hermes answer (auxiliary_client.py, issue
#54465): management calls run on their OWN budget -- owned retries (never
the SDK's hidden 3x) and wall-clock deadlines -- and the resolved aux route
is observable. Pinned here:
  - get_llm's optional per-call attempt/timeout budget (None = untouched).
  - the classifier's env budget (attempts/timeout) and per-call route
    resolution (env -> cheap table -> main fallback -- hermes' ladder).
  - a dead ROUTE can never kill the MISSION ('continue' fallback), while
    Stop still cancels.
  - run_terminal's output cap (hermes' _get_max_read_chars config-knob
    pattern: default + env override, read per call).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# get_llm: the per-call budget plumbing
# ---------------------------------------------------------------------------

def test_get_llm_budget_overrides_reach_groq(monkeypatch):
    import src.llm.factory as factory

    monkeypatch.setattr(factory, "GROQ_API_KEY", "test-key")
    llm = factory.get_llm("groq", "m", max_attempts=1, request_timeout=10)
    assert llm._max_attempts == 1
    assert llm._llm.request_timeout == 10

    plain = factory.get_llm("groq", "m")
    assert plain._max_attempts == 5  # historical default untouched


def test_get_llm_custom_branch_honors_budget(monkeypatch):
    import src.llm.factory as factory

    monkeypatch.setattr(factory, "CUSTOM_API_KEY", "k")
    monkeypatch.setattr(factory, "CUSTOM_BASE_URL", "http://localhost:9/v1")
    monkeypatch.delenv("PULSEAI_LLM_STREAMING", raising=False)
    monkeypatch.delenv("PULSEAI_LLM_TIMEOUT", raising=False)
    llm = factory.get_llm("custom", "m", max_attempts=2, request_timeout=8)
    assert llm._max_attempts == 2
    assert llm._llm.request_timeout == 8


# ---------------------------------------------------------------------------
# the classifier lane: budget + route + never-die
# ---------------------------------------------------------------------------

@pytest.fixture()
def _custom_route(monkeypatch):
    """A buildable custom aux route so constructor errors don't mask the
    budget assertions."""
    monkeypatch.setenv("AUX_LLM_PROVIDER", "custom")
    monkeypatch.setattr("src.llm.factory.CUSTOM_API_KEY", "test-key")
    monkeypatch.setattr("src.llm.factory.CUSTOM_BASE_URL", "http://localhost:9/v1")
    monkeypatch.delenv("PULSEAI_LLM_STREAMING", raising=False)
    monkeypatch.delenv("PULSEAI_LLM_TIMEOUT", raising=False)


def test_classifier_budget_is_env_driven(monkeypatch, _custom_route):
    """Fresh resolution per call: defaults 1x10s, env moves both."""
    import src.graphs.chat_graph as chat_graph

    monkeypatch.delenv("AUX_LLM_MODEL", raising=False)
    monkeypatch.delenv("PULSEAI_CLASSIFIER_ATTEMPTS", raising=False)
    monkeypatch.delenv("PULSEAI_CLASSIFIER_TIMEOUT_S", raising=False)

    proxy = chat_graph._task_manager_llm("custom", "auto/best-chat")
    assert proxy._max_attempts == 1
    assert proxy._llm.request_timeout == 10.0

    monkeypatch.setenv("PULSEAI_CLASSIFIER_ATTEMPTS", "2")
    monkeypatch.setenv("PULSEAI_CLASSIFIER_TIMEOUT_S", "25")
    proxy = chat_graph._task_manager_llm("custom", "auto/best-chat")
    assert proxy._max_attempts == 2
    assert proxy._llm.request_timeout == 25.0

    monkeypatch.setenv("PULSEAI_CLASSIFIER_ATTEMPTS", "99")
    monkeypatch.setenv("PULSEAI_CLASSIFIER_TIMEOUT_S", "1")
    proxy = chat_graph._task_manager_llm("custom", "auto/best-chat")
    assert proxy._max_attempts == 5  # clamped to hi
    assert proxy._llm.request_timeout == 2.0  # clamped to lo


def test_classifier_route_resolves_fresh_per_call(monkeypatch, _custom_route):
    """AUX_LLM_MODEL set -> the cheap route; unset on custom -> main-model
    fallback (hermes' documented ladder). The get_llm call must receive the
    resolved model, read per call, not captured at import."""
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setenv("LLM_PROVIDER", "custom")

    monkeypatch.setenv("AUX_LLM_MODEL", "llama-3.1-8b-instant")
    proxy = chat_graph._task_manager_llm("custom", "auto/best-chat")
    assert proxy._llm.model_name == "llama-3.1-8b-instant"

    monkeypatch.delenv("AUX_LLM_MODEL", raising=False)
    # unset env + unknown provider -> the documented MAIN-MODEL fallback
    # ("identical behavior, the safe degradation"). Whatever LLM_MODEL
    # resolves to in this environment IS the contract.
    from src.config import settings as settings_mod

    proxy = chat_graph._task_manager_llm("custom", "auto/best-chat")
    assert proxy._llm.model_name == settings_mod.LLM_MODEL


def test_route_budget_logged_once(capsys, monkeypatch, _custom_route):
    import src.graphs.chat_graph as chat_graph

    monkeypatch.setenv("AUX_LLM_MODEL", "fast-mini")
    chat_graph._CLASSIFIER_ROUTE_LOGGED.clear()
    chat_graph._task_manager_llm("custom", "auto/best-chat")
    out1 = capsys.readouterr().out
    chat_graph._task_manager_llm("custom", "auto/best-chat")
    out2 = capsys.readouterr().out
    assert "[task_classifier] route" in out1
    assert "(source: env)" in out1
    assert "budget 1 attempt(s) x 10s" in out1
    assert "[task_classifier] route" not in out2  # once per process


def test_transport_death_defaults_to_continue(capsys):
    """Budget exhausted / endpoint dead on the ROUTER -> the MISSION lives."""
    from langchain_core.messages import AIMessage, HumanMessage

    import src.graphs.chat_graph as chat_graph

    class DeadRoute:
        def invoke(self, messages):
            raise RuntimeError("endpoint gone after budget")

    decision = chat_graph._invoke_task_decision(DeadRoute(), [])
    assert decision.action == "continue"
    assert "[task_classifier] route unavailable" in capsys.readouterr().out


def test_cancellation_still_propagates():
    from langchain_core.messages import HumanMessage

    import src.graphs.chat_graph as chat_graph
    from src.llm.factory import TurnCancelledError

    class Stopped:
        def invoke(self, messages):
            raise TurnCancelledError("Stop pressed")

    with pytest.raises(TurnCancelledError):
        chat_graph._invoke_task_decision(Stopped(), [])


def test_node_end_to_end_with_dead_route(monkeypatch):
    """Full node: the router's death produces a usable state dict."""
    from langchain_core.messages import HumanMessage

    import src.graphs.chat_graph as chat_graph

    monkeypatch.setenv("AUX_LLM_MODEL", "fast-mini")

    def _dead(provider, model):
        class Dead:
            def invoke(self, messages):
                raise RuntimeError("budget gone")

        return Dead()

    monkeypatch.setattr(chat_graph, "_task_manager_llm", _dead)
    state = {
        "messages": [HumanMessage("also fix the flaky login test")],
        "latest_instruction": "also fix the flaky login test",
        "current_task": "build a chat app",
        "token_usage": {},
    }
    out = chat_graph.task_manager_node(dict(state), {"configurable": {"thread_id": "t", "workspace": "."}})
    assert out["current_task"] == "build a chat app"


# ---------------------------------------------------------------------------
# run_terminal output knob (hermes _get_max_read_chars pattern)
# ---------------------------------------------------------------------------

def test_run_terminal_caps_monstrous_output(tmp_path):
    import sys

    from src.tools.terminal_tools import run_terminal

    command = (
        "for /l %i in (1,1,200000) do @echo line-%i"
        if sys.platform == "win32" else "seq 1 200000"
    )
    result = run_terminal.invoke(
        {"command": command},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert len(result) < 40_000, f"output not capped: {len(result)} chars"
    assert "Terminal output truncated" in result
    assert "Total characters" in result


def test_output_cap_is_env_driven(tmp_path, monkeypatch):
    import sys

    from src.tools.terminal_tools import run_terminal

    monkeypatch.setenv("PULSEAI_TERMINAL_MAX_OUTPUT_CHARS", "5000")
    command = (
        "for /l %i in (1,1,100000) do @echo line-%i"
        if sys.platform == "win32" else "seq 1 100000"
    )
    result = run_terminal.invoke(
        {"command": command},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert len(result) < 12_000, f"env cap not honored: {len(result)} chars"


def test_small_output_passes_untouched(tmp_path):
    from src.tools.terminal_tools import run_terminal

    result = run_terminal.invoke(
        {"command": "echo hello-from-terminal"},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert "hello-from-terminal" in result
    assert "Terminal output truncated" not in result

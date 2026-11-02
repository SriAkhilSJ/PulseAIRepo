"""Provider-free continuous execution and real SQLite checkpoint boundaries."""
from __future__ import annotations

import sqlite3
from typing import TypedDict

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from src.graphs import budget
from src.graphs.continuous_execution import stream_checkpointed_segments


@pytest.fixture(autouse=True)
def continuous(monkeypatch):
    monkeypatch.setenv("AGENT_CONTINUOUS_EXECUTION", "1")
    for name in ("AGENT_ITERATION_BUDGET", "AGENT_TOKEN_BUDGET", "AGENT_COST_BUDGET"):
        monkeypatch.delenv(name, raising=False)


def test_default_mode_and_explicit_limits(monkeypatch):
    state = {"iteration_used": 1000, "turn_token_usage": {"total_tokens": 2_500_000, "estimated_cost_usd": 2}}
    assert budget._iteration_budget() is None
    assert budget._token_budget() is None
    assert budget._cost_budget() is None
    assert not budget._budget_exhausted(state)
    assert not budget._final_response_reserve_reached(state)
    assert budget._budget_warning_threshold() is None
    assert not budget._verification_reserve_reached(state)
    assert "iterations 1000/uncapped" in budget._budget_trip_reason(state)
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "100")
    assert budget._iteration_budget() == 100
    assert budget._final_response_reserve_reached({"iteration_used": 99})
    assert budget._budget_exhausted(state)
    monkeypatch.delenv("AGENT_ITERATION_BUDGET")
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "1000")
    assert budget._token_budget() == 1000
    assert budget._budget_exhausted(state)
    monkeypatch.delenv("AGENT_TOKEN_BUDGET")
    monkeypatch.setenv("AGENT_COST_BUDGET", "1")
    assert budget._budget_exhausted(state)
    monkeypatch.delenv("AGENT_CONTINUOUS_EXECUTION")
    monkeypatch.delenv("AGENT_COST_BUDGET")
    assert budget._iteration_budget() == 45
    assert budget._token_budget() == 600_000
    assert budget._cost_budget() == 1


class State(TypedDict, total=False):
    intent: str
    calls: int
    pending: int
    receipts: list[int]
    verified: bool
    cancelled: bool
    approvals: str


def make_graph(db, effects, cancelled):
    graph = StateGraph(State)

    def model(state):
        assert state["intent"] == "build and verify"
        assert state["approvals"] == "ask"
        return {"calls": state["calls"] + 1, "pending": state["calls"] + 1}

    def tool(state):
        # Model the same fail-closed admission that the production tool node
        # enforces before running a side effect.
        if cancelled[0]:
            return {"cancelled": True}
        effects.append(state["pending"])
        return {"receipts": state["receipts"] + [state["pending"]]}

    def after_tool(state):
        if state.get("cancelled"):
            return END
        return "verify" if state["calls"] == 75 else "model"

    def verify(state):
        return {"verified": state["receipts"] == list(range(1, 76))}

    graph.add_node("model", model)
    graph.add_node("tool", tool)
    graph.add_node("verify", verify)
    graph.add_edge(START, "model")
    graph.add_edge("model", "tool")
    graph.add_conditional_edges("tool", after_tool)
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=SqliteSaver(db))


def test_75_productive_calls_across_sqlite_boundaries(tmp_path):
    effects = []
    with sqlite3.connect(tmp_path / "checkpoints.sqlite", check_same_thread=False) as db:
        graph = make_graph(db, effects, [False])
        config = {"configurable": {"thread_id": "turn"}, "recursion_limit": 5}
        segments = []
        events = list(stream_checkpointed_segments(
            graph, {"intent": "build and verify", "calls": 0, "receipts": [], "approvals": "ask"},
            config=config, stream_mode="updates", on_segment=segments.append,
        ))
        state = graph.get_state(config)
        assert len(segments) > 1
        assert state.next == ()
        assert state.values["calls"] == 75
        assert state.values["verified"] is True
        assert state.values["approvals"] == "ask"
        assert effects == list(range(1, 76))
        assert len([e for e in events if "tool" in e]) == 75
        assert len([e for e in events if "model" in e]) == 75


def test_cancel_at_boundary_does_not_admit_later_tool(tmp_path):
    effects = []
    stopped = [False]
    with sqlite3.connect(tmp_path / "cancel.sqlite", check_same_thread=False) as db:
        graph = make_graph(db, effects, stopped)
        config = {"configurable": {"thread_id": "turn"}, "recursion_limit": 3}
        def cancel(_):
            stopped[0] = True
        list(stream_checkpointed_segments(graph,
             {"intent": "build and verify", "calls": 0, "receipts": [], "approvals": "ask"},
             config=config, stream_mode="updates", on_segment=cancel))
        state = graph.get_state(config).values
        assert state["cancelled"] is True
        assert not state.get("verified", False)
        assert len(effects) <= 1


def test_resume_fails_closed_on_nonadvancing_or_missing_checkpoint(monkeypatch):
    import src.graphs.continuous_execution as ce
    monkeypatch.setattr(ce, "_is_framework_boundary", lambda exc: True)
    class Snapshot:
        next = ("tool",)
        metadata = {"step": 2}
    class BadGraph:
        def stream(self, *args, **kwargs):
            raise GraphRecursionError("Recursion limit of 2 reached")
            yield
        def get_state(self, config):
            return Snapshot()
    with pytest.raises(GraphRecursionError):
        list(stream_checkpointed_segments(BadGraph(), {}, config={}, stream_mode="updates"))
    Snapshot.next = ()
    with pytest.raises(GraphRecursionError):
        list(stream_checkpointed_segments(BadGraph(), {}, config={}, stream_mode="updates"))


def test_node_recursion_error_is_not_retried():
    class BadGraph:
        def get_state(self, config):
            return None
        def stream(self, *args, **kwargs):
            raise GraphRecursionError("Recursion limit of 2 reached (raised by a tool)")
            yield
    with pytest.raises(GraphRecursionError, match="raised by a tool"):
        list(stream_checkpointed_segments(BadGraph(), {}, config={}, stream_mode="updates"))


def test_bridge_token_budget_continuous_respects_explicit_values():
    from types import SimpleNamespace
    from scripts.run_bridge_turn import resolve_token_budget
    args = SimpleNamespace(max_input_tokens=None)
    assert resolve_token_budget(args, {"AGENT_CONTINUOUS_EXECUTION": "1"}) == (0, "continuous default (uncapped)")
    assert resolve_token_budget(args, {"AGENT_CONTINUOUS_EXECUTION": "1", "AGENT_TOKEN_BUDGET": "12000"}) == (12000, "AGENT_TOKEN_BUDGET")
    args.max_input_tokens = 30000
    assert resolve_token_budget(args, {"AGENT_CONTINUOUS_EXECUTION": "1", "AGENT_TOKEN_BUDGET": "12000"}) == (30000, "--max-input-tokens")


def test_real_ai_node_keeps_tools_at_iteration_75(monkeypatch):
    from langchain_core.messages import AIMessage, SystemMessage
    import src.graphs.chat_graph as cg
    from src.graphs.gates import should_continue

    class LLM:
        model = "m"
        def __init__(self):
            self.bound = False
            self.messages = []
        def bind_tools(self, tools):
            self.bound = True
            return self
        def invoke(self, messages, **kwargs):
            self.messages = messages
            return AIMessage(content="", id="r75", tool_calls=[
                {"name": "run_terminal", "args": {"command": "pytest"}, "id": "c75"}
            ])
    class Engine:
        def build_ai_messages(self, state, system_message):
            return [SystemMessage(content="PERSONA")]
    llm = LLM()
    monkeypatch.setattr(cg, "get_llm", lambda **kwargs: llm)
    monkeypatch.setattr(cg, "get_context_engine", lambda config: Engine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))
    state = {"iteration_used": 75, "current_task": "fix bug", "messages": []}
    out = cg.ai_node(state, {"configurable": {"thread_id": "continuous-test", "provider": "groq", "model": "m"}})
    assert llm.bound
    assert out["iteration_used"] == 76
    assert "ITERATION BUDGET CHECKPOINT" not in " ".join(str(m.content) for m in llm.messages)
    assert should_continue({**state, **out}) == "tools"


def test_long_driver_preserves_explicit_iteration_limit(monkeypatch):
    from scripts.run_long_session import _build_parser, build_env
    parser = _build_parser()
    base = ["--workspace", "w", "--prompts-file", "p", "--continuous"]
    monkeypatch.delenv("AGENT_ITERATION_BUDGET", raising=False)
    env = build_env(parser.parse_args(base))
    assert env["AGENT_CONTINUOUS_EXECUTION"] == "1"
    assert "AGENT_ITERATION_BUDGET" not in env
    env = build_env(parser.parse_args(base + ["--agent-iteration-budget", "90"]))
    assert env["AGENT_ITERATION_BUDGET"] == "90"
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "80")
    assert build_env(parser.parse_args(base))["AGENT_ITERATION_BUDGET"] == "80"


def test_explicit_cost_limit_uses_cost_summary(monkeypatch):
    from langchain_core.messages import AIMessage, SystemMessage
    import src.graphs.chat_graph as cg
    class LLM:
        model = "m"
        def __init__(self):
            self.messages = []
        def bind_tools(self, tools):
            return self
        def invoke(self, messages, **kwargs):
            self.messages = messages
            return AIMessage(content="incomplete")
    class Engine:
        def build_ai_messages(self, state, system_message):
            return [SystemMessage(content="PERSONA")]
    llm = LLM()
    monkeypatch.setenv("AGENT_COST_BUDGET", "1")
    monkeypatch.setattr(cg, "get_llm", lambda **kwargs: llm)
    monkeypatch.setattr(cg, "get_context_engine", lambda config: Engine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))
    out = cg.ai_node({"iteration_used": 75, "turn_token_usage": {"estimated_cost_usd": 2},
                "current_task": "fix bug", "messages": []},
               {"configurable": {"thread_id": "continuous-test", "provider": "groq", "model": "m"}})
    text = str(out["messages"][0].content)
    assert "tripped: cost" in text
    assert "incomplete" in text
    assert not llm.messages  # no additional paid grace call
    assert out["grace_done"] == 1


def test_continuous_usage_telemetry_never_invents_known_cost(monkeypatch):
    import src.graphs.chat_graph as cg
    events = []
    monkeypatch.setattr(cg.event_bus, "emit", lambda name, data: events.append((name, data)))
    cg._emit_continuous_usage({"token_usage": {
        "prompt_tokens": 200, "completion_tokens": 20, "calls_made": 2,
        "estimated_cost_usd": 0.12, "cost_known": True,
    }}, "session")
    assert events[-1][0] == "analytics.update"
    assert events[-1][1]["totalCost"] == 0.12
    assert events[-1][1]["apiCalls"] == 2
    cg._emit_continuous_usage({"token_usage": {"cost_known": False}}, "session")
    assert events[-1][1]["totalCost"] is None
    assert events[-1][1]["costKnown"] is False


def test_explicit_cost_cap_fails_closed_for_unknown_pricing(monkeypatch):
    monkeypatch.setenv("AGENT_COST_BUDGET", "0.25")
    state = {"iteration_used": 2, "turn_token_usage": {"cost_known": False}}
    assert budget._budget_exhausted(state)
    assert "tripped: cost unknown" in budget._budget_trip_reason(state)


def test_bridge_cli_continuous_echo_round_trip(tmp_path, monkeypatch):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("hello")
    ws = tmp_path / "ws"
    ws.mkdir()
    env = dict(os.environ, CRUSORAI_BRIDGE_RUNNER="echo")
    for key in ("AGENT_ITERATION_BUDGET", "AGENT_TOKEN_BUDGET", "AGENT_COST_BUDGET", "CRUSORAI_MAX_INPUT_TOKENS"):
        env.pop(key, None)
    proc = subprocess.run([
        sys.executable, "scripts/run_bridge_turn.py", "--workspace", str(ws),
        "--prompt-file", str(prompt), "--results-root", str(tmp_path / "out"),
        "--continuous", "--timeout-s", "30",
    ], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, timeout=45)
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(next((tmp_path / "out").glob("*/outcome.json")).read_text())
    assert receipt["agent_iteration_budget"] is None
    assert receipt["token_budget"] == 0
    assert not receipt["budget_stop"]


def test_nonfinite_cost_cannot_bypass_a_configured_limit(monkeypatch):
    monkeypatch.setenv("AGENT_COST_BUDGET", "nan")
    with pytest.raises(ValueError):
        budget._cost_budget()
    monkeypatch.setenv("AGENT_COST_BUDGET", "1")
    assert budget._budget_exhausted({"turn_token_usage": {"estimated_cost_usd": float("nan")}})


def test_long_session_cli_continuous_echo_round_trip(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    prompt = tmp_path / "prompts.txt"
    prompt.write_text("one\n---\ntwo\n")
    env = dict(os.environ, CRUSORAI_BRIDGE_RUNNER="echo")
    proc = subprocess.run([
        sys.executable, "scripts/run_long_session.py", "--workspace", str(tmp_path / "ws"),
        "--prompts-file", str(prompt), "--results-root", str(tmp_path / "out"),
        "--continuous", "--timeout-s-per-turn", "30", "--max-session-minutes", "5",
    ], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, timeout=45)
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(next((tmp_path / "out").glob("*/long_session.json")).read_text())
    assert receipt["turns_completed"] == 2
    assert "[continuous]" in proc.stdout

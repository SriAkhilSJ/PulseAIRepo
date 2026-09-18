"""Per-turn reasoning effort threading.

The desktop's Think picker sends ``reasoning_effort`` on every prompt frame.
A pick must win over the static ``REASONING_EFFORT`` env var for that turn
only, fall back cleanly when absent, and ride queued prompts so a turn
started while another is active keeps its own pick.
"""
from __future__ import annotations

import pytest

from src.config.reasoning_config import parse_reasoning_effort
from src.graphs.chat_graph import _resolve_reasoning_config
from src.runtime.turn_control import TurnControlRegistry


# ---------------------------------------------------------------------------
# parse_reasoning_effort (backend ladder)
# ---------------------------------------------------------------------------

def test_parse_reasoning_effort_levels_and_none():
    assert parse_reasoning_effort("high") == {"enabled": True, "effort": "high"}
    assert parse_reasoning_effort("  MEDium ") == {"enabled": True, "effort": "medium"}
    assert parse_reasoning_effort("none") == {"enabled": False}
    assert parse_reasoning_effort("") is None
    assert parse_reasoning_effort(None) is None


def test_parse_reasoning_effort_rejects_unknown():
    assert parse_reasoning_effort("shrimping") is None


# ---------------------------------------------------------------------------
# _resolve_reasoning_config: per-turn pick wins, env var falls back
# ---------------------------------------------------------------------------

def test_per_turn_pick_wins_over_env(monkeypatch):
    monkeypatch.setenv("REASONING_EFFORT", "low")
    assert _resolve_reasoning_config({"reasoning_effort": "high"}) == {
        "enabled": True, "effort": "high",
    }


def test_env_fallback_when_no_per_turn_pick(monkeypatch):
    monkeypatch.setenv("REASONING_EFFORT", "high")
    assert _resolve_reasoning_config({}) == {"enabled": True, "effort": "high"}
    assert _resolve_reasoning_config(None) == {"enabled": True, "effort": "high"}


def test_blank_or_unknown_per_turn_value_falls_back(monkeypatch):
    monkeypatch.setenv("REASONING_EFFORT", "medium")
    # Blank / unknown values must not shadow a valid env var.
    assert _resolve_reasoning_config({"reasoning_effort": ""}) == {
        "enabled": True, "effort": "medium",
    }
    assert _resolve_reasoning_config({"reasoning_effort": "  "}) == {
        "enabled": True, "effort": "medium",
    }
    assert _resolve_reasoning_config({"reasoning_effort": "wat"}) == {
        "enabled": True, "effort": "medium",
    }


def test_no_config_anywhere_resolves_to_none(monkeypatch):
    monkeypatch.delenv("REASONING_EFFORT", raising=False)
    assert _resolve_reasoning_config({}) is None
    assert _resolve_reasoning_config(None) is None


def test_per_turn_none_disables_thinking(monkeypatch):
    # The picker's Off entry must disable thinking even when the env var
    # would have enabled it — an explicit Off is a real pick.
    monkeypatch.setenv("REASONING_EFFORT", "high")
    assert _resolve_reasoning_config({"reasoning_effort": "none"}) == {"enabled": False}


def test_per_turn_pick_beats_env_off_too(monkeypatch):
    monkeypatch.setenv("REASONING_EFFORT", "none")
    assert _resolve_reasoning_config({"reasoning_effort": "high"}) == {
        "enabled": True, "effort": "high",
    }


# ---------------------------------------------------------------------------
# Queue plumbing: (text, effort) pairs
# ---------------------------------------------------------------------------

def test_queue_carries_effort_with_prompt():
    controls = TurnControlRegistry()
    assert controls.queue("s", "write docs", "high") == 1
    assert controls.queue("s", "then test") == 2
    assert controls.pop_queued("s") == ("write docs", "high")
    assert controls.pop_queued("s") == ("then test", None)
    assert controls.pop_queued("s") is None


# ---------------------------------------------------------------------------
# Wire mapping: build_model_kwargs_for_reasoning
# ---------------------------------------------------------------------------

def test_anthropic_adaptive_and_legacy_budgets():
    from src.config.reasoning_config import build_model_kwargs_for_reasoning

    adaptive = build_model_kwargs_for_reasoning(
        "anthropic", "claude-opus-4-7-20260101", {"enabled": True, "effort": "xhigh"}
    )
    assert adaptive["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert adaptive["output_config"] == {"effort": "xhigh"}

    legacy = build_model_kwargs_for_reasoning(
        "anthropic", "claude-3-7-sonnet-20250219", {"enabled": True, "effort": "high"}
    )
    assert legacy["thinking"] == {"type": "enabled", "budget_tokens": 16000}
    assert legacy["temperature"] == 1


def test_openai_compatible_reasoning_effort():
    from src.config.reasoning_config import build_model_kwargs_for_reasoning

    for provider in ("openai", "custom", "cheap", "groq"):
        kwargs = build_model_kwargs_for_reasoning(
            provider, "any-model", {"enabled": True, "effort": "low"}
        )
        assert kwargs == {"reasoning_effort": "low"}


def test_disabled_thinking_disables_anthropic_only():
    from src.config.reasoning_config import build_model_kwargs_for_reasoning

    assert build_model_kwargs_for_reasoning(
        "anthropic", "claude-opus-4-7-20260101", {"enabled": False}
    ) == {"thinking": {"type": "disabled"}}
    # OpenAI-compat has no wire-level disable.
    assert build_model_kwargs_for_reasoning(
        "openai", "gpt-5", {"enabled": False}
    ) == {}


# ---------------------------------------------------------------------------
# stream_agent: effort reaches the graph configurable
# ---------------------------------------------------------------------------

def test_stream_agent_threads_reasoning_effort_into_configurable(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    captured = {}

    class _FakeCompiled:
        def stream(self, state, config=None, stream_mode=None):
            captured["config"] = config
            yield {"messages": []}

    monkeypatch.setattr(chat_graph, "graph", _FakeCompiled())
    import src.context.convention_learner as _cl
    monkeypatch.setattr(_cl.ConventionLearner, "get_conventions_text", lambda self, ws: "")

    chat_graph.stream_agent("hello", thread_id="t-effort", workspace=".", reasoning_effort="high")

    configurable = captured["config"]["configurable"]
    assert configurable["reasoning_effort"] == "high"


def test_stream_agent_defaults_to_none_effort(monkeypatch):
    import src.graphs.chat_graph as chat_graph

    captured = {}

    class _FakeCompiled:
        def stream(self, state, config=None, stream_mode=None):
            captured["config"] = config
            yield {"messages": []}

    monkeypatch.setattr(chat_graph, "graph", _FakeCompiled())
    import src.context.convention_learner as _cl
    monkeypatch.setattr(_cl.ConventionLearner, "get_conventions_text", lambda self, ws: "")

    chat_graph.stream_agent("hello", thread_id="t-effort-default", workspace=".")

    assert captured["config"]["configurable"]["reasoning_effort"] is None


# ---------------------------------------------------------------------------
# Bridge: the prompt frame's reasoning_effort reaches stream_agent
# ---------------------------------------------------------------------------

def test_bridge_prompt_frame_carries_effort_to_stream_agent(tmp_path, monkeypatch):
    from src.bridge.__main__ import BridgeServer
    import src.graphs.chat_graph as chat_graph

    captured = {}

    def fake_stream_agent(text, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(chat_graph, "stream_agent", fake_stream_agent)
    server = object.__new__(BridgeServer)
    server.emit = lambda frame: None
    server._run_turn(
        "effort-regression", "build it", str(tmp_path), "agent", "high",
    )

    assert captured["reasoning_effort"] == "high"


def test_bridge_prompt_without_effort_passes_none(tmp_path, monkeypatch):
    from src.bridge.__main__ import BridgeServer
    import src.graphs.chat_graph as chat_graph

    captured = {}

    def fake_stream_agent(text, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(chat_graph, "stream_agent", fake_stream_agent)
    server = object.__new__(BridgeServer)
    server.emit = lambda frame: None
    server._run_turn("effort-regression-2", "build it", str(tmp_path))

    assert captured["reasoning_effort"] is None

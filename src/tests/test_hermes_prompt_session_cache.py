"""Session-caching behaviour of the ported prompt engine (Law 1, enforced).

The prompt text is upstream's; what Pulse has to get right is *when it is
built*. These tests pin that: build once per session, reuse for every turn,
rebuild only at a compaction/reset boundary, and fall back to the legacy
persona the instant the engine is switched off or misbehaves.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.prompts.hermes import session as session_mod  # noqa: E402
from src.prompts.hermes.view import PulsePromptView  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_sessions():
    session_mod.invalidate_all_sessions()
    yield
    session_mod.invalidate_all_sessions()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "provider": "groq", "model": "qwen3.6-27b", "workspace": str(REPO)}}


def test_prompt_is_built_once_per_session(monkeypatch):
    """The rebuild count is the whole point: parts are computed ONCE per session."""
    calls = {"n": 0}
    from src.prompts.hermes import system_prompt as sp_mod

    original_parts = sp_mod.build_system_prompt_parts

    def counting_parts(view, system_message=None):
        calls["n"] += 1
        return original_parts(view, system_message=system_message)

    monkeypatch.setattr(sp_mod, "build_system_prompt_parts", counting_parts)
    cfg = _config("build-once")
    first = session_mod.system_prompt_for_session(cfg, {"current_task": "one"})
    second = session_mod.system_prompt_for_session(cfg, {"current_task": "two and different"})
    assert first and first == second
    assert calls["n"] == 1, "a second turn must reuse the cached prefix, not rebuild it"


def test_every_extra_turn_still_costs_no_rebuild(monkeypatch):
    from src.prompts.hermes import system_prompt as sp_mod

    calls = {"n": 0}
    original_parts = sp_mod.build_system_prompt_parts

    def counting_parts(view, system_message=None):
        calls["n"] += 1
        return original_parts(view, system_message=system_message)

    monkeypatch.setattr(sp_mod, "build_system_prompt_parts", counting_parts)
    cfg = _config("ten-turns")
    for i in range(10):
        text = session_mod.system_prompt_for_session(cfg, {"current_task": f"turn {i}"})
    assert text
    assert calls["n"] == 1


def test_sessions_are_isolated():
    a = session_mod.system_prompt_for_session(_config("thread-a"), {})
    b = session_mod.system_prompt_for_session(_config("thread-b"), {})
    assert a and b
    assert "Session ID: thread-a" in a
    assert "Session ID: thread-a" not in b


def test_invalidation_rebuilds_and_only_for_that_thread():
    cfg_a, cfg_b = _config("inv-a"), _config("inv-b")
    session_mod.system_prompt_for_session(cfg_a, {})
    session_mod.system_prompt_for_session(cfg_b, {})
    assert session_mod.invalidate_session("inv-a") is True
    assert session_mod.invalidate_session("inv-a") is False
    # the other thread's cache survives — a per-thread compaction must not
    # rebuild every session in the process
    assert session_mod.session_stats(cfg_b)["cached"] is True
    assert session_mod.session_stats(cfg_a)["cached"] is False


def test_context_engine_hooks_call_the_invalidator(monkeypatch):
    """Compaction and session reset are the ONLY rebuild triggers."""
    from src.context.context_engine import ContextEngine

    calls = []
    monkeypatch.setattr(session_mod, "invalidate_session", lambda tid: calls.append(tid) or True)

    engine = object.__new__(ContextEngine)  # no construction: exercise the hook only
    engine.thread_id = "engine-thread"
    ContextEngine._invalidate_stable_prefix(engine, "compaction")
    assert calls == ["engine-thread"]
    assert engine._stable_prefix_invalidations == 1

    calls.clear()
    engine2 = object.__new__(ContextEngine)
    engine2.thread_id = ""
    ContextEngine._invalidate_stable_prefix(engine2, "compaction")
    assert calls == [], "no thread id means no session to invalidate"


def test_kill_switch_falls_back_to_the_legacy_persona(monkeypatch):
    monkeypatch.setenv("PULSEAI_STABLE_PREFIX", "off")
    assert session_mod.stable_prefix_enabled() is False
    assert session_mod.system_prompt_for_session(_config("off-thread"), {}) == ""


def test_chat_graph_uses_the_cached_prefix_and_degrades_safely(monkeypatch):
    """The wiring point: an engine failure must not remove the system message."""
    pytest.importorskip("langgraph")
    from langchain_core.messages import SystemMessage

    from src.graphs import chat_graph

    session_mod.invalidate_all_sessions()
    msg = chat_graph._session_system_message(_config("graph-thread"), {"current_task": "hi"}, autonomous=False)
    assert isinstance(msg, SystemMessage)
    assert "You are Pulse Agent." in msg.content or "Pulse" in msg.content
    assert "Conversation started:" in msg.content

    monkeypatch.setattr(chat_graph, "system_message", SystemMessage(content="LEGACY-PERSONA"))
    monkeypatch.setattr(session_mod, "stable_prefix_enabled", lambda: False)
    fallback = chat_graph._session_system_message(_config("graph-thread-2"), {}, autonomous=False)
    assert fallback.content == "LEGACY-PERSONA"

    # A raising engine must degrade to the persona, never lose the system message.
    from src.prompts.hermes import system_prompt as sp_mod

    monkeypatch.setattr(session_mod, "stable_prefix_enabled", lambda: True)
    session_mod.invalidate_all_sessions()

    def boom(view, *a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(sp_mod, "build_system_prompt_parts", boom)
    degraded = chat_graph._session_system_message(_config("graph-thread-3"), {}, autonomous=True)
    assert isinstance(degraded, SystemMessage)
    assert degraded is chat_graph.autonomous_system_message


def test_autonomous_sessions_get_their_own_bucket():
    interactive = session_mod.view_for_session(_config("auto-shared"), {}, autonomous=False)
    autonomous = session_mod.view_for_session(_config("auto-shared"), {}, autonomous=True)
    assert autonomous.steer_enabled is False
    assert interactive.steer_enabled is True


def test_truncation_reaches_the_status_channel_not_the_prompt():
    view = PulsePromptView(
        model="qwen3.6-27b",
        provider="groq",
        context_length=64,  # tiny window → tiny cap → truncation
        cwd=REPO,
        skills_enabled=False,
        skip_context_files=False,
    )
    from src.prompts.hermes.system_prompt import build_system_prompt

    prompt = build_system_prompt(view, use_cache=False)
    assert "TRUNCATED" not in prompt
    assert isinstance(view.status_sink, list)


def test_session_stats_report_the_tier_split():
    session_mod.system_prompt_for_session(_config("stats-thread"), {})
    stats = session_mod.session_stats(_config("stats-thread"))
    assert stats["cached"] is True
    assert stats["stable_chars"] > stats["volatile_chars"], "the cacheable band must dominate"
    assert stats["static_bytes"] == stats["stable_chars"]

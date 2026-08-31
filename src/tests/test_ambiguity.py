"""P10 behavior contracts for src/context/ambiguity.py.

The ambiguity detector's hard contract: deadline-bound turns (the
default, ``allow_embedding_compute=False``) NEVER encode — the
deterministic keyword path runs, and the flag is fed LIVE by the
engine delegate so flipping the policy mid-session takes effect
immediately.
"""

import pytest

from langchain_core.messages import SystemMessage

from src.context import ambiguity
from src.context.context_engine import ContextEngine


def _engine() -> ContextEngine:
    return ContextEngine(max_tokens=4000, llm=None, memory_manager=None)


# ---------------------------------------------------------------------------
# Fallback (deterministic) path
# ---------------------------------------------------------------------------

def test_fallback_flags_vague_task():
    out = ambiguity.detect_ambiguity_fallback("just fix it")
    assert isinstance(out, SystemMessage)
    assert out.content == ambiguity.AMBIGUITY_ALERT_FALLBACK
    assert out.content.startswith("=== AMBIGUITY ALERT ===")


def test_fallback_allows_specific_task():
    assert ambiguity.detect_ambiguity_fallback(
        "fix the bug in parser.py on line 42"
    ) is None


def test_fallback_case_insensitive():
    out = ambiguity.detect_ambiguity_fallback("FIX IT")
    assert out is not None


def test_fallback_specific_word_suppresses_vague():
    # "improve" (vague) + "test" (specific) -> no alert
    assert ambiguity.detect_ambiguity_fallback(
        "improve the test suite"
    ) is None


# ---------------------------------------------------------------------------
# Advanced (embedding-gated) path
# ---------------------------------------------------------------------------

def test_advanced_disabled_never_encodes_and_uses_fallback(monkeypatch):
    """Flag off: the detector must return the fallback result without
    even touching the embedder (deadline-bound safety)."""
    calls = []

    def _boom():
        calls.append(1)
        raise AssertionError("advanced path encoded on a deadline-bound turn")

    monkeypatch.setattr("src.llm.factory.get_embedder", _boom)
    out = ambiguity.detect_ambiguity_advanced("just fix it", False)
    assert calls == []
    assert out is not None
    assert out.content == ambiguity.AMBIGUITY_ALERT_FALLBACK


def test_advanced_embedder_failure_falls_back(monkeypatch):
    def _boom():
        raise RuntimeError("no embedder available in sandbox")

    monkeypatch.setattr("src.llm.factory.get_embedder", _boom)
    out = ambiguity.detect_ambiguity_advanced("just fix it", True)
    assert out is not None
    assert out.content == ambiguity.AMBIGUITY_ALERT_FALLBACK


# ---------------------------------------------------------------------------
# Engine delegation seams (test_embedding_cache.py pins _detect_ambiguity_advanced)
# ---------------------------------------------------------------------------

def test_engine_advanced_feeds_live_flag(monkeypatch):
    """The delegate must read the flag LIVE per call: off -> never
    touches the embedder; flip it mid-session -> next call does."""
    eng = _engine()
    calls = []

    def _record():
        calls.append(1)
        raise RuntimeError("no embedder in sandbox")

    monkeypatch.setattr("src.llm.factory.get_embedder", _record)

    assert eng._allow_embedding_compute is False
    out = eng._detect_ambiguity_advanced("just fix it")
    assert calls == [], "deadline-bound turn encoded"
    assert out is not None
    assert out.content == ambiguity.AMBIGUITY_ALERT_FALLBACK

    eng._allow_embedding_compute = True  # mid-session policy flip
    out = eng._detect_ambiguity_advanced("just fix it")
    assert calls == [1], "delegate fed a stale (captured) flag"
    assert out is not None
    assert out.content == ambiguity.AMBIGUITY_ALERT_FALLBACK


def test_engine_fallback_delegates_to_module():
    eng = _engine()
    for task in ("just fix it", "fix the bug in parser.py on line 42", "improve the test suite"):
        assert eng._detect_ambiguity_fallback(task) == \
            ambiguity.detect_ambiguity_fallback(task)

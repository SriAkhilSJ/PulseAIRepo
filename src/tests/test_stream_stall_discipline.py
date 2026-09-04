"""Pins for the streaming stall discipline + owned retry policy (factory).

Field proof (owner run): the endpoint hung after a tool call and the
generation-sized 180s timeout handed it 3 silent minutes per attempt
(the "died after a tool call" panel), while ChatOpenAI's SDK default
max_retries quietly multiplied every attempt. Hermes: max_retries=0 on SDK
clients (#54465) and silence-sized read timeouts on streams (extend while
tokens move — only silence is the enemy).
"""

from __future__ import annotations

import pytest

from src.llm import factory


@pytest.fixture
def _custom_creds(monkeypatch):
    monkeypatch.setattr(factory, "CUSTOM_API_KEY", "test-key")
    monkeypatch.setattr(factory, "CUSTOM_BASE_URL", "http://test.local/v1")
    monkeypatch.delenv("PULSEAI_LLM_STREAMING", raising=False)
    monkeypatch.delenv("PULSEAI_LLM_TIMEOUT", raising=False)
    monkeypatch.delenv("PULSEAI_LLM_STALL_TIMEOUT_S", raising=False)


def _core(proxy):
    return proxy._llm


def test_streaming_custom_uses_silence_sized_timeout(_custom_creds):
    llm = _core(factory.get_llm("custom", "test-model"))

    assert llm.streaming is True
    assert llm.request_timeout == 45.0, "default silence budget"
    assert llm.max_retries == 0, "no hidden SDK retries — the proxy owns the policy"


def test_stall_budget_is_env_tunable_per_call(_custom_creds, monkeypatch):
    monkeypatch.setenv("PULSEAI_LLM_STALL_TIMEOUT_S", "15")
    assert _core(factory.get_llm("custom", "m")).request_timeout == 15.0

    monkeypatch.setenv("PULSEAI_LLM_STALL_TIMEOUT_S", "not-a-number")
    assert _core(factory.get_llm("custom", "m")).request_timeout == 45.0

    monkeypatch.setenv("PULSEAI_LLM_STALL_TIMEOUT_S", "9999")
    assert _core(factory.get_llm("custom", "m")).request_timeout == 300.0, "clamped"


def test_explicit_request_timeout_wins(_custom_creds):
    """Aux/management lanes pass their own budget — untouched."""
    llm = _core(factory.get_llm("custom", "m", request_timeout=7))
    assert llm.request_timeout == 7.0


def test_non_streaming_keeps_generation_sized_timeout(_custom_creds, monkeypatch):
    monkeypatch.setenv("PULSEAI_LLM_STREAMING", "off")
    monkeypatch.setenv("PULSEAI_LLM_TIMEOUT", "200")
    llm = _core(factory.get_llm("custom", "m"))

    assert llm.streaming is False
    assert llm.request_timeout == 200.0


def test_stall_helper_clamps():
    import os

    os.environ["PULSEAI_LLM_STALL_TIMEOUT_S"] = "3"
    try:
        assert factory._stream_stall_timeout() == 10.0
    finally:
        os.environ.pop("PULSEAI_LLM_STALL_TIMEOUT_S", None)


def test_bridge_forwards_llm_status_despite_session_filter():
    """Source pin: the llm.* bypass must exist in the event forwarder (field:
    the frames were dropped and the activity row never named the model)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    bridge = (root / "src/bridge/__main__.py").read_text(encoding="utf-8")
    assert 'startswith("llm.")' in bridge
    assert "not is_llm_status" in bridge

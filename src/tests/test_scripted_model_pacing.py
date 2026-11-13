"""Pacing seam tests: chunk delay must apply only in authorized scripted runs.

The delay exists so a benchmark can deliver the deterministic fixture at a
provider-like cadence. It must never touch a real provider path, must never
reorder or alter chunk text, and must never sleep on an asyncio loop thread.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from src.llm import scripted_model as sm


CHUNKS = ["Alpha ", "beta ", "gamma ", "डेल्टा ", "🚀", " end"]


def _script() -> list[dict[str, Any]]:
    content = "".join(CHUNKS)
    return [{
        "content": content,
        "chunks": list(CHUNKS),
        "usage": {"input_tokens": 10, "output_tokens": 6, "total_tokens": 16},
    }]


class _Collector:
    """Mimics the gateway's token callback handler."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def on_llm_new_token(self, token: str) -> None:
        self.chunks.append(token)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CRUSORAI_TEST_CHUNK_DELAY_MS", "CRUSORAI_TEST_MODE", "CRUSORAI_TEST_LLM_SCRIPT"):
        monkeypatch.delenv(name, raising=False)
    sm._SCRIPT_CURSORS.clear()


def _authorize(monkeypatch: pytest.MonkeyPatch, delay_ms: int) -> None:
    monkeypatch.setenv("CRUSORAI_TEST_MODE", "1")
    monkeypatch.setenv("CRUSORAI_TEST_LLM_SCRIPT", json.dumps(_script()))
    monkeypatch.setenv("CRUSORAI_TEST_CHUNK_DELAY_MS", str(delay_ms))


def _run_one(config_key: str = "pacing-test") -> tuple[list[str], list[float]]:
    model = sm.scripted_model_from_env()
    collector = _Collector()
    sleeps: list[float] = []

    real_sleep = time.sleep

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        real_sleep(0)  # do not actually wait: keep the suite fast

    original = time.sleep
    time.sleep = fake_sleep  # type: ignore[assignment]
    try:
        model.invoke([], {"callbacks": [collector], "configurable": {"thread_id": config_key}})
    finally:
        time.sleep = original  # type: ignore[assignment]
    return collector.chunks, sleeps


def test_default_delay_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUSORAI_TEST_MODE", "1")
    monkeypatch.setenv("CRUSORAI_TEST_LLM_SCRIPT", json.dumps(_script()))
    assert sm._pacing_delay_s() == 0.0

    chunks, sleeps = _run_one("default")
    assert chunks == CHUNKS
    assert sleeps == []


def test_delay_applies_only_when_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    # Delay set, but the scripted seam is not active: must be ignored.
    monkeypatch.setenv("CRUSORAI_TEST_CHUNK_DELAY_MS", "20")
    assert sm._pacing_delay_s() == 0.0

    _authorize(monkeypatch, 20)
    assert sm._pacing_delay_s() == pytest.approx(0.020)

    chunks, sleeps = _run_one("authorized")
    assert chunks == CHUNKS, "chunk text and order must be preserved exactly"
    assert len(sleeps) == len(CHUNKS) - 1, "no delay before the first chunk"
    assert all(s == pytest.approx(0.020) for s in sleeps)


@pytest.mark.parametrize("bad", ["abc", "-5", "501", "100000"])
def test_invalid_or_out_of_range_values_are_rejected(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    _authorize(monkeypatch, 0)
    monkeypatch.setenv("CRUSORAI_TEST_CHUNK_DELAY_MS", bad)
    with pytest.raises(RuntimeError):
        sm._pacing_delay_s()


def test_upper_bound_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _authorize(monkeypatch, 500)
    assert sm._pacing_delay_s() == pytest.approx(0.5)


def test_pacing_is_skipped_on_an_asyncio_loop_thread() -> None:
    """A blocking sleep on the loop thread would stall the bridge; skip instead."""

    recorded: list[float] = []
    real_sleep = time.sleep
    time.sleep = lambda seconds: recorded.append(seconds)  # type: ignore[assignment]
    try:
        async def on_loop() -> None:
            sm._sleep_unless_on_event_loop(0.05)

        asyncio.run(on_loop())
    finally:
        time.sleep = real_sleep  # type: ignore[assignment]

    assert recorded == [], "must not sleep while an event loop is running"


def test_worker_thread_path_does_sleep() -> None:
    recorded: list[float] = []
    real_sleep = time.sleep
    time.sleep = lambda seconds: recorded.append(seconds)  # type: ignore[assignment]
    try:
        sm._sleep_unless_on_event_loop(0.05)
    finally:
        time.sleep = real_sleep  # type: ignore[assignment]
    assert recorded == [0.05]


def test_stream_path_preserves_order_and_usage_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    _authorize(monkeypatch, 0)
    model = sm.scripted_model_from_env()
    out = list(model.stream([], {"configurable": {"thread_id": "stream-path"}}))
    text = "".join(chunk.content for chunk in out)
    assert text == "".join(CHUNKS)
    assert out[-1].usage_metadata and out[-1].usage_metadata["output_tokens"] == 6

"""Pins for the memory warm-up budget (hermes housekeeping discipline).

Field proof (owner run + Attempt 8): the first tool memory write used to
construct the embedding backend SYNCHRONOUSLY in the turn's critical path —
a model download behind tool_call_end, wedging tool->model for >10 minutes.
The LazyMemoryManager must construct in a background thread and bound every
call's wait to PULSEAI_MEMORY_WARMUP_BUDGET_S, degrading to defaults.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.context.lazy_memory import LazyMemoryManager


@pytest.fixture(autouse=True)
def _tight_budget(monkeypatch):
    monkeypatch.setenv("PULSEAI_MEMORY_WARMUP_BUDGET_S", "0.2")


def test_slow_backend_never_blocks_the_call():
    gate = threading.Event()
    started = threading.Event()

    def factory():
        started.set()
        gate.wait(timeout=10)  # simulates a model download
        return _FakeBackend(store={"kept": True})

    manager = LazyMemoryManager(factory)

    t0 = time.monotonic()
    result = manager.store_tool_memory(tool_name="run_terminal", summary="x")
    elapsed = time.monotonic() - t0

    assert result is None, "cold backend must degrade to the method default"
    assert elapsed < 5, f"call waited {elapsed:.1f}s — budget not owned"
    assert started.is_set(), "warm-up thread should have been kicked off"


def test_warm_backend_serves_normally():
    manager = LazyMemoryManager(_FakeBackend)
    manager.warmup()
    _wait_until(lambda: manager.initialized)

    assert manager.store_tool_memory(tool_name="t", summary="s") == "stored"
    assert manager.retrieve_tool_memories() == ["hit"]


def test_budget_is_read_per_call(monkeypatch):
    gate = threading.Event()

    def factory():
        gate.wait(timeout=10)
        return _FakeBackend()

    manager = LazyMemoryManager(factory)
    manager.warmup()

    monkeypatch.setenv("PULSEAI_MEMORY_WARMUP_BUDGET_S", "0")
    t0 = time.monotonic()
    manager.get_memory_count()
    assert time.monotonic() - t0 < 1, "budget 0 must not wait at all"
    monkeypatch.setenv("PULSEAI_MEMORY_WARMUP_BUDGET_S", "bogus")
    # invalid values fall back to the default instead of crashing the turn
    manager.get_memory_count()


def test_factory_failure_still_disables(monkeypatch):
    def boom():
        raise RuntimeError("no embedding backend")

    manager = LazyMemoryManager(boom)
    assert manager.store_tool_memory(tool_name="t", summary="s") is None
    assert manager.disabled is True
    assert manager.retrieve_tool_memories() == []
    assert bool(manager) is False


def test_slow_wait_logs_once(capsys):
    gate = threading.Event()

    def factory():
        gate.wait(timeout=10)
        return _FakeBackend()

    manager = LazyMemoryManager(factory)
    manager.store_tool_memory(tool_name="t", summary="s")
    manager.store_tool_memory(tool_name="t", summary="s")

    out = capsys.readouterr().out
    assert out.count("not warm after") == 1, "one honest line, not spam"
    gate.set()


class _FakeBackend:
    def __init__(self, store=None):
        self._store = store or {}

    def store_tool_memory(self, **kwargs):
        self._store["kept"] = kwargs
        return "stored"

    def retrieve_tool_memories(self, *args, **kwargs):
        return ["hit"]

    def get_memory_count(self, *args, **kwargs):
        return 1


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail("condition not met in time")

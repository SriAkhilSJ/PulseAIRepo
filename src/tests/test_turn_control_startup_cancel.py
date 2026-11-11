"""Startup-cancellation contract for the turn-control registry.

Phase 2 r1 proved a real race: a Stop sent ~0.9s after Send returned
``accepted=False`` and the prompt still completed, because the bridge had
accepted the prompt but the turn had not called ``begin()`` yet. These tests
pin the bounded single-slot fix:

* a Stop during the pending window is accepted and applied by ``begin()``;
* a Stop after the turn ended is rejected and never poisons the next turn;
* the pending slot expires so a worker that never begins cannot capture a
  later turn's Stop;
* pending/cancel state is per session;
* an active-turn Stop still fires abort handles.
"""
from __future__ import annotations

import threading

import pytest

from src.runtime import turn_control as tc
from src.runtime.turn_control import TurnControlRegistry


@pytest.fixture()
def registry() -> TurnControlRegistry:
    return TurnControlRegistry()


def test_startup_cancel_is_applied_at_begin(registry: TurnControlRegistry) -> None:
    registry.mark_pending("s1")
    assert registry.cancel("s1") is True, "a Stop during startup must be accepted"
    assert registry.pending("s1") is True
    assert registry.cancelled("s1") is True

    registry.begin("s1")
    try:
        assert registry.cancelled("s1") is True, "begin() must consume the startup Stop"
        assert registry.pending("s1") is False
        assert registry.turn_elapsed("s1") is not None
    finally:
        registry.end("s1")
    assert registry.cancelled("s1") is False, "a consumed Stop must not outlive its turn"


def test_startup_cancel_does_not_leak_into_the_next_turn(registry: TurnControlRegistry) -> None:
    registry.mark_pending("s1")
    assert registry.cancel("s1") is True
    registry.begin("s1")
    registry.end("s1")
    assert registry.cancelled("s1") is False

    # The cancelled turn finished; the next prompt starts clean.
    registry.mark_pending("s1")
    registry.begin("s1")
    try:
        assert registry.cancelled("s1") is False
    finally:
        registry.end("s1")


def test_cancel_after_completion_is_rejected(registry: TurnControlRegistry) -> None:
    registry.begin("s1")
    registry.end("s1")
    assert registry.cancel("s1") is False
    assert registry.cancelled("s1") is False
    registry.begin("s1")
    try:
        assert registry.cancelled("s1") is False, "a late Stop must not poison the next turn"
    finally:
        registry.end("s1")


def test_pending_slot_expires(registry: TurnControlRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tc, "PENDING_CANCEL_TTL_S", 0.0)
    registry.mark_pending("s1")
    assert registry.cancel("s1") is False, "an expired pending window cannot capture a Stop"
    registry.begin("s1")
    try:
        assert registry.cancelled("s1") is False
    finally:
        registry.end("s1")


def test_pending_and_cancel_are_session_scoped(registry: TurnControlRegistry) -> None:
    registry.mark_pending("s1")
    assert registry.cancel("s2") is False
    registry.begin("s2")
    try:
        assert registry.cancelled("s2") is False
    finally:
        registry.end("s2")

    assert registry.cancel("s1") is True
    registry.begin("s1")
    try:
        assert registry.cancelled("s1") is True
    finally:
        registry.end("s1")


def test_active_cancel_still_fires_abort_handles(registry: TurnControlRegistry) -> None:
    fired = threading.Event()
    registry.begin("s1")
    try:
        registry.register_abort("s1", fired.set)
        assert registry.cancel("s1") is True
        assert fired.wait(timeout=1.0), "registered request abort must fire"
        assert registry.cancelled("s1") is True
    finally:
        registry.end("s1")


def test_nested_begin_does_not_erase_an_active_stop(registry: TurnControlRegistry) -> None:
    registry.begin("s1")
    try:
        assert registry.cancel("s1") is True
        registry.begin("s1")  # graph's nested acquire
        assert registry.cancelled("s1") is True
        registry.end("s1")
        assert registry.cancelled("s1") is True, "outer owner still active"
    finally:
        registry.end("s1")
    assert registry.cancelled("s1") is False

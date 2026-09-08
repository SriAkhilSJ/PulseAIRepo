"""Turn-liveness watchdog — hermes agent/activity_tracking.py, bridge-sized.

Hermes' liveness discipline (agent/activity_tracking.py): activity events
stamp under a lock, the code "Bumps a monotonic generation under the activity
lock so the watchdog can bind a stall observation to" a fixed state, and
"Real progress invalidates a reserved abort claim". Pulse's bridge instead
timed the TOTAL wall time from turn start — field log 2026-09-08: it fired
600s into a turn the owner was actively watching work (311.6s non-streaming
LLM answer, 264.9s browser_navigate, 108.7s context build), emitted a
synthetic turn_done ("run stopped but agent is still in job"), while the
engine kept going and painted more tool cards.

The budget therefore measures SILENCE, not total time: the bridge's event
forwarder touches the generation for every own-session event it relays, and
a stall observation fires only if one full budget window passes with the
generation unchanged. PULSEAI_TURN_STALL_TIMEOUT_S keeps its name and clamp
(default 600s, ceiling 3600s, 0 = off); the semantics are inactivity, as in
hermes.
"""
from __future__ import annotations

import threading


class TurnLiveness:
    """Monotonic progress generation (hermes activity_tracking shape)."""

    __slots__ = ("_lock", "_gen")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gen = 0

    def touch(self) -> None:
        """One piece of real engine output reached the client."""
        with self._lock:
            self._gen += 1

    def generation(self) -> int:
        with self._lock:
            return self._gen


def stall_budget(raw: str, *, default: float = 600.0, ceiling: float = 3600.0) -> float:
    """PULSEAI_TURN_STALL_TIMEOUT_S value, clamped (0 disables the watchdog)."""
    try:
        budget = float(raw) if raw else default
    except (TypeError, ValueError):
        budget = default
    return max(0.0, min(budget, ceiling))


def run_stall_watchdog(*, terminal: threading.Event, liveness: TurnLiveness,
                       budget_env: str, fire, wait: float | None = None) -> None:
    """Fire ``fire(budget)`` iff one full budget window sees zero liveness.

    Each loop binds the observation to the generation seen BEFORE the wait
    (hermes: the watchdog binds a stall observation to a state); any relayed
    engine event during the window invalidates it and re-arms a fresh budget.
    ``wait`` is a test seam (poll interval); production polls once per budget.
    """
    budget = stall_budget(budget_env)
    if budget <= 0:
        return
    poll = budget if wait is None else max(0.01, min(wait, budget))
    while True:
        observed = liveness.generation()
        if terminal.wait(poll):
            return
        if liveness.generation() != observed:
            continue  # real progress invalidates the stall observation
        fire(budget)
        return

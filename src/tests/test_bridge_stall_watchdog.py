"""Bridge stall watchdog: inactivity-based, hermes activity_tracking shape.

Field receipt that pinned this behavior (owner log 2026-09-08): the old
wall-clock watchdog fired 600s into a live turn — 311.6s non-streaming LLM
answer + 264.9s browser_navigate + 108.7s context build — emitted a synthetic
turn_done ("run stopped but agent is still in job") while the engine kept
working. Hermes binds stall observations to an activity generation and real
progress invalidates them (agent/activity_tracking.py), so the budget must
measure SILENCE: an actively-relayed turn never fires; a silent one does.
"""
from __future__ import annotations

import threading
import time

from src.bridge.turn_watchdog import TurnLiveness, run_stall_watchdog, stall_budget


def test_silent_turn_fires_once_with_the_budget():
    terminal = threading.Event()
    fired: list[float] = []
    run_stall_watchdog(
        terminal=terminal, liveness=TurnLiveness(), budget_env="0.2",
        fire=fired.append, wait=0.05,
    )
    assert fired == [0.2]


def test_active_turn_never_fires_while_events_flow():
    terminal = threading.Event()
    fired: list[float] = []
    liveness = TurnLiveness()
    stop = threading.Event()

    def engine() -> None:
        while not stop.is_set():
            liveness.touch()
            time.sleep(0.02)

    threading.Thread(target=engine, daemon=True).start()
    # A full budget window plus several re-arms pass; the watchdog must still
    # be waiting, and must exit cleanly the moment the terminal frame lands.
    threading.Timer(0.6, terminal.set).start()
    run_stall_watchdog(
        terminal=terminal, liveness=liveness, budget_env="0.2",
        fire=fired.append, wait=0.05,
    )
    stop.set()
    assert fired == []


def test_terminal_frame_wins_even_in_total_silence():
    terminal = threading.Event()
    terminal.set()
    fired: list[float] = []
    run_stall_watchdog(
        terminal=terminal, liveness=TurnLiveness(), budget_env="600",
        fire=fired.append,
    )
    assert fired == []


def test_progress_then_silence_fires_after_a_full_quiet_window():
    liveness = TurnLiveness()
    terminal = threading.Event()
    fired: list[float] = []
    liveness.touch()  # engine activity, then the engine goes quiet
    run_stall_watchdog(
        terminal=terminal, liveness=liveness, budget_env="0.2",
        fire=fired.append, wait=0.05,
    )
    assert fired == [0.2]


def test_budget_env_contract_default_off_and_ceiling():
    assert stall_budget("") == 600.0            # default unchanged
    assert stall_budget("0") == 0.0             # off stays off
    assert stall_budget("99999") == 3600.0      # ceiling unchanged
    assert stall_budget("garbage") == 600.0     # junk falls back to default


def test_liveness_generation_is_monotonic():
    liveness = TurnLiveness()
    assert liveness.generation() == 0
    liveness.touch()
    liveness.touch()
    assert liveness.generation() == 2

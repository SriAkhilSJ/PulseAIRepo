"""B-LIVE-002: terminal outcomes are authoritative, live and restored.

Two layers are covered here:

* the bridge's durable terminal rows become a `turnId -> outcome` map that the
  client can trust (unit test, no provider);
* the renderer consumes that map (and the terminal frame) instead of inventing
  success. The decision itself is executed by
  `scripts/test_crusorai_turn_outcome.mjs`; these assertions pin the wiring so a
  refactor cannot silently re-introduce the old "not cancelled means completed"
  derivation.
"""
from __future__ import annotations

from pathlib import Path

from src.bridge.__main__ import BridgeServer

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts"
PROTOCOL = REPO / "desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts"


def event(kind: str, turn_id: str | None) -> dict:
    return {"type": kind, "turn_id": turn_id, "payload": {}}


# --------------------------------------------------------------------------- #
# durable terminal rows
# --------------------------------------------------------------------------- #

def test_terminal_rows_map_to_outcomes() -> None:
    outcomes = BridgeServer._turn_outcomes([
        event("turn.started", "turn-1"),
        event("turn.completed", "turn-1"),
        event("turn.failed", "turn-2"),
        event("turn.cancelled", "turn-3"),
        event("turn.interrupted", "turn-4"),
        event("turn.watchdog", "turn-5"),
    ])
    assert outcomes == {
        "turn-1": "completed",
        "turn-2": "failed",
        "turn-3": "cancelled",
        "turn-4": "incomplete",
        "turn-5": "incomplete",
    }


def test_first_terminal_row_wins_and_other_events_are_ignored() -> None:
    outcomes = BridgeServer._turn_outcomes([
        event("turn.failed", "turn-1"),
        event("turn.completed", "turn-1"),  # cannot relabel a settled turn
        event("agent_card", "turn-1"),
        event("turn.started", "turn-2"),
    ])
    assert outcomes == {"turn-1": "failed"}


def test_rows_without_a_turn_id_are_not_attributed() -> None:
    assert BridgeServer._turn_outcomes([
        event("turn.completed", None),
        event("turn.failed", ""),
    ]) == {}


def test_a_turn_without_a_terminal_row_is_absent() -> None:
    """The client must see "no entry", not a manufactured success."""
    outcomes = BridgeServer._turn_outcomes([event("turn.started", "turn-1")])
    assert "turn-1" not in outcomes


# --------------------------------------------------------------------------- #
# renderer wiring
# --------------------------------------------------------------------------- #

def test_renderer_derives_outcome_from_the_terminal_frame() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    assert "terminalTurnOutcome({" in text
    assert "terminalStatus: canonical?.terminal_status" in text
    assert "this.turnOutcome = frame.cancelled ? 'cancelled' : 'completed'" not in text


def test_failure_text_is_not_left_as_the_assistant_answer() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    assert "dropDuplicatedFailureText(" in text
    assert "private dropDuplicatedFailureText(" in text


def test_restore_uses_durable_outcomes_and_never_invents_success() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    assert "restoredTurnOutcome(turnOutcomes, turn.turnId)" in text
    assert "turnOutcome: 'completed' as const" not in text
    assert "state: 'recorded'" in text
    assert "state: 'passed' }" not in text


def test_protocol_declares_optional_turn_outcomes() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "readonly turn_outcomes?: Readonly<Record<string, string>>" in text

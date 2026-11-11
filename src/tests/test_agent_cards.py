"""Typed Agent UI cards and the provider-free scripted desktop turn."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from src.bridge.agent_cards import (
    CARD_EVENT_NAME,
    CARD_TYPES,
    card_for_frame,
    card_frames_for_frame,
    normalize_card,
)
from src.bridge.protocol import decode_line, encode
from src.bridge.scripted_turn import STREAM_TEXT, run_scripted_turn


class _Identity:
    def __init__(self) -> None:
        self.session_id = "s-card"
        self.turn_id = "t-card"
        self.workspace_id = "ws"

    def event_fields(self) -> dict:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "workspace_id": self.workspace_id,
        }


def test_agent_card_frame_round_trips_unicode() -> None:
    card = normalize_card({
        "schema_version": 1,
        "card_type": "delivery",
        "card_id": "d-1",
        "data": {"verdict": "COMPLETED", "message": "Crusor — Build 🚀 क्रूसोर"},
    }, session_id="s", turn_id="t")
    frame = {"type": CARD_EVENT_NAME, "session_id": "s", "card": card}
    decoded = decode_line(encode(frame))
    assert decoded["card"]["data"]["message"] == "Crusor — Build 🚀 क्रूसोर"


def test_all_required_card_types_are_declared() -> None:
    assert CARD_TYPES == {
        "activity", "plan", "file_change", "approval", "tool",
        "test_results", "verification", "delivery", "cost",
    }


def test_unknown_card_type_is_safe_and_visible() -> None:
    card = normalize_card({
        "schema_version": 1, "card_type": "evil_component", "card_id": "x",
        "data": {"html": "<script>alert(1)</script>"},
    }, session_id="s", turn_id="t")
    assert card is not None
    assert card["supported"] is False
    assert card["card_type"] == "unsupported"
    assert card["declared_type"] == "evil_component"
    assert card["data"] == {}


def test_invalid_envelope_and_versions_are_rejected() -> None:
    assert normalize_card("not-a-card") is None
    assert normalize_card({"schema_version": 2, "card_type": "plan", "card_id": "x"}) is None
    assert normalize_card({"schema_version": 1, "card_type": "plan", "card_id": ""}) is None


def test_card_data_is_bounded_and_prototypes_are_dropped() -> None:
    card = normalize_card({
        "schema_version": 1, "card_type": "tool", "card_id": "t-1",
        "data": {
            "__proto__": {"polluted": True},
            "constructor": {"bad": True},
            "name": "x" * 20_000,
        },
    }, session_id="s", turn_id="t")
    assert "polluted" not in card["data"]
    assert "constructor" not in card["data"]
    assert len(card["data"]["name"]) <= 8_001


def test_plan_and_approval_cards_use_typed_event_data() -> None:
    plan = card_for_frame({
        "type": "plan_updated", "session_id": "s", "turn_id": "t",
        "steps": [{"text": "Inspect", "status": "completed"}],
        "summary": "Ship",
    })
    assert plan["card_type"] == "plan"
    assert plan["data"]["steps"][0]["status"] == "completed"

    approval = card_for_frame({
        "type": "safety_request", "session_id": "s", "turn_id": "t",
        "tool_id": "tool-1", "name": "write_file",
        "diff": {"path": "hello.md", "operation": "create", "unified": "+ok"},
    })
    assert approval["card_type"] == "approval"
    assert approval["data"]["status"] == "pending"
    assert "hello.md" in approval["data"]["diff"]


def test_verification_and_cost_distinguish_states() -> None:
    verified = card_for_frame({
        "type": "verification_updated", "session_id": "s", "turn_id": "t",
        "verification_status": "verified", "verified_requirements": ["a"],
        "unverified_requirements": [],
    })
    assert verified["data"]["status"] == "verified"
    assert verified["data"]["verified"] == ["a"]

    cost = card_for_frame({
        "type": "telemetry", "session_id": "s", "turn_id": "t",
        "input_tokens": 3, "output_tokens": 2, "cost_inr": None,
        "cost_certainty": "unknown",
    })
    assert cost["card_type"] == "cost"
    assert cost["data"]["certainty"] == "unknown"


def test_delivery_card_consumes_canonical_receipt() -> None:
    card = card_for_frame({
        "type": "turn_done", "session_id": "s", "turn_id": "t",
        "receipt": {
            "terminal_status": "completed", "engineering_verdict": "COMPLETED",
            "verification_status": "verified", "changed_files": ["hello.md"],
            "tests": {"executed": ["3"], "passed": ["3"], "failed": []},
            "approval_receipts": [{"id": "a"}],
            "mutation_receipts": [{"id": "m"}],
        },
    })
    assert card["card_type"] == "delivery"
    assert card["data"]["verdict"] == "COMPLETED"
    assert card["data"]["approvals"] == 1
    assert card["data"]["mutations"] == 1


def test_tool_end_can_project_tool_and_file_change_cards() -> None:
    cards = card_frames_for_frame({
        "type": "tool_call_end", "session_id": "s", "turn_id": "t",
        "tool_id": "w-1", "name": "write_file", "status": "completed",
        "result": {"path": "hello.md", "lines_added": 4, "lines_removed": 0},
    })
    types = [card["card_type"] for card in cards]
    assert types == ["tool", "file_change"]
    assert cards[1]["data"]["added"] == 4


def _run_fixture(tmp_path: Path, *, approve: bool, cancelled=None) -> tuple[list[dict], dict]:
    frames: list[dict] = []
    terminal: dict = {}

    def emit(frame: dict) -> None:
        frames.append(frame)

    def finalize(**kwargs) -> dict:
        return {"status": kwargs.get("status", "completed"), "missing": []}

    def emit_terminal(frame: dict) -> None:
        terminal.update(frame)
        frames.append(frame)

    identity = _Identity()
    if not approve:
        def trigger_cancel():
            time.sleep(0.3)
            return True
        return frames, terminal

    def approve_soon() -> None:
        from src.dashboard.event_bus import approval_queue

        deadline = time.time() + 5
        while time.time() < deadline:
            pending = approval_queue.get_pending("s-card")
            if pending:
                approval_queue.resolve(pending[0]["id"], True, session_id="s-card")
                return
            time.sleep(0.02)

    thread = threading.Thread(target=approve_soon, daemon=True)
    thread.start()
    run_scripted_turn(
        emit=emit,
        identity=identity,
        workspace=str(tmp_path),
        session_id="s-card",
        prompt="Create hello.md",
        finalize_evidence=finalize,
        emit_terminal=emit_terminal,
        touch_turn=lambda sid, text: None,
        cancelled=cancelled or (lambda sid: False),
    )
    return frames, terminal


def test_scripted_turn_streams_cards_and_writes_utf8(tmp_path: Path) -> None:
    frames, terminal = _run_fixture(tmp_path, approve=True)

    assert terminal["type"] == "turn_done"
    assert terminal["completed"] is True
    assert terminal["receipt"]["verification_status"] == "verified"

    tokens = [frame["text"] for frame in frames if frame.get("type") == "token"]
    assert "".join(tokens) == STREAM_TEXT
    assert len(tokens) == len(set(tokens)) or all(tokens.count(token) == 1 for token in set(tokens))

    cards = [frame["card"] for frame in frames if frame.get("type") == "agent_card"]
    types = {card["card_type"] for card in cards}
    assert {"activity", "plan", "tool", "approval", "file_change",
            "test_results", "verification", "delivery", "cost"} <= types
    approval_states = [c["data"]["status"] for c in cards
                       if c["card_type"] == "approval"]
    assert "pending" in approval_states and "approved" in approval_states

    assert (tmp_path / "hello.md").read_bytes() == STREAM_TEXT.encode("utf-8")
    assert (tmp_path / "hello.md").read_text(encoding="utf-8") == STREAM_TEXT


def test_scripted_turn_cancels_without_writing(tmp_path: Path) -> None:
    frames: list[dict] = []
    terminal: dict = {}

    run_scripted_turn(
        emit=frames.append,
        identity=_Identity(),
        workspace=str(tmp_path),
        session_id="s-card",
        prompt="Create hello.md",
        finalize_evidence=lambda **kw: {"status": kw.get("status", "completed")},
        emit_terminal=lambda frame: (terminal.update(frame), frames.append(frame)),
        touch_turn=lambda sid, text: None,
        cancelled=lambda sid: True,
    )
    assert terminal["cancelled"] is True
    assert not (tmp_path / "hello.md").exists()

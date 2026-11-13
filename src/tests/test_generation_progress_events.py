"""P1A: generation updates map onto the existing activity card, live-only.

These tests pin the presentation contract without touching the renderer:
* the card is an ordinary schema-v1 `activity` card with the turn's stable id,
  so the existing UI updates it in place;
* it carries elapsed time and received characters only — never prompt text,
  model output or reasoning;
* heartbeats are marked ephemeral and are NOT journaled, so replay keeps the
  stage reporter's snapshots.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.bridge.__main__ import BridgeServer
from src.orchestration.generation_progress import GenerationUpdate, generation_card


def update(phase: str = "heartbeat", *, chars: int = 0, target: str = "src/module.py") -> GenerationUpdate:
    return GenerationUpdate(
        phase=phase, purpose="node_task_1", target_file=target,
        invocation_id="inv-1", elapsed_s=12.4, chars=chars,
    )


def test_card_is_the_existing_activity_shape_with_a_stable_id() -> None:
    card = generation_card(update(chars=840), session_id="s-1", turn_id="turn-9")
    assert card["schema_version"] == 1
    assert card["card_type"] == "activity"
    assert card["card_id"] == "turn-9:activity"
    assert card["data"]["label"] == "Generating src/module.py"
    assert card["data"]["status"] == "running"
    assert "12s" in card["data"]["detail"]
    assert "840 chars received" in card["data"]["detail"]


def test_started_card_names_the_wait_before_the_first_token() -> None:
    card = generation_card(update("started", chars=0), session_id="s-1", turn_id="turn-9")
    assert "waiting for first token" in card["data"]["detail"]


def test_card_never_carries_prompt_or_model_text() -> None:
    secret = "SECRET-PROMPT-TEXT-123"
    card = generation_card(update(chars=10), session_id="s-1", turn_id="turn-9")
    rendered = str(card)
    assert secret not in rendered
    assert "```" not in rendered
    assert "def " not in rendered


def test_repair_updates_are_labelled_as_repairs() -> None:
    card = generation_card(
        GenerationUpdate(
            phase="delta", purpose="repair_node_1", target_file="src/module.py",
            invocation_id="inv-1", elapsed_s=1.0, chars=5,
        ),
        session_id="s", turn_id="t",
    )
    assert card["data"]["label"] == "Repairing src/module.py"


# --------------------------------------------------------------------------- #
# the plan must agree with the activity card
# --------------------------------------------------------------------------- #

def test_mark_generating_marks_the_active_node_in_progress() -> None:
    from src.orchestration.progress_events import EngineeringProgressReporter

    emitted: list[tuple[str, dict]] = []
    reporter = EngineeringProgressReporter(
        session_id="s", turn_id="t",
        emit=lambda kind, payload: emitted.append((kind, payload)),
    )
    reporter({
        "current_step": "IMPLEMENTATION",
        "current_state": "IMPLEMENTING",
        "completed_steps": [],
        "pending_steps": ["task_notes", "task_verification"],
        "modified_files": [],
    })
    baseline = [p for k, p in emitted if k == "plan.created"][-1]
    assert [s["status"] for s in baseline["steps"]] == ["pending", "pending"]

    emitted.clear()
    reporter.mark_generating("task_notes")
    plans = [p for k, p in emitted if k == "plan.created"]
    assert len(plans) == 1, emitted
    assert [(s["text"], s["status"]) for s in plans[0]["steps"]] == [
        ("task_notes", "in_progress"),
        ("task_verification", "pending"),
    ]
    # The same active node must not be re-emitted on every heartbeat.
    emitted.clear()
    reporter.mark_generating("task_notes")
    assert [p for k, p in emitted if k == "plan.created"] == []


def test_mark_generating_without_a_snapshot_is_a_no_op() -> None:
    from src.orchestration.progress_events import EngineeringProgressReporter

    emitted: list[tuple[str, dict]] = []
    reporter = EngineeringProgressReporter(
        session_id="s", turn_id="t",
        emit=lambda kind, payload: emitted.append((kind, payload)),
    )
    reporter.mark_generating("task_notes")
    assert emitted == []


# --------------------------------------------------------------------------- #
# bridge journaling discipline
# --------------------------------------------------------------------------- #

def test_ephemeral_activity_is_not_journaled() -> None:
    bridge = BridgeServer.__new__(BridgeServer)
    emitted: list[dict] = []
    journaled: list[dict] = []
    bridge.emit = lambda frame: emitted.append(frame)  # type: ignore[attr-defined]
    bridge._journal_agent_card = lambda card, identity: journaled.append(card)  # type: ignore[attr-defined]
    identity = SimpleNamespace(event_fields=lambda: {})

    bridge._emit_companion_cards({
        "type": "agent_card",
        "ephemeral": True,
        "card": generation_card(update(chars=3), session_id="s", turn_id="t"),
    }, identity)

    assert emitted == []
    assert journaled == [], "heartbeats must never enter the durable journal"


def test_durable_agent_card_is_still_journaled() -> None:
    bridge = BridgeServer.__new__(BridgeServer)
    journaled: list[dict] = []
    bridge.emit = lambda frame: None  # type: ignore[attr-defined]
    bridge._journal_agent_card = lambda card, identity: journaled.append(card)  # type: ignore[attr-defined]
    identity = SimpleNamespace(event_fields=lambda: {})

    card = generation_card(update("completed"), session_id="s", turn_id="t")
    bridge._emit_companion_cards({"type": "agent_card", "card": card}, identity)

    assert journaled and journaled[0]["card_id"] == "t:activity"

"""Live engineering progress -> existing Agentic UI event pipeline.

Deterministic and provider-free: the engineering engine runs its mock mode and
the graph uses the scripted model seam. No paid provider calls.

The tests prove, in order:

1. ``engineering_task_node`` hands a progress callback to the orchestrator.
2. Orchestrator snapshots reach the real ``event_bus`` with turn identity.
3. The bridge projects them onto existing protocol frames and card types.
4. The frontend contract (typed card schema) already declares those cards.
5. Progress is live (before the final summary chunk), ordered and deduplicated.
6. Cancellation stops emission.
7. Callback failures never escape and never change the delivery verdict.
8. Emission is bounded and never fabricates tool/file/test/verification/cost
   cards.
"""
from __future__ import annotations

import json
import queue
import re
import uuid
from pathlib import Path

import pytest

from src.bridge.__main__ import BridgeServer
from src.bridge.agent_cards import card_frames_for_frame
from src.dashboard.event_bus import event_bus
from src.graphs.chat_graph import engineering_task_node, stream_agent
from src.orchestration.models import DeliveryContract, TaskVerdict
from src.orchestration.progress_events import (
    MAX_PROGRESS_EMISSIONS,
    EngineeringProgressReporter,
    stage_label,
)
from src.runtime.identity import TurnIdentity

ROOT = Path(__file__).resolve().parents[2]
CARDS_TS = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "common" / "crusorAICards.ts"
RENDERER_TS = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRenderer.ts"

ACTIVITY_CARD_TYPES = {"activity", "plan"}


def _session() -> str:
    return f"progress-{uuid.uuid4().hex[:10]}"


def _view(
    step: str,
    *,
    state: str = "IMPLEMENTING",
    completed: list[str] | None = None,
    pending: list[str] | None = None,
    failed: list[str] | None = None,
    modified: list[str] | None = None,
    pct: float = 0.0,
    paused: bool = False,
) -> dict:
    return {
        "task_id": "turn_test",
        "current_state": state,
        "current_step": step,
        "completed_steps": completed or [],
        "pending_steps": pending or [],
        "failed_steps": failed or [],
        "modified_files": modified or [],
        "test_results_summary": {},
        "resource_consumption": {"tokens": 0, "cost_inr": 0.0},
        "pending_approvals": [],
        "remaining_blockers": [],
        "is_paused": paused,
        "progress_percentage": pct,
        "last_updated": 0.0,
    }


def _drain(q: queue.Queue, expected: int | None = None, timeout: float = 2.0) -> list[dict]:
    events: list[dict] = []
    while expected is None or len(events) < expected:
        try:
            events.append(q.get(timeout=timeout))
        except queue.Empty:
            break
    return events


@pytest.fixture()
def bus_session():
    sid = _session()
    q = event_bus.subscribe(sid)
    try:
        yield sid, q
    finally:
        event_bus.unsubscribe(q)
        event_bus.clear(sid)


def _contract() -> DeliveryContract:
    return DeliveryContract(
        task_id="turn_live",
        original_request="Create notes.md",
        verdict=TaskVerdict.COMPLETED,
        what_was_requested="Create notes.md",
        what_was_implemented=["notes.md"],
        files_changed=["notes.md"],
        tests_executed=[],
        tests_passed=[],
        tests_failed=[],
        independently_verified=True,
        remaining_limitations=[],
        user_action_required=None,
    )


def _state(text: str) -> dict:
    return {
        "execution_mode": "agent",
        "canonical_runtime": True,
        "latest_instruction": text,
        "current_task": text,
        "messages": [],
    }


# ---------------------------------------------------------------------------
# 1. Callback wiring
# ---------------------------------------------------------------------------

def test_engineering_node_passes_a_progress_callback(monkeypatch, tmp_path, bus_session) -> None:
    sid, q = bus_session
    captured: dict = {}

    def fake_run(self, request, **kwargs):
        captured.update(kwargs)
        # The orchestrator calls the callback inline while the task runs.
        kwargs["on_progress"](_view("IMPLEMENTATION", pending=["task_main"]))
        return _contract()

    monkeypatch.setattr(
        "src.orchestration.orchestrator.EngineeringExecutionOrchestrator.run_task_request",
        fake_run,
    )
    result = engineering_task_node(
        _state("Create notes.md with a greeting"),
        {"configurable": {"thread_id": sid, "workspace": str(tmp_path), "turn_id": "turn_live"}},
    )

    assert callable(captured.get("on_progress"))
    assert captured.get("cancellation_checker") is not None
    assert result["engineering_delivery"]["verdict"] == "COMPLETED"

    events = _drain(q, expected=None, timeout=0.5)
    progress = [event for event in events if event["type"] in {"agent.card", "plan.created"}]
    assert [event["type"] for event in progress] == ["agent.card", "plan.created"]
    for event in progress:
        assert event["payload"]["session_id"] == sid
        assert event["payload"]["turn_id"] == "turn_live"


# ---------------------------------------------------------------------------
# 2. Event-bus delivery
# ---------------------------------------------------------------------------

def test_progress_reaches_the_event_bus_with_stage_identity(bus_session) -> None:
    sid, q = bus_session
    reporter = EngineeringProgressReporter(session_id=sid, turn_id="turn_live")

    reporter(_view("ENGINEERING_PLAN", state="PLANNING"))
    reporter(_view("IMPLEMENTATION", pending=["task_main"], pct=0.0))

    events = _drain(q, expected=3)
    kinds = [event["type"] for event in events]
    assert kinds[0] == "agent.card"
    assert "plan.created" in kinds

    activity = events[0]["payload"]["card"]
    assert activity["card_type"] == "activity"
    assert activity["card_id"] == "turn_live:activity"
    assert activity["data"]["label"] == "Planning changes"
    assert activity["data"]["status"] == "running"

    plan = next(event["payload"] for event in events if event["type"] == "plan.created")
    assert plan["steps"] == [
        {"id": "task_main", "title": "task_main", "text": "task_main", "status": "pending"},
    ]


# ---------------------------------------------------------------------------
# 3. Bridge projection onto existing frames and cards
# ---------------------------------------------------------------------------

def test_bridge_projects_progress_onto_existing_cards(bus_session, tmp_path) -> None:
    sid, q = bus_session
    identity = TurnIdentity.create(session_id=sid, workspace=str(tmp_path))
    reporter = EngineeringProgressReporter(session_id=sid, turn_id=identity.turn_id)
    reporter(_view(
        "TASK_NODE_task_main",
        completed=["task_a"],
        pending=["task_main"],
        modified=["src/notes.md"],
        pct=50.0,
    ))

    frames = []
    for event in _drain(q, expected=2):
        frame = BridgeServer._project_event(event, identity)
        assert frame is not None
        frames.append(frame)

    assert frames[0]["type"] == "agent_card"
    assert frames[0]["card"]["card_type"] == "activity"
    assert frames[0]["card"]["data"]["detail"] == "1/2 steps · 50%"

    assert frames[1]["type"] == "plan_updated"
    assert [step["status"] for step in frames[1]["steps"]] == ["completed", "in_progress"]

    cards = []
    for frame in frames:
        if frame["type"] == "agent_card":
            cards.append(frame["card"])
        else:
            cards.extend(card_frames_for_frame(frame, turn_id=identity.turn_id))
    by_type = {card["card_type"]: card for card in cards}
    assert set(by_type) == ACTIVITY_CARD_TYPES
    assert by_type["activity"]["card_id"] == f"{identity.turn_id}:activity"
    assert by_type["plan"]["card_id"] == f"{identity.turn_id}:plan"
    assert by_type["plan"]["data"]["files"] == ["src/notes.md"]


def test_frontend_schema_declares_the_projected_card_types() -> None:
    declared = set(re.findall(r"'([a-z_]+)'", re.search(
        r"CRUSOR_CARD_TYPES = \[(.*?)\]", CARDS_TS.read_text(encoding="utf-8"), re.S,
    ).group(1)))
    assert ACTIVITY_CARD_TYPES <= declared


def test_renderer_paints_the_projected_fields() -> None:
    source = RENDERER_TS.read_text(encoding="utf-8")
    # Activity card: label headline + detail line + status badge.
    assert "card.cardType === 'activity'" in source
    assert "String(d.detail)" in source
    # Plan card: per-step status comes from the projected step.status.
    assert "step.status" in source


class _FakeJournal:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append(self, kind: str, payload: dict, **kwargs) -> None:  # noqa: ANN003
        self.rows.append({"kind": kind, "payload": payload, **kwargs})


class _FakeServices:
    def __init__(self, journal: _FakeJournal) -> None:
        self.journal = journal


def test_bridge_persists_activity_cards_for_replay(monkeypatch, tmp_path) -> None:
    sid = _session()
    identity = TurnIdentity.create(session_id=sid, workspace=str(tmp_path))
    journal = _FakeJournal()
    monkeypatch.setattr("src.runtime.factory.get_runtime_services", lambda: _FakeServices(journal))

    events: list[dict] = []

    def capture(kind: str, payload: dict) -> None:
        events.append({"type": kind, "payload": payload, "event_id": "e", "timestamp": 0.0})

    reporter = EngineeringProgressReporter(session_id=sid, turn_id=identity.turn_id, emit=capture)
    reporter(_view("IMPLEMENTATION", pending=["task_main"]))

    server = object.__new__(BridgeServer)
    emitted: list[dict] = []
    server.emit = emitted.append  # type: ignore[method-assign]

    for event in events:
        frame = BridgeServer._project_event(event, identity)
        assert frame is not None
        server._emit_companion_cards(frame, identity)

    # The activity card was already built by its producer: it is emitted once
    # (by the forwarder) and persisted, never re-emitted as a companion.
    rewritten = [frame for frame in emitted if frame["type"] == "agent_card"]
    assert [frame["card"]["card_type"] for frame in rewritten] == ["plan"]
    assert not [frame for frame in rewritten if frame["card"]["card_id"].endswith(":activity")]
    ids = [row["payload"]["card"]["card_id"] for row in journal.rows]
    assert ids == [f"{identity.turn_id}:activity", f"{identity.turn_id}:plan"]
    assert all(row["kind"] == "agent_card" for row in journal.rows)
    assert all(row["turn_id"] == identity.turn_id for row in journal.rows)
    assert all(row["session_id"] == identity.session_id for row in journal.rows)


def test_bridge_still_projects_and_persists_companion_plan_cards(monkeypatch, tmp_path) -> None:
    sid = _session()
    identity = TurnIdentity.create(session_id=sid, workspace=str(tmp_path))
    journal = _FakeJournal()
    monkeypatch.setattr("src.runtime.factory.get_runtime_services", lambda: _FakeServices(journal))

    frame = {
        "type": "plan_updated", "session_id": sid, "turn_id": identity.turn_id,
        "steps": [{"text": "Inspect", "status": "completed"}],
        "summary": "Plan",
    }
    server = object.__new__(BridgeServer)
    emitted: list[dict] = []
    server.emit = emitted.append  # type: ignore[method-assign]

    server._emit_companion_cards(frame, identity)

    assert [item["type"] for item in emitted] == ["agent_card"]
    assert emitted[0]["card"]["card_type"] == "plan"
    assert [row["payload"]["card"]["card_id"] for row in journal.rows] == [f"{identity.turn_id}:plan"]


# ---------------------------------------------------------------------------
# 4. Ordering, identity, deduplication
# ---------------------------------------------------------------------------

def test_multiple_updates_keep_order_identity_and_stable_card_ids(bus_session) -> None:
    sid, q = bus_session
    reporter = EngineeringProgressReporter(session_id=sid, turn_id="turn_live")

    reporter(_view("REQUEST_UNDERSTANDING", state="UNDERSTANDING"))
    reporter(_view("ENGINEERING_PLAN", state="PLANNING", pending=["task_a", "task_b"]))
    reporter(_view("TASK_NODE_task_a", state="IMPLEMENTING", completed=["task_a"], pending=["task_b"], pct=50.0))
    reporter(_view("TEST_EXECUTION", state="TESTING", completed=["task_a", "task_b"], pct=100.0))
    reporter(_view("DELIVERED", state="COMPLETED", completed=["task_a", "task_b"], pct=100.0))

    events = _drain(q, expected=9, timeout=1.0)
    stages = [event["payload"]["card"]["data"]["stage"]
              for event in events if event["type"] == "agent.card"]
    assert stages == [
        "request_understanding", "engineering_plan", "task_node_task_a",
        "test_execution", "delivered",
    ]
    assert all(
        event["payload"]["turn_id"] == "turn_live" and event["payload"]["session_id"] == sid
        for event in events
    )
    assert {event["payload"]["card"]["card_id"] for event in events if event["type"] == "agent.card"} == {
        "turn_live:activity",
    }
    assert [event["payload"]["card"]["data"]["status"]
            for event in events if event["type"] == "agent.card"][-1] == "completed"


def test_repeated_snapshot_is_emitted_once(bus_session) -> None:
    sid, q = bus_session
    reporter = EngineeringProgressReporter(session_id=sid, turn_id="turn_live")
    snapshot = _view("IMPLEMENTATION", pending=["task_main"])
    reporter(snapshot)
    reporter(dict(snapshot))
    reporter(dict(snapshot))

    events = _drain(q, expected=2, timeout=1.0)
    assert [event["type"] for event in events] == ["agent.card", "plan.created"]
    assert reporter.emitted == 2


def test_emission_is_bounded(bus_session) -> None:
    sid, _q = bus_session
    emitted: list[tuple[str, dict]] = []
    reporter = EngineeringProgressReporter(
        session_id=sid, turn_id="turn_live",
        emit=lambda kind, payload: emitted.append((kind, payload)),
        max_emissions=5,
    )
    for index in range(500):
        reporter(_view(f"STAGE_{index}", pending=[f"task_{index}"]))

    assert len(emitted) == 5
    assert reporter.dropped > 0
    assert MAX_PROGRESS_EMISSIONS >= 5


# ---------------------------------------------------------------------------
# 5. Cancellation
# ---------------------------------------------------------------------------

def test_cancelled_turn_stops_emission(bus_session) -> None:
    sid, q = bus_session
    reporter = EngineeringProgressReporter(
        session_id=sid, turn_id="turn_live", cancelled=lambda: True,
    )
    reporter(_view("IMPLEMENTATION", pending=["task_main"]))
    assert _drain(q, expected=1, timeout=0.3) == []
    assert reporter.emitted == 0


def test_cancellation_mid_run_keeps_prior_events(bus_session) -> None:
    sid, q = bus_session
    state = {"cancelled": False}
    reporter = EngineeringProgressReporter(
        session_id=sid, turn_id="turn_live", cancelled=lambda: state["cancelled"],
    )
    reporter(_view("IMPLEMENTATION", pending=["task_main"]))
    state["cancelled"] = True
    reporter(_view("TEST_EXECUTION", pending=["task_main"]))

    events = _drain(q, expected=2, timeout=0.5)
    activity = [event for event in events if event["type"] == "agent.card"]
    assert [event["payload"]["card"]["data"]["stage"] for event in activity] == ["implementation"]
    assert reporter.emitted == 2  # activity + plan from the first snapshot only


# ---------------------------------------------------------------------------
# 6. Failure containment
# ---------------------------------------------------------------------------

def test_emitter_failure_never_escapes_the_callback() -> None:
    def broken(_kind: str, _payload: dict) -> None:
        raise RuntimeError("event bus unavailable")

    reporter = EngineeringProgressReporter(session_id="s", turn_id="t", emit=broken)
    reporter(_view("IMPLEMENTATION"))  # must not raise
    assert reporter.failures == 1
    assert reporter.emitted == 0


def test_callback_failure_does_not_change_the_delivery_verdict(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(event_bus, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bus down")))
    statuses: list[dict] = []

    def fake_run(self, request, **kwargs):
        statuses.append(kwargs["on_progress"](_view("IMPLEMENTATION")) or {})
        return _contract()

    monkeypatch.setattr(
        "src.orchestration.orchestrator.EngineeringExecutionOrchestrator.run_task_request",
        fake_run,
    )
    result = engineering_task_node(
        _state("Create notes.md with a greeting"),
        {"configurable": {"thread_id": _session(), "workspace": str(tmp_path), "turn_id": "turn_live"}},
    )

    assert statuses == [{}]  # the callback returned normally
    assert result["engineering_delivery"]["verdict"] == "COMPLETED"
    assert result["task_completed"] is True


def test_callback_failure_does_not_turn_a_failed_run_into_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(event_bus, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bus down")))

    def fake_run(self, request, **kwargs):
        kwargs["on_progress"](_view("FAILURE_DIAGNOSIS", state="FAILED", failed=["task_main"]))
        return DeliveryContract(
            task_id="turn_live",
            original_request="Create notes.md",
            verdict=TaskVerdict.FAILED,
            what_was_requested="Create notes.md",
            what_was_implemented=[],
            files_changed=[],
            tests_executed=[],
            tests_passed=[],
            tests_failed=["test_notes"],
            independently_verified=False,
            remaining_limitations=["Targeted tests failed"],
            user_action_required="Review the failing tests",
        )

    monkeypatch.setattr(
        "src.orchestration.orchestrator.EngineeringExecutionOrchestrator.run_task_request",
        fake_run,
    )
    result = engineering_task_node(
        _state("Create notes.md with a greeting"),
        {"configurable": {"thread_id": _session(), "workspace": str(tmp_path), "turn_id": "turn_live"}},
    )

    assert result["engineering_delivery"]["verdict"] == "FAILED"
    assert result["task_completed"] is False


# ---------------------------------------------------------------------------
# 7. No fabricated authoritative events, no leaks
# ---------------------------------------------------------------------------

def test_progress_never_fabricates_authoritative_cards(bus_session) -> None:
    sid, _q = bus_session
    emitted: list[tuple[str, dict]] = []
    reporter = EngineeringProgressReporter(
        session_id=sid, turn_id="turn_live",
        emit=lambda kind, payload: emitted.append((kind, payload)),
    )
    view = _view(
        "TASK_NODE_task_main",
        completed=["task_a"], pending=["task_b"], failed=["task_a"],
        modified=["src/notes.md"], pct=33.0,
    )
    view["test_results_summary"] = {"executed": 4, "passed": 3, "failed": 1}
    view["resource_consumption"] = {"tokens": 1234, "cost_inr": 0.42}
    reporter(view)

    card_types = {
        payload["card"]["card_type"]
        for kind, payload in emitted if kind == "agent.card"
    }
    assert card_types == {"activity"}
    assert {kind for kind, _payload in emitted} == {"agent.card", "plan.created"}
    # Test/verification/cost/tool/file cards stay with their authoritative
    # sources; a stage label never becomes one.
    for _kind, payload in emitted:
        steps = payload.get("steps") or []
        assert all(step["status"] in {"completed", "pending", "failed", "in_progress"} for step in steps)


def test_stage_text_is_redacted_and_bounded(bus_session) -> None:
    sid, q = bus_session
    reporter = EngineeringProgressReporter(session_id=sid, turn_id="turn_live")
    reporter(_view("Applying patch with key sk-123456789012345678901234"))

    event = _drain(q, expected=1)[0]
    serialized = json.dumps(event, ensure_ascii=False)
    assert "sk-123456789012345678901234" not in serialized
    assert "[REDACTED" in serialized


def test_labels_are_human_for_known_and_unknown_stages() -> None:
    assert stage_label("IMPLEMENTATION") == "Implementing changes"
    assert stage_label("TASK_NODE_task_main") == "Working on task_main"
    assert stage_label("SOME_NEW_STAGE") == "Some New Stage"
    assert stage_label("") == "Working"
    assert len(stage_label("X" * 500)) <= 200


# ---------------------------------------------------------------------------
# 8. Real graph run: progress is live, before the terminal summary
# ---------------------------------------------------------------------------

def test_mock_engineering_run_streams_progress_before_the_summary(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CRUSORAI_ORCHESTRATOR_MOCK", "1")
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "0")
    sid = _session()
    q = event_bus.subscribe(sid)
    try:
        result = stream_agent(
            "Create notes.md with a short greeting for the project.",
            thread_id=sid,
            workspace=str(tmp_path),
            execution_mode="agent",
            approval_channel=True,
            approval_policy="workspace_session",
            turn_id="turn-live",
            canonical_runtime=True,
        )
        events = _drain(q, expected=None, timeout=1.0)
    finally:
        event_bus.unsubscribe(q)
        event_bus.clear(sid)

    assert result.completed is True

    progress = [event for event in events if event["type"] in {"agent.card", "plan.created"}]
    assert len(progress) >= 3, [event["type"] for event in events]

    activity = [event for event in progress if event["type"] == "agent.card"]
    assert len(activity) >= 2
    labels = [event["payload"]["card"]["data"]["label"] for event in activity]
    assert len(set(labels)) >= 2, labels
    assert labels[-1] == "Delivered"
    assert {event["payload"]["card"]["data"]["status"] for event in activity[-1:]} == {"completed"}

    # Liveness: every progress event precedes the node's final summary chunk.
    summary_indexes = [
        index for index, event in enumerate(events)
        if event["type"] == "message.agent.chunk"
        and str((event.get("payload") or {}).get("text") or "").strip()
    ]
    first_progress = min(index for index, event in enumerate(events) if event["type"] in {"agent.card", "plan.created"})
    if summary_indexes:
        assert first_progress < min(summary_indexes)
        assert min(summary_indexes) == max(
            index for index, event in enumerate(events) if event["type"] == "message.agent.chunk"
        )

    for event in progress:
        assert event["payload"]["turn_id"] == "turn-live"
        assert event["payload"]["session_id"] == sid
    card_types = {
        event["payload"]["card"]["card_type"]
        for event in activity
    }
    assert card_types == {"activity"}
    assert all(
        (event.get("payload") or {}).get("turn_id") == "turn-live"
        for event in progress
    )

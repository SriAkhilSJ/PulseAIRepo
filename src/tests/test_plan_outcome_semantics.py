"""Truthful plan outcome states: completed / failed / blocked / cancelled.

Deterministic and provider-free. The real scheduler, context manager and
progress projection are exercised with explicit executors and predicates; no
model call is made.

The contract keeps the original four states and adds exactly two more that the
real execution path can produce:

    pending | in_progress | completed | failed | blocked | cancelled

* ``blocked`` — the work never ran (dependency/upstream failure or a halted
  pipeline). It is not a failure of that work.
* ``cancelled`` — the user's Stop interrupted the node or prevented it from
  starting.

The scheduler has no intentional-skip outcome of its own (its only SKIPPED
case is a failed prerequisite), so SKIPPED maps to ``blocked`` rather than
being conflated with ``failed``.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from src.bridge.__main__ import BridgeServer
from src.bridge.agent_cards import card_frames_for_frame, normalize_card
from src.llm.factory import TurnCancelledError
from src.orchestration.context_manager import AdaptiveContextManager
from src.orchestration.models import (
    EngineeringPlanDAG,
    EngineeringTaskNode,
    TaskExecutionState,
)
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.orchestration.progress_events import EngineeringProgressReporter, plan_event
from src.orchestration.scheduler import DependencyAwareScheduler
from src.orchestration.visibility import DesktopVisibilityReporter
from src.runtime.identity import TurnIdentity

ROOT = Path(__file__).resolve().parents[2]
RENDERER_TS = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRenderer.ts"
SERVICE_TS = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRendererService.ts"


def _node(node_id: str, dependencies: list[str] | None = None) -> EngineeringTaskNode:
    return EngineeringTaskNode(
        node_id=node_id,
        description=f"Implement {node_id}",
        objective=node_id,
        dependencies=list(dependencies or []),
        target_files=[f"{node_id}.py"],
    )


def _context(tmp_path: Path, *specs: tuple[str, list[str]]) -> tuple[AdaptiveContextManager, EngineeringPlanDAG]:
    context = AdaptiveContextManager(f"task_{uuid.uuid4().hex[:8]}", str(tmp_path))
    plan = EngineeringPlanDAG(task_id=context.task_id)
    for node_id, deps in specs:
        plan.add_node(_node(node_id, deps))
    context.record_plan(plan)
    return context, plan


def _run(
    context: AdaptiveContextManager,
    plan: EngineeringPlanDAG,
    executor,
    *,
    is_cancelled=None,
) -> tuple[bool, list[EngineeringTaskNode]]:
    orchestrator = object.__new__(EngineeringExecutionOrchestrator)
    snapshots: list[EngineeringTaskNode] = []

    def emit(_step: str) -> None:
        pass

    def on_progress(node: EngineeringTaskNode) -> None:
        snapshots.append(_copy_node(node))
        orchestrator._record_scheduler_progress(context, emit, node)

    succeeded = DependencyAwareScheduler().execute_plan(
        plan, executor, on_progress=on_progress, is_cancelled=is_cancelled,
    )
    return succeeded, snapshots


def _copy_node(node: EngineeringTaskNode) -> EngineeringTaskNode:
    return EngineeringTaskNode(
        node_id=node.node_id,
        description=node.description,
        objective=node.objective,
        dependencies=list(node.dependencies),
        target_files=list(node.target_files),
        status=node.status,
        error_message=node.error_message,
    )


def _view(context: AdaptiveContextManager, step: str) -> dict:
    plan = context.context.plan
    total = list(plan.nodes) if plan else []
    accounted = (
        set(context.context.completed_steps)
        | set(context.context.outstanding_failures)
        | set(context.context.blocked_steps)
        | set(context.context.cancelled_steps)
    )
    return DesktopVisibilityReporter.compute_view(
        task_id=context.task_id,
        state=TaskExecutionState.IMPLEMENTING,
        current_step=step,
        completed_steps=list(context.context.completed_steps),
        pending_steps=[node for node in total if node not in accounted],
        failed_steps=list(context.context.outstanding_failures),
        blocked_steps=list(context.context.blocked_steps),
        cancelled_steps=list(context.context.cancelled_steps),
        modified_files=[],
    ).to_safe_dict()


def _statuses(context: AdaptiveContextManager, step: str = "TASK_NODE_task_a") -> dict[str, str]:
    event = plan_event(_view(context, step), session_id="s", turn_id="turn")
    return {step_item["id"]: step_item["status"] for step_item in (event or {}).get("steps", [])}


# ---------------------------------------------------------------------------
# 1-2: the two states that already existed
# ---------------------------------------------------------------------------

def test_successful_execution_is_completed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    succeeded, snapshots = _run(context, plan, lambda _node: True)

    assert succeeded is True
    assert context.context.completed_steps == ["task_a"]
    assert _statuses(context) == {"task_a": "completed"}
    assert snapshots[0].status == "IN_PROGRESS"
    assert snapshots[-1].status == "COMPLETED"


def test_genuine_failure_is_failed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    succeeded, _snapshots = _run(context, plan, lambda _node: False)

    assert succeeded is False
    assert context.context.outstanding_failures == ["task_a"]
    assert context.context.blocked_steps == []
    assert context.context.cancelled_steps == []
    assert _statuses(context) == {"task_a": "failed"}


def test_exception_without_cancellation_is_failed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))

    def boom(_node: EngineeringTaskNode) -> bool:
        raise RuntimeError("generation failed")

    succeeded, _snapshots = _run(context, plan, boom, is_cancelled=lambda: False)

    assert succeeded is False
    assert context.context.outstanding_failures == ["task_a"]
    assert _statuses(context) == {"task_a": "failed"}


# ---------------------------------------------------------------------------
# 3-6: the new truthful states
# ---------------------------------------------------------------------------

def test_halted_pipeline_blocks_unrun_work(tmp_path: Path) -> None:
    """Real orchestrator: first node fails, dependent is blocked, not failed."""
    workspace = Path(tmp_path)
    (workspace / "README.md").write_text("# demo\n", encoding="utf-8")
    orchestrator = EngineeringExecutionOrchestrator(
        workspace_root=str(workspace), tenant_id="outcomes", mock_mode=True,
    )
    events: list[tuple[str, dict]] = []
    views: list[dict] = []
    reporter = EngineeringProgressReporter(
        session_id="session-outcomes", turn_id="turn-outcomes",
        emit=lambda kind, payload: events.append((kind, payload)),
    )

    def failing(_node: EngineeringTaskNode) -> bool:
        return False

    def on_progress(view: dict) -> None:
        views.append(view)
        reporter(view)

    with pytest.raises(RuntimeError):
        orchestrator.run_task(
            task_prompt="Create notes.md with a short greeting",
            task_id="task_outcomes",
            custom_executor=failing,
            on_progress=on_progress,
        )

    plan_payloads = [payload for kind, payload in events if kind == "plan.created"]
    assert plan_payloads
    final = {step["id"]: step["status"] for step in plan_payloads[-1]["steps"]}
    assert "failed" in final.values(), final
    assert "blocked" in final.values(), final
    assert "completed" not in final.values(), final
    # The blocked node never ran; the failed node did.
    assert views[-1]["blocked_steps"], views[-1]
    assert views[-1]["failed_steps"], views[-1]


def test_cancellation_during_execution_is_cancelled(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    state = {"cancelled": False}

    def cancel_mid_node(_node: EngineeringTaskNode) -> bool:
        state["cancelled"] = True
        raise TurnCancelledError("Task execution cancelled by user")

    succeeded, _snapshots = _run(
        context, plan, cancel_mid_node, is_cancelled=lambda: state["cancelled"],
    )

    assert succeeded is False
    assert context.context.completed_steps == []
    assert context.context.outstanding_failures == []
    assert context.context.cancelled_steps == ["task_a"]
    assert _statuses(context) == {"task_a": "cancelled"}


def test_cancellation_before_execution_is_cancelled_without_running(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    executed: list[str] = []

    def executor(node: EngineeringTaskNode) -> bool:
        executed.append(node.node_id)
        return True

    succeeded, snapshots = _run(context, plan, executor, is_cancelled=lambda: True)

    assert succeeded is False
    assert executed == []
    assert context.context.cancelled_steps == ["task_a"]
    assert _statuses(context) == {"task_a": "cancelled"}
    assert snapshots and snapshots[0].status == "CANCELLED"


def test_cancellation_between_planned_nodes_cancels_remaining(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []), ("task_b", ["task_a"]))
    state = {"cancelled": False}

    def executor(node: EngineeringTaskNode) -> bool:
        if node.node_id == "task_a":
            state["cancelled"] = True  # Stop lands as task_a settles
        return True

    succeeded, _snapshots = _run(
        context, plan, executor, is_cancelled=lambda: state["cancelled"],
    )

    assert succeeded is False
    assert context.context.completed_steps == ["task_a"]
    assert context.context.cancelled_steps == ["task_b"]


def test_cancellation_while_awaiting_approval_is_cancelled(tmp_path: Path) -> None:
    """Real orchestrator: Stop while the approval wait is pending."""
    from src.orchestration.approval_gateway import ApprovalDenied

    workspace = Path(tmp_path)
    (workspace / "README.md").write_text("# demo\n", encoding="utf-8")
    orchestrator = EngineeringExecutionOrchestrator(
        workspace_root=str(workspace), tenant_id="outcomes-cancel", mock_mode=True,
    )
    state = {"cancelled": False}
    events: list[tuple[str, dict]] = []
    reporter = EngineeringProgressReporter(
        session_id="session-cancel", turn_id="turn-cancel",
        emit=lambda kind, payload: events.append((kind, payload)),
    )

    def abandoned_approval(_node: EngineeringTaskNode) -> bool:
        state["cancelled"] = True
        raise ApprovalDenied("turn_cancelled")

    with pytest.raises(ApprovalDenied):
        orchestrator.run_task(
            task_prompt="Create notes.md with a short greeting",
            task_id="task_cancel",
            custom_executor=abandoned_approval,
            on_progress=reporter,
            cancellation_checker=lambda: state["cancelled"],
        )

    plan_payloads = [payload for kind, payload in events if kind == "plan.created"]
    assert plan_payloads
    final = {step["id"]: step["status"] for step in plan_payloads[-1]["steps"]}
    assert final, final
    assert set(final.values()) == {"cancelled"}, final
    assert "completed" not in final.values() and "failed" not in final.values()


def test_skipped_is_not_conflated_with_failure() -> None:
    """SKIPPED means "could not run"; the contract maps it to blocked."""
    context = AdaptiveContextManager(f"task_{uuid.uuid4().hex[:8]}", str(Path.cwd()))
    skipped = _node("task_b")
    skipped.status = "SKIPPED"
    skipped.error_message = "Prerequisite task failed"

    assert context.record_task_outcome(skipped) == "BLOCKED"
    assert context.context.blocked_steps == ["task_b"]
    assert context.context.outstanding_failures == []
    assert context.context.completed_steps == []

    blocked = _node("task_c")
    blocked.status = "BLOCKED"
    assert context.record_task_outcome(blocked) == "BLOCKED"
    assert context.context.blocked_steps == ["task_b", "task_c"]


# ---------------------------------------------------------------------------
# 7: retries
# ---------------------------------------------------------------------------

def test_retry_moves_failed_blocked_and_cancelled_to_completed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    context.record_task_failure("task_a")
    context.record_task_outcome(_node("task_a"))  # PENDING/IN_PROGRESS: no change
    assert context.context.outstanding_failures == ["task_a"]

    context.record_task_completion("task_a")
    assert context.context.completed_steps == ["task_a"]
    assert context.context.outstanding_failures == []
    assert context.context.blocked_steps == []
    assert context.context.cancelled_steps == []

    context.record_task_blocked("task_b")
    context.record_task_completion("task_b")
    assert context.context.completed_steps == ["task_a", "task_b"]
    assert context.context.blocked_steps == []

    context.record_task_cancelled("task_c")
    context.record_task_completion("task_c")
    assert context.context.completed_steps == ["task_a", "task_b", "task_c"]
    assert context.context.cancelled_steps == []


def test_retry_does_not_duplicate_completion(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    _run(context, plan, lambda _node: True)
    _run(context, plan, lambda _node: True)

    assert context.context.completed_steps == ["task_a"]


# ---------------------------------------------------------------------------
# 8: persistence and journal replay
# ---------------------------------------------------------------------------

def test_outcome_buckets_survive_context_reload(tmp_path: Path) -> None:
    context, _plan = _context(
        tmp_path, ("task_ok", []), ("task_bad", []), ("task_blocked", []), ("task_cancelled", []),
    )
    context.record_task_completion("task_ok")
    context.record_task_failure("task_bad")
    context.record_task_blocked("task_blocked")
    context.record_task_cancelled("task_cancelled")

    reloaded = AdaptiveContextManager(context.task_id, str(tmp_path))
    assert reloaded.context.completed_steps == ["task_ok"]
    assert reloaded.context.outstanding_failures == ["task_bad"]
    assert reloaded.context.blocked_steps == ["task_blocked"]
    assert reloaded.context.cancelled_steps == ["task_cancelled"]


class _FakeJournal:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append(self, kind: str, payload: dict, **kwargs) -> None:  # noqa: ANN003
        self.rows.append({"kind": kind, "payload": payload, **kwargs})


class _FakeServices:
    def __init__(self, journal: _FakeJournal) -> None:
        self.journal = journal


def test_all_outcome_states_survive_the_journal_projection(tmp_path: Path, monkeypatch) -> None:
    context, _plan = _context(
        tmp_path, ("task_ok", []), ("task_bad", []), ("task_blocked", []),
        ("task_cancelled", []), ("task_active", []),
    )
    context.record_task_completion("task_ok")
    context.record_task_failure("task_bad")
    context.record_task_blocked("task_blocked")
    context.record_task_cancelled("task_cancelled")

    event = plan_event(_view(context, "TASK_NODE_task_active"), session_id="session-outcomes", turn_id="turn-outcomes")
    assert event is not None
    assert {step["status"] for step in event["steps"]} == {
        "completed", "failed", "blocked", "cancelled", "in_progress",
    }

    identity = TurnIdentity.create(session_id="session-outcomes", workspace=str(tmp_path))
    journal = _FakeJournal()
    monkeypatch.setattr("src.runtime.factory.get_runtime_services", lambda: _FakeServices(journal))
    server = object.__new__(BridgeServer)
    emitted: list[dict] = []
    server.emit = emitted.append  # type: ignore[method-assign]

    frame = BridgeServer._project_event(
        {"type": "plan.created", "payload": event, "event_id": "e1", "timestamp": 1.0},
        identity,
    )
    assert frame is not None and frame["type"] == "plan_updated"
    server._emit_companion_cards(frame, identity)

    card = emitted[0]["card"]
    statuses = {step["text"]: step["status"] for step in card["data"]["steps"]}
    assert statuses == {
        "task_ok": "completed",
        "task_bad": "failed",
        "task_blocked": "blocked",
        "task_cancelled": "cancelled",
        "task_active": "in_progress",
    }
    # The durable row carries the same statuses: replay cannot flatten them.
    assert journal.rows[0]["payload"]["card"]["data"]["steps"] == card["data"]["steps"]


# ---------------------------------------------------------------------------
# 9: backward compatibility
# ---------------------------------------------------------------------------

def test_legacy_four_status_plan_cards_stay_valid(tmp_path: Path) -> None:
    legacy = {
        "schema_version": 1,
        "card_type": "plan",
        "card_id": "turn-legacy:plan",
        "data": {
            "summary": "Legacy plan",
            "steps": [
                {"text": "a", "status": "completed"},
                {"text": "b", "status": "in_progress"},
                {"text": "c", "status": "pending"},
                {"text": "d", "status": "failed"},
            ],
        },
    }
    card = normalize_card(legacy, session_id="s", turn_id="turn-legacy")
    assert card is not None and card["supported"] is True
    assert [step["status"] for step in card["data"]["steps"]] == [
        "completed", "in_progress", "pending", "failed",
    ]


def test_frontend_contract_lists_all_six_states_and_marks() -> None:
    service = SERVICE_TS.read_text(encoding="utf-8")
    assert "const PLAN_STATUSES: readonly string[] = ['pending', 'in_progress', 'completed', 'failed', 'blocked', 'cancelled'];" in service

    renderer = RENDERER_TS.read_text(encoding="utf-8")
    assert "readonly status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'blocked' | 'cancelled';" in renderer
    # Strip glyphs and typed-card marks both know the new states.
    assert "status === 'blocked'" in renderer and "status === 'cancelled'" in renderer
    assert "case 'blocked': return '⊘';" in renderer
    assert "case 'cancelled': return '–';" in renderer


def test_missing_outcome_keys_in_an_old_snapshot_do_not_break_projection() -> None:
    legacy_view = DesktopVisibilityReporter.compute_view(
        task_id="t",
        state=TaskExecutionState.IMPLEMENTING,
        current_step="TASK_NODE_task_a",
        completed_steps=["task_done"],
        pending_steps=["task_a"],
        failed_steps=[],
        modified_files=[],
    ).to_safe_dict()
    event = plan_event(legacy_view, session_id="s", turn_id="turn")
    assert event is not None
    assert {step["status"] for step in event["steps"]} == {"completed", "in_progress"}
    assert legacy_view["blocked_steps"] == [] and legacy_view["cancelled_steps"] == []

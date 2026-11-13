"""Truthful DAG task completion for the engineering plan.

Deterministic and provider-free: the orchestrator's model adapter runs in mock
mode (its pytest default) and node execution is driven by explicit executors
whose outcomes are the real scheduler inputs. No paid provider call is made.

Proves:

1. a genuinely successful node is recorded completed;
2. a failed node is never completed;
3. a cancelled node is never completed;
4. a blocked (skipped) dependent node is never completed;
5. retries never duplicate a completion entry;
6. several DAG nodes complete in real execution order;
7. the real orchestrator publishes pending -> in_progress -> completed plan
   transitions through the existing progress reporter;
8. activity updates keep streaming alongside the plan;
9. completed plan state survives the journal projection used by replay;
10. an ordinary chat turn produces no engineering node completion.
"""
from __future__ import annotations

import json
import queue
import uuid
from pathlib import Path

import pytest

from src.bridge.__main__ import BridgeServer
from src.bridge.agent_cards import card_frames_for_frame
from src.dashboard.event_bus import event_bus
from src.graphs.chat_graph import graph, stream_agent
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


def _run_plan(
    context: AdaptiveContextManager,
    plan: EngineeringPlanDAG,
    executor,
    *,
    views: list[dict] | None = None,
) -> tuple[bool, list[str]]:
    """Drive the real scheduler through the orchestrator's own callback."""
    orchestrator = object.__new__(EngineeringExecutionOrchestrator)
    steps: list[str] = []

    def emit(step: str) -> None:
        steps.append(step)
        if views is not None:
            views.append(_view(context, step))

    succeeded = DependencyAwareScheduler().execute_plan(
        plan,
        executor,
        on_progress=lambda node: orchestrator._record_scheduler_progress(context, emit, node),
    )
    return succeeded, steps


def _view(context: AdaptiveContextManager, step: str) -> dict:
    plan = context.context.plan
    total = list(plan.nodes) if plan else []
    completed = list(context.context.completed_steps)
    failed = list(context.context.outstanding_failures)
    return DesktopVisibilityReporter.compute_view(
        task_id=context.task_id,
        state=TaskExecutionState.IMPLEMENTING,
        current_step=step,
        completed_steps=completed,
        pending_steps=[s for s in total if s not in completed and s not in failed],
        failed_steps=failed,
        modified_files=[],
    ).to_safe_dict()


def _plan_statuses(context: AdaptiveContextManager, step: str = "TASK_NODE_task_a") -> dict[str, str]:
    event = plan_event(_view(context, step), session_id="s", turn_id="turn")
    return {step_item["id"]: step_item["status"] for step_item in (event or {}).get("steps", [])}


# ---------------------------------------------------------------------------
# 1-4: settled outcomes
# ---------------------------------------------------------------------------

def test_successful_node_is_recorded_completed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    views: list[dict] = []
    succeeded, steps = _run_plan(context, plan, lambda _node: True, views=views)

    assert succeeded is True
    assert context.context.completed_steps == ["task_a"]
    assert context.context.pending_steps == []
    assert context.context.outstanding_failures == []
    assert plan.nodes["task_a"].status == "COMPLETED"

    # The scheduler announces the start and the settled outcome, in order.
    assert steps == ["TASK_NODE_task_a", "TASK_NODE_task_a"]
    assert _plan_statuses(context) == {"task_a": "completed"}

    # Live transition: executing first, completed only after the outcome.
    assert views[0]["completed_steps"] == []
    assert views[1]["completed_steps"] == ["task_a"]
    assert views[0]["pending_steps"] == ["task_a"]
    assert views[1]["pending_steps"] == []


def test_failed_node_is_never_completed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    succeeded, _steps = _run_plan(context, plan, lambda _node: False)

    assert succeeded is False
    assert context.context.completed_steps == []
    assert context.context.outstanding_failures == ["task_a"]
    assert plan.nodes["task_a"].status == "FAILED"
    assert _plan_statuses(context) == {"task_a": "failed"}


def test_cancelled_node_is_never_completed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))

    def cancelled(_node: EngineeringTaskNode) -> bool:
        raise TurnCancelledError("Task execution cancelled by user")

    succeeded, _steps = _run_plan(context, plan, cancelled)

    assert succeeded is False
    assert context.context.completed_steps == []
    assert context.context.outstanding_failures == ["task_a"]
    assert plan.nodes["task_a"].status == "FAILED"
    assert _plan_statuses(context) == {"task_a": "failed"}


def test_blocked_dependent_is_never_completed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []), ("task_b", ["task_a"]))
    executed: list[str] = []

    def executor(node: EngineeringTaskNode) -> bool:
        executed.append(node.node_id)
        return False

    succeeded, _steps = _run_plan(context, plan, executor)

    assert succeeded is False
    assert executed == ["task_a"]  # the blocked node never ran
    assert context.context.completed_steps == []
    assert context.context.outstanding_failures == ["task_a"]
    assert plan.nodes["task_b"].status == "PENDING"  # the scheduler halted before reaching it
    # At the scheduler level the unreached node is still pending; the
    # orchestrator's halt back-fill (covered below) turns it into "blocked".
    assert _plan_statuses(context) == {"task_a": "failed", "task_b": "pending"}


# ---------------------------------------------------------------------------
# 5-6: retries and ordering
# ---------------------------------------------------------------------------

def test_retry_does_not_duplicate_completion(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    _run_plan(context, plan, lambda _node: True)
    _run_plan(context, plan, lambda _node: True)

    assert context.context.completed_steps == ["task_a"]


def test_retry_success_moves_a_failed_node_to_completed(tmp_path: Path) -> None:
    context, plan = _context(tmp_path, ("task_a", []))
    _run_plan(context, plan, lambda _node: False)
    assert context.context.outstanding_failures == ["task_a"]

    _run_plan(context, plan, lambda _node: True)
    assert context.context.completed_steps == ["task_a"]
    assert context.context.outstanding_failures == []


def test_multiple_nodes_complete_in_execution_order(tmp_path: Path) -> None:
    context, plan = _context(
        tmp_path, ("task_a", []), ("task_b", ["task_a"]), ("task_c", ["task_b"]),
    )
    succeeded, steps = _run_plan(context, plan, lambda _node: True)

    assert succeeded is True
    assert context.context.completed_steps == ["task_a", "task_b", "task_c"]
    assert context.context.pending_steps == []
    assert steps == [
        "TASK_NODE_task_a", "TASK_NODE_task_a",
        "TASK_NODE_task_b", "TASK_NODE_task_b",
        "TASK_NODE_task_c", "TASK_NODE_task_c",
    ]
    assert _plan_statuses(context, "TASK_NODE_task_c") == {
        "task_a": "completed", "task_b": "completed", "task_c": "completed",
    }


# ---------------------------------------------------------------------------
# 7-8: the real orchestrator run, through the real reporter
# ---------------------------------------------------------------------------

def test_real_orchestrator_publishes_plan_completion_and_activity(tmp_path: Path) -> None:
    workspace = Path(tmp_path)
    (workspace / "README.md").write_text("# demo workspace\n", encoding="utf-8")

    orchestrator = EngineeringExecutionOrchestrator(
        workspace_root=str(workspace), tenant_id="plan_completion", mock_mode=True,
    )
    events: list[tuple[str, dict]] = []
    views: list[dict] = []

    def executor(node: EngineeringTaskNode) -> bool:
        # Deterministic test adapter: real mutation path, real return value.
        for target in node.target_files:
            orchestrator.impl_engine.execute_node_mutation(
                task_id="task_plan",
                node=node,
                rel_path=target,
                content="# generated by the plan-completion test fixture\nVALUE = 1\n",
            )
        return True

    reporter = EngineeringProgressReporter(
        session_id="session-plan", turn_id="turn-plan",
        emit=lambda kind, payload: events.append((kind, payload)),
    )

    def on_progress(view: dict) -> None:
        views.append(view)
        reporter(view)

    try:
        orchestrator.run_task(
            task_prompt="Create notes.md with a short greeting",
            task_id="task_plan",
            custom_executor=executor,
            on_progress=on_progress,
        )
    except Exception:
        # Later global gates (tests/verification) may reject this synthetic
        # fixture; the implementation stage and its progress are already real.
        pass

    plan_payloads = [payload for kind, payload in events if kind == "plan.created"]
    activity = [payload for kind, payload in events if kind == "agent.card"]
    assert plan_payloads, "the plan projection received no engineering plan"
    assert activity, "activity cards stopped streaming"

    history: dict[str, list[str]] = {}
    for payload in plan_payloads:
        for step in payload["steps"]:
            history.setdefault(step["id"], []).append(step["status"])

    final = plan_payloads[-1]["steps"]
    completed = {step["id"] for step in final if step["status"] == "completed"}
    assert completed, f"no DAG node completed: {final}"

    for node_id in completed:
        sequence = history[node_id]
        assert sequence[0] == "pending", sequence
        assert "in_progress" in sequence, sequence
        assert sequence.index("in_progress") < sequence.index("completed"), sequence
        assert sequence[-1] == "completed", sequence

    # Completed work is never reported as pending again by a later stage.
    seen_completed: set[str] = set()
    for payload in plan_payloads:
        for step in payload["steps"]:
            if step["id"] in seen_completed:
                assert step["status"] == "completed", (step, sorted(seen_completed))
        seen_completed.update(
            step["id"] for step in payload["steps"] if step["status"] == "completed"
        )

    assert views[-1]["completed_steps"]
    assert set(views[-1]["completed_steps"]) >= completed

    # Activity cards carry human stage labels, not raw node ids only.
    labels = [payload["card"]["data"]["label"] for payload in activity]
    assert any("Working on" in label or "Delivering" in label or "Delivered" in label
               or "Validating" in label for label in labels), labels


def test_halted_pipeline_marks_unrun_nodes_blocked(tmp_path: Path) -> None:
    workspace = Path(tmp_path)
    (workspace / "README.md").write_text("# demo workspace\n", encoding="utf-8")
    orchestrator = EngineeringExecutionOrchestrator(
        workspace_root=str(workspace), tenant_id="plan_halted", mock_mode=True,
    )
    events: list[tuple[str, dict]] = []
    reporter = EngineeringProgressReporter(
        session_id="session-halted", turn_id="turn-halted",
        emit=lambda kind, payload: events.append((kind, payload)),
    )

    def failing(_node: EngineeringTaskNode) -> bool:
        return False

    with pytest.raises(RuntimeError):
        orchestrator.run_task(
            task_prompt="Create notes.md with a short greeting",
            task_id="task_halted",
            custom_executor=failing,
            on_progress=reporter,
        )

    plan_payloads = [payload for kind, payload in events if kind == "plan.created"]
    assert plan_payloads
    for payload in plan_payloads:
        assert not [
            step for step in payload["steps"] if step["status"] == "completed"
        ], payload
    final = plan_payloads[-1]["steps"]
    assert final
    # Nothing is left looking like work that will still run: the node that was
    # attempted failed, and the node the halt prevented is blocked.
    statuses = [step["status"] for step in final]
    assert "failed" in statuses, final
    assert statuses.count("blocked") >= 1, final
    assert all(status in {"failed", "blocked"} for status in statuses), final
    assert [kind for kind, _payload in events].count("agent.card") >= 2


# ---------------------------------------------------------------------------
# 9: journal/replay projection keeps the completed status
# ---------------------------------------------------------------------------

class _FakeJournal:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append(self, kind: str, payload: dict, **kwargs) -> None:  # noqa: ANN003
        self.rows.append({"kind": kind, "payload": payload, **kwargs})


class _FakeServices:
    def __init__(self, journal: _FakeJournal) -> None:
        self.journal = journal


def test_completed_plan_survives_the_journal_projection(tmp_path: Path, monkeypatch) -> None:
    context, _plan = _context(tmp_path, ("task_a", []), ("task_b", ["task_a"]))
    context.record_task_completion("task_a")
    view = _view(context, "TASK_NODE_task_b")
    event = plan_event(view, session_id="session-plan", turn_id="turn-plan")
    assert event is not None

    identity = TurnIdentity.create(session_id="session-plan", workspace=str(tmp_path))
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
    assert statuses["task_a"] == "completed"
    assert statuses["task_b"] == "in_progress"
    assert journal.rows[0]["payload"]["card"]["data"]["steps"] == card["data"]["steps"]


# ---------------------------------------------------------------------------
# 10: ordinary chat is unchanged
# ---------------------------------------------------------------------------

def test_normal_chat_turn_has_no_engineering_node_completion(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CRUSORAI_TEST_LLM_SCRIPT", json.dumps([{
        "content": "Hello. How can I help with your project?",
    }]))
    monkeypatch.setenv("CRUSORAI_TEST_MODE", "1")
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "0")

    thread = f"chat-{uuid.uuid4().hex[:8]}"
    q = event_bus.subscribe(thread)
    try:
        result = stream_agent(
            "hello there",
            thread_id=thread,
            workspace=str(tmp_path),
            execution_mode="agent",
            approval_channel=True,
            approval_policy="ask",
        )
        events: list[dict] = []
        while True:
            try:
                events.append(q.get(timeout=0.4))
            except queue.Empty:
                break
    finally:
        event_bus.unsubscribe(q)
        event_bus.clear(thread)

    assert result.completed is True
    state = graph.get_state({"configurable": {"thread_id": thread}})
    assert not (state.values or {}).get("engineering_delivery")

    stages = [
        event["payload"]["card"]["data"]["stage"]
        for event in events
        if event.get("type") == "agent.card"
    ]
    assert not [stage for stage in stages if str(stage).startswith("task_node_")], stages
    messages = (state.values or {}).get("messages") or []
    assert any("Hello" in str(getattr(message, "content", "")) for message in messages)

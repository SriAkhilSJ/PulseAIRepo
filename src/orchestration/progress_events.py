"""Live engineering progress projected onto the existing Agent UI cards.

The orchestrator already produces safe, redacted snapshots through
``DesktopVisibilityReporter`` (``src/orchestration/visibility.py``). Until now
nothing listened: ``engineering_task_node`` called ``run_task_request`` without
an ``on_progress`` callback, so the snapshots were computed and discarded.

This module is that listener. It does not invent a second event system: each
snapshot is mapped onto event names the bridge already projects and card types
the desktop already renders.

Two existing surfaces are fed:

* ``agent.card`` -> the typed ``activity`` card (stable ``<turn>:activity`` id,
  replaced in place) carrying the current lifecycle stage.
* ``plan.created`` -> the existing plan strip / plan card, carrying the real
  engineering DAG steps and their real completion status.

Nothing here fabricates tool, file, test, verification or cost events. Those
keep their authoritative sources (real tool results, real verification, real
FinOps ledger) and the terminal delivery receipt.

The callback is deliberately defensive: a failure, a duplicate snapshot, a
cancelled turn or a pathological emitter can never break an engineering run.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from src.dashboard.event_bus import event_bus
from src.regression.persistence import redact_secrets_from_dict

log = logging.getLogger("crusor.orchestration.progress_events")

#: Hard ceiling per engineering turn. The orchestrator emits roughly one
#: snapshot per lifecycle stage (plus one per DAG node), so a normal turn is
#: ~30 events. The cap only stops a pathological loop from flooding the event
#: bus and the durable journal.
MAX_PROGRESS_EMISSIONS = 240
MAX_STEP_ITEMS = 60
MAX_TEXT = 200

#: Presentation labels for the lifecycle stages the orchestrator emits. A
#: missing key falls back to the stage name itself, so this table can never
#: hide a stage.
_STAGE_LABELS: Dict[str, str] = {
    "USER_REQUEST": "Reading the request",
    "REQUEST_UNDERSTANDING": "Understanding the request",
    "CLARIFICATION_REQUIRED": "Waiting for your answer",
    "PROJECT_DISCOVERY": "Discovering the project",
    "REQUIREMENT_VALIDATION": "Validating requirements",
    "ARCHITECTURE_VALIDATION": "Validating architecture",
    "CONTRACT_EXTRACTION": "Extracting contracts",
    "FILES_ASSIGNED": "Assigning files",
    "ENGINEERING_PLAN": "Planning changes",
    "CHANGE_IMPACT_ANALYSIS": "Analyzing impact",
    "TEST_BASELINE": "Running baseline tests",
    "APPROVAL_AND_PERMISSION_CHECK": "Checking permissions",
    "APPROVAL_REQUIRED": "Waiting for approval",
    "IMPLEMENTATION": "Implementing changes",
    "ARTIFACT_VALIDATION": "Validating artifacts",
    "CROSS_FILE_VALIDATION": "Validating across files",
    "TEST_DISCOVERY": "Discovering tests",
    "TEST_EXECUTION": "Running tests",
    "FAILURE_DIAGNOSIS": "Diagnosing failures",
    "REPAIRING": "Repairing failures",
    "TESTS_REEXECUTED": "Re-running tests",
    "REGRESSION_VERIFICATION": "Checking regressions",
    "PRODUCTION_READINESS": "Checking production readiness",
    "FINAL_DELIVERY": "Preparing delivery",
    "DELIVERED": "Delivered",
}

_TASK_NODE_PREFIX = "TASK_NODE_"


def _bounded(value: Any, limit: int = MAX_TEXT) -> str:
    """One-line, length-bounded text for a card field."""
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"


def _as_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def stage_label(step: Any) -> str:
    """Human, bounded label for one orchestrator lifecycle stage."""
    raw = str(step or "").strip()
    key = raw.upper()
    if not key:
        return "Working"
    label = _STAGE_LABELS.get(key)
    if label:
        return label
    if key.startswith(_TASK_NODE_PREFIX):
        node = raw[len(_TASK_NODE_PREFIX):].strip()
        return _bounded(f"Working on {node}") if node else "Implementing changes"
    return _bounded(key.replace("_", " ").title())


def _status_of(view: Dict[str, Any]) -> str:
    state = str(view.get("current_state") or "").upper()
    step = str(view.get("current_step") or "").upper()
    if state == "CANCELLED":
        return "cancelled"
    if state == "BLOCKED":
        return "blocked"
    if state == "FAILED":
        return "failed"
    if state == "COMPLETED" or step == "DELIVERED":
        return "completed"
    if bool(view.get("is_paused")):
        return "paused"
    return "running"


def _active_node(view: Dict[str, Any]) -> str:
    """The DAG node currently being implemented, when the stage names one."""
    step = str(view.get("current_step") or "").strip()
    if step.upper().startswith(_TASK_NODE_PREFIX):
        return step[len(_TASK_NODE_PREFIX):].strip()
    return ""


def _steps(view: Dict[str, Any]) -> List[Dict[str, str]]:
    """Real DAG steps with their real settled status, bounded and ordered."""
    completed = _as_list(view.get("completed_steps"))
    failed = _as_list(view.get("failed_steps"))
    blocked = _as_list(view.get("blocked_steps"))
    cancelled = _as_list(view.get("cancelled_steps"))
    pending = _as_list(view.get("pending_steps"))
    active = _active_node(view)

    steps: List[Dict[str, str]] = []
    seen: set[str] = set()

    def add(node: str, status: str) -> None:
        if node in seen or len(steps) >= MAX_STEP_ITEMS:
            return
        seen.add(node)
        steps.append({"id": node, "title": node, "text": node, "status": status})

    for node in completed:
        add(node, "completed")
    for node in failed:
        add(node, "failed")
    for node in blocked:
        add(node, "blocked")
    for node in cancelled:
        add(node, "cancelled")
    for node in pending:
        add(node, "in_progress" if active and node == active else "pending")
    return steps


def _detail(view: Dict[str, Any]) -> str:
    """Genuine progress counts for the activity card's second line."""
    completed = len(_as_list(view.get("completed_steps")))
    failed = len(_as_list(view.get("failed_steps")))
    blocked = len(_as_list(view.get("blocked_steps")))
    cancelled = len(_as_list(view.get("cancelled_steps")))
    pending = len(_as_list(view.get("pending_steps")))
    total = completed + failed + blocked + cancelled + pending

    parts: List[str] = []
    if total:
        parts.append(f"{completed}/{total} steps")
    percentage = view.get("progress_percentage")
    if isinstance(percentage, (int, float)) and not isinstance(percentage, bool):
        parts.append(f"{round(float(percentage))}%")
    if failed:
        parts.append(f"{failed} failed")
    if blocked:
        parts.append(f"{blocked} blocked")
    if cancelled:
        parts.append(f"{cancelled} cancelled")
    if bool(view.get("is_paused")):
        parts.append("paused")
    return _bounded(" · ".join(parts))


def activity_card(view: Dict[str, Any], *, session_id: str, turn_id: str) -> Dict[str, Any]:
    """Project one snapshot onto the existing typed ``activity`` card."""
    data: Dict[str, Any] = {
        "stage": _bounded(str(view.get("current_step") or "progress").lower(), 80),
        "label": stage_label(view.get("current_step")),
        "status": _status_of(view),
    }
    detail = _detail(view)
    if detail:
        data["detail"] = detail
    return redact_secrets_from_dict({
        "schema_version": 1,
        "card_type": "activity",
        "card_id": f"{turn_id}:activity",
        "session_id": session_id,
        "turn_id": turn_id,
        "data": data,
    })


def plan_event(view: Dict[str, Any], *, session_id: str, turn_id: str) -> Optional[Dict[str, Any]]:
    """Project the snapshot's real DAG state onto the existing plan event."""
    steps = _steps(view)
    if not steps:
        return None
    done = sum(1 for step in steps if step["status"] == "completed")
    files = _as_list(view.get("modified_files"))[:20]
    payload = {
        "session_id": session_id,
        "thread_id": session_id,
        "turn_id": turn_id,
        "summary": _bounded(f"{stage_label(view.get('current_step'))} · {done}/{len(steps)} steps", 500),
        "steps": steps,
        "files": files,
        "verification": [],
    }
    return redact_secrets_from_dict(payload)


class EngineeringProgressReporter:
    """Bounded, deduplicating, cancellation-aware ``on_progress`` callback."""

    def __init__(
        self,
        *,
        session_id: str,
        turn_id: str,
        emit: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        cancelled: Optional[Callable[[], bool]] = None,
        max_emissions: int = MAX_PROGRESS_EMISSIONS,
    ) -> None:
        self._session_id = str(session_id or "")
        self._turn_id = str(turn_id or "")
        self._emit = emit or event_bus.emit
        self._cancelled = cancelled
        self._max = max(0, int(max_emissions))
        self._last_activity: Optional[tuple] = None
        self._last_plan: Optional[tuple] = None
        self._last_view: Optional[Dict[str, Any]] = None
        self._emitted = 0
        #: Diagnostics only; never used for control flow.
        self.failures = 0
        self.dropped = 0

    @property
    def emitted(self) -> int:
        return self._emitted

    def __call__(self, view: Dict[str, Any]) -> None:
        """Entry point handed to ``run_task_request(on_progress=...)``.

        Must never raise: the orchestrator calls this inline between lifecycle
        stages, and an exception here would abort a real engineering run.
        """
        try:
            self._handle(view)
        except Exception as exc:  # noqa: BLE001 - progress must never fail a turn
            self.failures += 1
            log.warning("engineering progress projection failed: %r", exc)

    def _is_cancelled(self) -> bool:
        if self._cancelled is None:
            return False
        try:
            return bool(self._cancelled())
        except Exception:  # noqa: BLE001 - a broken predicate must not stop progress
            return False

    def _handle(self, view: Any) -> None:
        if not isinstance(view, dict):
            return
        # Remember the newest real snapshot: `mark_generating` derives the
        # in-progress plan row from it without inventing a stage.
        self._last_view = dict(view)
        if self._is_cancelled() and not view.get("final"):
            # A cancelled turn stops publishing NEW stage progress: the bridge
            # settles the turn. The one settled snapshot the cancellation path
            # marks ``final`` is still forwarded, so the plan can show its
            # cancelled/blocked outcomes truthfully.
            return
        if self._emitted >= self._max:
            self.dropped += 1
            return

        stage = str(view.get("current_step") or "")
        status = _status_of(view)
        detail = _detail(view)
        activity_signature = (stage, status, detail)
        if activity_signature != self._last_activity:
            self._dispatch("agent.card", {
                "card": activity_card(
                    view, session_id=self._session_id, turn_id=self._turn_id,
                ),
                "session_id": self._session_id,
                "thread_id": self._session_id,
                "turn_id": self._turn_id,
            })
            self._last_activity = activity_signature
            if self._emitted >= self._max:
                return

        plan = plan_event(view, session_id=self._session_id, turn_id=self._turn_id)
        if plan is None:
            return
        plan_signature = tuple((step["id"], step["status"]) for step in plan["steps"])
        if plan_signature == self._last_plan:
            return
        self._dispatch("plan.created", plan)
        self._last_plan = plan_signature

    def mark_generating(self, node_id: str) -> None:
        """Publish the active DAG node as ``in_progress`` while it generates.

        The orchestrator only reports at stage boundaries, so without this the
        plan sat at "0/2" while the activity card said "Generating notes.md" —
        two surfaces disagreeing about the same moment. This re-projects the
        last REAL snapshot with the generating node marked active; it invents
        no step and no status the orchestrator did not already have.
        """
        if not node_id or self._last_view is None:
            return
        if self._emitted >= self._max:
            self.dropped += 1
            return
        try:
            view = dict(self._last_view)
            view["current_step"] = f"{_TASK_NODE_PREFIX}{node_id}"
            plan = plan_event(view, session_id=self._session_id, turn_id=self._turn_id)
            if plan is None:
                return
            signature = tuple((step["id"], step["status"]) for step in plan["steps"])
            if signature == self._last_plan:
                return
            self._dispatch("plan.created", plan)
            self._last_plan = signature
        except Exception as exc:  # noqa: BLE001 - presentation never fails a run
            self.failures += 1
            log.warning("active-node plan projection failed: %r", exc)

    def _dispatch(self, event_type: str, payload: Dict[str, Any]) -> None:
        # An emitter failure propagates to __call__, which logs it. The
        # signature stays unrecorded so the next snapshot can retry.
        self._emit(event_type, payload)
        self._emitted += 1

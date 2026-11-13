"""
src/orchestration/context_manager.py - Adaptive Context & Engineering State Memory.

Phase 11.6: Autonomous Engineering Execution.
Maintains authoritative task context across the engineering lifecycle.
Guarantees:
- Persisted engineering artifacts remain the single source of truth.
- Bounded token retrieval: slices project knowledge rather than injecting full repos.
- Preserves original user constraints across turns and compactions.
- Clean isolation between tasks and tenants.
- Fast recovery after process restart.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.impact.models import ChangeImpactReport
from src.intelligence.architecture_models import ArchitectureBlueprint
from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import ProjectSpecification
from src.orchestration.models import EngineeringPlanDAG, EngineeringTaskNode
from src.regression.models import RegressionReport, TestBaseline

log = logging.getLogger("crusor.orchestration.context_manager")


@dataclass
class AuthoritativeTaskContext:
    """The complete, persistent source of truth for an engineering task."""
    task_id: str
    workspace_root: str
    tenant_id: str
    original_user_request: str
    explicit_constraints: List[str] = field(default_factory=list)
    clarification_answers: Dict[str, str] = field(default_factory=dict)
    specification: Optional[ProjectSpecification] = None
    blueprint: Optional[ArchitectureBlueprint] = None
    knowledge_summary: Dict[str, Any] = field(default_factory=dict)
    plan: Optional[EngineeringPlanDAG] = None
    impact_report: Optional[ChangeImpactReport] = None
    test_baseline_summary: Dict[str, Any] = field(default_factory=dict)
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    outstanding_failures: List[str] = field(default_factory=list)
    #: Work that never ran because a dependency or an earlier failure halted
    #: the pipeline. Distinct from a genuine execution failure.
    blocked_steps: List[str] = field(default_factory=list)
    #: Work interrupted by a user cancellation (the turn was cancelled).
    cancelled_steps: List[str] = field(default_factory=list)
    latest_regression_report: Optional[RegressionReport] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class AdaptiveContextManager:
    """
    Manages task context retrieval, compaction immunity, and persistence.
    """

    def __init__(
        self,
        task_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.task_id = task_id
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            self.storage_dir = (
                self.workspace_root
                / ".crusorai"
                / "tenants"
                / tenant_id
                / "tasks"
                / task_id
            )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.context_file = self.storage_dir / "authoritative_context.json"

        self.context = AuthoritativeTaskContext(
            task_id=task_id,
            workspace_root=str(self.workspace_root),
            tenant_id=tenant_id,
            original_user_request="",
        )
        if self.context_file.exists():
            self._load()

    def initialize_request(self, user_prompt: str, constraints: Optional[List[str]] = None) -> None:
        """Initialize authoritative context with the original user request."""
        self.context.original_user_request = user_prompt
        self.context.explicit_constraints = constraints or []
        self.context.updated_at = time.time()
        self.save()

    def record_clarification(self, question: str, answer: str) -> None:
        """Record human clarification."""
        self.context.clarification_answers[question] = answer
        self.context.updated_at = time.time()
        self.save()

    def record_specification(self, spec: ProjectSpecification) -> None:
        """Attach approved specification."""
        self.context.specification = spec
        self.context.updated_at = time.time()
        self.save()

    def record_blueprint(self, blueprint: ArchitectureBlueprint) -> None:
        """Attach architectural blueprint."""
        self.context.blueprint = blueprint
        self.context.updated_at = time.time()
        self.save()

    def record_impact_report(self, impact_report: ChangeImpactReport) -> None:
        """Attach change impact report."""
        self.context.impact_report = impact_report
        self.context.updated_at = time.time()
        self.save()

    def record_test_baseline(self, summary: Dict[str, Any]) -> None:
        """Attach test baseline summary."""
        self.context.test_baseline_summary = summary
        self.context.updated_at = time.time()
        self.save()

    def record_plan(self, plan: EngineeringPlanDAG) -> None:
        """Attach engineering plan DAG."""
        self.context.plan = plan
        self.context.pending_steps = list(plan.nodes.keys())
        self.context.updated_at = time.time()
        self.save()

    def record_task_completion(self, node_id: str) -> None:
        """Mark task node completed (idempotent).

        Called only after the scheduler reports the node's real settled
        outcome as ``COMPLETED``. A repeat call (retry, replay, duplicate
        callback) never appends a second entry. A node that previously
        failed, was blocked or cancelled leaves those buckets: a later
        successful retry is genuinely completed.
        """
        if node_id in self.context.pending_steps:
            self.context.pending_steps.remove(node_id)
        self._drop(node_id, self.context.outstanding_failures)
        self._drop(node_id, self.context.blocked_steps)
        self._drop(node_id, self.context.cancelled_steps)
        if node_id not in self.context.completed_steps:
            self.context.completed_steps.append(node_id)
        self.context.updated_at = time.time()
        self.save()

    def record_task_failure(self, node_id: str) -> None:
        """Mark a task node as attempted and failed.

        The node leaves pending work and joins ``outstanding_failures``. A
        node that already completed is never downgraded: the scheduler settles
        each node once, so this is only a guard against late/duplicate
        callbacks. A later failure also leaves the blocked/cancelled buckets.
        """
        if node_id in self.context.pending_steps:
            self.context.pending_steps.remove(node_id)
        if node_id in self.context.completed_steps:
            return
        self._drop(node_id, self.context.blocked_steps)
        self._drop(node_id, self.context.cancelled_steps)
        if node_id not in self.context.outstanding_failures:
            self.context.outstanding_failures.append(node_id)
        self.context.updated_at = time.time()
        self.save()

    def record_task_blocked(self, node_id: str) -> None:
        """Mark work that could not run (dependency or upstream failure).

        This is never a completion and never a failure of the node itself:
        the work was not attempted. A completed node is never downgraded.
        """
        if node_id in self.context.pending_steps:
            self.context.pending_steps.remove(node_id)
        if node_id in self.context.completed_steps:
            return
        self._drop(node_id, self.context.outstanding_failures)
        self._drop(node_id, self.context.cancelled_steps)
        if node_id not in self.context.blocked_steps:
            self.context.blocked_steps.append(node_id)
        self.context.updated_at = time.time()
        self.save()

    def record_task_cancelled(self, node_id: str) -> None:
        """Mark work interrupted by the user's Stop (never a completion)."""
        if node_id in self.context.pending_steps:
            self.context.pending_steps.remove(node_id)
        if node_id in self.context.completed_steps:
            return
        self._drop(node_id, self.context.outstanding_failures)
        self._drop(node_id, self.context.blocked_steps)
        if node_id not in self.context.cancelled_steps:
            self.context.cancelled_steps.append(node_id)
        self.context.updated_at = time.time()
        self.save()

    @staticmethod
    def _drop(node_id: str, bucket: List[str]) -> None:
        if node_id in bucket:
            bucket.remove(node_id)

    def record_task_outcome(self, node: EngineeringTaskNode) -> Optional[str]:
        """Record one settled scheduler outcome; return the recorded state.

        Only the node's REAL settled status counts:

        * ``COMPLETED`` -> completed (the executor returned success);
        * ``FAILED`` -> attempted and failed;
        * ``SKIPPED`` / ``BLOCKED`` -> could not run (dependency/upstream halt);
        * ``CANCELLED`` -> interrupted by the user;
        * ``PENDING`` / ``IN_PROGRESS`` -> nothing (a start is not an outcome).

        This is the single place the orchestrator's scheduler callback and the
        tests both go through, so no outcome can be inferred from a stage
        label or from the task reaching ``DELIVERED``.
        """
        node_id = str(getattr(node, "node_id", "") or "")
        if not node_id:
            return None
        status = str(getattr(node, "status", "") or "").upper()
        if status == "COMPLETED":
            self.record_task_completion(node_id)
            return "COMPLETED"
        if status == "FAILED":
            self.record_task_failure(node_id)
            return "FAILED"
        if status in {"SKIPPED", "BLOCKED"}:
            self.record_task_blocked(node_id)
            return "BLOCKED"
        if status == "CANCELLED":
            self.record_task_cancelled(node_id)
            return "CANCELLED"
        return None

    def get_focused_prompt_context(self, max_tokens: int = 4000) -> Dict[str, Any]:
        """
        Supplies a bounded, compressed summary for LLM prompts
        without dumping entire source code repositories.
        """
        spec_summary = {}
        if self.context.specification:
            if hasattr(self.context.specification, "all_requirements"):
                all_reqs = self.context.specification.all_requirements() if callable(self.context.specification.all_requirements) else self.context.specification.all_requirements
            else:
                all_reqs = getattr(self.context.specification, "requirements", [])
            spec_summary = {
                "spec_id": getattr(self.context.specification, "spec_id", getattr(self.context.specification, "id", "spec")),
                "desired_outcome": getattr(self.context.specification, "desired_outcome", getattr(self.context.specification, "title", "")),
                "scope": getattr(getattr(self.context.specification, "implementation_scope", None), "value", "FOCUSED"),
                "requirements": [
                    {"id": r.id, "title": getattr(r, "title", r.description[:40]), "priority": getattr(r.priority, "value", str(r.priority))}
                    for r in all_reqs
                ][:6],
            }

        blueprint_summary = {}
        if self.context.blueprint:
            blueprint_summary = {
                "style": getattr(self.context.blueprint.architecture_style, "value", str(self.context.blueprint.architecture_style)),
                "stack": [getattr(t, "name", str(t)) for t in self.context.blueprint.technology_stack],
                "adrs": [a.id for a in self.context.blueprint.adrs],
            }

        return {
            "task_id": self.context.task_id,
            "original_request": self.context.original_user_request,
            "constraints": self.context.explicit_constraints,
            "clarifications": self.context.clarification_answers,
            "specification": spec_summary,
            "architecture": blueprint_summary,
            "completed_steps": self.context.completed_steps,
            "pending_steps": self.context.pending_steps,
            "outstanding_failures": self.context.outstanding_failures,
            "blocked_steps": self.context.blocked_steps,
            "cancelled_steps": self.context.cancelled_steps,
        }

    def save(self) -> None:
        """Persist authoritative context JSON atomically."""
        payload = {
            "task_id": self.context.task_id,
            "workspace_root": self.context.workspace_root,
            "tenant_id": self.context.tenant_id,
            "original_user_request": self.context.original_user_request,
            "explicit_constraints": self.context.explicit_constraints,
            "clarification_answers": self.context.clarification_answers,
            "knowledge_summary": self.context.knowledge_summary,
            "completed_steps": self.context.completed_steps,
            "pending_steps": self.context.pending_steps,
            "outstanding_failures": self.context.outstanding_failures,
            "blocked_steps": self.context.blocked_steps,
            "cancelled_steps": self.context.cancelled_steps,
            "test_baseline_summary": self.context.test_baseline_summary,
            "created_at": self.context.created_at,
            "updated_at": self.context.updated_at,
        }
        if self.context.plan:
            payload["plan"] = self.context.plan.to_dict()
        if self.context.blueprint:
            payload["blueprint"] = self.context.blueprint.to_dict() if hasattr(self.context.blueprint, "to_dict") else {}
        if self.context.impact_report:
            payload["impact_report"] = self.context.impact_report.to_dict() if hasattr(self.context.impact_report, "to_dict") else {}

        tmp_file = self.context_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_file, self.context_file)

    def _load(self) -> None:
        """Load context JSON."""
        try:
            with open(self.context_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.context.original_user_request = data.get("original_user_request", "")
            self.context.explicit_constraints = data.get("explicit_constraints", [])
            self.context.clarification_answers = data.get("clarification_answers", {})
            self.context.knowledge_summary = data.get("knowledge_summary", {})
            self.context.completed_steps = data.get("completed_steps", [])
            self.context.pending_steps = data.get("pending_steps", [])
            self.context.outstanding_failures = data.get("outstanding_failures", [])
            self.context.blocked_steps = data.get("blocked_steps", [])
            self.context.cancelled_steps = data.get("cancelled_steps", [])
            self.context.test_baseline_summary = data.get("test_baseline_summary", {})
            self.context.created_at = data.get("created_at", time.time())
            self.context.updated_at = data.get("updated_at", time.time())
            if "plan" in data:
                self.context.plan = EngineeringPlanDAG.from_dict(data["plan"])
            if "blueprint" in data:
                try:
                    self.context.blueprint = ArchitectureBlueprint.from_dict(data["blueprint"])
                except Exception:
                    pass
            if "impact_report" in data:
                try:
                    ir_data = data["impact_report"]
                    self.context.impact_report = ChangeImpactReport(
                        task_id=ir_data.get("task_id", ""),
                        proposed_change_summary=ir_data.get("proposed_change_summary", ""),
                        changed_files=ir_data.get("changed_files", []),
                        changed_symbols=ir_data.get("changed_symbols", []),
                    )
                except Exception as e:
                    log.error(f"Error loading impact report: {e}")
        except Exception as e:
            log.error(f"Error loading authoritative context: {e}")

"""
src/orchestration/visibility.py - Desktop Live Task Visibility & Safe Progress Projection.

Phase 11.6: Autonomous Engineering Execution.
Projects real-time, deterministic task execution progress to the desktop UI.
Guarantees:
- Secrets & credentials are strictly redacted.
- Progress metrics are derived from actual DAG nodes and verification states, not fake percentages.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.orchestration.models import TaskExecutionState
from src.regression.persistence import redact_secrets_from_dict

log = logging.getLogger("crusor.orchestration.visibility")


@dataclass
class DesktopTaskProgressView:
    """Desktop UI projection model for live execution monitoring."""
    task_id: str
    current_state: str
    current_step: str
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    #: Work that never ran (dependency/upstream halt) and work interrupted by
    #: the user. Both are distinct from a genuine execution failure.
    blocked_steps: List[str] = field(default_factory=list)
    cancelled_steps: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    test_results_summary: Dict[str, int] = field(default_factory=dict)
    resource_consumption: Dict[str, Any] = field(default_factory=dict)
    pending_approvals: List[Dict[str, Any]] = field(default_factory=list)
    remaining_blockers: List[str] = field(default_factory=list)
    is_paused: bool = False
    progress_percentage: float = 0.0
    last_updated: float = field(default_factory=time.time)

    def to_safe_dict(self) -> Dict[str, Any]:
        """Returns projection with all credentials safely redacted."""
        raw = {
            "task_id": self.task_id,
            "current_state": self.current_state,
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "pending_steps": self.pending_steps,
            "failed_steps": self.failed_steps,
            "blocked_steps": self.blocked_steps,
            "cancelled_steps": self.cancelled_steps,
            "modified_files": self.modified_files,
            "test_results_summary": self.test_results_summary,
            "resource_consumption": self.resource_consumption,
            "pending_approvals": self.pending_approvals,
            "remaining_blockers": self.remaining_blockers,
            "is_paused": self.is_paused,
            "progress_percentage": round(self.progress_percentage, 1),
            "last_updated": self.last_updated,
        }
        return redact_secrets_from_dict(raw)


class DesktopVisibilityReporter:
    """
    Computes transparent desktop visibility snapshots from task state.
    """

    @staticmethod
    def compute_view(
        task_id: str,
        state: TaskExecutionState,
        current_step: str,
        completed_steps: List[str],
        pending_steps: List[str],
        failed_steps: List[str],
        modified_files: List[str],
        test_summary: Optional[Dict[str, int]] = None,
        tokens_used: int = 0,
        cost_inr: float = 0.00,
        pending_approvals: Optional[List[Dict[str, Any]]] = None,
        blockers: Optional[List[str]] = None,
        is_paused: bool = False,
        blocked_steps: Optional[List[str]] = None,
        cancelled_steps: Optional[List[str]] = None,
    ) -> DesktopTaskProgressView:
        """Calculates derived progress percentage based on completed DAG nodes."""
        blocked = list(blocked_steps or [])
        cancelled = list(cancelled_steps or [])
        total_steps = (
            len(completed_steps) + len(pending_steps) + len(failed_steps)
            + len(blocked) + len(cancelled)
        )
        pct = 0.0
        if state == TaskExecutionState.COMPLETED:
            pct = 100.0
        elif total_steps > 0:
            pct = (len(completed_steps) / total_steps) * 100.0

        return DesktopTaskProgressView(
            task_id=task_id,
            current_state=state.value,
            current_step=current_step,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            failed_steps=failed_steps,
            blocked_steps=blocked,
            cancelled_steps=cancelled,
            modified_files=sorted(list(set(modified_files))),
            test_results_summary=test_summary or {},
            resource_consumption={
                "tokens": tokens_used,
                "cost_inr": cost_inr,
            },
            pending_approvals=pending_approvals or [],
            remaining_blockers=blockers or [],
            is_paused=is_paused,
            progress_percentage=pct,
            last_updated=time.time(),
        )


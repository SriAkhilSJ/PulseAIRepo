"""
src/orchestration/lifecycle.py - Explicit Task Lifecycle and Deterministic Gate Validation.

Phase 11.6: Autonomous Engineering Execution.
Defines the 15 sequential lifecycle stages:
Preconditions, postconditions, inputs, outputs, deterministic validators, and failure handling.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from src.orchestration.models import TaskLifecycleStage

log = logging.getLogger("crusor.orchestration.lifecycle")


@dataclass
class StageExecutionRecord:
    """Audit record for a single stage execution."""
    stage: TaskLifecycleStage
    status: str  # PENDING, IN_PROGRESS, PASSED, FAILED, SKIPPED
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    precondition_errors: List[str] = field(default_factory=list)
    postcondition_errors: List[str] = field(default_factory=list)
    evidence_references: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


class LifecycleManager:
    """
    Governs the 15-stage task lifecycle with deterministic pre/post-condition checks.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.stage_history: List[StageExecutionRecord] = []
        self.current_stage: Optional[TaskLifecycleStage] = None

    def begin_stage(
        self,
        stage: TaskLifecycleStage,
        inputs: Dict[str, Any],
        precondition_check: Optional[Callable[[], List[str]]] = None,
    ) -> StageExecutionRecord:
        """
        Validate preconditions and begin stage execution.
        """
        pre_errors: List[str] = []
        if precondition_check:
            pre_errors = precondition_check()

        rec = StageExecutionRecord(
            stage=stage,
            status="IN_PROGRESS" if not pre_errors else "FAILED",
            inputs=inputs,
            precondition_errors=pre_errors,
        )
        if pre_errors:
            rec.error_message = f"Preconditions failed for {stage.value}: {'; '.join(pre_errors)}"
            rec.completed_at = time.time()
            self.stage_history.append(rec)
            log.error(rec.error_message)
            raise ValueError(rec.error_message)

        self.current_stage = stage
        self.stage_history.append(rec)
        log.info(f"Task {self.task_id}: Stage {stage.value} started.")
        return rec

    def complete_stage(
        self,
        outputs: Dict[str, Any],
        postcondition_check: Optional[Callable[[], List[str]]] = None,
        evidence: Optional[List[str]] = None,
    ) -> StageExecutionRecord:
        """
        Validate postconditions deterministically and close stage.
        """
        if not self.stage_history:
            raise RuntimeError("No active stage to complete")

        rec = self.stage_history[-1]
        rec.outputs = outputs
        rec.completed_at = time.time()
        rec.evidence_references = evidence or []

        post_errors: List[str] = []
        if postcondition_check:
            post_errors = postcondition_check()

        if post_errors:
            rec.status = "FAILED"
            rec.postcondition_errors = post_errors
            rec.error_message = f"Postconditions failed for {rec.stage.value}: {'; '.join(post_errors)}"
            log.error(rec.error_message)
            raise ValueError(rec.error_message)

        rec.status = "PASSED"
        log.info(f"Task {self.task_id}: Stage {rec.stage.value} PASSED.")
        return rec

    def fail_stage(self, error_message: str) -> StageExecutionRecord:
        """Mark current stage as failed."""
        if not self.stage_history:
            raise RuntimeError("No active stage to fail")

        rec = self.stage_history[-1]
        rec.status = "FAILED"
        rec.completed_at = time.time()
        rec.error_message = error_message
        log.error(f"Task {self.task_id}: Stage {rec.stage.value} FAILED: {error_message}")
        return rec


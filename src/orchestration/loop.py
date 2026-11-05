"""
src/orchestration/loop.py - Bounded Autonomous Engineering Reasoning Loop.

Phase 11.6: Autonomous Engineering Execution.
Orchestrates the classic bounded cognitive loop:
OBSERVE -> UNDERSTAND -> PLAN -> ACT -> VERIFY -> EVALUATE -> (DIAGNOSE -> REPLAN -> RETRY)
Enforces hard limits on attempts, tokens, costs, durations, and tool errors.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.orchestration.models import ExecutionLimits

log = logging.getLogger("crusor.orchestration.loop")


class ResourceLimitExceededError(RuntimeError):
    """Raised when an execution boundary (attempts, time, tokens, cost) is exceeded."""
    pass


class BoundedAutonomousReasoningLoop:
    """
    Executes bounded cycles with safety halting and replanning governance.
    """

    def __init__(self, limits: Optional[ExecutionLimits] = None) -> None:
        self.limits = limits or ExecutionLimits()
        self.correction_attempts: int = 0
        self.planning_revisions: int = 0
        self.tool_failures: int = 0
        self.file_modifications_count: int = 0
        self.start_time: float = time.time()
        self.accumulated_cost_inr: float = 0.00
        self.accumulated_tokens: int = 0
        self.failure_history: List[str] = []

    def check_boundaries(self) -> None:
        """Enforces all configured boundaries; raises ResourceLimitExceededError if breached."""
        # 1. Duration check
        elapsed = time.time() - self.start_time
        if elapsed > self.limits.max_task_duration_seconds:
            raise ResourceLimitExceededError(
                f"Task exceeded maximum duration: {elapsed:.1f}s > {self.limits.max_task_duration_seconds}s"
            )

        # 2. Correction attempts
        if self.correction_attempts > self.limits.max_correction_attempts:
            raise ResourceLimitExceededError(
                f"Correction attempts exceeded: {self.correction_attempts} > {self.limits.max_correction_attempts}"
            )

        # 3. Planning revisions
        if self.planning_revisions > self.limits.max_planning_revisions:
            raise ResourceLimitExceededError(
                f"Planning revisions exceeded: {self.planning_revisions} > {self.limits.max_planning_revisions}"
            )

        # 4. Tool failures
        if self.tool_failures > self.limits.max_repeated_tool_failures:
            raise ResourceLimitExceededError(
                f"Tool failures exceeded: {self.tool_failures} > {self.limits.max_repeated_tool_failures}"
            )

        # 5. Token budget
        if self.accumulated_tokens > self.limits.max_token_budget:
            raise ResourceLimitExceededError(
                f"Token budget exceeded: {self.accumulated_tokens} > {self.limits.max_token_budget}"
            )

        # 6. Cost budget
        if self.accumulated_cost_inr > self.limits.max_cost_inr:
            raise ResourceLimitExceededError(
                f"Cost budget exceeded: INR {self.accumulated_cost_inr:.2f} > INR {self.limits.max_cost_inr:.2f}"
            )

        # 7. File modifications
        if self.file_modifications_count > self.limits.max_file_modifications:
            raise ResourceLimitExceededError(
                f"File modifications count exceeded: {self.file_modifications_count} > {self.limits.max_file_modifications}"
            )

    def record_action(
        self,
        files_modified: int = 0,
        tokens_used: int = 0,
        cost_inr: float = 0.00,
        tool_failed: bool = False,
    ) -> None:
        """Record usage and update state."""
        self.file_modifications_count += files_modified
        self.accumulated_tokens += tokens_used
        self.accumulated_cost_inr += cost_inr
        if tool_failed:
            self.tool_failures += 1
        else:
            self.tool_failures = 0  # reset consecutive tool failure counter
        self.check_boundaries()

    def record_correction_attempt(self, diagnosis: str) -> None:
        """Register a corrective repair cycle."""
        self.correction_attempts += 1
        self.failure_history.append(diagnosis)
        self.check_boundaries()

    def record_planning_revision(self) -> None:
        """Register a plan revision."""
        self.planning_revisions += 1
        self.check_boundaries()


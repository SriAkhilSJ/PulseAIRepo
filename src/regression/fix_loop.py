"""
src/regression/fix_loop.py - Controlled Bounded Regression Fix Loop.

Phase 11.5: Regression Prevention & Recovery.
Orchestrates bounded corrective iterations:
- Detects regression -> diagnoses cause -> proposes smallest justified patch.
- Limits iterations (max_attempts = 3) to prevent infinite autonomous repair loops.
- Routes all file modifications through Phase 11.3 WorkspaceMutationBroker.
- Halts and reports failure if budget or iteration limits are reached.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.regression.models import (
    FailureClassification,
    FailureDiagnosis,
    TestCaseResult,
    TestStatus,
)

log = logging.getLogger("crusor.regression.fix_loop")


class ControlledRegressionFixLoop:
    """
    Executes a bounded, disciplined corrective cycle for newly introduced regressions.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.attempts_history: List[Dict[str, Any]] = []

    def execute_fix_loop(
        self,
        task_id: str,
        regressions: List[TestCaseResult],
        diagnoses: List[FailureDiagnosis],
        apply_patch_fn: Callable[[Dict[str, Any]], bool],
        verify_tests_fn: Callable[[], Dict[str, TestCaseResult]],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Executes bounded repair loop.
        Returns:
            (success_bool, corrective_operations_log)
        """
        start_time = time.time()
        operations_log: List[Dict[str, Any]] = []

        if not regressions:
            return True, operations_log

        for attempt in range(1, self.max_attempts + 1):
            if time.time() - start_time > self.timeout_seconds:
                log.warning(f"Regression fix loop timed out after {self.timeout_seconds}s")
                operations_log.append({
                    "attempt": attempt,
                    "status": "STOPPED_TIMEOUT",
                    "rationale": "Exceeded execution timeout budget",
                })
                break

            target_reg = regressions[0]
            target_diag = diagnoses[0] if diagnoses else None

            op_record = {
                "attempt": attempt,
                "target_test": target_reg.test_id,
                "diagnosed_cause": target_diag.root_cause_summary if target_diag else "Unknown",
                "timestamp": time.time(),
            }

            # Attempt corrective patch
            patch_success = apply_patch_fn(op_record)
            if not patch_success:
                op_record["status"] = "PATCH_FAILED"
                operations_log.append(op_record)
                continue

            # Re-run verification tests
            post_patch_results = verify_tests_fn()
            still_failing = [
                r for r in post_patch_results.values()
                if r.status in (TestStatus.FAILING, TestStatus.BLOCKED)
            ]

            if not still_failing:
                op_record["status"] = "SUCCESS_RESOLVED"
                operations_log.append(op_record)
                return True, operations_log
            else:
                op_record["status"] = f"UNRESOLVED_REMAINING_{len(still_failing)}"
                operations_log.append(op_record)
                regressions = still_failing

        return False, operations_log


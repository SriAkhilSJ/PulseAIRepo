"""
src/regression/flaky.py - Flaky Test Detection & Nondeterminism Classifier.

Phase 11.5: Regression Prevention & Recovery.
Identifies and isolates intermittent test instability:
- Executes bounded repeat runs (e.g. 3 attempts).
- Classifies tests with non-deterministic outcomes as FLAKY.
- Distinguishes intermittent failures from genuine deterministic regressions.
- Never classifies a deterministic regression as flaky.
- Reports flaky tests in separate audit category.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.regression.models import (
    FlakyTestRecord,
    TestCaseResult,
    TestStatus,
)

log = logging.getLogger("crusor.regression.flaky")


class FlakyTestDetector:
    """
    Evaluates test stability through bounded re-runs and historical execution outcomes.
    """

    def evaluate_test_stability(
        self,
        test_id: str,
        execution_results: List[TestCaseResult],
    ) -> FlakyTestRecord:
        """
        Examines execution results for a test across multiple runs.
        Returns a FlakyTestRecord.
        """
        runs_count = len(execution_results)
        pass_count = sum(1 for r in execution_results if r.status == TestStatus.PASSING)
        fail_count = sum(1 for r in execution_results if r.status in (TestStatus.FAILING, TestStatus.BLOCKED))

        is_flaky = (pass_count > 0 and fail_count > 0)

        if is_flaky:
            rationale = (
                f"Test showed inconsistent outcomes across {runs_count} runs "
                f"({pass_count} passed, {fail_count} failed) without code changes"
            )
        elif fail_count == runs_count and runs_count > 0:
            rationale = "Deterministic failure across all repeat executions"
        else:
            rationale = "Consistently passing across all executions"

        return FlakyTestRecord(
            test_id=test_id,
            runs_count=runs_count,
            pass_count=pass_count,
            fail_count=fail_count,
            is_flaky=is_flaky,
            variance_rationale=rationale,
        )


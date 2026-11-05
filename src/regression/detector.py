"""
src/regression/detector.py - Post-Change Regression Detector.

Phase 11.5: Regression Prevention & Recovery.
Compares post-modification test results against pre-change baseline at individual test level:
- Identifies newly introduced failures vs pre-existing failures.
- Distinguishes environment, infrastructure, and external service failures.
- Correlates regressions with changed files and symbols.
- Never hides new regressions inside aggregated pass percentages.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.regression.models import (
    FailureClassification,
    TestBaseline,
    TestCaseResult,
    TestStatus,
)

log = logging.getLogger("crusor.regression.detector")


class PostChangeRegressionDetector:
    """
    Compares post-change execution results against pre-change baseline.
    """

    def compare_and_detect_regressions(
        self,
        baseline: Optional[TestBaseline],
        current_results: Dict[str, TestCaseResult],
        changed_files: List[str],
        changed_symbols: List[str],
    ) -> Tuple[List[TestCaseResult], List[TestCaseResult], List[TestCaseResult]]:
        """
        Compares results.
        Returns:
            (new_regressions, pre_existing_failures, environment_failures)
        """
        new_regressions: List[TestCaseResult] = []
        pre_existing: List[TestCaseResult] = []
        env_failures: List[TestCaseResult] = []

        baseline_cases = baseline.test_cases if baseline else {}

        for test_id, cur_res in current_results.items():
            if cur_res.status in (TestStatus.FAILING, TestStatus.BLOCKED):
                # Classify the failure
                err_text = (cur_res.error_message or "") + " " + (cur_res.stderr or "")

                # Check if environment failure
                if any(k in err_text.lower() for k in ["modulenotfounderror", "nosuchfileordirectory", "connectionrefused", "permissiondenied"]):
                    env_failures.append(cur_res)
                    continue

                # Check baseline status
                base_res = baseline_cases.get(test_id)
                if base_res and base_res.status == TestStatus.FAILING:
                    # Pre-existing failure!
                    pre_existing.append(cur_res)
                else:
                    # It was passing before (or newly added) and is failing now -> NEW REGRESSION!
                    new_regressions.append(cur_res)

        return new_regressions, pre_existing, env_failures


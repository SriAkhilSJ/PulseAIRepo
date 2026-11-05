"""
src/regression/performance_gate.py - Performance & FinOps Regression Auditor.

Phase 11.5: Regression Prevention & Recovery.
Compares post-change runtime and resource consumption against baseline:
- Measures test execution latency, memory consumption, and token expenditure.
- Connects cost metrics with Phase 9.7 FinOps tracking.
- Distinguishes genuine performance degradation from statistical noise.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("crusor.regression.performance_gate")


class PerformanceRegressionAuditor:
    """
    Evaluates execution latency, token expenditure, and memory overhead.
    """

    def compare_performance(
        self,
        baseline_metrics: Dict[str, float],
        post_change_metrics: Dict[str, float],
        threshold_ratio: float = 1.5,
    ) -> Dict[str, Any]:
        """
        Compares baseline vs post-change metrics.
        threshold_ratio: 1.5 means >50% increase triggers regression warning.
        """
        comparison: Dict[str, Any] = {
            "regressions_detected": False,
            "metrics": {},
            "warnings": [],
        }

        for metric_name, base_val in baseline_metrics.items():
            if metric_name in post_change_metrics:
                cur_val = post_change_metrics[metric_name]
                ratio = (cur_val / base_val) if base_val > 0 else 1.0

                is_regressed = (ratio > threshold_ratio and cur_val - base_val > 0.05)

                comparison["metrics"][metric_name] = {
                    "baseline": base_val,
                    "current": cur_val,
                    "ratio": round(ratio, 3),
                    "is_regressed": is_regressed,
                }

                if is_regressed:
                    comparison["regressions_detected"] = True
                    comparison["warnings"].append(
                        f"Metric '{metric_name}' degraded by {round((ratio - 1.0) * 100, 1)}% "
                        f"(baseline: {base_val}, current: {cur_val})"
                    )

        return comparison


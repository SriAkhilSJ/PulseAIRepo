"""
multi_vector_scorecard.py - Multi-Vector Quality & Efficiency Scorecard.

Pillar 6 of the Hardened Production Architecture.
Evaluates agent performance across a balanced multi-vector scorecard:
- Correctness: Acceptance Check Pass Rate
- Integrity: Regression Rate
- Efficiency: Token Consumption Ratio
- Speed: p50 & p95 Wall-Clock Latency
- Autonomy: Headless Completion Rate
- Stability: Repetitive Action Ratio (< 5%)
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class MultiVectorScorecard:
    run_id: str
    model: str
    total_checks_defined: int = 0
    checks_passed: int = 0
    checks_regressed: int = 0
    tokens_consumed: int = 0
    wall_clock_seconds: float = 0.0
    request_latencies_ms: List[float] = field(default_factory=list)
    total_actions: int = 0
    repetitive_actions: int = 0
    headless_completed: bool = False

    @property
    def pass_rate(self) -> float:
        if self.total_checks_defined == 0:
            return 1.0 if self.headless_completed else 0.0
        return round(self.checks_passed / self.total_checks_defined, 4)

    @property
    def regression_rate(self) -> float:
        if self.total_checks_defined == 0:
            return 0.0
        return round(self.checks_regressed / self.total_checks_defined, 4)

    @property
    def repetitive_action_ratio(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return round(self.repetitive_actions / self.total_actions, 4)

    @property
    def latency_p50_ms(self) -> float:
        if not self.request_latencies_ms:
            return 0.0
        return round(statistics.median(self.request_latencies_ms), 1)

    @property
    def latency_p95_ms(self) -> float:
        if not self.request_latencies_ms:
            return 0.0
        sorted_lats = sorted(self.request_latencies_ms)
        idx = int(0.95 * len(sorted_lats))
        return round(sorted_lats[min(idx, len(sorted_lats) - 1)], 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "correctness_pass_rate": self.pass_rate,
            "integrity_regression_rate": self.regression_rate,
            "efficiency_tokens_consumed": self.tokens_consumed,
            "speed_wall_clock_s": round(self.wall_clock_seconds, 2),
            "speed_p50_ms": self.latency_p50_ms,
            "speed_p95_ms": self.latency_p95_ms,
            "autonomy_completed": self.headless_completed,
            "stability_repetitive_ratio": self.repetitive_action_ratio,
        }

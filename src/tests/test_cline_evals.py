"""Cline-Standard Evals & Metrics Test Suite for PulseAI Agent Core.

Implements Cline's Layer 1 (Contract Tests), Layer 2 (MetricsCalculator: pass@k, pass^k, flakiness),
and Parallel Tool Calling evaluation contracts directly aligned with cline/evals.
"""
import math
from typing import List
import pytest

from src.prompts.claude_persona import CLAUDE_SYSTEM_PERSONA, AUTONOMOUS_SYSTEM_PERSONA
from src.graphs.parallel_tools import is_eligible, _batch_conflict


class ClineMetricsCalculator:
    """Cline-standard statistical metrics calculator (evals/analysis/src/metrics.ts).
    
    References:
    - HumanEval: https://arxiv.org/abs/2107.03374
    - pass@k: 1 - C(n-c, k) / C(n, k)
    - pass^k: C(c, k) / C(n, k)
    - flakiness: -p*log2(p) - (1-p)*log2(1-p)
    """

    @staticmethod
    def _comb(n: int, k: int) -> int:
        return math.comb(n, k)

    def pass_at_k(self, trials: List[bool], k: int) -> float:
        """Probability that at least 1 of k trials succeeds (HumanEval unbiased estimator)."""
        n = len(trials)
        c = sum(1 for t in trials if t)
        if n < k:
            raise ValueError(f"Cannot calculate pass@{k} with only {n} trials")
        if n - c < k:
            return 1.0
        if c == 0:
            return 0.0
        numerator = self._comb(n - c, k)
        denominator = self._comb(n, k)
        return 1.0 - (numerator / denominator)

    def pass_caret_k(self, trials: List[bool], k: int) -> float:
        """Probability that ALL k trials succeed (reliability metric)."""
        n = len(trials)
        c = sum(1 for t in trials if t)
        if n < k:
            raise ValueError(f"Cannot calculate pass^{k} with only {n} trials")
        if c < k:
            return 0.0
        numerator = self._comb(c, k)
        denominator = self._comb(n, k)
        return numerator / denominator

    def flakiness_score(self, trials: List[bool]) -> float:
        """Entropy-based measure of variance [0, 1]."""
        n = len(trials)
        if n == 0:
            return 0.0
        p = sum(1 for t in trials if t) / n
        if p == 0.0 or p == 1.0:
            return 0.0
        return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


def test_cline_metrics_pass_at_k():
    calc = ClineMetricsCalculator()
    # 5 trials, 3 passes -> pass@1 should be 3/5 = 0.6
    trials = [True, True, True, False, False]
    p_at_1 = calc.pass_at_k(trials, 1)
    assert abs(p_at_1 - 0.6) < 1e-5

    # pass@3 with 3 passes out of 5
    p_at_3 = calc.pass_at_k(trials, 3)
    assert p_at_3 > 0.0

    # All pass -> 1.0
    assert calc.pass_at_k([True, True, True], 2) == 1.0
    # All fail -> 0.0
    assert calc.pass_at_k([False, False, False], 2) == 0.0


def test_cline_metrics_pass_caret_k():
    calc = ClineMetricsCalculator()
    # 3 passes out of 3 trials -> pass^3 = 1.0
    assert calc.pass_caret_k([True, True, True], 3) == 1.0

    # 2 passes out of 3 trials -> pass^3 = 0.0 (not all pass)
    assert calc.pass_caret_k([True, True, False], 3) == 0.0

    # 4 passes out of 5 trials -> pass^2 = C(4,2) / C(5,2) = 6/10 = 0.6
    assert abs(calc.pass_caret_k([True, True, True, True, False], 2) - 0.6) < 1e-5


def test_cline_metrics_flakiness():
    calc = ClineMetricsCalculator()
    # Deterministic -> 0.0 entropy
    assert calc.flakiness_score([True, True, True]) == 0.0
    assert calc.flakiness_score([False, False, False]) == 0.0

    # 50/50 split -> maximum entropy = 1.0
    assert abs(calc.flakiness_score([True, False]) - 1.0) < 1e-5


def test_cline_parallel_tool_contract_in_prompts():
    """Verify that both system prompts enforce Cline's Parallel Tool Calling specification."""
    # Check interactive persona
    assert "Parallel Tool Calling" in CLAUDE_SYSTEM_PERSONA
    assert "Rule of Parallelism" in CLAUDE_SYSTEM_PERSONA
    assert "Never ping-pong serially" in CLAUDE_SYSTEM_PERSONA

    # Check autonomous persona
    assert "Parallel Tool Calling" in AUTONOMOUS_SYSTEM_PERSONA
    assert "Never ping-pong serially" in AUTONOMOUS_SYSTEM_PERSONA


def test_cline_scenario_04_multi_file_parallel_eligibility():
    """Verify that Cline's scenario 04 (Create multiple files: index.html + style.css + logo.png)
    is proven eligible for concurrent execution without conflict."""
    tools = {
        "write_file": object(),
        "generate_image": object(),
        "read_file": object(),
    }
    tool_calls = [
        {"name": "write_file", "args": {"path": "index.html", "content": "<html>...</html>"}},
        {"name": "write_file", "args": {"path": "style.css", "content": "body { font-family: Arial; }"}},
        {"name": "generate_image", "args": {"filename": "logo.png", "prompt": "tech logo"}},
    ]
    # No path conflict between distinct files
    assert not _batch_conflict(tool_calls, "/tmp/workspace")
    assert is_eligible(tool_calls, tools, "/tmp/workspace")


def test_cline_scenario_file_conflict_detection():
    """Verify that write-after-write or write-then-read on the SAME file triggers conflict refusal
    so it falls back to deterministic sequential execution."""
    tools = {
        "write_file": object(),
        "read_file": object(),
    }
    conflicting_calls = [
        {"name": "write_file", "args": {"path": "index.html", "content": "<html>1</html>"}},
        {"name": "read_file", "args": {"path": "index.html"}},
    ]
    # Touching the same file is refused for parallel execution
    assert _batch_conflict(conflicting_calls, "/tmp/workspace")
    assert not is_eligible(conflicting_calls, tools, "/tmp/workspace")

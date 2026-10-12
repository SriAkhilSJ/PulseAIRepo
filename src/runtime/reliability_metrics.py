"""Multi-trial reliability metrics for stochastic agent evals.

Modeled on the strongest open-source evaluators:
  - Cline (cline/cline evals/analysis/src/metrics.ts): pass@k, pass^k, flakiness
  - HumanEval (Chen et al. 2021): unbiased combinatorial pass@k estimator
  - Aider (Aider-AI/aider benchmark/benchmark.py): pass_rate_1/2, cost-per-edit
  - SWE-bench (SWE-bench/SWE-bench grading.py): attributable test execution
  - agent-eval-reliability: ICC, cluster-bootstrap CIs, honest-UNKNOWN rule

Two metrics pull apart what single-run scoring hides:
  - pass@k = 1 - C(n-c,k)/C(n,k)  — capability (at least one of k tries succeeds)
  - pass^k = C(c,k)/C(n,k)        — reliability (all k tries succeed)

The gap between them IS the flakiness story. A model at 80% pass@1 hits
pass^5 ~= 33% — best-of-5 looks strong while the user hits a wall 2 times
in 5. Production SLAs care about pass^k; demos select for pass@k.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional


def _comb(n: int, k: int) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased combinatorial pass@k (HumanEval / Chen et al. 2021).

    pass@k = 1 - C(n-c, k) / C(n, k)

    Uses sampling WITHOUT replacement — the naive (c/n)^k plug-in samples
    with replacement and biases upward (a vanity metric).
    """
    if n <= 0 or k <= 0 or k > n:
        return 0.0
    if c < 0 or c > n:
        return 0.0
    return 1.0 - (_comb(n - c, k) / _comb(n, k))


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Exact pass^k — probability all k tries succeed.

    pass^k = C(c, k) / C(n, k)
    """
    if n <= 0 or k <= 0 or k > n:
        return 0.0
    if c < 0 or c > n:
        return 0.0
    return _comb(c, k) / _comb(n, k)


def wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — honest CI for small n (not the binomial Wald).

    With n < 30 the textbook p +/- z*sqrt(p(1-p)/n) interval is anti-
    conservative. Wilson stays calibrated down to n=1.
    """
    if n <= 0:
        return (0.0, 1.0)
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def flakiness_entropy(pass_rates: list[float]) -> float:
    """Shannon entropy of the pass distribution (Cline flakiness score).

    H = -sum(p_i * log2(p_i)) over the histogram of per-task pass rates
    bucketed into [0, 0.25, 0.5, 0.75, 1.0]. H=0 means all tasks at the
    same rate (stable); H>1.5 means wildly inconsistent.
    """
    if not pass_rates:
        return 0.0
    buckets = [0, 0, 0, 0, 0]
    for r in pass_rates:
        idx = min(4, max(0, int(r * 4)))
        buckets[idx] += 1
    n = len(pass_rates)
    h = 0.0
    for b in buckets:
        if b > 0:
            p = b / n
            h -= p * math.log2(p)
    return round(h, 4)


def icc_1(trial_matrix: list[list[float]]) -> float:
    """ICC(1) — one-way random effects, n0-corrected for unbalanced designs.

    ICC(1) = (MSB - MSW) / (MSB + (n0 - 1) * MSW)

    Values near 1.0 mean run-to-run variance is small relative to per-task
    variance (the agent has consistent skill). Values near 0.0 mean most
    variance is luck — a single run is a coin flip, not a measurement.
    """
    if not trial_matrix or not any(trial_matrix):
        return 0.0
    rows = [r for r in trial_matrix if r]
    n_rows = len(rows)
    if n_rows < 2:
        return 0.0
    n_cols = min(len(r) for r in rows)
    if n_cols < 2:
        return 0.0
    row_means = [sum(r[:n_cols]) / n_cols for r in rows]
    grand = sum(row_means) / n_rows
    n0 = n_cols
    msb = n_cols * sum((m - grand) ** 2 for m in row_means) / (n_rows - 1)
    msw = sum(
        (r[i] - row_means[j]) ** 2
        for j, r in enumerate(rows)
        for i in range(n_cols)
    ) / (n_rows * (n_cols - 1))
    denom = msb + (n0 - 1) * msw
    if denom <= 0:
        return 0.0
    return round((msb - msw) / denom, 4)


@dataclass
class ReliabilityReport:
    """Multi-trial reliability verdict for one task or a suite of tasks."""

    n_trials: int
    n_passed: int
    pass_at_1: float
    pass_at_k: float
    k: int
    pass_hat_k: float
    ci_low: float
    ci_high: float
    icc1: float
    flakiness_entropy: float
    verdict: str
    honest: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_trials": self.n_trials,
            "n_passed": self.n_passed,
            "pass_at_1": round(self.pass_at_1, 4),
            "pass_at_k": round(self.pass_at_k, 4),
            "k": self.k,
            "pass_hat_k": round(self.pass_hat_k, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "icc1": self.icc1,
            "flakiness_entropy": self.flakiness_entropy,
            "verdict": self.verdict,
        }


def evaluate_reliability(
    trial_outcomes: list[bool],
    trial_matrix: Optional[list[list[float]]] = None,
    k: int = 3,
) -> ReliabilityReport:
    """Grade a task's multi-trial run honestly.

    The honest-UNKNOWN rule: you cannot estimate pass@10 from 5 trials without
    extrapolating, so we clamp k to n and say so via the verdict string.
    """
    n = len(trial_outcomes)
    c = sum(1 for o in trial_outcomes if o)
    if n == 0:
        return ReliabilityReport(
            n_trials=0, n_passed=0, pass_at_1=0.0, pass_at_k=0.0, k=k,
            pass_hat_k=0.0, ci_low=0.0, ci_high=1.0, icc1=0.0,
            flakiness_entropy=0.0, verdict="no-trials", honest=False,
        )
    k_eff = min(k, n)
    p_at_1 = c / n
    p_at_k = pass_at_k(n, c, k_eff)
    p_hat_k = pass_hat_k(n, c, k_eff)
    lo, hi = wilson_ci(p_at_1, n)
    icc = icc_1(trial_matrix) if trial_matrix else 0.0
    entropy = flakiness_entropy([p_at_1])

    if n < 3:
        verdict = "insufficient-trials"
    elif c == n:
        verdict = "reliable-pass"
    elif c == 0:
        verdict = "broken"
    elif p_hat_k < 0.34:
        verdict = "flaky"
    else:
        verdict = "capable-not-reliable"

    honest = k_eff >= k and verdict != "insufficient-trials"
    return ReliabilityReport(
        n_trials=n, n_passed=c, pass_at_1=p_at_1, pass_at_k=p_at_k, k=k_eff,
        pass_hat_k=p_hat_k, ci_low=lo, ci_high=hi, icc1=icc,
        flakiness_entropy=entropy, verdict=verdict, honest=honest,
    )


def cost_per_correct_edit(total_cost_usd: float, n_correct: int) -> Optional[float]:
    """Aider's CFO-grade $/edit metric — the true cost of a correct deliverable.

    Raw price-per-token is deceptive: inefficient models burn millions of cheap
    tokens in retry loops. $/edit penalizes that directly. A model needing 4
    attempts to pass aggregates all 4 attempts' cost.
    """
    if n_correct <= 0:
        return None
    return round(total_cost_usd / n_correct, 4)


def detect_malformed_response(text: str) -> list[str]:
    """Aider-style malformed/truncated response detection.

    Catches the failure modes that single-run pass@1 scoring hides: truncated
    JSON, incomplete tool calls, leaked reasoning, empty outputs.
    """
    issues: list[str] = []
    if not text or not text.strip():
        issues.append("empty-output")
        return issues
    stripped = text.strip()
    if stripped.endswith(("...", "…", "[truncated]", "[cut off]")):
        issues.append("truncated-output")
    if stripped.count("{") != stripped.count("}"):
        issues.append("unbalanced-braces")
    if stripped.count("[") != stripped.count("]"):
        issues.append("unbalanced-brackets")
    if "<think>" in stripped or "</think>" in stripped:
        issues.append("leaked-reasoning")
    if stripped.endswith(","):
        issues.append("trailing-comma")
    return issues


def parse_test_execution(output: str) -> dict[str, Any]:
    """SWE-bench attributable verification: did the suite ACTUALLY run?

    Parses pytest/unittest/node-style output for executed-count and result
    counts. The critical SWE-bench lesson: "Executed 0 of 0" under
    FAIL_ONLY eval scores every test as passing — a zero-count read as
    evidence turns a suite that never ran into a resolved instance.
    """
    import re
    result: dict[str, Any] = {
        "ran": False,
        "executed": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "invalid": False,
        "evidence": "",
    }
    if not output:
        return result

    m = re.search(r"Executed\s+(\d+)\s+of\s+(\d+)", output)
    if m:
        result["ran"] = True
        result["executed"] = int(m.group(1))
        result["passed"] = int(m.group(2))
        result["evidence"] = m.group(0)
        if result["executed"] == 0:
            result["invalid"] = True
        return result

    m = re.search(r"=+ .*?(\d+) passed.* =+", output)
    if m:
        result["ran"] = True
        result["passed"] = int(m.group(1))
        result["evidence"] = m.group(0)[:80]
        return result

    m = re.search(r"Tests run:\s+(\d+),\s+Failures:\s+(\d+),\s+Errors:\s+(\d+)", output)
    if m:
        result["ran"] = True
        result["executed"] = int(m.group(1))
        result["passed"] = int(m.group(1)) - int(m.group(2)) - int(m.group(3))
        result["failed"] = int(m.group(2)) + int(m.group(3))
        result["evidence"] = m.group(0)
        return result

    if re.search(r"\b(passed|failed|error)\b", output, re.IGNORECASE):
        result["ran"] = True
        result["evidence"] = output.strip()[:80]
    return result


def tool_efficiency(tool_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-tool efficiency: success rate, failure count, retry overhead.

    High retry counts on one tool = the agent is fighting the interface,
    not the task. This is the signal that distinguishes "model is weak" from
    "tool is hostile".
    """
    by_tool: dict[str, dict[str, int]] = {}
    for tc in tool_records:
        name = tc.get("name", "unknown")
        status = tc.get("status", "unknown")
        if name not in by_tool:
            by_tool[name] = {"calls": 0, "success": 0, "failed": 0}
        by_tool[name]["calls"] += 1
        if status == "success":
            by_tool[name]["success"] += 1
        elif status == "failed":
            by_tool[name]["failed"] += 1
    for name, stats in by_tool.items():
        total = stats["calls"]
        stats["success_rate"] = round(stats["success"] / total, 4) if total else 0.0
    return by_tool

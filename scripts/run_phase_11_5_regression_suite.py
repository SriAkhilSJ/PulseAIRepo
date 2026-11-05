#!/usr/bin/env python3
"""
scripts/run_phase_11_5_regression_suite.py - Phase 11.5 Regression Prevention & Recovery Adversarial Suite Runner.

Executes all 36 adversarial test scenarios defined in
  src/tests/test_phase_11_5_regression_prevention.py
and records structured JSON evidence to:
  bench-results/phase115_regression_prevention/PHASE_11_5_ADVERSARIAL_RESULTS.json
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BENCH_DIR = REPO_ROOT / "bench-results" / "phase115_regression_prevention"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSON = BENCH_DIR / "PHASE_11_5_ADVERSARIAL_RESULTS.json"

from src.tests.test_phase_11_5_regression_prevention import TestPhase115RegressionPrevention


def run_adversarial_suite():
    print("=" * 80)
    print("CRUSOR AI IDE -- PHASE 11.5 REGRESSION PREVENTION & RECOVERY SUITE")
    print("Repository: SriAkhilSJ/PulseAIRepo | Branch: feat/prompt-cache-stabilization")
    print("Budget: INR 0.00 (Zero paid LLM API calls)")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPhase115RegressionPrevention)

    results = []
    total_start = time.time()
    all_passed = True

    for test in suite:
        test_name = test._testMethodName
        print(f"Running scenario: {test_name} ... ", end="", flush=True)

        single_suite = unittest.TestSuite([test])
        runner = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0)

        t0 = time.time()
        test_res = runner.run(single_suite)
        dur = time.time() - t0

        if test_res.wasSuccessful():
            status = "PASS"
            err_msg = None
            print(f"[PASS] ({dur:.4f}s)")
        else:
            status = "FAIL"
            all_passed = False
            err_msg = ""
            if test_res.failures:
                err_msg += test_res.failures[0][1]
            if test_res.errors:
                err_msg += test_res.errors[0][1]
            print(f"[FAIL] ({dur:.4f}s)")

        results.append({
            "scenario": test_name,
            "status": status,
            "duration_seconds": round(dur, 4),
            "error": err_msg,
        })

    total_duration = time.time() - total_start
    passed_count = sum(1 for r in results if r["status"] == "PASS")
    total_count = len(results)

    verdict = "REGRESSION PREVENTION VERIFIED" if all_passed else "REGRESSION PREVENTION FAILED"

    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "11.5",
        "title": "Regression Prevention & Recovery Engine Adversarial Test Results",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "budget_inr": 0.00,
        "paid_llm_api_calls": 0,
        "total_scenarios": total_count,
        "passed_scenarios": passed_count,
        "failed_scenarios": total_count - passed_count,
        "pass_rate_pct": round(passed_count / total_count * 100, 2) if total_count > 0 else 0.0,
        "total_duration_seconds": round(total_duration, 4),
        "verdict": verdict,
        "results": results,
    }

    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("=" * 80)
    print(f"Results: {passed_count}/{total_count} PASSED in {total_duration:.3f}s")
    print(f"Verdict: {verdict}")
    print(f"Saved: {RESULTS_JSON}")
    print("=" * 80)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    run_adversarial_suite()


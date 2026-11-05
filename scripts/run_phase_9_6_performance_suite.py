#!/usr/bin/env python3
"""
scripts/run_phase_9_6_performance_suite.py - Phase 9.6 Performance Suite Runner.

Executes the 20 deterministic performance, observability, and reliability scenarios.
Outputs:
  bench-results/phase96_desktop_performance/PHASE_9_6_PERFORMANCE_REGRESSION_RESULTS.json
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

# Add PulseAIRepo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.tests.test_phase_9_6_desktop_performance import TestPhase96DesktopPerformance


def main():
    print("=" * 80)
    print("CRUSOR AI IDE - PHASE 9.6 DESKTOP PERFORMANCE & OBSERVABILITY SUITE")
    print("=" * 80)
    print("Repository: SriAkhilSJ/PulseAIRepo")
    print("Branch: feat/prompt-cache-stabilization")
    print("Platform: Windows 10/11 x64")
    print("Budget Expended: INR 0.00 (Zero paid LLM API calls)")
    print("-" * 80)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPhase96DesktopPerformance)
    all_test_names = [test._testMethodName for test in suite if test is not None and hasattr(test, "_testMethodName")]

    start_time = time.time()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    duration_s = time.time() - start_time

    failed_map = {test._testMethodName: err for test, err in result.failures}
    error_map = {test._testMethodName: err for test, err in result.errors}

    test_records = []
    for tname in all_test_names:
        status = "PASSED"
        err = None
        if tname in failed_map:
            status = "FAILED"
            err = failed_map[tname]
        elif tname in error_map:
            status = "ERROR"
            err = error_map[tname]

        test_records.append({
            "name": tname,
            "status": status,
            "error": err,
        })

    out_dir = REPO_ROOT / "bench-results" / "phase96_desktop_performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "PHASE_9_6_PERFORMANCE_REGRESSION_RESULTS.json"

    passed_count = result.testsRun - len(result.failures) - len(result.errors)
    success_rate = round((passed_count / max(1, result.testsRun)) * 100, 2)
    is_success = result.wasSuccessful()

    report_payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "9.6",
        "title": "Desktop Performance & Observability Suite",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "verdict": "DESKTOP PERFORMANCE AND OBSERVABILITY VERIFIED" if is_success else "VERIFICATION FAILED",
        "total_tests": result.testsRun,
        "passed": passed_count,
        "failed": len(result.failures),
        "errors": len(result.errors),
        "success_rate_pct": success_rate,
        "duration_seconds": round(duration_s, 4),
        "paid_api_calls": 0,
        "paid_api_cost_inr": 0.0,
        "baseline_targets_ms": {
            "startup_cold": 3500.0,
            "startup_warm": 1200.0,
            "startup_sidecar": 1000.0,
            "ipc_round_trip": 15.0,
            "bridge_first_token": 800.0,
            "context_retrieval": 250.0,
            "inline_completion": 180.0,
            "diff_preview": 300.0,
        },
        "tests": test_records,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print("-" * 80)
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Passed: {passed_count}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success Rate: {success_rate}%")
    print(f"Total Duration: {duration_s:.4f}s")
    print(f"Verdict: {report_payload['verdict']}")
    print(f"Output File: {out_file}")
    print("=" * 80)

    if not is_success:
        sys.exit(1)


if __name__ == "__main__":
    main()


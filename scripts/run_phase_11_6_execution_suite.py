#!/usr/bin/env python3
"""
scripts/run_phase_11_6_execution_suite.py - Phase 11.6 Adversarial Test Suite Runner.

Executes all 44 deterministic scenarios in src/tests/test_phase_11_6_autonomous_execution.py
and writes machine-readable results to:
  bench-results/phase116_autonomous_execution/PHASE_11_6_ADVERSARIAL_RESULTS.json
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

OUTPUT_DIR = REPO_ROOT / "bench-results" / "phase116_autonomous_execution"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_FILE = OUTPUT_DIR / "PHASE_11_6_ADVERSARIAL_RESULTS.json"


def main():
    print("=" * 80)
    print("CRUSOR AI IDE -- PHASE 11.6 AUTONOMOUS ENGINEERING EXECUTION SUITE")
    print("Repository: SriAkhilSJ/PulseAIRepo | Branch: feat/prompt-cache-stabilization")
    print("Budget: INR 0.00 (Zero paid LLM API calls)")
    print("=" * 80)

    from src.tests.test_phase_11_6_autonomous_execution import TestPhase116AutonomousExecution

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPhase116AutonomousExecution)

    results_data = []
    total_passed = 0
    total_failed = 0
    total_errors = 0
    start_time = time.time()

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
            err = None
            total_passed += 1
        elif test_res.failures:
            status = "FAIL"
            err = test_res.failures[0][1]
            total_failed += 1
        else:
            status = "ERROR"
            err = test_res.errors[0][1]
            total_errors += 1

        print(f"[{status}] ({dur:.4f}s)")
        results_data.append({
            "test_name": test_name,
            "status": status,
            "duration_seconds": round(dur, 4),
            "error": err,
        })

    total_duration = time.time() - start_time
    total_tests = total_passed + total_failed + total_errors
    verdict = "AUTONOMOUS EXECUTION VERIFIED" if (total_failed == 0 and total_errors == 0 and total_tests > 0) else "AUTONOMOUS EXECUTION FAILED"

    report_payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "11.6",
        "title": "Autonomous Engineering Execution Suite - Phase 11.6",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "budget_inr": 0.00,
        "paid_llm_api_budget_inr": 0.00,
        "verdict": verdict,
        "summary": {
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "errors": total_errors,
            "pass_rate_pct": round(total_passed / total_tests * 100, 2) if total_tests > 0 else 0.0,
            "total_duration_seconds": round(total_duration, 4),
        },
        "scenarios": results_data,
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print("=" * 80)
    print(f"Results: {total_passed}/{total_tests} PASSED in {total_duration:.3f}s")
    print(f"Verdict: {verdict}")
    print(f"Saved: {REPORT_FILE}")
    print("=" * 80)

    if verdict != "AUTONOMOUS EXECUTION VERIFIED":
        sys.exit(1)


if __name__ == "__main__":
    main()

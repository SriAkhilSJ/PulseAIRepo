#!/usr/bin/env python3
"""
scripts/run_phase_11_7_verification_suite.py - Phase 11.7 Adversarial Test Suite Runner.

Executes all 44 deterministic adversarial test scenarios in:
  src/tests/test_phase_11_7_independent_verification.py
Validates:
- Independence of verification authority
- Requirement-to-implementation verification
- Test integrity and weak-test detection
- Actual runtime & workflow verification
- Security & code quality defect detection
- Defect lifecycle management
- Independent completion gate
- Demonstrations Scenarios A through H
Saves machine-readable results to:
  bench-results/phase117_independent_verification/PHASE_11_7_ADVERSARIAL_RESULTS.json
"""

from __future__ import annotations

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

BENCH_DIR = REPO_ROOT / "bench-results" / "phase117_independent_verification"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
REPORT_JSON = BENCH_DIR / "PHASE_11_7_ADVERSARIAL_RESULTS.json"


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE -- PHASE 11.7 INDEPENDENT VERIFICATION & QA SUITE")
    print("Repository: SriAkhilSJ/PulseAIRepo | Branch: feat/prompt-cache-stabilization")
    print("Budget: INR 0.00 (Zero paid LLM API calls)")
    print("=" * 80)

    from src.tests.test_phase_11_7_independent_verification import TestPhase117IndependentVerification

    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase117IndependentVerification)
    total_tests = suite.countTestCases()

    passed = 0
    failed = 0
    errors = 0
    details = []

    t_all_start = time.time()

    for test in suite:
        test_name = test._testMethodName
        sys.stdout.write(f"Running scenario: {test_name} ... ")
        sys.stdout.flush()

        res = unittest.TestResult()
        t0 = time.time()
        test.run(res)
        duration = round(time.time() - t0, 4)

        if res.wasSuccessful():
            passed += 1
            print(f"[PASS] ({duration:.4f}s)")
            details.append({"name": test_name, "status": "PASS", "duration_seconds": duration})
        elif res.failures:
            failed += 1
            err_msg = res.failures[0][1]
            print(f"[FAIL] ({duration:.4f}s)")
            details.append({"name": test_name, "status": "FAIL", "duration_seconds": duration, "error": err_msg})
        elif res.errors:
            errors += 1
            err_msg = res.errors[0][1]
            print(f"[ERROR] ({duration:.4f}s)")
            details.append({"name": test_name, "status": "ERROR", "duration_seconds": duration, "error": err_msg})

    total_duration = round(time.time() - t_all_start, 4)
    all_passed = (passed == total_tests) and (failed == 0) and (errors == 0)
    verdict = "INDEPENDENT VERIFICATION VERIFIED" if all_passed else "INDEPENDENT VERIFICATION FAILED"

    print("=" * 80)
    print(f"Results: {passed}/{total_tests} PASSED in {total_duration:.3f}s")
    print(f"Verdict: {verdict}")

    report_payload = {
        "phase": "11.7",
        "phase_name": "Independent Verification & Quality Assurance",
        "timestamp": time.time(),
        "total_scenarios": total_tests,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total_duration_seconds": total_duration,
        "paid_llm_cost_inr": 0.00,
        "verdict": verdict,
        "scenarios": details,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print(f"Saved: {REPORT_JSON}")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())


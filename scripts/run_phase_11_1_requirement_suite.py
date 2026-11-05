#!/usr/bin/env python3
"""
scripts/run_phase_11_1_requirement_suite.py -- Phase 11.1 Verification Suite Runner.

Executes all 23 deterministic requirement understanding scenarios and saves:
  bench-results/phase111_requirement_understanding/PHASE_11_1_ADVERSARIAL_RESULTS.json
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

from src.tests.test_phase_11_1_requirement_understanding import TestPhase111RequirementUnderstanding

BENCH_DIR = REPO_ROOT / "bench-results" / "phase111_requirement_understanding"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = BENCH_DIR / "PHASE_11_1_ADVERSARIAL_RESULTS.json"


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE -- PHASE 11.1 REQUIREMENT UNDERSTANDING & DISCOVERY TEST SUITE")
    print("Repository: SriAkhilSJ/PulseAIRepo | Branch: feat/prompt-cache-stabilization")
    print("Budget: INR 0.00 (Zero paid LLM API calls)")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPhase111RequirementUnderstanding)

    scenarios = []
    t_start = time.time()
    passed_count = 0
    failed_count = 0

    for test in suite:
        test_name = test._testMethodName
        print(f"Running scenario: {test_name} ... ", end="", flush=True)
        result = unittest.TestResult()
        t0 = time.time()
        test.run(result)
        dur = time.time() - t0

        if result.wasSuccessful():
            print(f"[PASS] ({dur:.4f}s)")
            passed_count += 1
            scenarios.append({
                "test": test_name,
                "status": "PASS",
                "duration_s": round(dur, 4),
                "paid_cost": "0.00",
            })
        else:
            print(f"[FAIL] ({dur:.4f}s)")
            failed_count += 1
            err_msg = ""
            if result.failures:
                err_msg = result.failures[0][1]
            elif result.errors:
                err_msg = result.errors[0][1]
            scenarios.append({
                "test": test_name,
                "status": "FAIL",
                "duration_s": round(dur, 4),
                "paid_cost": "0.00",
                "error": err_msg,
            })

    total_duration = time.time() - t_start
    verdict = "REQUIREMENT UNDERSTANDING VERIFIED" if failed_count == 0 else "REQUIREMENT UNDERSTANDING FAILED"

    payload = {
        "phase": "11.1",
        "title": "Requirement Understanding & Discovery",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(total_duration, 3),
        "paid_llm_api_budget_expended": "0.00",
        "verdict": verdict,
        "scenarios_tested": len(scenarios),
        "scenarios_passed": passed_count,
        "scenarios_failed": failed_count,
        "scenarios": scenarios,
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("=" * 80)
    print(f"Results: {passed_count}/{len(scenarios)} PASSED in {total_duration:.2f}s")
    print(f"Verdict: {verdict}")
    print(f"Saved: {OUT_JSON}")
    print("=" * 80)
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

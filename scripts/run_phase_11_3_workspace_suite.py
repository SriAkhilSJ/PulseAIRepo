"""
scripts/run_phase_11_3_workspace_suite.py - Verification Runner for Phase 11.3.

Runs all 34 deterministic test scenarios covering:
- Clean and dirty workspace baselines
- Staged, unstaged, and untracked file preservation
- Agent create/modify/delete/rename tracking
- Path safety and boundary enforcement
- Optimistic concurrency and atomic writes
- Transaction journaling and crash recovery
- Risk-based approvals and replay prevention
- Cleanliness checks and terminal restrictions
- Git discipline and Upstream Invariant 7 protection
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
import unittest
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.tests.test_phase_11_3_workspace_discipline import TestPhase113WorkspaceDiscipline


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE -- PHASE 11.3 WORKSPACE DISCIPLINE & CHANGE MANAGEMENT SUITE")
    print("Repository: SriAkhilSJ/PulseAIRepo | Branch: feat/prompt-cache-stabilization")
    print("Budget: INR 0.00 (Zero paid LLM API calls)")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPhase113WorkspaceDiscipline)

    start_total = time.time()
    results_list = []
    passed_count = 0
    failed_count = 0

    for test in suite:
        test_name = test._testMethodName
        t0 = time.time()
        test_res = unittest.TestResult()
        print(f"Running scenario: {test_name} ... ", end="", flush=True)

        test.run(test_res)
        dur = time.time() - t0

        if test_res.wasSuccessful():
            print(f"[PASS] ({dur:.4f}s)")
            passed_count += 1
            results_list.append({
                "test": test_name,
                "status": "PASS",
                "duration_s": round(dur, 4),
                "paid_cost": "0.00",
            })
        else:
            err_msg = ""
            if test_res.errors:
                err_msg = test_res.errors[0][1]
            elif test_res.failures:
                err_msg = test_res.failures[0][1]
            print(f"[FAIL] ({dur:.4f}s)")
            failed_count += 1
            results_list.append({
                "test": test_name,
                "status": "FAIL",
                "duration_s": round(dur, 4),
                "paid_cost": "0.00",
                "error": err_msg,
            })

    total_dur = round(time.time() - start_total, 3)
    verdict = "WORKSPACE DISCIPLINE VERIFIED" if failed_count == 0 else "WORKSPACE DISCIPLINE FAILED"

    print("=" * 80)
    print(f"Results: {passed_count}/{len(results_list)} PASSED in {total_dur}s")
    print(f"Verdict: {verdict}")

    bench_dir = REPO_ROOT / "bench-results" / "phase113_workspace_discipline"
    bench_dir.mkdir(parents=True, exist_ok=True)
    out_file = bench_dir / "PHASE_11_3_ADVERSARIAL_RESULTS.json"

    data = {
        "phase": "11.3",
        "title": "Workspace Discipline & Change Management",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": total_dur,
        "paid_llm_api_budget_expended": "0.00",
        "verdict": verdict,
        "scenarios_tested": len(results_list),
        "scenarios_passed": passed_count,
        "scenarios_failed": failed_count,
        "scenarios": results_list,
    }

    out_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved: {out_file}")
    print("=" * 80)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


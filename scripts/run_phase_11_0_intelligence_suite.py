#!/usr/bin/env python3
"""
scripts/run_phase_11_0_intelligence_suite.py -- Phase 11.0 Project Intelligence Verification Runner.

Executes all 18 deterministic test scenarios and writes results to:
  bench-results/phase110_project_intelligence/PHASE_11_0_ADVERSARIAL_RESULTS.json
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

BENCH_DIR = REPO_ROOT / "bench-results" / "phase110_project_intelligence"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
REPORT_JSON = BENCH_DIR / "PHASE_11_0_ADVERSARIAL_RESULTS.json"


class ResultsCollector:
    def __init__(self):
        self.reports = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            self.reports.append(report)


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE — PHASE 11.0 PROJECT INTELLIGENCE VERIFICATION RUNNER")
    print("=" * 80)

    collector = ResultsCollector()
    test_file = str(REPO_ROOT / "src" / "tests" / "test_phase_11_0_project_intelligence.py")

    t0 = time.time()
    exit_code = pytest.main(["-v", test_file], plugins=[collector])
    duration = time.time() - t0

    scenarios = []
    for r in collector.reports:
        test_method = r.nodeid.split("::")[-1]
        scenarios.append({
            "test": test_method,
            "status": "PASS" if r.passed else "FAIL",
            "duration_s": round(r.duration, 4),
            "paid_cost": "0.00",
        })

    passed_count = sum(1 for s in scenarios if s["status"] == "PASS")
    total_count = len(scenarios)

    payload = {
        "phase": "11.0",
        "title": "Project & Repository Intelligence",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(duration, 3),
        "paid_llm_api_budget_expended": "0.00",
        "verdict": "PROJECT INTELLIGENCE VERIFIED" if (passed_count == total_count and total_count == 18) else "VERIFICATION_FAILED",
        "scenarios_tested": total_count,
        "scenarios_passed": passed_count,
        "scenarios": scenarios,
    }

    REPORT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWritten {passed_count}/{total_count} scenario results to: {REPORT_JSON}")
    print(f"Overall Phase Verdict: {payload['verdict']}")
    return int(exit_code)


if __name__ == "__main__":
    sys.exit(main())


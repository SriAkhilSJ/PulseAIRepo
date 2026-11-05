#!/usr/bin/env python3
"""
scripts/run_phase_10_0_identity_suite.py -- Phase 10.0 Enterprise Identity & RBAC Verification Runner.

Executes all 25 deterministic adversarial scenarios and writes results to:
  bench-results/phase100_enterprise_identity_rbac/PHASE_10_0_ADVERSARIAL_RESULTS.json
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

BENCH_DIR = REPO_ROOT / "bench-results" / "phase100_enterprise_identity_rbac"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
REPORT_JSON = BENCH_DIR / "PHASE_10_0_ADVERSARIAL_RESULTS.json"


class FinOpsResultsCollector:
    def __init__(self):
        self.reports = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            self.reports.append(report)


def main() -> int:
    print("=" * 80)
    print("CRUSOR AI IDE — PHASE 10.0 ENTERPRISE IDENTITY & RBAC VERIFICATION RUNNER")
    print("=" * 80)

    collector = FinOpsResultsCollector()
    test_file = str(REPO_ROOT / "src" / "tests" / "test_phase_10_0_enterprise_identity_rbac.py")

    t0 = time.time()
    exit_code = pytest.main(["-v", test_file], plugins=[collector])
    duration = time.time() - t0

    scenarios = []
    for r in collector.reports:
        # e.g. test_01_invalid_authentication_token
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
        "phase": "10.0",
        "title": "Enterprise Identity, Authentication & Role-Based Access Control",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(duration, 3),
        "paid_llm_api_budget_expended": "0.00",
        "verdict": "ENTERPRISE IDENTITY AND ACCESS CONTROL VERIFIED" if (passed_count == total_count and total_count == 25) else "VERIFICATION_FAILED",
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


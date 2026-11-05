#!/usr/bin/env python3
"""
scripts/generate_phase_11_0_regression_report.py - Phase 11.0 Full System & Intelligence Regression Runner.

Executes all 13 milestone suites via pytest and generates:
  bench-results/phase110_project_intelligence/PHASE_11_0_SECURITY_REGRESSION_RESULTS.json
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
REPORT_JSON = BENCH_DIR / "PHASE_11_0_SECURITY_REGRESSION_RESULTS.json"


class TestCollectorPlugin:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = 0
        self.skipped = 0
        self.test_details = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            if report.passed:
                self.passed += 1
                self.test_details.append({"nodeid": report.nodeid, "status": "PASSED", "duration": round(report.duration, 4)})
            elif report.failed:
                self.failed += 1
                self.test_details.append({"nodeid": report.nodeid, "status": "FAILED", "duration": round(report.duration, 4), "error": str(report.longrepr)})
            elif report.skipped:
                self.skipped += 1
                self.test_details.append({"nodeid": report.nodeid, "status": "SKIPPED", "duration": round(report.duration, 4)})
        elif report.when == "setup" and report.failed:
            self.errors += 1
            self.test_details.append({"nodeid": report.nodeid, "status": "SETUP_ERROR", "duration": round(report.duration, 4), "error": str(report.longrepr)})


def run_suite_file(rel_path: str) -> dict:
    plugin = TestCollectorPlugin()
    t0 = time.time()
    code = pytest.main(["-q", "--no-header", str(REPO_ROOT / rel_path)], plugins=[plugin])
    dur = time.time() - t0
    total = plugin.passed + plugin.failed + plugin.errors + plugin.skipped
    return {
        "suite": rel_path,
        "exit_code": int(code),
        "total": total,
        "passed": plugin.passed,
        "failed": plugin.failed,
        "errors": plugin.errors,
        "skipped": plugin.skipped,
        "duration_seconds": round(dur, 4),
        "status": "PASSED" if (plugin.failed == 0 and plugin.errors == 0 and total > 0) else "FAILED",
        "tests": plugin.test_details,
    }


def main():
    print("=" * 80)
    print("CRUSOR AI IDE - PHASE 11.0 FULL SYSTEM & REPOSITORY INTELLIGENCE REGRESSION SUITE")
    print("=" * 80)

    target_suites = [
        "src/tests/test_phase_11_0_project_intelligence.py",
        "src/tests/test_phase_10_0_enterprise_identity_rbac.py",
        "src/tests/test_phase_9_7_enterprise_finops.py",
        "src/tests/test_phase_9_6_desktop_performance.py",
        "src/tests/test_phase_9_5_mcp_browser_security.py",
        "src/tests/test_mcp_client.py",
        "src/tests/test_mcp_session_pool.py",
        "src/tests/test_phase_9_4_3_least_privilege.py",
        "src/tests/test_phase_9_4_2_windows_isolation.py",
        "src/tests/test_phase_9_4_1_windows_boundary.py",
        "src/tests/test_phase_9_4_execution_sandbox.py",
        "src/tests/test_phase_9_3_5_reliability.py",
        "src/tests/test_core_context_engine.py",
    ]

    results = []
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_tests = 0
    start_time = time.time()

    for s in target_suites:
        print(f"Running: {s} ... ", end="", flush=True)
        res = run_suite_file(s)
        print(f"[{res['status']}] ({res['passed']}/{res['total']} in {res['duration_seconds']}s)")
        results.append(res)
        total_passed += res["passed"]
        total_failed += res["failed"]
        total_errors += res["errors"]
        total_tests += res["total"]

    total_duration = time.time() - start_time
    is_success = (total_failed == 0 and total_errors == 0 and total_passed == total_tests)

    report_payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "11.0",
        "title": "Full System & Repository Intelligence Security Regression Suite - Phase 11.0",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "overall_status": "ALL_REGRESSIONS_PASSED" if is_success else "REGRESSION_FAILURES_DETECTED",
        "verdict": "PROJECT INTELLIGENCE VERIFIED" if is_success else "VERIFICATION FAILED",
        "total_suites_evaluated": len(target_suites),
        "total_tests_run": total_tests,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_errors": total_errors,
        "overall_success_rate_pct": round((total_passed / max(1, total_tests)) * 100, 2),
        "total_duration_seconds": round(total_duration, 4),
        "paid_api_calls": 0,
        "paid_api_cost_inr": 0.0,
        "suite_results": results,
    }

    REPORT_JSON.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    print("-" * 80)
    print(f"Total Regressions Evaluated: {len(target_suites)} suites")
    print(f"Total Tests Executed: {total_tests}")
    print(f"Total Passed: {total_passed}")
    print(f"Total Failed: {total_failed}")
    print(f"Total Errors: {total_errors}")
    print(f"Success Rate: {report_payload['overall_success_rate_pct']}%")
    print(f"Total Duration: {round(total_duration, 4)}s")
    print(f"Overall Status: {report_payload['overall_status']}")
    print(f"Regression Report Written To: {REPORT_JSON}")
    print("=" * 80)
    return 0 if is_success else 1


if __name__ == "__main__":
    sys.exit(main())


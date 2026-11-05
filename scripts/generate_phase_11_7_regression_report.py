#!/usr/bin/env python3
"""
scripts/generate_phase_11_7_regression_report.py - Phase 11.7 Full System & Regression Report Generator.

Executes all 20 milestone test suites via pytest and generates:
  bench-results/phase117_independent_verification/PHASE_11_7_SECURITY_REGRESSION_RESULTS.json
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BENCH_DIR = REPO_ROOT / "bench-results" / "phase117_independent_verification"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
REPORT_JSON = BENCH_DIR / "PHASE_11_7_SECURITY_REGRESSION_RESULTS.json"


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
            self.test_details.append({"nodeid": report.nodeid, "status": "SETUP_ERROR", "duration": round(report.duration, 4)})


ALL_SUITES = [
    "src/tests/test_phase_11_7_independent_verification.py",
    "src/tests/test_phase_11_6_autonomous_execution.py",
    "src/tests/test_phase_11_5_regression_prevention.py",
    "src/tests/test_phase_11_4_change_impact_analysis.py",
    "src/tests/test_phase_11_3_workspace_discipline.py",
    "src/tests/test_phase_11_2_architecture_intelligence.py",
    "src/tests/test_phase_11_1_requirement_understanding.py",
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


def run_full_regression():
    print("=" * 80)
    print("CRUSOR AI IDE -- FULL SYSTEM REGRESSION & INDEPENDENT VERIFICATION RUNNER")
    print("Executing all 20 milestone test suites (Phase 9.3 through Phase 11.7)")
    print("=" * 80)

    start_all = time.time()
    suite_results = []
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_skipped = 0

    for suite_rel in ALL_SUITES:
        suite_path = REPO_ROOT / suite_rel
        if not suite_path.exists():
            print(f"[-] Suite not found: {suite_rel}")
            continue

        print(f"\n[+] Running suite: {suite_rel} ...")
        collector = TestCollectorPlugin()
        t0 = time.time()

        ret = pytest.main([
            str(suite_path),
            "-q",
            "--tb=short",
            "-o", "pythonpath=.",
            "-o", "asyncio_mode=strict",
            "-o", "testpaths=src/tests",
        ], plugins=[collector])

        duration = round(time.time() - t0, 4)
        suite_total = collector.passed + collector.failed + collector.errors + collector.skipped
        status = "PASSED" if (collector.failed == 0 and collector.errors == 0 and collector.passed > 0) else "FAILED"

        print(f"    Status: {status} | Total: {suite_total} | Passed: {collector.passed} | Failed: {collector.failed} | Duration: {duration}s")

        total_passed += collector.passed
        total_failed += collector.failed
        total_errors += collector.errors
        total_skipped += collector.skipped

        suite_results.append({
            "suite": suite_rel,
            "status": status,
            "total": suite_total,
            "passed": collector.passed,
            "failed": collector.failed,
            "errors": collector.errors,
            "skipped": collector.skipped,
            "duration_seconds": duration,
        })

    total_duration = round(time.time() - start_all, 4)
    grand_total = total_passed + total_failed + total_errors + total_skipped
    pass_rate = round((total_passed / grand_total * 100), 2) if grand_total > 0 else 0.0

    print("\n" + "=" * 80)
    print("FULL REGRESSION SUMMARY")
    print(f"Total Suites: {len(suite_results)}")
    print(f"Total Tests:  {grand_total}")
    print(f"Passed:       {total_passed}")
    print(f"Failed:       {total_failed}")
    print(f"Errors:       {total_errors}")
    print(f"Pass Rate:    {pass_rate}%")
    print(f"Total Time:   {total_duration}s")
    print("=" * 80)

    report_data = {
        "timestamp": time.time(),
        "phase": "11.7",
        "phase_name": "Independent Verification & Quality Assurance",
        "summary": {
            "total_suites": len(suite_results),
            "passed_suites": sum(1 for s in suite_results if s["status"] == "PASSED"),
            "failed_suites": sum(1 for s in suite_results if s["status"] == "FAILED"),
            "total_tests": grand_total,
            "passed_tests": total_passed,
            "failed_tests": total_failed,
            "error_tests": total_errors,
            "skipped_tests": total_skipped,
            "pass_rate_pct": pass_rate,
            "total_duration_seconds": total_duration,
        },
        "suite_results": suite_results,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print(f"Regression report written to: {REPORT_JSON}")
    return 0 if (total_failed == 0 and total_errors == 0) else 1


if __name__ == "__main__":
    sys.exit(run_full_regression())


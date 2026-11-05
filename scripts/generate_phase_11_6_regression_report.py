#!/usr/bin/env python3
"""
scripts/generate_phase_11_6_regression_report.py - Phase 11.6 Full System & Autonomous Execution Runner.

Executes all 19 milestone suites via pytest and generates:
  bench-results/phase116_autonomous_execution/PHASE_11_6_SECURITY_REGRESSION_RESULTS.json
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

BENCH_DIR = REPO_ROOT / "bench-results" / "phase116_autonomous_execution"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
REPORT_JSON = BENCH_DIR / "PHASE_11_6_SECURITY_REGRESSION_RESULTS.json"


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
    print("CRUSOR AI IDE - PHASE 11.6 FULL SYSTEM & AUTONOMOUS EXECUTION REGRESSION SUITE")
    print("Repository: SriAkhilSJ/PulseAIRepo | Branch: feat/prompt-cache-stabilization")
    print("Budget: INR 0.00 (Zero paid LLM API calls)")
    print("=" * 80)

    target_suites = [
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
        "phase": "11.6",
        "title": "Full System & Autonomous Execution Suite - Phase 11.6",
        "repository": "SriAkhilSJ/PulseAIRepo",
        "branch": "feat/prompt-cache-stabilization",
        "budget_inr": 0.00,
        "paid_llm_api_budget_inr": 0.00,
        "overall_status": "PASSED" if is_success else "FAILED",
        "verdict": "AUTONOMOUS EXECUTION VERIFIED" if is_success else "AUTONOMOUS EXECUTION FAILED",
        "summary": {
            "total_suites": len(target_suites),
            "passed_suites": sum(1 for r in results if r["status"] == "PASSED"),
            "failed_suites": sum(1 for r in results if r["status"] != "PASSED"),
            "total_tests": total_tests,
            "passed_tests": total_passed,
            "failed_tests": total_failed,
            "error_tests": total_errors,
            "skipped_tests": sum(r["skipped"] for r in results),
            "pass_rate_pct": round(total_passed / total_tests * 100, 2) if total_tests > 0 else 0.0,
            "total_duration_seconds": round(total_duration, 4),
        },
        "suite_results": results,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print("=" * 80)
    print(f"Regression Suite Complete: {total_passed}/{total_tests} passed in {total_duration:.2f}s")
    print(f"Verdict: {report_payload['verdict']}")
    print(f"Saved: {REPORT_JSON}")
    print("=" * 80)

    if not is_success:
        sys.exit(1)


if __name__ == "__main__":
    main()


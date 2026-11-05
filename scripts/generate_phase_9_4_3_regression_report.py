"""
generate_phase_9_4_3_regression_report.py - Run all core security and platform test suites and record JSON results.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = REPO_ROOT / "bench-results" / "phase943_least_privilege" / "PHASE_9_4_3_REGRESSION_RESULTS.json"
ROOT_OUT_FILE = REPO_ROOT / "PHASE_9_4_3_REGRESSION_RESULTS.json"

TEST_FILES = [
    "src/tests/test_phase_9_3_4_2_workflows.py",
    "src/tests/test_phase_9_3_4_3_security.py",
    "src/tests/test_phase_9_3_5_reliability.py",
    "src/tests/test_phase_9_4_execution_sandbox.py",
    "src/tests/test_phase_9_4_1_windows_boundary.py",
    "src/tests/test_phase_9_4_2_windows_isolation.py",
    "src/tests/test_phase_9_4_3_least_privilege.py",
]

def main():
    print("Running Regression Test Suites for Phase 9.4.3...")
    all_results = []
    total_passed = 0
    total_failed = 0
    total_skipped = 0

    for test_file in TEST_FILES:
        full_path = REPO_ROOT / test_file
        print(f"Executing: {test_file} ...", end=" ", flush=True)
        t0 = datetime.datetime.now(datetime.timezone.utc)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(full_path), "-v", "--tb=short"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        t1 = datetime.datetime.now(datetime.timezone.utc)
        duration_s = (t1 - t0).total_seconds()

        passed = proc.returncode == 0
        status = "PASSED" if passed else "FAILED"
        print(f"{status} ({duration_s:.2f}s)")

        lines = proc.stdout.splitlines()
        test_cases = []
        for line in lines:
            if "::" in line and ("PASSED" in line or "FAILED" in line or "SKIPPED" in line):
                parts = line.strip().split()
                nodeid = parts[0]
                outcome = parts[1] if len(parts) > 1 else "UNKNOWN"
                test_cases.append({"nodeid": nodeid, "outcome": outcome})
                if outcome == "PASSED":
                    total_passed += 1
                elif outcome == "FAILED":
                    total_failed += 1
                elif outcome == "SKIPPED":
                    total_skipped += 1

        all_results.append({
            "module": test_file,
            "exit_code": proc.returncode,
            "passed": passed,
            "duration_s": duration_s,
            "test_count": len(test_cases),
            "test_cases": test_cases,
            "stderr_snippet": proc.stderr[:500] if proc.stderr else "",
        })

    summary = {
        "suite_version": "9.4.3",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_modules": len(TEST_FILES),
        "modules_passed": sum(1 for r in all_results if r["passed"]),
        "total_tests": total_passed + total_failed + total_skipped,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
        "pass_rate_pct": (total_passed / (total_passed + total_failed)) * 100.0 if (total_passed + total_failed) > 0 else 0.0,
        "modules": all_results,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    ROOT_OUT_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nAll tests completed. Total Passed: {total_passed}/{total_passed + total_failed} ({summary['pass_rate_pct']:.1f}%)")
    print(f"Results written to: {OUT_FILE} and {ROOT_OUT_FILE}")

if __name__ == "__main__":
    main()


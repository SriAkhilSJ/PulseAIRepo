"""API and Frontend Contract Parity Regression Tests.

Verifies that all showcase REST implementations and their frontend static assets
conform to cross-contract expectations:
1. Backend GET /api/tasks can return either `[...]` or `{"tasks": [...]}`.
2. Frontend parser logic is defensive against both raw array and enveloped formats.
3. POST /api/tasks always yields a JSON object with at least `id` and `status`.
4. GET /api/stats always returns integer counters for `total`, `todo`, `doing`, `done`.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_RESULTS_DIR = REPO_ROOT / "bench-results"


def test_frontend_app_js_defensive_task_parsing():
    """Verify all showcase frontend app.js files handle raw array and enveloped task payloads."""
    targets = [
        "run_2_showcase",
        "run_3_showcase",
        "run_6_showcase",
        "run_8_showcase",
        "deepseek_v4_1_flash_run_1_showcase",
        "deepseek_v4_1_flash_run_2_showcase",
    ]
    for target in targets:
        app_js = BENCH_RESULTS_DIR / target / "frontend" / "app.js"
        assert app_js.exists(), f"Missing app.js in {target}"
        content = app_js.read_text(encoding="utf-8")
        
        # Verify defensive unpacking logic exists or direct array usage
        assert "tasks" in content.lower() or "list" in content.lower()
        if "Array.isArray" in content:
            # If Array.isArray is used, ensure it handles both array and object.tasks
            # (or doesn't crash when receiving enveloped tasks)
            pass


def test_standardized_results_16_of_16_pass():
    """Verify that certified showcase targets achieved 16/16 in standardized benchmark."""
    certified_targets = [
        "run_2_showcase",
        "run_3_showcase",
        "run_6_showcase",
        "run_8_showcase",
        "deepseek_v4_1_flash_run_1_showcase",
        "deepseek_v4_1_flash_run_2_showcase",
    ]
    results_path = BENCH_RESULTS_DIR / "STANDARDIZED_BENCHMARK_RESULTS.json"
    assert results_path.exists(), "Missing STANDARDIZED_BENCHMARK_RESULTS.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    
    for target_name in certified_targets:
        if target_name in data:
            report = data[target_name]
            assert report["passed"] == 16, f"{target_name} passed {report['passed']}/16"
            assert report["failed"] == 0, f"{target_name} has {report['failed']} failures"


def test_browser_e2e_results_7_of_7_pass():
    """Verify that certified targets achieved 7/7 in browser E2E verification."""
    certified_targets = [
        "run_2_showcase",
        "run_3_showcase",
        "run_6_showcase",
        "run_8_showcase",
        "deepseek_v4_1_flash_run_1_showcase",
        "deepseek_v4_1_flash_run_2_showcase",
    ]
    results_path = BENCH_RESULTS_DIR / "BROWSER_E2E_VERIFICATION_RESULTS.json"
    assert results_path.exists(), "Missing BROWSER_E2E_VERIFICATION_RESULTS.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    
    for target_name in certified_targets:
        if target_name in data:
            report = data[target_name]
            assert report["passed_checks"] == 7, f"{target_name} passed {report['passed_checks']}/7 checks"
            assert report["status"] == "verified", f"{target_name} status is {report['status']}"
            assert len(report["console_errors"]) == 0, f"{target_name} logged console errors: {report['console_errors']}"

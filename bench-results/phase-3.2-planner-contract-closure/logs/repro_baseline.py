"""Reproduce the eight Phase 11.6 contract failures with full detail.

Provider-free. Each case builds a fresh workspace, runs the real orchestrator
(mock/deterministic requirement analysis), catches PlanValidationError and
dumps the persisted contract plus the requirement metadata the contract saw.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.orchestration.contract import (
    _mentioned_files,
    _requirement_classification,
    _requirement_description,
    _requirement_id,
    requirement_intent,
)
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator

CASES = [
    ("test_02_complex_product_request", "Build a multi-tier ecommerce store with catalog, checkout, and inventory modules", "t02"),
    ("test_04_nontechnical_user_request", "Build an online marketplace for my new pottery business", "t04"),
    ("test_05_essential_clarification_interruption", "Build an app for customers", "t05"),
    ("test_11_architecture_decision_integration", "Build high volume ingestion pipeline", "t11"),
    ("test_26_pre_existing_failure_classification", "Clean task", "t26"),
    ("test_38_scenario_b_existing_bug_demonstration", "Fix authentication return value in auth_bug.py", "demo_scenario_b"),
    ("test_40_scenario_d_regression_introduced_demonstration", "Refactor database connection pool with regression safeguard", "demo_scenario_d"),
    ("test_42_scenario_f_unresolved_business_decision_demonstration", "Build subscription tier with payment processor", "demo_scenario_f"),
]


def main() -> int:
    reports = []
    for test_name, prompt, task_id in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="p32_baseline_"))
        ws = tmp / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        if task_id == "demo_scenario_b":
            (ws / "src").mkdir()
            (ws / "src" / "auth_bug.py").write_text("def authenticate(): return False\n", encoding="utf-8")
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(ws), tenant_id="tenant_p32", storage_dir=str(tmp / "storage")
        )
        entry = {"test": test_name, "prompt": prompt, "task_id": task_id}
        try:
            result = orch.run_task(task_prompt=prompt, task_id=task_id)
            entry["outcome"] = "PASS"
            entry["verdict"] = getattr(result.verdict, "value", str(result.verdict))
        except Exception as exc:  # noqa: BLE001 - this is the reproduction
            entry["outcome"] = "FAIL"
            entry["error_type"] = type(exc).__name__
            entry["error"] = str(exc)[:4000]
            entry["traceback_tail"] = traceback.format_exc().splitlines()[-6:]

        # Requirement metadata the contract consumed.
        try:
            analysis = orch.req_system.analyze_request(
                task_prompt=prompt, workspace_root=str(ws),
                task_id=task_id, tenant_id="tenant_p32",
            )
            spec = analysis.specification
            raw = getattr(spec, "all_requirements", None)
            reqs = raw() if callable(raw) else (raw or getattr(spec, "requirements", []))
            entry["requirements"] = [
                {
                    "id": _requirement_id(r),
                    "description": _requirement_description(r),
                    "classification_raw": str(getattr(getattr(r, "classification", None), "value", getattr(r, "classification", ""))),
                    "contract_classification": _requirement_classification(r),
                    "intent": requirement_intent(_requirement_description(r)).value,
                    "mentioned_files": _mentioned_files(_requirement_description(r)),
                }
                for r in reqs
            ]
        except Exception as exc:  # noqa: BLE001
            entry["requirements_error"] = f"{type(exc).__name__}: {exc}"

        # Persisted contract.
        try:
            path = ws / ".crusorai" / "contracts" / f"{task_id}_contract.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                entry["contract"] = {
                    "requirement_map": data.get("requirement_map"),
                    "ambiguities": data.get("ambiguities"),
                    "components": [
                        {
                            "target": c.get("target_file"),
                            "role": c.get("role"),
                            "requirement_ids": c.get("requirement_ids"),
                        }
                        for c in data.get("components", [])
                    ],
                }
        except Exception as exc:  # noqa: BLE001
            entry["contract_error"] = f"{type(exc).__name__}: {exc}"
        reports.append(entry)
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

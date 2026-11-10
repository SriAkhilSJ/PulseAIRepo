"""Post-fix extraction for the eight Phase 11.6 prompts (no execution)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.intelligence.requirement_integration import RequirementIntelligenceSystem
from src.intelligence.requirement_models import RequirementClassification
from src.orchestration.contract import (
    _mentioned_files,
    _requirement_classification,
    _requirement_description,
    _requirement_id,
    extract_contract,
    requirement_intent,
)

CASES = [
    ("test_02", "Build a multi-tier ecommerce store with catalog, checkout, and inventory modules", "t02"),
    ("test_04", "Build an online marketplace for my new pottery business", "t04"),
    ("test_05", "Build an app for customers", "t05"),
    ("test_11", "Build high volume ingestion pipeline", "t11"),
    ("test_26", "Clean task", "t26"),
    ("test_38", "Fix authentication return value in auth_bug.py", "demo_scenario_b"),
    ("test_40", "Refactor database connection pool with regression safeguard", "demo_scenario_d"),
    ("test_42", "Build subscription tier with payment processor", "demo_scenario_f"),
]


def main() -> int:
    import tempfile

    reports = []
    for name, prompt, task_id in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="p32_after_"))
        ws = tmp / "workspace"
        ws.mkdir()
        sys_req = RequirementIntelligenceSystem()
        analysis = sys_req.analyze_request(
            task_prompt=prompt, workspace_root=str(ws),
            task_id=task_id, tenant_id="tenant_p32",
        )
        spec = analysis.specification
        raw = getattr(spec, "all_requirements", None)
        reqs = raw() if callable(raw) else (raw or getattr(spec, "requirements", []))
        contract = extract_contract(
            prompt, reqs, [], task_id=task_id, workspace=str(ws),
        )
        reports.append({
            "test": name,
            "prompt": prompt,
            "requirements": [
                {
                    "id": _requirement_id(r),
                    "classification": _requirement_classification(r),
                    "intent": requirement_intent(_requirement_description(r)).value,
                    "mentioned": _mentioned_files(_requirement_description(r)),
                }
                for r in reqs
            ],
            "requirement_map": contract.requirement_map,
            "components": [
                {"target": c.target_file, "role": c.role, "requirements": c.requirement_ids}
                for c in contract.components
            ],
            "ambiguities": contract.ambiguities,
        })
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

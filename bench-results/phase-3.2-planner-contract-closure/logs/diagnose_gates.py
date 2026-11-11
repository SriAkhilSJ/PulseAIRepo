"""Compare a passing and a failing task's discovery/plan/testing gates."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("CRUSORAI_TEST_MODE", "1")

from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from unittest.mock import patch

_ORIG_TESTING = EngineeringExecutionOrchestrator._testing_required

def _spy_testing(prompt, discovery, plan_dag):
    result = _ORIG_TESTING(prompt, discovery, plan_dag)
    print("GATE", json.dumps({
        "prompt": prompt[:50],
        "testing_required": result,
        "discovery_files": len(getattr(discovery, "files", None) or []),
        "nodes": [(n.node_id, list(n.target_files)) for n in plan_dag.nodes.values()],
    }), flush=True)
    return result

CASES = [
    ("pass_02", "Build a multi-tier ecommerce store with catalog, checkout, and inventory modules", "t02"),
    ("fail_26", "Clean task", "t26"),
    ("fail_38", "Fix authentication return value in auth_bug.py", "demo_scenario_b"),
    ("fail_40", "Refactor database connection pool with regression safeguard", "demo_scenario_d"),
]


def main() -> int:
    out = []
    for name, prompt, task_id in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="p32_gate_"))
        ws = tmp / "workspace"
        ws.mkdir(parents=True)
        if name == "fail_38":
            (ws / "src").mkdir()
            (ws / "src" / "auth_bug.py").write_text("def authenticate(): return False\n", encoding="utf-8")
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(ws), tenant_id="tenant_p32", storage_dir=str(tmp / "storage")
        )
        with patch.object(EngineeringExecutionOrchestrator, "_testing_required", staticmethod(_spy_testing)):
            res = orch.run_task(task_prompt=prompt, task_id=task_id)
        entry = {"case": name, "verdict": res.verdict.value, "files": list(res.files_changed)}
        # journal
        for path in tmp.rglob("*.jsonl"):
            try:
                events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except Exception:
                continue
            for ev in events:
                if ev.get("event_type") in {"DISCOVERY_COMPLETED", "PLAN_GENERATED", "COMPLETION_EVALUATED", "POLICY_EVALUATED"}:
                    entry.setdefault("journal", []).append({
                        "event": ev.get("event_type"),
                        "payload": ev.get("payload"),
                    })
        out.append(entry)
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

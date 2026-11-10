"""Diagnose the three remaining Phase 11.6 verdict failures."""
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

from src.orchestration.orchestrator import EngineeringExecutionOrchestrator

CASES = [
    ("test_26", "Clean task", "t26"),
    ("test_38", "Fix authentication return value in auth_bug.py", "demo_scenario_b"),
    ("test_40", "Refactor database connection pool with regression safeguard", "demo_scenario_d"),
]


def main() -> int:
    out = []
    for name, prompt, task_id in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="p32_diag_"))
        ws = tmp / "workspace"
        ws.mkdir(parents=True)
        if name == "test_38":
            (ws / "src").mkdir()
            (ws / "src" / "auth_bug.py").write_text("def authenticate(): return False\n", encoding="utf-8")
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(ws), tenant_id="tenant_p32", storage_dir=str(tmp / "storage")
        )
        entry = {"case": name, "prompt": prompt}
        try:
            res = orch.run_task(task_prompt=prompt, task_id=task_id)
            entry.update({
                "verdict": getattr(res.verdict, "value", str(res.verdict)),
                "files_changed": list(res.files_changed),
                "tests_executed": list(res.tests_executed),
                "tests_passed": list(res.tests_passed),
                "tests_failed": list(res.tests_failed),
                "limitations": list(res.remaining_limitations),
                "user_action": res.user_action_required,
            })
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback_tail"] = traceback.format_exc().splitlines()[-8:]
        # diagnostic artifacts
        diag = ws / "diagnostics"
        if diag.exists():
            entry["diagnostics"] = sorted(p.name for p in diag.iterdir() if p.is_file())[:8]
            report = sorted(diag.glob("PERFORMANCE_REPORT_*.md"))
            if report:
                entry["report_head"] = report[0].read_text(encoding="utf-8", errors="replace")[:500]
        out.append(entry)
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

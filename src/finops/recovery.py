"""Startup reconciliation for interrupted financial and submission state.

Live11's second turn left ``res_d7990e4d3dc3`` in ``in_flight`` because Electron
was stopped while the provider call was outstanding. A process that dies cannot
settle its own call, so the next process must resolve the durable state:

* ``reserved``  -> release (the adapter marks ``in_flight`` before dispatch)
* ``in_flight`` -> uncertain (dispatch may have reached the provider)

Submission ledgers get the same treatment: a ``running`` submission from a dead
process becomes ``failed`` so a reconnect cannot replay it as a new turn.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

_PROCESS_START = time.time()


def _read_accounting(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def reconcile_workspace_finops(workspace_root: str | Path, *, reason: str = "process_restart",
                               force: bool = False) -> Dict[str, Any]:
    """Reconcile every task FinOps file in one workspace.

    By default only reservations created **before this process started** are
    touched, so a late first frame in a multi-session process cannot reconcile a
    call that is currently in flight. ``force=True`` is for shutdown, when the
    process is about to disappear.
    """
    workspace = Path(workspace_root).expanduser().resolve()
    finops_dir = workspace / ".crusorai" / "finops"
    summary: Dict[str, Any] = {
        "workspace": str(workspace),
        "reason": reason,
        "files_scanned": 0,
        "tasks_reconciled": 0,
        "events": [],
        "failures": [],
    }
    if not finops_dir.is_dir():
        return summary
    cutoff = float("inf") if force else _PROCESS_START
    for path in sorted(finops_dir.glob("*_finops.json")):
        summary["files_scanned"] += 1
        try:
            data = _read_accounting(path)
        except Exception as exc:  # noqa: BLE001
            summary["failures"].append({"file": path.name, "error": str(exc)[:300]})
            continue
        active = data.get("active_reservations") or {}
        if not isinstance(active, dict) or not active:
            continue
        old_ids = {
            str(rid) for rid, row in active.items()
            if force or float((row or {}).get("created_at") or 0.0) < cutoff
        }
        if not old_ids:
            continue
        accounting = data.get("accounting") or {}
        task_id = str(accounting.get("task_id") or path.stem.removesuffix("_finops"))
        budget = float(accounting.get("budget_inr") or 0.0)
        tokens = int(accounting.get("token_budget") or 150000)
        try:
            from src.orchestration.finops_governor import OrchestrationFinOpsGovernor

            governor = OrchestrationFinOpsGovernor(
                task_id,
                budget_inr=budget,
                token_budget=tokens,
                storage_dir=str(finops_dir),
                workspace_root=str(workspace),
            )
            events = governor.reconcile_orphaned_reservations(
                reason=reason, reservation_ids=None if force else old_ids,
            )
            if events:
                summary["tasks_reconciled"] += 1
                summary["events"].extend(events)
        except Exception as exc:  # noqa: BLE001 - preserve hold, report
            summary["failures"].append({
                "file": path.name,
                "task_id": task_id,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            })
    return summary


def reconcile_workspace_submissions(workspace_root: str | Path) -> Dict[str, Any]:
    """Mark abandoned ``running`` submissions as failed (no replay)."""
    from src.runtime.submission_ledger import get_submission_ledger

    workspace = str(Path(workspace_root).expanduser().resolve())
    try:
        ledger = get_submission_ledger(workspace)
        changed = ledger.reconcile_running()
        return {
            "workspace": workspace,
            "reconciled": len(changed),
            "submission_ids": [rec.submission_id for rec in changed],
        }
    except Exception as exc:  # noqa: BLE001 - ledger corruption fails closed at use
        return {"workspace": workspace, "reconciled": 0, "error": str(exc)[:300]}


def reconcile_workspace(workspace_root: str | Path, *, reason: str = "process_restart") -> Dict[str, Any]:
    """Both ledgers, one receipt for startup/shutdown diagnostics."""
    return {
        "finops": reconcile_workspace_finops(workspace_root, reason=reason),
        "submissions": reconcile_workspace_submissions(workspace_root),
    }

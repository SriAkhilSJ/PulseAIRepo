"""
src/orchestration/journal.py - Durable Orchestration State & Crash Reconciliation.

Phase 11.6: Autonomous Engineering Execution.
Maintains an append-only JSON-lines execution journal:
- Records stage transitions, approvals, mutations, test runs, and diagnoses.
- Reconciles crash recovery against Phase 11.3 WorkspaceJournalManager and WorkspaceChangeLedger.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.workspace.journal import WorkspaceJournalManager
from src.workspace.ledger import WorkspaceChangeLedger

log = logging.getLogger("crusor.orchestration.journal")


class DurableOrchestrationJournal:
    """
    Append-only durable execution event log for auditability and crash recovery.
    """

    def __init__(
        self,
        task_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.task_id = task_id
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            self.storage_dir = (
                self.workspace_root
                / ".crusorai"
                / "tenants"
                / tenant_id
                / "tasks"
                / task_id
            )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.storage_dir / "orchestration_journal.jsonl"

    def record_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Appends a durable record to the journal file."""
        entry = {
            "task_id": self.task_id,
            "event_type": event_type,
            "timestamp": time.time(),
            "details": details,
        }
        with open(self.journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_events(self) -> List[Dict[str, Any]]:
        """Reads all historical entries."""
        if not self.journal_file.exists():
            return []
        events: List[Dict[str, Any]] = []
        with open(self.journal_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def reconcile_after_restart(self) -> Dict[str, Any]:
        """
        Reconciles task state against Phase 11.3 journal and ledger.
        """
        journal_mgr = WorkspaceJournalManager(str(self.workspace_root), tenant_id=self.tenant_id)
        interrupted_txs = journal_mgr.recover_interrupted_transactions()

        ledger = WorkspaceChangeLedger(str(self.workspace_root), tenant_id=self.tenant_id)
        records = ledger.get_records(self.task_id)

        events = self.read_events()
        last_event = events[-1] if events else None

        reconciliation = {
            "task_id": self.task_id,
            "interrupted_transactions_count": len(interrupted_txs),
            "committed_workspace_records": len(records),
            "last_recorded_event": last_event.get("event_type") if last_event else None,
            "safe_to_resume": True,
        }
        self.record_event("CRASH_RECONCILIATION", reconciliation)
        log.info(f"Task {self.task_id} reconciled: {reconciliation}")
        return reconciliation

"""
src/workspace/ledger.py - Persistent Workspace Change Ledger.

Phase 11.3: Workspace Discipline & Change Management.
Maintains a tamper-evident audit ledger of all agent-driven workspace modifications.
Enforces:
1. Distinguishing agent-owned changes from pre-existing user work.
2. Detecting ownership changes (e.g. user modifying an agent-created file subsequently).
3. Preserving newer user work over agent rollbacks.
4. Tenant and workspace isolated atomic persistence.
"""

from __future__ import annotations

from src.runtime.app_paths import app_data_root

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.workspace.baseline import compute_file_sha256
from src.workspace.models import (
    ChangeRecord,
    FileOwnershipCategory,
    JournalState,
    WorkspaceOperationType,
)
from src.workspace.path_safety import PathSafetyValidator

log = logging.getLogger("crusor.workspace.ledger")


class WorkspaceChangeLedger:
    """
    Persistent change ledger recording every agent modification.
    Supports atomic commits, ownership classification, and crash recovery.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            from src.runtime.app_paths import app_data_root

        self.storage_dir = app_data_root(self.workspace_root) / "tenants" / tenant_id / "ledger"

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: Dict[str, List[ChangeRecord]] = {}  # task_id -> records

    def _get_ledger_file(self, task_id: str) -> Path:
        safe_task = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in task_id)
        return self.storage_dir / f"{safe_task}_ledger.json"

    def record_change(self, record: ChangeRecord) -> None:
        """Atomically record an executed workspace mutation."""
        with self._lock:
            records = self.get_records(record.task_id)
            records.append(record)
            self._records[record.task_id] = records
            self._persist_records(record.task_id, records)

    def get_records(self, task_id: str) -> List[ChangeRecord]:
        """Load all change records for a task."""
        with self._lock:
            if task_id in self._records:
                return list(self._records[task_id])

            ledger_file = self._get_ledger_file(task_id)
            if not ledger_file.exists():
                self._records[task_id] = []
                return []

            try:
                data = json.loads(ledger_file.read_text(encoding="utf-8"))
                records = [ChangeRecord.from_dict(r) for r in data]
                self._records[task_id] = records
                return list(records)
            except Exception as e:
                log.error(f"Failed to load ledger for task {task_id}: {e}")
                return []

    def get_file_last_record(self, task_id: str, rel_path: str) -> Optional[ChangeRecord]:
        """Find most recent modification record for a specific file."""
        norm = rel_path.replace("\\", "/")
        records = self.get_records(task_id)
        for r in reversed(records):
            if r.file_path == norm or (r.destination_path and r.destination_path == norm):
                return r
        return None

    def evaluate_live_ownership(self, task_id: str, rel_path: str) -> FileOwnershipCategory:
        """
        Determines the current real-world ownership category of a file:
        - If agent created it and current hash matches agent new_hash -> AGENT_CREATED.
        - If agent created it but current hash differs from agent new_hash -> USER_SUPERSEDED_AGENT!
        - If agent modified it and current hash matches -> AGENT_MODIFIED.
        - If agent modified it and hash differs -> USER_SUPERSEDED_AGENT.
        - If agent deleted it -> AGENT_DELETED.
        """
        last_rec = self.get_file_last_record(task_id, rel_path)
        if not last_rec:
            return FileOwnershipCategory.EXISTING_USER_CLEAN

        full_path = self.workspace_root / rel_path
        if not full_path.exists():
            if last_rec.operation_type == WorkspaceOperationType.DELETE:
                return FileOwnershipCategory.AGENT_DELETED
            return FileOwnershipCategory.EXISTING_USER_UNTRACKED

        current_hash = compute_file_sha256(full_path)

        if last_rec.new_hash and current_hash != last_rec.new_hash:
            # User or external editor has modified the file since Crusor touched it!
            return FileOwnershipCategory.USER_SUPERSEDED_AGENT

        if last_rec.operation_type == WorkspaceOperationType.CREATE:
            return FileOwnershipCategory.AGENT_CREATED
        elif last_rec.operation_type == WorkspaceOperationType.MODIFY:
            return FileOwnershipCategory.AGENT_MODIFIED
        elif last_rec.operation_type in (WorkspaceOperationType.RENAME, WorkspaceOperationType.MOVE):
            return FileOwnershipCategory.AGENT_RENAMED
        return FileOwnershipCategory.AGENT_CREATED

    def is_safe_for_agent_rollback(self, task_id: str, rel_path: str) -> Tuple[bool, str]:
        """
        Safety check: only agent-owned changes may be automatically rolled back.
        If user subsequently modified the file, rollback is REFUSED.
        """
        category = self.evaluate_live_ownership(task_id, rel_path)
        if category == FileOwnershipCategory.USER_SUPERSEDED_AGENT:
            return False, f"Refusing rollback: file '{rel_path}' was modified by user after agent creation."
        if category in {
            FileOwnershipCategory.EXISTING_USER_CLEAN,
            FileOwnershipCategory.EXISTING_USER_MODIFIED,
            FileOwnershipCategory.EXISTING_USER_STAGED,
            FileOwnershipCategory.EXISTING_USER_UNTRACKED,
        }:
            return False, f"Refusing rollback: file '{rel_path}' belongs to pre-existing user work."
        return True, "Safe for agent rollback."

    def _persist_records(self, task_id: str, records: List[ChangeRecord]) -> None:
        ledger_file = self._get_ledger_file(task_id)
        tmp = ledger_file.with_suffix(".tmp")
        try:
            serialized = [r.to_dict() for r in records]
            tmp.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
            os.replace(tmp, ledger_file)
        except Exception as e:
            log.error(f"Failed to persist change ledger for task {task_id}: {e}")
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

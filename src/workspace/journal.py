"""
src/workspace/journal.py - Workspace Operation Journal & Crash Recovery.

Phase 11.3: Workspace Discipline & Change Management.
Tracks multi-file operations across lifecycle states:
PLANNED -> APPROVED -> IN_PROGRESS -> APPLIED -> VERIFIED (or FAILED -> ROLLBACK_PENDING -> ROLLED_BACK).
Provides crash recovery and selective rollback preserving user-modified work.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.runtime.app_paths import app_data_root
from src.workspace.baseline import compute_file_sha256
from src.workspace.ledger import WorkspaceChangeLedger
from src.workspace.models import (
    ChangeRecord,
    FileOwnershipCategory,
    JournalState,
    TransactionJournalEntry,
    WorkspaceOperationType,
)

log = logging.getLogger("crusor.workspace.journal")


class WorkspaceJournalManager:
    """
    Manages transactional multi-file changes and crash recovery.
    Enforces that rollbacks only revert verified agent-owned changes.
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
            self.storage_dir = app_data_root(self.workspace_root) / "tenants" / tenant_id / "journal"

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = WorkspaceChangeLedger(str(self.workspace_root), tenant_id=tenant_id)

    def _get_journal_file(self, tx_id: str) -> Path:
        safe_tx = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in tx_id)
        return self.storage_dir / f"tx_{safe_tx}.json"

    def begin_transaction(self, tx_id: str, task_id: str, operations: List[ChangeRecord]) -> TransactionJournalEntry:
        """Initialize an atomic transaction in PLANNED state."""
        entry = TransactionJournalEntry(
            tx_id=tx_id,
            task_id=task_id,
            operations=operations,
            state=JournalState.PLANNED,
            start_time=time.time(),
        )
        self._save_entry(entry)
        return entry

    def update_transaction_state(self, tx_id: str, state: JournalState, error: Optional[str] = None) -> Optional[TransactionJournalEntry]:
        """Update lifecycle state of an active transaction."""
        entry = self.load_transaction(tx_id)
        if not entry:
            return None

        entry.state = state
        if error:
            entry.rollback_error = error
        if state in (JournalState.VERIFIED, JournalState.ROLLED_BACK, JournalState.FAILED):
            entry.finish_time = time.time()

        self._save_entry(entry)
        return entry

    def load_transaction(self, tx_id: str) -> Optional[TransactionJournalEntry]:
        """Load journal entry from disk."""
        j_file = self._get_journal_file(tx_id)
        if not j_file.exists():
            return None
        try:
            data = json.loads(j_file.read_text(encoding="utf-8"))
            return TransactionJournalEntry.from_dict(data)
        except Exception as e:
            log.error(f"Failed to load journal entry {tx_id}: {e}")
            return None

    def list_pending_transactions(self) -> List[TransactionJournalEntry]:
        """List any transactions interrupted or incomplete (crash recovery)."""
        pending = []
        for p in self.storage_dir.glob("tx_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                entry = TransactionJournalEntry.from_dict(data)
                if entry.state in (JournalState.IN_PROGRESS, JournalState.ROLLBACK_PENDING):
                    pending.append(entry)
            except Exception:
                continue
        return pending

    def rollback_transaction(self, tx_id: str) -> Tuple[bool, List[str], List[str]]:
        """
        Safely roll back operations in a transaction.
        CRITICAL RULE: Never roll back files subsequently modified by the user!
        Returns (success, rolled_back_files, skipped_user_files).
        """
        entry = self.load_transaction(tx_id)
        if not entry:
            return False, [], [f"Transaction {tx_id} not found."]

        self.update_transaction_state(tx_id, JournalState.ROLLBACK_PENDING)

        rolled_back: List[str] = []
        skipped_user_files: List[str] = []

        # Revert operations in reverse order
        for op in reversed(entry.operations):
            target_path = self.workspace_root / op.file_path
            safe, reason = self.ledger.is_safe_for_agent_rollback(op.task_id, op.file_path)

            if not safe:
                skipped_user_files.append(f"{op.file_path}: {reason}")
                continue

            try:
                if op.operation_type == WorkspaceOperationType.CREATE:
                    # Created by agent -> remove if it still exists and matches
                    if target_path.exists():
                        target_path.unlink()
                        rolled_back.append(op.file_path)

                elif op.operation_type == WorkspaceOperationType.DELETE:
                    # Deleted by agent -> restore original content if backup exists
                    backup_path = self.storage_dir / f"backup_{op.operation_id}"
                    if backup_path.exists():
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_path, target_path)
                        rolled_back.append(op.file_path)

                elif op.operation_type == WorkspaceOperationType.MODIFY:
                    # Modified by agent -> restore backup if present
                    backup_path = self.storage_dir / f"backup_{op.operation_id}"
                    if backup_path.exists():
                        shutil.copy2(backup_path, target_path)
                        rolled_back.append(op.file_path)

                elif op.operation_type in (WorkspaceOperationType.RENAME, WorkspaceOperationType.MOVE):
                    # Renamed/moved -> move back
                    if op.destination_path:
                        dest = self.workspace_root / op.destination_path
                        if dest.exists() and not target_path.exists():
                            shutil.move(str(dest), str(target_path))
                            rolled_back.append(f"{op.destination_path} -> {op.file_path}")

            except Exception as e:
                skipped_user_files.append(f"Failed reverting {op.file_path}: {e}")

        all_clean = len(skipped_user_files) == 0
        final_state = JournalState.ROLLED_BACK if all_clean else JournalState.FAILED
        self.update_transaction_state(tx_id, final_state)
        return all_clean, rolled_back, skipped_user_files

    def _save_entry(self, entry: TransactionJournalEntry) -> None:
        j_file = self._get_journal_file(entry.tx_id)
        tmp = j_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(entry.to_dict(), indent=2), encoding="utf-8")
            os.replace(tmp, j_file)
        except Exception as e:
            log.error(f"Failed to persist journal entry {entry.tx_id}: {e}")
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


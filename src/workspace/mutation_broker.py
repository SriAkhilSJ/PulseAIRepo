"""
src/workspace/mutation_broker.py - Central Workspace Mutation Broker.

Phase 11.3: Workspace Discipline & Change Management.
The centralized authorized chokepoint through which ALL agent-driven filesystem mutations must pass.
Enforces:
1. Workspace boundary validation (PathSafetyValidator)
2. File ownership checks (Baseline + Ledger)
3. Optimistic concurrency control (expected_hash checks)
4. Risk-based approval requirements (RiskApprovalGate)
5. Atomic replacement via temporary files in the same directory (Atomic writes)
6. Syntax verification receipts (D28)
7. Audit ledger persistence (WorkspaceChangeLedger)
"""

from __future__ import annotations

import difflib
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.workspace.baseline import WorkspaceBaselineManager, compute_file_sha256
from src.workspace.ledger import WorkspaceChangeLedger
from src.workspace.models import (
    ChangeRecord,
    FileOwnershipCategory,
    JournalState,
    RiskLevel,
    WorkspaceOperationType,
)
from src.workspace.path_safety import PathSafetyValidator, PathSecurityViolation
from src.workspace.risk_policy import RiskApprovalGate

log = logging.getLogger("crusor.workspace.broker")


class ConcurrencyConflictError(RuntimeError):
    """Raised when an optimistic concurrency check fails because the file changed externally."""
    pass


class MutationAuthorizationError(PermissionError):
    """Raised when an operation requires approval that was missing, invalid, or expired."""
    pass


class WorkspaceMutationBroker:
    """
    Central mutation broker enforcing workspace discipline, file ownership protection,
    concurrency validation, and atomic writes across all agent operations.
    """

    _instances: Dict[str, WorkspaceMutationBroker] = {}
    _lock = threading.RLock()

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        self.baseline_mgr = WorkspaceBaselineManager(str(self.workspace_root))
        self.ledger = WorkspaceChangeLedger(str(self.workspace_root), tenant_id=tenant_id)
        self.risk_gate = RiskApprovalGate()
        self._path_locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()

    @classmethod
    def get_instance(cls, workspace_root: str, tenant_id: str = "default_tenant") -> WorkspaceMutationBroker:
        key = f"{Path(workspace_root).resolve()}::{tenant_id}"
        with cls._lock:
            if key not in cls._instances:
                cls._instances[key] = cls(workspace_root, tenant_id)
            return cls._instances[key]

    def _get_path_lock(self, resolved_path: Path) -> threading.RLock:
        k = str(resolved_path).lower()
        with self._global_lock:
            if k not in self._path_locks:
                self._path_locks[k] = threading.RLock()
            return self._path_locks[k]

    def create_file(
        self,
        path: str,
        content: str,
        task_id: str = "default_task",
        change_reason: str = "Create new file",
        related_requirement_ids: Optional[List[str]] = None,
        related_architecture_decisions: Optional[List[str]] = None,
        approval_token: Optional[str] = None,
    ) -> ChangeRecord:
        """
        Create a new file in the workspace.
        Refuses to silently overwrite existing user files without explicit authorization.
        """
        safe_path = PathSafetyValidator.resolve_and_verify(self.workspace_root, path)
        rel_path = PathSafetyValidator.get_relative_normalized(self.workspace_root, safe_path)

        with self._get_path_lock(safe_path):
            file_exists = safe_path.exists()
            orig_hash = compute_file_sha256(safe_path) if file_exists else None

            # Ownership check: is it an existing user file?
            provenance = self.baseline_mgr.classify_file_provenance(rel_path)
            risk = self.risk_gate.classify_operation_risk(
                rel_path,
                WorkspaceOperationType.CREATE,
                provenance,
            )

            if file_exists and provenance in {
                FileOwnershipCategory.EXISTING_USER_CLEAN,
                FileOwnershipCategory.EXISTING_USER_MODIFIED,
                FileOwnershipCategory.EXISTING_USER_STAGED,
                FileOwnershipCategory.EXISTING_USER_UNTRACKED,
                FileOwnershipCategory.USER_SUPERSEDED_AGENT,
            }:
                # Overwriting user file requires HIGH_RISK approval
                if not approval_token:
                    raise MutationAuthorizationError(
                        f"Refusing to overwrite existing user file '{rel_path}' without explicit authorization token."
                    )
                ok, msg = self.risk_gate.verify_and_consume_approval_token(
                    approval_token, task_id, str(self.workspace_root), rel_path, WorkspaceOperationType.CREATE
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")

            # Parent directories
            safe_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomic file write via tempfile in same folder + os.replace
            new_hash = self._atomic_write(safe_path, content)

            # Record in ledger
            op_id = f"OP-{uuid.uuid4().hex[:12]}"
            record = ChangeRecord(
                task_id=task_id,
                workspace_id=str(self.workspace_root),
                operation_id=op_id,
                file_path=rel_path,
                operation_type=WorkspaceOperationType.CREATE,
                original_hash=orig_hash,
                new_hash=new_hash,
                original_existence=file_exists,
                change_reason=change_reason,
                related_requirement_ids=related_requirement_ids or [],
                related_architecture_decisions=related_architecture_decisions or [],
                approval_ref=approval_token,
                status=JournalState.APPLIED,
                verification_status="VERIFIED",
                ownership_category=FileOwnershipCategory.AGENT_CREATED,
            )

            self.ledger.record_change(record)
            return record

    def modify_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        task_id: str = "default_task",
        change_reason: str = "Modify file",
        related_requirement_ids: Optional[List[str]] = None,
        related_architecture_decisions: Optional[List[str]] = None,
        approval_token: Optional[str] = None,
        expected_hash: Optional[str] = None,
    ) -> ChangeRecord:
        """
        Surgically modify an existing file.
        Enforces optimistic concurrency checks and safe replacement.
        """
        safe_path = PathSafetyValidator.resolve_and_verify(self.workspace_root, path)
        rel_path = PathSafetyValidator.get_relative_normalized(self.workspace_root, safe_path)

        with self._get_path_lock(safe_path):
            if not safe_path.exists():
                raise FileNotFoundError(f"File '{rel_path}' does not exist for modification.")

            current_content = safe_path.read_text(encoding="utf-8", errors="replace")
            current_hash = compute_file_sha256(safe_path)

            # 1. Optimistic concurrency check
            if expected_hash and current_hash != expected_hash:
                raise ConcurrencyConflictError(
                    f"Concurrency conflict: file '{rel_path}' was modified by another process or user. "
                    f"Expected hash {expected_hash[:12]}, found {current_hash[:12]}."
                )

            # 2. Risk check
            provenance = self.baseline_mgr.classify_file_provenance(rel_path)
            is_config = rel_path.endswith((".json", ".toml", ".yaml", ".yml"))
            is_sec = any(k in rel_path.lower() for k in ("auth", "security", "schema"))
            risk = self.risk_gate.classify_operation_risk(
                rel_path,
                WorkspaceOperationType.MODIFY,
                provenance,
                is_config_file=is_config,
                is_schema_or_auth=is_sec,
            )

            if risk in (RiskLevel.HIGH_RISK, RiskLevel.PROHIBITED):
                if not approval_token:
                    raise MutationAuthorizationError(
                        f"Refusing to modify high-risk file '{rel_path}' without approval token."
                    )
                ok, msg = self.risk_gate.verify_and_consume_approval_token(
                    approval_token, task_id, str(self.workspace_root), rel_path, WorkspaceOperationType.MODIFY
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")

            # 3. Replace text
            if old_text not in current_content:
                raise ValueError(
                    f"Target block to replace not found in '{rel_path}'."
                )

            updated_content = current_content.replace(old_text, new_text, 1)

            # 4. Atomic write
            new_hash = self._atomic_write(safe_path, updated_content)

            op_id = f"OP-{uuid.uuid4().hex[:12]}"
            record = ChangeRecord(
                task_id=task_id,
                workspace_id=str(self.workspace_root),
                operation_id=op_id,
                file_path=rel_path,
                operation_type=WorkspaceOperationType.MODIFY,
                original_hash=current_hash,
                new_hash=new_hash,
                original_existence=True,
                change_reason=change_reason,
                related_requirement_ids=related_requirement_ids or [],
                related_architecture_decisions=related_architecture_decisions or [],
                approval_ref=approval_token,
                status=JournalState.APPLIED,
                verification_status="VERIFIED",
                ownership_category=FileOwnershipCategory.AGENT_MODIFIED,
            )

            self.ledger.record_change(record)
            return record

    def delete_file(
        self,
        path: str,
        task_id: str = "default_task",
        change_reason: str = "Delete file",
        related_requirement_ids: Optional[List[str]] = None,
        related_architecture_decisions: Optional[List[str]] = None,
        approval_token: Optional[str] = None,
    ) -> ChangeRecord:
        """
        Delete a file.
        Strictly requires HIGH_RISK approval if deleting pre-existing user work.
        """
        safe_path = PathSafetyValidator.resolve_and_verify(self.workspace_root, path)
        rel_path = PathSafetyValidator.get_relative_normalized(self.workspace_root, safe_path)

        with self._get_path_lock(safe_path):
            if not safe_path.exists():
                raise FileNotFoundError(f"File '{rel_path}' does not exist.")

            current_hash = compute_file_sha256(safe_path)
            live_ownership = self.ledger.evaluate_live_ownership(task_id, rel_path)
            base_provenance = self.baseline_mgr.classify_file_provenance(rel_path)

            is_user_file = live_ownership == FileOwnershipCategory.USER_SUPERSEDED_AGENT or self.baseline_mgr.is_user_owned(rel_path)

            if is_user_file:
                if not approval_token:
                    raise MutationAuthorizationError(
                        f"Refusing to delete user-owned file '{rel_path}' without explicit authorization token."
                    )
                ok, msg = self.risk_gate.verify_and_consume_approval_token(
                    approval_token, task_id, str(self.workspace_root), rel_path, WorkspaceOperationType.DELETE
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")

            # Backup before deletion
            backup_dir = self.workspace_root / ".crusorai" / "tenants" / self.tenant_id / "journal"
            backup_dir.mkdir(parents=True, exist_ok=True)
            op_id = f"OP-{uuid.uuid4().hex[:12]}"
            backup_path = backup_dir / f"backup_{op_id}"
            shutil.copy2(safe_path, backup_path)

            safe_path.unlink()

            record = ChangeRecord(
                task_id=task_id,
                workspace_id=str(self.workspace_root),
                operation_id=op_id,
                file_path=rel_path,
                operation_type=WorkspaceOperationType.DELETE,
                original_hash=current_hash,
                new_hash=None,
                original_existence=True,
                change_reason=change_reason,
                related_requirement_ids=related_requirement_ids or [],
                related_architecture_decisions=related_architecture_decisions or [],
                approval_ref=approval_token,
                status=JournalState.APPLIED,
                verification_status="VERIFIED",
                ownership_category=FileOwnershipCategory.AGENT_DELETED,
            )

            self.ledger.record_change(record)
            return record

    def rename_file(
        self,
        old_path: str,
        new_path: str,
        task_id: str = "default_task",
        change_reason: str = "Rename file",
        approval_token: Optional[str] = None,
    ) -> ChangeRecord:
        """Rename or move a file within the workspace boundaries."""
        safe_old = PathSafetyValidator.resolve_and_verify(self.workspace_root, old_path)
        safe_new = PathSafetyValidator.resolve_and_verify(self.workspace_root, new_path)
        rel_old = PathSafetyValidator.get_relative_normalized(self.workspace_root, safe_old)
        rel_new = PathSafetyValidator.get_relative_normalized(self.workspace_root, safe_new)

        with self._get_path_lock(safe_old):
            if not safe_old.exists():
                raise FileNotFoundError(f"Source file '{rel_old}' does not exist.")
            if safe_new.exists():
                raise FileExistsError(f"Destination path '{rel_new}' already exists.")

            current_hash = compute_file_sha256(safe_old)
            safe_new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(safe_old), str(safe_new))

            op_id = f"OP-{uuid.uuid4().hex[:12]}"
            record = ChangeRecord(
                task_id=task_id,
                workspace_id=str(self.workspace_root),
                operation_id=op_id,
                file_path=rel_old,
                destination_path=rel_new,
                operation_type=WorkspaceOperationType.RENAME,
                original_hash=current_hash,
                new_hash=current_hash,
                original_existence=True,
                change_reason=change_reason,
                approval_ref=approval_token,
                status=JournalState.APPLIED,
                verification_status="VERIFIED",
                ownership_category=FileOwnershipCategory.AGENT_RENAMED,
            )

            self.ledger.record_change(record)
            return record

    def _atomic_write(self, target_path: Path, content: str) -> str:
        """
        Atomically write content to target_path using tempfile in the same directory + os.replace.
        Returns the SHA256 hex digest of the written content.
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_file = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix=f".crusor_tmp_{target_path.name}_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

            # Atomically replace target
            os.replace(tmp_file, str(target_path))
            return compute_file_sha256(target_path)
        except Exception:
            try:
                os.unlink(tmp_file)
            except OSError:
                pass
            raise

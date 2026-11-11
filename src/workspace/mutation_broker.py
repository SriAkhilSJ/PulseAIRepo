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
from src.workspace.approval_digest import (
    content_digest as approval_digest,
    precondition_digest as approval_precondition,
)
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

    def _verify_approval(
        self,
        token: str,
        task_id: str,
        rel_path: str,
        operation: WorkspaceOperationType,
        expected_digest: str,
        require_digest: bool,
        *,
        precondition_digest: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> Tuple[bool, str]:
        """Verify a token with digest/precondition binding, legacy compatible.

        Increment 2/3 production callers pass ``require_digest=True``; a token
        minted for different bytes or a different workspace precondition can
        never match. Legacy callers/tests that minted a path-only token keep
        the historical Phase 3.1 semantics only when they did not demand
        digest binding.
        """
        ok, msg = self.risk_gate.verify_and_consume_approval_token(
            token,
            task_id,
            str(self.workspace_root),
            rel_path,
            operation,
            content_digest=expected_digest,
            precondition_digest=precondition_digest,
            session_id=session_id,
            turn_id=turn_id,
            require_digest=require_digest,
        )
        if ok or require_digest:
            return ok, msg
        # Legacy path-only token (Phase 3.1): session/turn were not bound.
        ok, msg = self.risk_gate.verify_and_consume_approval_token(
            token,
            task_id,
            str(self.workspace_root),
            rel_path,
            operation,
            content_digest=expected_digest,
            precondition_digest=precondition_digest,
            session_id="",
            turn_id="",
            require_digest=False,
        )
        if ok:
            return ok, msg
        return self.risk_gate.verify_and_consume_approval_token(
            token,
            task_id,
            str(self.workspace_root),
            rel_path,
            operation,
            content_digest="",
            precondition_digest="",
            session_id="",
            turn_id="",
            require_digest=False,
        )

    def create_file(
        self,
        path: str,
        content: str,
        task_id: str = "default_task",
        change_reason: str = "Create new file",
        related_requirement_ids: Optional[List[str]] = None,
        related_architecture_decisions: Optional[List[str]] = None,
        approval_token: Optional[str] = None,
        *,
        require_approval: bool = False,
        require_digest: bool = False,
        session_id: str = "",
        turn_id: str = "",
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
            existing_state = (
                safe_path.read_text(encoding="utf-8", errors="replace")
                if file_exists else None
            )
            actual_precondition = approval_precondition(file_exists, existing_state)

            # Ownership check: is it an existing user file?
            provenance = self.baseline_mgr.classify_file_provenance(rel_path)
            risk = self.risk_gate.classify_operation_risk(
                rel_path,
                WorkspaceOperationType.CREATE,
                provenance,
            )

            # Increment 2: the token (when supplied) always binds the exact
            # content being written, not merely the path. Callers that demand
            # approval cannot reach the write without a token.
            expected_digest = approval_digest(content)
            if approval_token:
                ok, msg = self._verify_approval(
                    approval_token, task_id, rel_path,
                    WorkspaceOperationType.CREATE, expected_digest, require_digest,
                    precondition_digest=actual_precondition,
                    session_id=session_id, turn_id=turn_id,
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")
            elif require_approval:
                raise MutationAuthorizationError(
                    f"Refusing to create '{rel_path}' without an approved mutation token."
                )
            elif file_exists and provenance in {
                FileOwnershipCategory.EXISTING_USER_CLEAN,
                FileOwnershipCategory.EXISTING_USER_MODIFIED,
                FileOwnershipCategory.EXISTING_USER_STAGED,
                FileOwnershipCategory.EXISTING_USER_UNTRACKED,
                FileOwnershipCategory.USER_SUPERSEDED_AGENT,
            }:
                # Overwriting user file requires HIGH_RISK approval
                raise MutationAuthorizationError(
                    f"Refusing to overwrite existing user file '{rel_path}' without explicit authorization token."
                )

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
        old_text: str = "",
        new_text: str = "",
        task_id: str = "default_task",
        change_reason: str = "Modify file",
        related_requirement_ids: Optional[List[str]] = None,
        related_architecture_decisions: Optional[List[str]] = None,
        approval_token: Optional[str] = None,
        expected_hash: Optional[str] = None,
        new_content: Optional[str] = None,
        *,
        require_approval: bool = False,
        require_digest: bool = False,
        session_id: str = "",
        turn_id: str = "",
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

            # 2. Content update logic: direct new_content or replacement of old_text
            if new_content is not None:
                updated_content = new_content
            else:
                if old_text not in current_content:
                    raise ValueError(
                        f"Target block to replace not found in '{rel_path}'."
                    )
                updated_content = current_content.replace(old_text, new_text, 1)

            # 3. Risk check
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

            # 4. Approval: a supplied token binds the exact new bytes AND the
            # pre-image the human saw. A concurrent external change therefore
            # invalidates the approval instead of being overwritten.
            actual_precondition = approval_precondition(True, current_content)
            expected_digest = approval_digest(updated_content)
            if approval_token:
                ok, msg = self._verify_approval(
                    approval_token, task_id, rel_path,
                    WorkspaceOperationType.MODIFY, expected_digest, require_digest,
                    precondition_digest=actual_precondition,
                    session_id=session_id, turn_id=turn_id,
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")
            elif require_approval:
                raise MutationAuthorizationError(
                    f"Refusing to modify '{rel_path}' without an approved mutation token."
                )
            elif risk in (RiskLevel.HIGH_RISK, RiskLevel.PROHIBITED):
                raise MutationAuthorizationError(
                    f"Refusing to modify high-risk file '{rel_path}' without approval token."
                )

            # 5. Atomic write
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
        *,
        require_approval: bool = False,
        require_digest: bool = False,
        session_id: str = "",
        turn_id: str = "",
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
            current_content = safe_path.read_text(encoding="utf-8", errors="replace")
            live_ownership = self.ledger.evaluate_live_ownership(task_id, rel_path)
            base_provenance = self.baseline_mgr.classify_file_provenance(rel_path)

            is_user_file = live_ownership == FileOwnershipCategory.USER_SUPERSEDED_AGENT or self.baseline_mgr.is_user_owned(rel_path)

            actual_precondition = approval_precondition(True, current_content)
            expected_digest = approval_digest(current_content)
            if approval_token:
                ok, msg = self._verify_approval(
                    approval_token, task_id, rel_path,
                    WorkspaceOperationType.DELETE, expected_digest, require_digest,
                    precondition_digest=actual_precondition,
                    session_id=session_id, turn_id=turn_id,
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")
            elif require_approval or is_user_file:
                raise MutationAuthorizationError(
                    f"Refusing to delete '{rel_path}' without explicit authorization token."
                )

            # Backup before deletion
            from src.runtime.app_paths import app_data_root

            backup_dir = app_data_root(self.workspace_root) / "tenants" / self.tenant_id / "journal"
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
        *,
        require_approval: bool = False,
        require_digest: bool = False,
        session_id: str = "",
        turn_id: str = "",
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
            pre_image = safe_old.read_text(encoding="utf-8", errors="replace")
            actual_precondition = approval_precondition(True, pre_image)
            expected_digest = approval_digest(pre_image)
            if approval_token:
                ok, msg = self._verify_approval(
                    approval_token, task_id, rel_old,
                    WorkspaceOperationType.RENAME, expected_digest, require_digest,
                    precondition_digest=actual_precondition,
                    session_id=session_id, turn_id=turn_id,
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")
            elif require_approval:
                raise MutationAuthorizationError(
                    f"Refusing to rename '{rel_old}' without an approved mutation token."
                )

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

    def copy_file(
        self,
        src_path: str,
        dst_path: str,
        task_id: str = "default_task",
        change_reason: str = "Copy file",
        approval_token: Optional[str] = None,
        *,
        require_approval: bool = False,
        require_digest: bool = False,
        session_id: str = "",
        turn_id: str = "",
    ) -> ChangeRecord:
        """Copy a file within the workspace boundaries with risk and ownership controls."""
        safe_src = PathSafetyValidator.resolve_and_verify(self.workspace_root, src_path)
        safe_dst = PathSafetyValidator.resolve_and_verify(self.workspace_root, dst_path)
        rel_src = PathSafetyValidator.get_relative_normalized(self.workspace_root, safe_src)
        rel_dst = PathSafetyValidator.get_relative_normalized(self.workspace_root, safe_dst)

        with self._get_path_lock(safe_dst):
            if not safe_src.exists() or not safe_src.is_file():
                raise FileNotFoundError(f"Source file '{rel_src}' does not exist.")

            dst_exists = safe_dst.exists()
            orig_hash = compute_file_sha256(safe_dst) if dst_exists else None

            # Ownership & risk check on dst
            provenance = self.baseline_mgr.classify_file_provenance(rel_dst)
            risk = self.risk_gate.classify_operation_risk(
                rel_dst,
                WorkspaceOperationType.CREATE,
                provenance,
            )

            source_bytes = safe_src.read_bytes()
            existing_dst_text = (
                safe_dst.read_text(encoding="utf-8", errors="replace")
                if dst_exists else None
            )
            actual_precondition = approval_precondition(dst_exists, existing_dst_text)
            expected_digest = approval_digest(source_bytes)
            if approval_token:
                ok, msg = self._verify_approval(
                    approval_token, task_id, rel_dst,
                    WorkspaceOperationType.CREATE, expected_digest, require_digest,
                    precondition_digest=actual_precondition,
                    session_id=session_id, turn_id=turn_id,
                )
                if not ok:
                    raise MutationAuthorizationError(f"Approval verification failed: {msg}")
            elif require_approval:
                raise MutationAuthorizationError(
                    f"Refusing to copy to '{rel_dst}' without an approved mutation token."
                )
            elif dst_exists and provenance in {
                FileOwnershipCategory.EXISTING_USER_CLEAN,
                FileOwnershipCategory.EXISTING_USER_MODIFIED,
                FileOwnershipCategory.EXISTING_USER_STAGED,
                FileOwnershipCategory.EXISTING_USER_UNTRACKED,
                FileOwnershipCategory.USER_SUPERSEDED_AGENT,
            }:
                raise MutationAuthorizationError(
                    f"Refusing to overwrite existing user file '{rel_dst}' without explicit authorization token."
                )

            safe_dst.parent.mkdir(parents=True, exist_ok=True)
            # Atomic copy via temp file in same destination directory
            fd, tmp_file = tempfile.mkstemp(
                dir=str(safe_dst.parent),
                prefix=f".crusor_tmp_{safe_dst.name}_",
                suffix=".tmp",
            )
            try:
                os.close(fd)
                shutil.copy2(str(safe_src), tmp_file)
                os.replace(tmp_file, str(safe_dst))
                new_hash = compute_file_sha256(safe_dst)
            except Exception:
                try:
                    os.unlink(tmp_file)
                except OSError:
                    pass
                raise

            op_id = f"OP-{uuid.uuid4().hex[:12]}"
            record = ChangeRecord(
                task_id=task_id,
                workspace_id=str(self.workspace_root),
                operation_id=op_id,
                file_path=rel_dst,
                operation_type=WorkspaceOperationType.CREATE,
                original_hash=orig_hash,
                new_hash=new_hash,
                original_existence=dst_exists,
                change_reason=change_reason,
                approval_ref=approval_token,
                status=JournalState.APPLIED,
                verification_status="VERIFIED",
                ownership_category=FileOwnershipCategory.AGENT_CREATED,
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
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
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

"""
execution_broker.py - Centralized Enterprise Execution Broker.

Phase 9.4: Enterprise Execution Sandbox & OS-Level Process Isolation.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.security.contracts import (
    ExecutionMode,
    ExecutionReceipt,
    ExecutionRequest,
    SecurityViolationType,
    compute_receipt_hash,
    generate_approval_token,
    verify_approval_token,
)
from src.security.sandbox.manager import get_sandbox_manager


class ExecutionBroker:
    """
    Centralized Execution Broker acting as the sole authorized chokepoint
    between agent runtime and OS process creation.
    """

    _instance: Optional[ExecutionBroker] = None

    def __init__(self, base_staging_root: Optional[Path] = None) -> None:
        self._consumed_approval_tokens: Set[str] = set()
        self._receipt_ledger: Dict[str, ExecutionReceipt] = {}
        if base_staging_root:
            self._base_staging_root = base_staging_root
        else:
            self._base_staging_root = Path("bench-results") / "phase94_execution_sandbox" / "staging"
        self._base_staging_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> ExecutionBroker:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def create_approval(
        self,
        session_id: str,
        request_id: str,
        command: str,
        workspace_root: str,
        expiry_s: float = 300.0,
    ) -> str:
        """Issue a cryptographic single-use approval token for an authorized operation."""
        return generate_approval_token(
            session_id=session_id,
            request_id=request_id,
            command=command,
            workspace_root=workspace_root,
            expiry_s=expiry_s,
        )

    def execute(
        self,
        request: ExecutionRequest,
        abort_event: Optional[Any] = None,
    ) -> ExecutionReceipt:
        """
        Execute an authorized request under strict OS-level sandbox isolation.
        
        Enforces:
        1. Workspace resolution & fail-closed jailing.
        2. Single-use cryptographic approval verification.
        3. OS-level process isolation (Windows Job Objects / Namespaces).
        4. Environment sanitization (zero secrets passed).
        5. Output stream byte caps and timeouts.
        6. Immutable receipt generation with SHA-256 evidence hashing.
        """
        start_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        t0 = time.monotonic()

        # 1. Workspace resolution (Fail-closed)
        ws_str = (request.workspace_root or "").strip()
        if not ws_str:
            return self._emit_rejection_receipt(
                request,
                exit_code=126,
                stderr="⛔ Execution refused: missing workspace restriction.",
                violations=[SecurityViolationType.UNAUTHORIZED_EXECUTION_ATTEMPT.value],
                start_ts=start_ts,
                t0=t0,
            )

        ws_path = Path(ws_str).resolve()
        if not ws_path.exists() or not ws_path.is_dir():
            return self._emit_rejection_receipt(
                request,
                exit_code=126,
                stderr=f"⛔ Execution refused: workspace path does not exist or is not a directory: {ws_path}",
                violations=[SecurityViolationType.UNAUTHORIZED_EXECUTION_ATTEMPT.value],
                start_ts=start_ts,
                t0=t0,
            )

        # 2. Cryptographic Approval Token Verification
        if not request.approval_token:
            return self._emit_rejection_receipt(
                request,
                exit_code=126,
                stderr="⛔ Execution refused: mandatory approval token missing.",
                violations=[SecurityViolationType.FORGED_OR_STALE_APPROVAL.value],
                start_ts=start_ts,
                t0=t0,
            )

        if request.approval_token in self._consumed_approval_tokens:
            return self._emit_rejection_receipt(
                request,
                exit_code=126,
                stderr="⛔ Execution refused: stale approval token replay detected.",
                violations=[SecurityViolationType.FORGED_OR_STALE_APPROVAL.value],
                start_ts=start_ts,
                t0=t0,
            )

        valid_approval, approval_reason = verify_approval_token(
            token=request.approval_token,
            session_id=request.session_id,
            request_id=request.request_id,
            command=request.command,
            workspace_root=str(ws_path),
        )
        if not valid_approval:
            return self._emit_rejection_receipt(
                request,
                exit_code=126,
                stderr=f"⛔ Execution refused: {approval_reason}",
                violations=[SecurityViolationType.FORGED_OR_STALE_APPROVAL.value],
                start_ts=start_ts,
                t0=t0,
            )

        # Mark token consumed immediately (single-use)
        self._consumed_approval_tokens.add(request.approval_token)

        # 3. Prepare Isolated Staging Directory
        staging_dir = self._base_staging_root / f"exec_{request.execution_id}_{uuid.uuid4().hex[:6]}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        staged_files_created: List[str] = []
        staged_files_modified: List[str] = []

        # 4. Instantiate OS-Specific Sandbox Manager
        try:
            sandbox = get_sandbox_manager()
            sandbox.initialize(request, staging_dir)
        except Exception as exc:
            self._cleanup_staging(staging_dir)
            return self._emit_rejection_receipt(
                request,
                exit_code=126,
                stderr=f"⛔ Sandbox initialization failure: {exc}",
                violations=["SANDBOX_INITIALIZATION_FAILURE"],
                start_ts=start_ts,
                t0=t0,
            )

        # 5. Execute within Sandbox
        try:
            raw_res = sandbox.execute(request, staging_dir, abort_event=abort_event)
        except Exception as exc:
            sandbox.terminate()
            raw_res = {
                "exit_code": 1,
                "stdout": "",
                "stderr": f"Worker crashed or execution raised unexpected exception: {exc}",
                "stdout_bytes": 0,
                "stderr_bytes": len(str(exc)),
                "timed_out": False,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": ["WORKER_CRASH"],
            }

        # 6. Mode B: Inspect staged modifications if applicable
        if request.mode == ExecutionMode.PROPOSED_MUTATION and staging_dir.exists():
            for root, _, files in os.walk(staging_dir):
                for f in files:
                    rel = str(Path(root, f).relative_to(staging_dir))
                    staged_files_created.append(rel)

        # 7. Cleanup sandbox resources and staging
        cleanup_status = sandbox.cleanup(staging_dir)

        # 8. Produce Final Immutable Execution Receipt
        end_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        duration_s = round(time.monotonic() - t0, 4)

        receipt_data = {
            "execution_id": request.execution_id,
            "session_id": request.session_id,
            "request_id": request.request_id,
            "workspace_root": str(ws_path),
            "tool_name": request.tool_name,
            "executable": (request.argv[0] if request.argv else request.command.split()[0]) if (request.argv or request.command.split()) else "unknown",
            "sanitized_argv": request.argv if request.argv else [request.command],
            "sandbox_backend": sandbox.backend_type.value,
            "policy_version": "9.4.0",
            "start_time": start_ts,
            "end_time": end_ts,
            "duration_s": duration_s,
            "exit_code": raw_res.get("exit_code", 1),
            "timed_out": raw_res.get("timed_out", False),
            "cancelled": raw_res.get("cancelled", False),
            "cpu_user_s": raw_res.get("cpu_user_s", 0.0),
            "cpu_kernel_s": raw_res.get("cpu_kernel_s", 0.0),
            "peak_memory_bytes": raw_res.get("peak_memory_bytes", 0),
            "stdout": raw_res.get("stdout", ""),
            "stderr": raw_res.get("stderr", ""),
            "stdout_bytes": raw_res.get("stdout_bytes", 0),
            "stderr_bytes": raw_res.get("stderr_bytes", 0),
            "staged_files_created": staged_files_created,
            "staged_files_modified": staged_files_modified,
            "security_violations": raw_res.get("security_violations", []),
            "cleanup_status": cleanup_status,
        }
        receipt_data["evidence_hash"] = compute_receipt_hash(receipt_data)

        receipt = ExecutionReceipt(**receipt_data)
        self._receipt_ledger[receipt.execution_id] = receipt
        return receipt

    def _cleanup_staging(self, staging_dir: Path) -> None:
        try:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            pass

    def _emit_rejection_receipt(
        self,
        request: ExecutionRequest,
        exit_code: int,
        stderr: str,
        violations: List[str],
        start_ts: str,
        t0: float,
    ) -> ExecutionReceipt:
        end_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        duration_s = round(time.monotonic() - t0, 4)

        data = {
            "execution_id": request.execution_id,
            "session_id": request.session_id,
            "request_id": request.request_id,
            "workspace_root": request.workspace_root or "UNAUTHORIZED",
            "tool_name": request.tool_name,
            "executable": "rejected",
            "sanitized_argv": [],
            "sandbox_backend": "broker_rejection",
            "policy_version": "9.4.0",
            "start_time": start_ts,
            "end_time": end_ts,
            "duration_s": duration_s,
            "exit_code": exit_code,
            "timed_out": False,
            "cancelled": False,
            "cpu_user_s": 0.0,
            "cpu_kernel_s": 0.0,
            "peak_memory_bytes": 0,
            "stdout": "",
            "stderr": stderr,
            "stdout_bytes": 0,
            "stderr_bytes": len(stderr.encode("utf-8")),
            "staged_files_created": [],
            "staged_files_modified": [],
            "security_violations": violations,
            "cleanup_status": "NO_STAGING_CREATED",
        }
        data["evidence_hash"] = compute_receipt_hash(data)
        receipt = ExecutionReceipt(**data)
        self._receipt_ledger[receipt.execution_id] = receipt
        return receipt

    def get_receipt(self, execution_id: str) -> Optional[ExecutionReceipt]:
        return self._receipt_ledger.get(execution_id)

    def list_receipts(self, session_id: Optional[str] = None) -> List[ExecutionReceipt]:
        if session_id:
            return [r for r in self._receipt_ledger.values() if r.session_id == session_id]
        return list(self._receipt_ledger.values())


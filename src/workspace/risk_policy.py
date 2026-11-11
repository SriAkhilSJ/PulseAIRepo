"""
src/workspace/risk_policy.py - Risk-Based Approval Policy & Cryptographic Tokens.

Phase 11.3: Workspace Discipline & Change Management.
Implements deterministic risk evaluation and single-use, time-limited approval tokens.
Integrates with Phase 9.5 Tool Authorization and Phase 10.0 RBAC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.workspace.models import (
    FileOwnershipCategory,
    RiskLevel,
    WorkspaceOperationType,
)

log = logging.getLogger("crusor.workspace.risk_policy")

_SECRET_SALT = os.environ.get("CRUSOR_WORKSPACE_APPROVAL_KEY", "crusor-workspace-discipline-salt-2026")

# Protected upstream files that strictly trigger HIGH_RISK or PROHIBITED
PROTECTED_UPSTREAM_PATHS = frozenset({
    "build/buildfile.ts",
    "build/next/index.ts",
    "product.json",
    "src/vs/workbench/workbench.common.main.ts",
    "src/vs/workbench/workbench.desktop.main.ts",
    "desktop/selective_manifest.json",
})

# Patterns for sensitive credentials or security boundaries
SENSITIVE_PATTERNS = [
    r"\.env",
    r"\.git-credentials",
    r"\.ssh",
    r"id_rsa",
    r"id_ed25519",
    r".*\.pem$",
    r".*\.key$",
    r"credentials\.json",
    r"secrets\.json",
]


class RiskApprovalGate:
    """
    Evaluates operation risk and issues/verifies single-use cryptographic approval tokens.
    """

    def __init__(self) -> None:
        self._consumed_tokens: Set[str] = set()

    def classify_operation_risk(
        self,
        rel_path: str,
        op_type: WorkspaceOperationType,
        ownership: FileOwnershipCategory,
        is_config_file: bool = False,
        is_schema_or_auth: bool = False,
    ) -> RiskLevel:
        """
        Classifies risk tier for an intended operation based on file path, ownership, and context.
        """
        norm_path = rel_path.replace("\\", "/").lower()

        # 1. Prohibited operations
        # Modifying secret or credential files directly
        if any(re.search(pat, norm_path) for pat in SENSITIVE_PATTERNS):
            return RiskLevel.PROHIBITED

        # 2. Protected Upstream Invariant 7 files
        if norm_path in {p.lower() for p in PROTECTED_UPSTREAM_PATHS} or "desktop/selective_manifest.json" in norm_path:
            return RiskLevel.HIGH_RISK

        # 3. Operations on pre-existing user files
        if ownership in {
            FileOwnershipCategory.EXISTING_USER_CLEAN,
            FileOwnershipCategory.EXISTING_USER_MODIFIED,
            FileOwnershipCategory.EXISTING_USER_STAGED,
            FileOwnershipCategory.EXISTING_USER_UNTRACKED,
            FileOwnershipCategory.USER_SUPERSEDED_AGENT,
        }:
            if op_type in (WorkspaceOperationType.DELETE, WorkspaceOperationType.DIRECTORY_REMOVE):
                # Deleting user work is HIGH_RISK
                return RiskLevel.HIGH_RISK
            if op_type == WorkspaceOperationType.CREATE:
                # Overwriting an existing user file with CREATE is HIGH_RISK
                return RiskLevel.HIGH_RISK
            if is_config_file or is_schema_or_auth:
                return RiskLevel.MEDIUM_RISK
            # Surgical modification of existing file within task scope
            return RiskLevel.LOW_RISK

        # 4. Operations on agent-owned files
        if op_type in (WorkspaceOperationType.CREATE, WorkspaceOperationType.MODIFY, WorkspaceOperationType.RENAME, WorkspaceOperationType.MOVE):
            if is_config_file or is_schema_or_auth:
                return RiskLevel.MEDIUM_RISK
            return RiskLevel.LOW_RISK

        if op_type == WorkspaceOperationType.DELETE:
            # Deleting agent's own file during cleanup is LOW_RISK
            return RiskLevel.LOW_RISK

        return RiskLevel.LOW_RISK

    def generate_approval_token(
        self,
        task_id: str,
        workspace_root: str,
        file_path: str,
        operation_type: WorkspaceOperationType,
        expiry_seconds: float = 300.0,
        *,
        content_digest: str = "",
        precondition_digest: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> str:
        """Issue a cryptographic single-use approval token bound to exact parameters.

        ``content_digest`` binds the authorization to the exact proposed bytes
        (Increment 2). ``precondition_digest`` binds the workspace state the
        human saw (Increment 3): a file changed between approval and mutation
        invalidates the token. An empty digest is the legacy/path-only scope
        and is rejected by callers that require digest binding.
        """
        exp = int(time.time() + expiry_seconds)
        payload = (
            f"{task_id}:{workspace_root}:{file_path.replace(os.sep, '/')}:"
            f"{operation_type.value}:{content_digest}:{precondition_digest}:"
            f"{session_id}:{turn_id}:{exp}"
        )
        sig = hmac.new(_SECRET_SALT.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"APPV-{sig[:24]}-{exp}"
        return token

    def verify_and_consume_approval_token(
        self,
        token: str,
        task_id: str,
        workspace_root: str,
        file_path: str,
        operation_type: WorkspaceOperationType,
        *,
        content_digest: str = "",
        precondition_digest: str = "",
        session_id: str = "",
        turn_id: str = "",
        require_digest: bool = False,
    ) -> Tuple[bool, str]:
        """
        Verify that token is cryptographically valid, not expired, matches parameters,
        and has not been previously consumed.

        When ``require_digest`` is true the token must carry a non-empty
        content digest and it must equal ``content_digest`` (the digest the
        broker computed from the bytes it is about to apply).
        """
        if not token or not token.startswith("APPV-"):
            return False, "Invalid or missing approval token format."

        if token in self._consumed_tokens:
            return False, "Approval token has already been consumed (replay prevented)."

        try:
            parts = token.split("-")
            if len(parts) != 3:
                return False, "Malformed approval token structure."
            exp = int(parts[2])
            if time.time() > exp:
                return False, f"Approval token expired at {exp} (current time {time.time()})."

            # Check signature by reconstructing HMAC over expected payload.
            payload = (
                f"{task_id}:{workspace_root}:{file_path.replace(os.sep, '/')}:"
                f"{operation_type.value}:{content_digest}:{precondition_digest}:"
                f"{session_id}:{turn_id}:{exp}"
            )
            expected_sig = hmac.new(_SECRET_SALT.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(parts[1], expected_sig[:24]):
                if require_digest:
                    return False, (
                        "Approval token signature mismatch: the token is not "
                        "bound to the exact proposed content/diff digest and "
                        "workspace precondition."
                    )
                return False, "Approval token cryptographic signature mismatch or bound to different target."

            # Legacy path-only token: accepted only where the caller has not
            # demanded digest binding (Increment 2/3 production paths do).
            if require_digest and not content_digest:
                return False, "Approval token is missing the required content/diff digest binding."

            # Mark as consumed immediately
            self._consumed_tokens.add(token)
            return True, "Approval token successfully verified and consumed."

        except Exception as e:
            return False, f"Approval token validation failed: {e}"

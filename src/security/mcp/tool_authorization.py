"""
tool_authorization.py - Centralized MCP Tool Classification, Policy Enforcement & Approval Binding.

Phase 9.5: MCP Ecosystem & Browser Agent Security.
Enforces a 5-tier risk taxonomy (Levels 0 through 4) and cryptographically bounds
user/policy approvals to the exact tool name, server identity, and canonical arguments.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class ToolRiskLevel(int, enum.Enum):
    LEVEL_0_READ_ONLY_INFORMATIONAL = 0  # Docs, schema, status
    LEVEL_1_WORKSPACE_READ = 1           # Reading workspace source, git status, search
    LEVEL_2_REVERSIBLE_MODIFICATION = 2  # Creating/editing files in workspace
    LEVEL_3_EXECUTION_AND_SIDE_EFFECTS = 3 # Shell command, network mutation, outbound messaging
    LEVEL_4_HIGHLY_SENSITIVE_DESTRUCTIVE = 4 # Deletion, security changes, credential access


# Known mutating or dangerous tool prefixes/keywords
DESTRUCTIVE_KEYWORDS = frozenset({
    "delete", "remove", "drop", "destroy", "purge", "format", "wipe", "truncate", "reset", "unlink"
})

MUTATING_KEYWORDS = frozenset({
    "write", "create", "edit", "update", "modify", "patch", "append", "save", "post", "send", "publish",
    "exec", "execute", "run", "spawn", "terminal", "bash", "sh", "eval", "upload"
})

READ_KEYWORDS = frozenset({
    "read", "get", "list", "search", "find", "fetch", "query", "inspect", "view", "describe", "status", "info"
})


@dataclass(frozen=True)
class MCPToolMetadata:
    server_id: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    server_declared_annotations: Optional[Dict[str, Any]] = None
    assigned_risk_level: ToolRiskLevel = ToolRiskLevel.LEVEL_3_EXECUTION_AND_SIDE_EFFECTS


@dataclass(frozen=True)
class ToolApprovalBinding:
    approval_id: str
    server_id: str
    tool_name: str
    arguments_canonical_hash: str
    workspace_root: str
    risk_level: ToolRiskLevel
    expires_at: float
    signature: str


class MCPToolPolicyEngine:
    """
    Centralized policy engine evaluating MCP tool definitions, classifying risk levels,
    and generating/verifying tamper-proof single-use approval bindings.
    """

    def __init__(self, secret_key: Optional[bytes] = None) -> None:
        self._secret_key = secret_key or hashlib.sha256(f"mcp_policy_{os.getpid()}_{time.time()}".encode()).digest()
        self._consumed_approval_ids: Set[str] = set()

    @classmethod
    def canonical_arguments_hash(cls, arguments: Optional[Dict[str, Any]]) -> str:
        """Deterministic SHA-256 hash of canonical sorted JSON arguments."""
        args = arguments or {}
        canonical_json = json.dumps(args, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @classmethod
    def classify_tool(
        cls,
        server_id: str,
        name: str,
        description: str,
        input_schema: Optional[Dict[str, Any]] = None,
        annotations: Optional[Dict[str, Any]] = None,
    ) -> ToolRiskLevel:
        """
        Classify tool into 5-tier risk taxonomy.
        Crucial principle: MCP tool annotations (e.g. readOnlyHint=true) are UNTRUSTED metadata
        and cannot override Crusor policy checks.
        """
        name_lower = name.lower()
        desc_lower = (description or "").lower()

        # Check for Level 4: Destructive operations
        if any(kw in name_lower for kw in DESTRUCTIVE_KEYWORDS) or any(f" {kw} " in f" {desc_lower} " for kw in DESTRUCTIVE_KEYWORDS):
            return ToolRiskLevel.LEVEL_4_HIGHLY_SENSITIVE_DESTRUCTIVE

        # Check for Level 3: Execution and external mutations
        if any(kw in name_lower for kw in ("terminal", "command", "shell", "exec", "publish", "send", "post")):
            return ToolRiskLevel.LEVEL_3_EXECUTION_AND_SIDE_EFFECTS

        # Check for Level 2: Reversible workspace modifications
        if any(kw in name_lower for kw in ("write", "edit", "create", "patch", "modify", "append")):
            return ToolRiskLevel.LEVEL_2_REVERSIBLE_MODIFICATION

        # Check for Level 1: Workspace reads
        if any(kw in name_lower for kw in ("read_file", "search_files", "grep", "repo_map", "read_code")):
            return ToolRiskLevel.LEVEL_1_WORKSPACE_READ

        # Check for Level 0: Informational / docs / status
        if any(kw in name_lower for kw in ("doc", "status", "version", "ping", "help", "list_tools")):
            return ToolRiskLevel.LEVEL_0_READ_ONLY_INFORMATIONAL

        # Fallback to Level 3 (fail-closed for unknown side-effect risks)
        return ToolRiskLevel.LEVEL_3_EXECUTION_AND_SIDE_EFFECTS

    def create_approval(
        self,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        workspace_root: str,
        risk_level: ToolRiskLevel,
        expiry_s: float = 300.0,
    ) -> str:
        """Generate a cryptographically signed approval binding for an exact invocation."""
        approval_id = f"appr_{uuid.uuid4().hex[:12]}"
        args_hash = self.canonical_arguments_hash(arguments)
        ws_clean = str(Path(workspace_root).resolve())
        expires_at = time.time() + expiry_s

        payload = f"{approval_id}|{server_id}|{tool_name}|{args_hash}|{ws_clean}|{risk_level.value}|{int(expires_at)}"
        signature = hashlib.sha256(self._secret_key + payload.encode("utf-8")).hexdigest()

        return f"{payload}|{signature}"

    def _validate_token_internal(
        self,
        approval_token: str,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        workspace_root: str,
    ) -> Tuple[bool, Optional[str], Optional[ToolRiskLevel]]:
        if not approval_token:
            return False, "Missing mandatory approval token for MCP tool execution.", None

        parts = approval_token.split("|")
        if len(parts) != 8:
            return False, "Malformed approval token format.", None

        approval_id, tok_server, tok_tool, tok_args_hash, tok_ws, tok_risk, tok_expiry, tok_sig = parts

        if approval_id in self._consumed_approval_ids:
            return False, "Approval token already consumed (replay attack rejected).", None

        try:
            exp_ts = int(tok_expiry)
            if time.time() > exp_ts:
                return False, "Approval token has expired.", None
        except ValueError:
            return False, "Invalid approval token timestamp.", None

        if tok_server != server_id:
            return False, f"Approval was issued for server '{tok_server}', not '{server_id}'.", None
        if tok_tool != tool_name:
            return False, f"Approval was issued for tool '{tok_tool}', not '{tool_name}'.", None

        current_args_hash = self.canonical_arguments_hash(arguments)
        if tok_args_hash != current_args_hash:
            return False, "Tool arguments modified after approval was granted (hash mismatch).", None

        current_ws = str(Path(workspace_root).resolve())
        if tok_ws != current_ws:
            return False, "Workspace root mismatch in approval binding.", None

        expected_payload = f"{approval_id}|{tok_server}|{tok_tool}|{tok_args_hash}|{tok_ws}|{tok_risk}|{tok_expiry}"
        expected_sig = hashlib.sha256(self._secret_key + expected_payload.encode("utf-8")).hexdigest()

        if tok_sig != expected_sig:
            return False, "Forged or corrupted approval signature.", None

        risk_level = ToolRiskLevel(int(tok_risk))
        return True, "Valid", risk_level

    def verify_approval(
        self,
        approval_token: str,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        workspace_root: str,
    ) -> Tuple[bool, Optional[str]]:
        valid, err, _ = self._validate_token_internal(approval_token, server_id, tool_name, arguments, workspace_root)
        return valid, (None if valid else err)

    def consume_approval(
        self,
        approval_token: str,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        workspace_root: str,
    ) -> Tuple[bool, Optional[str]]:
        valid, err, _ = self.verify_and_consume_approval(approval_token, server_id, tool_name, arguments, workspace_root)
        return valid, (None if valid else err)

    def verify_and_consume_approval(
        self,
        approval_token: str,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        workspace_root: str,
    ) -> Tuple[bool, Optional[str], Optional[ToolRiskLevel]]:
        valid, err, risk = self._validate_token_internal(approval_token, server_id, tool_name, arguments, workspace_root)
        if not valid:
            return False, err, None

        parts = approval_token.split("|")
        approval_id = parts[0]
        self._consumed_approval_ids.add(approval_id)
        return True, "Approval valid and consumed.", risk


"""
contracts.py - Enterprise Execution Broker and Sandbox Contracts.

Phase 9.4: OS-Level Process Isolation & Execution Governance.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ExecutionMode(str, enum.Enum):
    READ_ONLY = "READ_ONLY"              # Mode A: strictly read-only workspace access
    PROPOSED_MUTATION = "PROPOSED_MUTATION"  # Mode B: isolated staging directory with diff review


class SandboxBackendType(str, enum.Enum):
    WINDOWS_JOB_OBJECT = "windows_job_object_lua"
    WINDOWS_APPCONTAINER = "windows_appcontainer_job_object"
    LINUX_NAMESPACES = "linux_namespaces_cgroups"
    MACOS_SANDBOX = "macos_sandbox_exec"
    FAIL_CLOSED_STUB = "fail_closed_unsupported"


class SecurityViolationType(str, enum.Enum):
    WORKSPACE_TRAVERSAL = "WORKSPACE_TRAVERSAL"
    SYMLINK_JUNCTION_ESCAPE = "SYMLINK_JUNCTION_ESCAPE"
    CREDENTIAL_ACCESS_ATTEMPT = "CREDENTIAL_ACCESS_ATTEMPT"
    NETWORK_ACCESS_ATTEMPT = "NETWORK_ACCESS_ATTEMPT"
    ENVIRONMENT_SECRET_HARVEST = "ENVIRONMENT_SECRET_HARVEST"
    FORK_BOMB_ACTIVE_PROCESS_LIMIT = "FORK_BOMB_ACTIVE_PROCESS_LIMIT"
    MEMORY_EXHAUSTION = "MEMORY_EXHAUSTION"
    TIMEOUT_EXCEEDED = "TIMEOUT_EXCEEDED"
    UNAUTHORIZED_EXECUTION_ATTEMPT = "UNAUTHORIZED_EXECUTION_ATTEMPT"
    FORGED_OR_STALE_APPROVAL = "FORGED_OR_STALE_APPROVAL"


# Minimal safe environment allowlist for sandboxed execution
SAFE_ENVIRONMENT_KEYS = frozenset({
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "TMP",
    "TEMP",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
    "CI",
    "NO_COLOR",
    "PYTHONPATH",
    "LANG",
    "LC_ALL",
})

# Blacklist of secret keys that must NEVER be passed to an execution worker
SENSITIVE_SECRET_PATTERNS = [
    "KEY",
    "SECRET",
    "TOKEN",
    "AUTH",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE",
    "SSH",
    "AWS",
    "AZURE",
    "GCP",
    "OPENAI",
    "ANTHROPIC",
    "GEMINI",
    "CRUSOR",
]


@dataclass(frozen=True)
class ExecutionRequest:
    execution_id: str
    session_id: str
    request_id: str
    workspace_root: str
    tool_name: str
    command: str
    argv: List[str]
    mode: ExecutionMode = ExecutionMode.READ_ONLY
    approval_token: str = ""
    timeout_s: float = 60.0
    max_memory_mb: int = 512
    max_processes: int = 10
    network_allowed: bool = False
    env_overrides: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionReceipt:
    execution_id: str
    session_id: str
    request_id: str
    workspace_root: str
    tool_name: str
    executable: str
    sanitized_argv: List[str]
    sandbox_backend: str
    policy_version: str
    start_time: str
    end_time: str
    duration_s: float
    exit_code: int
    timed_out: bool
    cancelled: bool
    cpu_user_s: float
    cpu_kernel_s: float
    peak_memory_bytes: int
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    staged_files_created: List[str]
    staged_files_modified: List[str]
    security_violations: List[str]
    cleanup_status: str
    evidence_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "workspace_root": self.workspace_root,
            "tool_name": self.tool_name,
            "executable": self.executable,
            "sanitized_argv": self.sanitized_argv,
            "sandbox_backend": self.sandbox_backend,
            "policy_version": self.policy_version,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_s": self.duration_s,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "cpu_user_s": self.cpu_user_s,
            "cpu_kernel_s": self.cpu_kernel_s,
            "peak_memory_bytes": self.peak_memory_bytes,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "staged_files_created": self.staged_files_created,
            "staged_files_modified": self.staged_files_modified,
            "security_violations": self.security_violations,
            "cleanup_status": self.cleanup_status,
            "evidence_hash": self.evidence_hash,
        }


# Cryptographic secret for signing approval tokens in this process
_BROKER_SECRET = hashlib.sha256(f"crusor_broker_secret_{os.getpid()}_{time.time()}".encode("utf-8")).hexdigest().encode("utf-8")


def generate_approval_token(
    session_id: str,
    request_id: str,
    command: str,
    workspace_root: str,
    expiry_s: float = 300.0,
) -> str:
    """Generate a single-use cryptographically bound approval token."""
    expiry_ts = int(time.time() + expiry_s)
    cmd_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()[:16]
    ws_hash = hashlib.sha256(workspace_root.encode("utf-8")).hexdigest()[:16]
    payload = f"{session_id}:{request_id}:{cmd_hash}:{ws_hash}:{expiry_ts}"
    signature = hmac.new(_BROKER_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_approval_token(
    token: str,
    session_id: str,
    request_id: str,
    command: str,
    workspace_root: str,
) -> tuple[bool, str]:
    """Verify an approval token against the exact request parameters."""
    if not token or not isinstance(token, str):
        return False, "Approval token missing or invalid."

    parts = token.split(":")
    if len(parts) != 6:
        return False, "Malformed approval token format."

    tok_session, tok_req, tok_cmd_hash, tok_ws_hash, tok_expiry, tok_sig = parts

    # Check expiry
    try:
        expiry_ts = int(tok_expiry)
        if time.time() > expiry_ts:
            return False, "Approval token has expired (stale token replay prevented)."
    except ValueError:
        return False, "Invalid token timestamp."

    expected_cmd_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()[:16]
    expected_ws_hash = hashlib.sha256(workspace_root.encode("utf-8")).hexdigest()[:16]
    expected_payload = f"{session_id}:{request_id}:{expected_cmd_hash}:{expected_ws_hash}:{tok_expiry}"
    expected_sig = hmac.new(_BROKER_SECRET, expected_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(tok_sig, expected_sig):
        return False, "Forged or mismatched approval signature."

    if tok_session != session_id or tok_req != request_id:
        return False, "Approval token session/request correlation mismatch."

    return True, "Approval token valid."


def compute_receipt_hash(data: Dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash of execution telemetry."""
    # Hash core identifying fields
    core = (
        f"{data.get('execution_id')}|"
        f"{data.get('session_id')}|"
        f"{data.get('request_id')}|"
        f"{data.get('exit_code')}|"
        f"{data.get('stdout_bytes')}|"
        f"{data.get('stderr_bytes')}|"
        f"{data.get('peak_memory_bytes')}|"
        f"{','.join(data.get('security_violations', []))}"
    )
    return hashlib.sha256(core.encode("utf-8")).hexdigest()


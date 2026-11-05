"""
Phase 9.3.2.2: Agent Tool Retry, Circuit Breaker & Typed Error Classification Controller.

Guards agent runtime loops against:
1. Non-retryable infrastructure errors (ImportError, missing tool registration, broken dispatcher).
2. Repeated identical invalid tool calls (duplicate parameter binding failures).
3. Protocol violations (invoking tools after entering FINALIZATION state).
4. Infinite recovery attempts.

Provides:
- Strict classification between RETRYABLE and NON_RETRYABLE_INFRASTRUCTURE errors.
- Typed exception class and telemetry preservation (exception_class, tool_name, request_id, session_id).
- Immediate termination on non-retryable infrastructure failures without model retries.
- Automatic schema inspection on binding failure to supply repair guidance to the model for retryable errors.
- Circuit breaker trip when an identical invalid call is repeated consecutively.
- Complete audit preservation in FinOps telemetry.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

# Error Classification Constants
ERROR_RETRYABLE = "RETRYABLE"
ERROR_NON_RETRYABLE_INFRASTRUCTURE = "NON_RETRYABLE_INFRASTRUCTURE"

# ---------------------------------------------------------------------------
# Phase 9.3.5: 14 Typed Agent Failure Categories & Recovery Policies
# ---------------------------------------------------------------------------

class FailureCategory(str, Enum):
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    MISSING_REQUIRED_PARAMETERS = "MISSING_REQUIRED_PARAMETERS"
    WORKSPACE_AUTHORIZATION_FAILURE = "WORKSPACE_AUTHORIZATION_FAILURE"
    MISSING_FILES = "MISSING_FILES"
    STALE_DOCUMENT_VERSIONS = "STALE_DOCUMENT_VERSIONS"
    TOOL_EXECUTION_ERRORS = "TOOL_EXECUTION_ERRORS"
    IMPORT_ERRORS = "IMPORT_ERRORS"
    PROVIDER_ERRORS = "PROVIDER_ERRORS"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
    TIMEOUTS = "TIMEOUTS"
    CANCELLATION = "CANCELLATION"
    VALIDATION_FAILURES = "VALIDATION_FAILURES"
    BACKEND_DISCONNECTION = "BACKEND_DISCONNECTION"
    FINALIZATION_FAILURE = "FINALIZATION_FAILURE"


@dataclass(frozen=True)
class RecoveryPolicy:
    category: FailureCategory
    is_retryable: bool
    max_retries: int
    recovery_action: str
    trip_circuit_breaker: bool = False


FAILURE_RECOVERY_POLICIES: Dict[FailureCategory, RecoveryPolicy] = {
    FailureCategory.INVALID_TOOL_ARGUMENTS: RecoveryPolicy(
        category=FailureCategory.INVALID_TOOL_ARGUMENTS,
        is_retryable=True,
        max_retries=2,
        recovery_action="Inspect tool schema, sanitize argument types, and retry with repaired payload.",
    ),
    FailureCategory.MISSING_REQUIRED_PARAMETERS: RecoveryPolicy(
        category=FailureCategory.MISSING_REQUIRED_PARAMETERS,
        is_retryable=True,
        max_retries=2,
        recovery_action="Inject missing mandatory arguments derived from context or schema guidance.",
    ),
    FailureCategory.WORKSPACE_AUTHORIZATION_FAILURE: RecoveryPolicy(
        category=FailureCategory.WORKSPACE_AUTHORIZATION_FAILURE,
        is_retryable=False,
        max_retries=0,
        recovery_action="Permanent security refusal: fail closed without retrying unauthorized paths.",
        trip_circuit_breaker=True,
    ),
    FailureCategory.MISSING_FILES: RecoveryPolicy(
        category=FailureCategory.MISSING_FILES,
        is_retryable=True,
        max_retries=2,
        recovery_action="Query directory structure or search_files to discover actual target file path.",
    ),
    FailureCategory.STALE_DOCUMENT_VERSIONS: RecoveryPolicy(
        category=FailureCategory.STALE_DOCUMENT_VERSIONS,
        is_retryable=True,
        max_retries=2,
        recovery_action="Re-read current document model from disk to refresh base buffer before patching.",
    ),
    FailureCategory.TOOL_EXECUTION_ERRORS: RecoveryPolicy(
        category=FailureCategory.TOOL_EXECUTION_ERRORS,
        is_retryable=True,
        max_retries=2,
        recovery_action="Analyze execution traceback and adjust tool invocation parameters.",
    ),
    FailureCategory.IMPORT_ERRORS: RecoveryPolicy(
        category=FailureCategory.IMPORT_ERRORS,
        is_retryable=False,
        max_retries=0,
        recovery_action="Permanent runtime defect: abort execution immediately without model retries.",
        trip_circuit_breaker=True,
    ),
    FailureCategory.PROVIDER_ERRORS: RecoveryPolicy(
        category=FailureCategory.PROVIDER_ERRORS,
        is_retryable=True,
        max_retries=3,
        recovery_action="Apply exponential backoff and retry provider request.",
    ),
    FailureCategory.CONTEXT_OVERFLOW: RecoveryPolicy(
        category=FailureCategory.CONTEXT_OVERFLOW,
        is_retryable=True,
        max_retries=1,
        recovery_action="Trigger eager history compaction and truncate oldest tool observations.",
    ),
    FailureCategory.TIMEOUTS: RecoveryPolicy(
        category=FailureCategory.TIMEOUTS,
        is_retryable=True,
        max_retries=1,
        recovery_action="Narrow execution scope or increase bounded timeout if authorized.",
    ),
    FailureCategory.CANCELLATION: RecoveryPolicy(
        category=FailureCategory.CANCELLATION,
        is_retryable=False,
        max_retries=0,
        recovery_action="Session was explicitly cancelled by human or client: terminate immediately.",
        trip_circuit_breaker=True,
    ),
    FailureCategory.VALIDATION_FAILURES: RecoveryPolicy(
        category=FailureCategory.VALIDATION_FAILURES,
        is_retryable=True,
        max_retries=2,
        recovery_action="Inspect failed validation assertions and generate targeted corrective edit.",
    ),
    FailureCategory.BACKEND_DISCONNECTION: RecoveryPolicy(
        category=FailureCategory.BACKEND_DISCONNECTION,
        is_retryable=True,
        max_retries=2,
        recovery_action="Attempt reconnect to desktop bridge RPC socket before declaring session dead.",
    ),
    FailureCategory.FINALIZATION_FAILURE: RecoveryPolicy(
        category=FailureCategory.FINALIZATION_FAILURE,
        is_retryable=False,
        max_retries=0,
        recovery_action="Deterministic fallback: emit structured FAILED/BLOCKED completion receipt.",
        trip_circuit_breaker=True,
    ),
}


def classify_granular_failure(
    error_msg: str,
    exception: Optional[Exception] = None,
    exception_class: Optional[str] = None,
) -> FailureCategory:
    """Classifies an error string or exception into one of the 14 granular failure classes."""
    exc_name = (exception_class or (type(exception).__name__ if exception is not None else "")).lower()
    msg = str(error_msg or "").lower()

    if "cancel" in msg or "cancellation" in msg or exc_name in ("cancellederror", "taskcancelled"):
        return FailureCategory.CANCELLATION
    if "import" in msg or "modulenotfound" in msg or exc_name in ("importerror", "modulenotfounderror"):
        return FailureCategory.IMPORT_ERRORS
    if any(w in msg for w in ("connection refused", "econnrefused", "disconnected", "bridge closed")):
        return FailureCategory.BACKEND_DISCONNECTION
    if any(w in msg for w in ("rate limit", "503", "502", "provider error")):
        return FailureCategory.PROVIDER_ERRORS
    if any(w in msg for w in ("missing required", "required argument", "missing parameter", "missing argument")):
        return FailureCategory.MISSING_REQUIRED_PARAMETERS
    if any(w in msg for w in ("invalid argument", "validation error", "schema error", "typeerror")):
        return FailureCategory.INVALID_TOOL_ARGUMENTS
    if any(w in msg for w in ("workspace", "permission", "refused", "unauthorized", "safetyguard", "security")):
        return FailureCategory.WORKSPACE_AUTHORIZATION_FAILURE
    if any(w in msg for w in ("filenotfound", "does not exist", "not found", "no such file")):
        return FailureCategory.MISSING_FILES
    if any(w in msg for w in ("stale", "outdated version", "conflict")):
        return FailureCategory.STALE_DOCUMENT_VERSIONS
    if any(w in msg for w in ("context length", "token limit", "overflow", "maximum context")):
        return FailureCategory.CONTEXT_OVERFLOW
    if any(w in msg for w in ("timeout", "timed out", "deadline exceeded")):
        return FailureCategory.TIMEOUTS
    if any(w in msg for w in ("validation failed", "verification failed", "assertionerror")):
        return FailureCategory.VALIDATION_FAILURES
    if any(w in msg for w in ("finalization", "cannot finalize")):
        return FailureCategory.FINALIZATION_FAILURE

    return FailureCategory.TOOL_EXECUTION_ERRORS

NON_RETRYABLE_INFRASTRUCTURE_PATTERNS = [
    "importerror",
    "modulenotfounderror",
    "cannot import name",
    "no module named",
    "broken dispatcher contract",
    "missing tool registration",
    "unknown tool",
    "missing runtime dependencies",
    "unhandled dispatcher defect",
    "safetyguard initialization failure",
    "safetyguard inspection failure",
    "security inspection error",
    "security denial",
    "security approval refused",
    "security approval required",
    "security policy violation",
    "invalid safety inspection result",
    "protocol violation",
]


@dataclass
class ToolExecutionAttempt:
    turn: int
    tool_name: str
    args_hash: str
    args: Dict[str, Any]
    status: str  # "success", "error", "protocol_violation", "security_denial", "security_inspection_failure"
    error: Optional[str] = None
    error_category: Optional[str] = None
    exception_class: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    workspace: Optional[str] = None
    security_denial_status: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None



class ToolRetryController:
    """
    Session-level controller for detecting, classifying, and terminating tool errors.
    """

    def __init__(self, max_consecutive_identical_failures: int = 1):
        self.max_identical = max_consecutive_identical_failures
        self.attempts: List[ToolExecutionAttempt] = []
        self._consecutive_failure_counts: Dict[str, int] = {}
        self.circuit_broken: bool = False
        self.break_reason: Optional[str] = None
        self.is_infrastructure_fatal: bool = False
        self.fatal_error_details: Optional[Dict[str, Any]] = None

    def _hash_args(self, args: Any) -> str:
        try:
            serialized = json.dumps(args, sort_keys=True, default=str)
        except Exception:
            serialized = str(args)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def classify_error(
        error_msg: str,
        exception: Optional[Exception] = None,
        exception_class: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Classifies whether an error is retryable or a non-retryable infrastructure defect.
        Returns: (classification, description)
        """
        exc_name = exception_class or (type(exception).__name__ if exception is not None else None)
        if exc_name in ("ImportError", "ModuleNotFoundError"):
            return ERROR_NON_RETRYABLE_INFRASTRUCTURE, f"Fatal infrastructure defect ({exc_name}): {exception or error_msg}"

        err_str = str(error_msg or "").lower()
        for pat in NON_RETRYABLE_INFRASTRUCTURE_PATTERNS:
            if pat in err_str:
                return ERROR_NON_RETRYABLE_INFRASTRUCTURE, f"Fatal infrastructure defect matching '{pat}': {error_msg}"

        return ERROR_RETRYABLE, "Recoverable schema, parameter, or execution error"

    def check_infrastructure_error(
        self,
        tool_name: str,
        error_msg: str,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        workspace: Optional[str] = None,
        security_denial_status: Optional[str] = None,
        exception: Optional[Exception] = None,
        exception_class: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Checks if an error represents a fatal, non-retryable infrastructure or security failure.
        If non-retryable:
        1. Immediately trips circuit breaker.
        2. Sets is_infrastructure_fatal = True.
        3. Captures fatal details (category, tool, request_id, session_id, workspace, security_denial_status, exception_class, error).
        4. Returns (True, actionable_error_message).
        """
        category, reason = self.classify_error(error_msg, exception, exception_class)
        exc_name = exception_class or (type(exception).__name__ if exception is not None else None)
        if category == ERROR_NON_RETRYABLE_INFRASTRUCTURE:
            self.circuit_broken = True
            self.is_infrastructure_fatal = True
            self.break_reason = reason
            default_status = "DENIED_SECURITY_INSPECTION" if any(w in error_msg.lower() for w in ("safetyguard", "security")) else "INFRASTRUCTURE_FAILURE"
            self.fatal_error_details = {
                "category": ERROR_NON_RETRYABLE_INFRASTRUCTURE,
                "tool_name": tool_name,
                "exception_class": exc_name or "InfrastructureOrSecurityDefect",
                "request_id": request_id or "UNKNOWN",
                "session_id": session_id or "UNKNOWN",
                "workspace": workspace or "UNKNOWN",
                "security_denial_status": security_denial_status or default_status,
                "error_message": error_msg,
                "reason": reason,
            }
            actionable_msg = (
                f"⛔ NON-RETRYABLE INFRASTRUCTURE/SECURITY ERROR: Tool '{tool_name}' failed with an unrecoverable "
                f"runtime or security defect ({error_msg}). Execution aborted immediately without model retry."
            )
            return True, actionable_msg

        return False, None

    def record_attempt(
        self,
        turn: int,
        tool_name: str,
        args: Dict[str, Any],
        status: str,
        error: Optional[str] = None,
        exception: Optional[Exception] = None,
        exception_class: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        workspace: Optional[str] = None,
        security_denial_status: Optional[str] = None,
        error_details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an attempt into session telemetry with typed error details."""
        args_hash = self._hash_args(args)
        key = f"{tool_name}:{args_hash}"

        category = None
        if status in ("error", "protocol_violation", "security_denial", "security_inspection_failure"):
            category, _ = self.classify_error(error or "", exception, exception_class)

        attempt = ToolExecutionAttempt(
            turn=turn,
            tool_name=tool_name,
            args_hash=args_hash,
            args=args,
            status=status,
            error=error,
            error_category=category,
            exception_class=exception_class or (type(exception).__name__ if exception is not None else None),
            request_id=request_id,
            session_id=session_id,
            workspace=workspace,
            security_denial_status=security_denial_status,
            error_details=error_details,
        )
        self.attempts.append(attempt)

        if status in ("error", "protocol_violation", "security_denial", "security_inspection_failure"):
            self._consecutive_failure_counts[key] = self._consecutive_failure_counts.get(key, 0) + 1
        else:
            self._consecutive_failure_counts[key] = 0


    def should_abort_duplicate(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an identical tool call already failed previously in this session.
        If so, abort immediately to break the doom loop.
        """
        if self.is_infrastructure_fatal:
            return True, self.break_reason

        args_hash = self._hash_args(args)
        key = f"{tool_name}:{args_hash}"
        count = self._consecutive_failure_counts.get(key, 0)

        if count >= self.max_identical:
            self.circuit_broken = True
            self.break_reason = (
                f"Circuit breaker tripped: tool '{tool_name}' previously failed with the exact same arguments. "
                "Aborting repeat invocation to prevent infinite doom loop. All retry attempts preserved in accounting."
            )
            return True, self.break_reason

        return False, None

    def format_schema_repair_guidance(
        self,
        tool_name: str,
        tool_definitions: List[Dict[str, Any]],
        original_error: str,
    ) -> str:
        """
        Inspect the model-facing tool schema and return a clear repair manual.
        """
        schema_props = {}
        required = []
        desc = ""
        for td in tool_definitions:
            fn = td.get("function", {})
            if fn.get("name") == tool_name:
                desc = fn.get("description", "")
                params = fn.get("parameters", {})
                schema_props = params.get("properties", {})
                required = params.get("required", [])
                break

        props_summary = ", ".join(
            f"'{k}' ({v.get('type', 'any')}): {v.get('description', '')}"
            for k, v in schema_props.items()
        )
        guidance = (
            f"❌ Tool execution error in '{tool_name}': {original_error}\n\n"
            f"📖 Schema Specification for '{tool_name}':\n"
            f"- Description: {desc}\n"
            f"- Required parameters: {required}\n"
            f"- All properties: {props_summary}\n\n"
            "⚠️ Do NOT repeat the exact same invalid call. Provide the required parameters correctly or formulate your final answer."
        )
        return guidance


def classify_error(
    error_msg: str,
    exception: Optional[Exception] = None,
    exception_class: Optional[str] = None,
) -> Tuple[str, str]:
    """Top-level functional export for error classification."""
    return ToolRetryController.classify_error(error_msg, exception, exception_class)


RetryController = ToolRetryController

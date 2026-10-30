"""Autonomous Reliability & Recovery Engine (ARRE) for CrusorAI 2.1.

Implements the 10-class failure taxonomy:
1. syntax_error: SyntaxError, IndentationError, AST parse crashes.
2. schema_argument_error: Missing required args, validation failure, conflicting aliases.
3. flaky_network_timeout: TimeoutError, ConnectionRefused, socket drops.
4. assertion_failure: AssertionError, test suite exit code > 0.
5. provider_error: HTTP 400, 429, 500, rate limits, invalid LLM responses.
6. permission_error: PermissionError, EACCES, read-only path escapes.
7. resource_exhaustion: Disk full (Errno 28), out of memory, token budget exceeded.
8. process_failure: Process crash, non-zero abnormal exit (SIGSEGV, -9, 137).
9. port_collision: EADDRINUSE, port already bound.
10. safety_denial: Operation blocked by safety guard or workspace lock.
"""
from __future__ import annotations

import re
from typing import Any, Dict, NamedTuple, Optional


class FailureClassification(NamedTuple):
    failure_class: str
    is_retryable: bool
    max_retries: int
    recommended_strategy: str
    diagnostic_message: str
    metadata: Dict[str, Any]


class FailureClassifier:
    """Deterministic, rule-based failure classifier for tool, environment, and code errors."""

    @staticmethod
    def classify_error(
        tool_name: str,
        error_str: str,
        exit_code: Optional[int] = None,
        is_idempotent: bool = True,
        attempt: int = 1,
    ) -> FailureClassification:
        err = (error_str or "").strip()
        err_lower = err.lower()

        # 1. Port Collision (EADDRINUSE)
        if "eaddrinuse" in err_lower or "address already in use" in err_lower:
            port_match = re.search(r"(?:port\s*[:=]?\s*|:::|:)(\d{3,5})\b", err_lower)
            port = int(port_match.group(1)) if port_match else None
            return FailureClassification(
                failure_class="port_collision",
                is_retryable=True,
                max_retries=2,
                recommended_strategy="inspect_port_owner_or_allocate_dynamic",
                diagnostic_message=f"Port collision detected{f' on port {port}' if port else ''}. Check colliding process owner.",
                metadata={"port": port},
            )

        # 2. Syntax / Indentation Errors
        if any(x in err_lower for x in ["syntaxerror", "indentationerror", "taberror", "unterminated string", "invalid syntax"]):
            return FailureClassification(
                failure_class="syntax_error",
                is_retryable=True,
                max_retries=3,
                recommended_strategy="ast_diagnostic_feedback",
                diagnostic_message="Syntax validation failed. Provide exact line-level AST diagnostics to the model.",
                metadata={"requires_code_mutation": True},
            )

        # 3. Schema & Argument Errors (e.g., from SafeArgumentNormalizer)
        if any(x in err_lower for x in ["conflicting_arguments_error", "ambiguous_argument_error", "invalid_arguments_type", "missing required argument"]):
            return FailureClassification(
                failure_class="schema_argument_error",
                is_retryable=True,
                max_retries=2,
                recommended_strategy="schema_feedback_prompt",
                diagnostic_message="Tool arguments invalid or conflicting. Provide JSON schema feedback.",
                metadata={"tool_name": tool_name},
            )

        # 4. Flaky Network / Timeouts
        if any(x in err_lower for x in ["timeouterror", "timed out", "connectionrefused", "connection reset", "econnrefused", "socket hang up"]):
            # Peer review rule: only retry if explicitly marked idempotent!
            can_retry = is_idempotent and (attempt <= 2)
            return FailureClassification(
                failure_class="flaky_network_timeout",
                is_retryable=can_retry,
                max_retries=2,
                recommended_strategy="bounded_idempotent_retry" if can_retry else "fail_closed_non_idempotent",
                diagnostic_message=(
                    "Network timeout occurred. Executing bounded retry."
                    if can_retry
                    else "Timeout occurred on non-idempotent or exhausted operation. Requires investigation."
                ),
                metadata={"attempt": attempt, "is_idempotent": is_idempotent},
            )

        # 5. Provider Errors (HTTP 429, 500, Rate Limits)
        if any(x in err_lower for x in ["rate limit", "429", "too many requests", "500 internal server error", "502 bad gateway", "503 service unavailable"]):
            return FailureClassification(
                failure_class="provider_error",
                is_retryable=True,
                max_retries=4,
                recommended_strategy="exponential_backoff_jitter",
                diagnostic_message="LLM provider rate limit or server error. Apply exponential backoff with jitter.",
                metadata={"backoff_base_s": 2, "attempt": attempt},
            )

        # 6. Permission & Access Denied
        if any(x in err_lower for x in ["permissionerror", "eacces", "permission denied", "access is denied", "operation not permitted"]):
            return FailureClassification(
                failure_class="permission_error",
                is_retryable=False,
                max_retries=0,
                recommended_strategy="audit_trail_fail_closed",
                diagnostic_message="Filesystem or command permission denied. Halting execution to protect sandbox.",
                metadata={"security_boundary": True},
            )

        # 7. Resource Exhaustion (Disk / Memory / Tokens)
        if any(x in err_lower for x in ["no space left on device", "errno 28", "out of memory", "memoryerror", "budget exceeded", "token budget"]):
            return FailureClassification(
                failure_class="resource_exhaustion",
                is_retryable=True,
                max_retries=2,
                recommended_strategy="landed_write_compaction_and_log_drain",
                diagnostic_message="System resources or token budget near ceiling. Triggering immediate context compaction.",
                metadata={"requires_compaction": True},
            )

        # 8. Process Failure (Killed / Segmentation Fault / Exit Code -9, 137)
        if exit_code in {-9, 137, 139, 255} or "segmentation fault" in err_lower or "killed" in err_lower:
            return FailureClassification(
                failure_class="process_failure",
                is_retryable=False,
                max_retries=1,
                recommended_strategy="clean_process_handles_and_dump_trace",
                diagnostic_message=f"Subprocess terminated abnormally with exit code {exit_code}.",
                metadata={"exit_code": exit_code},
            )

        # 9. Assertion & Unit Test Failures
        if "assertionerror" in err_lower or (exit_code is not None and exit_code > 0 and any(x in err_lower for x in ["failed", "failures=", "assert "])):
            return FailureClassification(
                failure_class="assertion_failure",
                is_retryable=True,
                max_retries=3,
                recommended_strategy="alternating_mutation_lock",
                diagnostic_message="Unit test assertions failed. Lock test runner until model applies relevant code mutation.",
                metadata={"exit_code": exit_code, "requires_code_mutation": True},
            )

        # 10. Default Safety Denial / Unhandled
        if "safety" in err_lower or "blocked" in err_lower or "denied" in err_lower:
            return FailureClassification(
                failure_class="safety_denial",
                is_retryable=False,
                max_retries=0,
                recommended_strategy="audit_trail_fail_closed",
                diagnostic_message="Operation denied by safety policy.",
                metadata={},
            )

        # Fallback: Generic Unclassified Failure
        return FailureClassification(
            failure_class="unclassified_error",
            is_retryable=False,
            max_retries=1,
            recommended_strategy="diagnose_and_report",
            diagnostic_message=f"Unhandled tool failure: {err[:150]}",
            metadata={"exit_code": exit_code},
        )

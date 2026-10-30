"""Autonomous Reliability & Recovery Engine (ARRE) for CrusorAI 2.1 (Phase 2 Master).

Implements the 15-class failure taxonomy:
1. logic_or_specification_failure: Structured requirement-verification evidence mismatch.
2. syntax_error: SyntaxError, IndentationError, AST parse crashes.
3. schema_argument_error: Missing required args, validation failure, conflicting aliases.
4. invalid_request_error: HTTP 400 (Bad Request). Fail-closed; never retry identical invalid payload.
5. provider_auth_failure: HTTP 401, 403. Fail-fast; halts immediately to avoid lockout.
6. provider_rate_limit: HTTP 429. Parses numeric and HTTP-date Retry-After headers with backoff.
7. provider_transient_error: HTTP 500, 502, 503, 504. Exponential backoff with jitter.
8. service_not_running: ECONNREFUSED + Process Dead (CrusorAI-owned) -> Single controlled relaunch.
9. network_warmup_delay: ECONNREFUSED + Process Alive (CrusorAI-owned) -> Bounded readiness polling.
10. unowned_service_collision: ECONNREFUSED + Foreign/Unowned Process -> Fail-closed; no restart.
11. flaky_network_timeout: TimeoutError (Idempotent=True) -> Bounded retry (max 2).
12. assertion_failure: AssertionError, test suite exit code > 0 -> Alternating mutation lock.
13. disk_exhaustion: Errno 28 (No space left on device) -> Drain eligible logs.
14. memory_exhaustion: MemoryError, OOM killer -> Terminate owned sub-processes; release caches.
15. hard_token_budget_stop: Token ceiling reached -> Cease tools; emit graceful completion summary.
"""
from __future__ import annotations

import email.utils
import re
import threading
import time
from typing import Any, Dict, List, NamedTuple, Optional, Protocol


class ProcessSupervisor(Protocol):
    def inspect_port_owner(self, port: int) -> tuple[bool, bool]:
        """Returns (is_alive, is_owned_by_crusorai)."""
        ...

    def relaunch_process(self, port: int) -> bool:
        """Controlled relaunch of CrusorAI-owned process on port."""
        ...

    def terminate_process(self, port: int) -> bool:
        """Safely terminates CrusorAI-owned process on port."""
        ...

    def cleanup_owned_subprocesses(self) -> int:
        """Terminates CrusorAI-owned child processes on resource exhaustion; returns count terminated."""
        ...


class RequirementEvidence(NamedTuple):
    requirement_id: str
    expected_behavior: str
    actual_behavior: str
    failed_acceptance_criterion: str
    required_correction: str
    workspace_revision: int = 0
    evaluator: str = "acceptance_tester"


class ProviderErrorMetadata(NamedTuple):
    status_code: int
    provider_id: str = "unknown"
    request_id: Optional[str] = None
    retry_after: Optional[float] = None
    error_category: str = "provider_error"
    raw_message: str = ""


class FailureClassification(NamedTuple):
    failure_class: str
    is_retryable: bool
    max_additional_retries: int  # Initial attempt + maximum additional retries
    recommended_strategy: str
    diagnostic_message: str
    metadata: Dict[str, Any]


class FailureClassifier:
    """Deterministic, rule-based failure classifier for tool, environment, and code errors."""

    @staticmethod
    def parse_retry_after(header_val: str) -> Optional[float]:
        """Parse numeric seconds or RFC 7231 / 2822 HTTP-date string."""
        if not header_val:
            return None
        header_val = header_val.strip()
        # 1. Numeric seconds
        if header_val.isdigit():
            return float(header_val)
        # 2. HTTP-Date (e.g. Wed, 21 Oct 2026 07:28:00 GMT)
        try:
            parsed_time = email.utils.parsedate_to_datetime(header_val)
            delay = (parsed_time.timestamp() - time.time())
            return max(0.0, delay)
        except Exception:
            return None

    @staticmethod
    def classify_error(
        tool_name: str,
        error_str: str,
        exit_code: Optional[int] = None,
        is_idempotent: bool = False,  # Peer review rule: Default must be False!
        attempt: int = 1,
        process_supervisor: Optional[ProcessSupervisor] = None,
        requirement_evidence: Optional[RequirementEvidence] = None,
        headers: Optional[Dict[str, str]] = None,
        provider_error: Optional[ProviderErrorMetadata] = None,
        current_workspace_revision: Optional[int] = None,
    ) -> FailureClassification:
        err = (error_str or "").strip()
        err_lower = err.lower()

        # 1. Logic or Specification Failure (Requires structured requirement-verification evidence)
        if requirement_evidence is not None:
            # Check for stale evidence: if workspace revision has advanced past verification, refuse stale remediation
            if current_workspace_revision is not None and requirement_evidence.workspace_revision < current_workspace_revision:
                return FailureClassification(
                    failure_class="stale_specification_evidence",
                    is_retryable=False,
                    max_additional_retries=0,
                    recommended_strategy="reverify_current_revision",
                    diagnostic_message=(
                        f"Specification evidence for '{requirement_evidence.requirement_id}' was verified against "
                        f"workspace revision {requirement_evidence.workspace_revision}, but current revision is "
                        f"{current_workspace_revision}. Re-verification required before applying remediation."
                    ),
                    metadata={
                        "stale": True,
                        "evidence_revision": requirement_evidence.workspace_revision,
                        "current_workspace_revision": current_workspace_revision,
                        "evaluator": requirement_evidence.evaluator,
                        "requirement_id": requirement_evidence.requirement_id,
                    },
                )

            return FailureClassification(
                failure_class="logic_or_specification_failure",
                is_retryable=True,
                max_additional_retries=2,
                recommended_strategy="requirement_delta_remediation",
                diagnostic_message=(
                    f"Specification mismatch on requirement '{requirement_evidence.requirement_id}': "
                    f"Expected: {requirement_evidence.expected_behavior}; Actual: {requirement_evidence.actual_behavior}. "
                    f"Action required: {requirement_evidence.required_correction}"
                ),
                metadata={
                    "requirement_id": requirement_evidence.requirement_id,
                    "criterion": requirement_evidence.failed_acceptance_criterion,
                    "requires_code_mutation": True,
                    "workspace_revision": requirement_evidence.workspace_revision,
                    "evaluator": requirement_evidence.evaluator,
                },
            )

        # 2. Structured Provider Error (Preferred when passed from LLM/HTTP client)
        if provider_error is not None:
            code = provider_error.status_code
            if code == 400:
                return FailureClassification(
                    failure_class="invalid_request_error",
                    is_retryable=False,
                    max_additional_retries=0,
                    recommended_strategy="diagnose_invalid_request",
                    diagnostic_message=f"Provider {provider_error.provider_id} rejected request as invalid (HTTP 400): {provider_error.raw_message or 'Invalid payload parameters'}.",
                    metadata={"status_code": 400, "provider_id": provider_error.provider_id, "request_id": provider_error.request_id, "category": "provider_error"},
                )
            elif code in (401, 403):
                return FailureClassification(
                    failure_class="provider_auth_failure",
                    is_retryable=False,
                    max_additional_retries=0,
                    recommended_strategy="fail_fast_auth",
                    diagnostic_message=f"Provider {provider_error.provider_id} authentication/authorization failed (HTTP {code}). Halting to prevent lockout.",
                    metadata={"status_code": code, "provider_id": provider_error.provider_id, "request_id": provider_error.request_id, "category": "provider_error"},
                )
            elif code == 429:
                return FailureClassification(
                    failure_class="provider_rate_limit",
                    is_retryable=True,
                    max_additional_retries=4,
                    recommended_strategy="respect_retry_after_or_backoff",
                    diagnostic_message=f"Provider {provider_error.provider_id} rate limit reached (HTTP 429). Applying backoff (Retry-After: {provider_error.retry_after or 0.0:.1f}s).",
                    metadata={"status_code": 429, "retry_after_seconds": provider_error.retry_after, "provider_id": provider_error.provider_id, "request_id": provider_error.request_id, "attempt": attempt, "category": "provider_error"},
                )
            elif 500 <= code <= 504:
                return FailureClassification(
                    failure_class="provider_transient_error",
                    is_retryable=True,
                    max_additional_retries=3,
                    recommended_strategy="exponential_backoff_jitter",
                    diagnostic_message=f"Provider {provider_error.provider_id} transient outage (HTTP {code}). Applying backoff with jitter.",
                    metadata={"status_code": code, "backoff_base_s": 2, "provider_id": provider_error.provider_id, "request_id": provider_error.request_id, "attempt": attempt, "category": "provider_error"},
                )

        # 3. Syntax / Indentation Errors
        if any(x in err_lower for x in ["syntaxerror", "indentationerror", "taberror", "unterminated string", "invalid syntax"]):
            return FailureClassification(
                failure_class="syntax_error",
                is_retryable=True,
                max_additional_retries=3,
                recommended_strategy="ast_diagnostic_feedback",
                diagnostic_message="Syntax validation failed. Provide exact line-level AST diagnostics to the model.",
                metadata={"requires_code_mutation": True},
            )

        # 4. Schema & Argument Errors (from SafeArgumentNormalizer)
        if any(x in err_lower for x in ["conflicting_arguments_error", "ambiguous_argument_error", "invalid_arguments_type", "missing required argument"]):
            return FailureClassification(
                failure_class="schema_argument_error",
                is_retryable=True,
                max_additional_retries=2,
                recommended_strategy="schema_feedback_prompt",
                diagnostic_message="Tool arguments invalid or conflicting. Provide JSON schema feedback.",
                metadata={"tool_name": tool_name},
            )

        # 5. Assertion & Unit Test Failures (Evaluated BEFORE HTTP codes to avoid matching test assertion values like '401 != 200')
        if "assertionerror" in err_lower or (exit_code is not None and exit_code > 0 and any(x in err_lower for x in ["failed", "failures=", "assert ", "failure:"])):
            return FailureClassification(
                failure_class="assertion_failure",
                is_retryable=True,
                max_additional_retries=3,
                recommended_strategy="alternating_mutation_lock",
                diagnostic_message="Unit test assertions failed. Lock test runner until model applies relevant code mutation.",
                metadata={"exit_code": exit_code, "requires_code_mutation": True},
            )

        # 6. Resource Exhaustion (Memory, Disk, Token Ceiling)
        # Memory Exhaustion (OOM)
        if "out of memory" in err_lower or "memoryerror" in err_lower or "oom-killer" in err_lower or "oomkiller" in err_lower:
            return FailureClassification(
                failure_class="memory_exhaustion",
                is_retryable=False,
                max_additional_retries=0,
                recommended_strategy="terminate_owned_subprocesses_and_release",
                diagnostic_message="Process memory exhausted (OOM). Terminate owned child processes and release caches.",
                metadata={"category": "resource_exhaustion"},
            )

        # Disk Exhaustion (Errno 28)
        if "no space left on device" in err_lower or "errno 28" in err_lower:
            return FailureClassification(
                failure_class="disk_exhaustion",
                is_retryable=True,
                max_additional_retries=1,
                recommended_strategy="drain_eligible_logs",
                diagnostic_message="Disk full (Errno 28). Drain eligible ephemeral debug logs and halt safely.",
                metadata={"category": "resource_exhaustion"},
            )

        # Hard Token Budget Ceiling
        if "token budget" in err_lower or "budget exceeded" in err_lower:
            return FailureClassification(
                failure_class="hard_token_budget_stop",
                is_retryable=False,
                max_additional_retries=0,
                recommended_strategy="hard_stop_grace_summary",
                diagnostic_message="Token budget ceiling reached. Cease tool execution and emit graceful completion summary.",
                metadata={},
            )

        # 7. HTTP Provider Errors (Refined Decoupling with Exact Code Preservation)
        # HTTP 400: Invalid Request (Fail-closed; 0 retries for identical request)
        if re.search(r"\b(?:http\s*)?400\b", err_lower) or "bad request" in err_lower or "invalid_request_error" in err_lower:
            return FailureClassification(
                failure_class="invalid_request_error",
                is_retryable=False,
                max_additional_retries=0,
                recommended_strategy="diagnose_invalid_request",
                diagnostic_message="Provider rejected request as invalid (HTTP 400). Do not retry identical payload; correct request parameters.",
                metadata={"status_code": 400, "category": "provider_error"},
            )

        # HTTP 401 / 403: Authentication / Permission failure (Fail-fast; 0 retries; Preserves 401 vs 403)
        if re.search(r"\b(?:http\s*)?(?:401|403)\b", err_lower) or "unauthorized" in err_lower or "forbidden" in err_lower:
            code = 403 if (re.search(r"\b403\b", err_lower) or "forbidden" in err_lower) else 401
            return FailureClassification(
                failure_class="provider_auth_failure",
                is_retryable=False,
                max_additional_retries=0,
                recommended_strategy="fail_fast_auth",
                diagnostic_message=f"Provider authentication or authorization failed (HTTP {code}). Halting to prevent credential lockout.",
                metadata={"status_code": code, "category": "provider_error"},
            )

        # HTTP 429: Rate Limit (Parses Retry-After numeric and date)
        if re.search(r"\b(?:http\s*)?429\b", err_lower) or "rate limit" in err_lower or "too many requests" in err_lower:
            retry_after_delay = None
            if headers:
                for k, v in headers.items():
                    if k.lower() == "retry-after":
                        retry_after_delay = FailureClassifier.parse_retry_after(v)
                        break
            return FailureClassification(
                failure_class="provider_rate_limit",
                is_retryable=True,
                max_additional_retries=4,
                recommended_strategy="respect_retry_after_or_backoff",
                diagnostic_message=f"Rate limit reached (HTTP 429). Applying backoff{f' (Retry-After: {retry_after_delay:.1f}s)' if retry_after_delay else ''}.",
                metadata={"status_code": 429, "retry_after_seconds": retry_after_delay, "attempt": attempt, "category": "provider_error"},
            )

        # HTTP 500 / 502 / 503 / 504: Transient Provider Outage
        code_match = re.search(r"\b(?:http\s*)?(50[0-4])\b", err_lower)
        if code_match or any(x in err_lower for x in ["internal server error", "bad gateway", "service unavailable", "gateway timeout"]):
            exact_5xx = int(code_match.group(1)) if code_match else 500
            return FailureClassification(
                failure_class="provider_transient_error",
                is_retryable=True,
                max_additional_retries=3,
                recommended_strategy="exponential_backoff_jitter",
                diagnostic_message=f"Transient provider error (HTTP {exact_5xx}). Apply bounded exponential backoff with jitter.",
                metadata={"status_code": exact_5xx, "backoff_base_s": 2, "attempt": attempt, "category": "provider_error"},
            )

        # 8. Port Binding / EADDRINUSE Collisions (Safe port detection: Never guess 8000!)
        if "eaddrinuse" in err_lower or "address already in use" in err_lower:
            port_match = re.search(r"(?:port\s*[:=]?\s*|:::|:)(\d{2,5})\b", err_lower)
            if not port_match:
                return FailureClassification(
                    failure_class="unknown_port_connection_failure",
                    is_retryable=False,
                    max_additional_retries=0,
                    recommended_strategy="fail_closed_unknown_port",
                    diagnostic_message="Port binding error (EADDRINUSE) occurred, but port number could not be determined. Refusing to guess port; manual inspection required.",
                    metadata={},
                )
            port = int(port_match.group(1))

            if process_supervisor:
                is_alive, is_owned = process_supervisor.inspect_port_owner(port)
                if is_alive and is_owned:
                    return FailureClassification(
                        failure_class="port_collision",
                        is_retryable=True,
                        max_additional_retries=1,
                        recommended_strategy="inspect_port_owner_or_allocate_dynamic",
                        diagnostic_message=f"CrusorAI-owned process already occupies port {port}. Inspect process or allocate dynamic port.",
                        metadata={"port": port, "is_owned": True},
                    )
                else:
                    return FailureClassification(
                        failure_class="unowned_service_collision",
                        is_retryable=False,
                        max_additional_retries=0,
                        recommended_strategy="unowned_process_fail_closed",
                        diagnostic_message=f"Port {port} is occupied by an external/foreign process. Automatic override prohibited.",
                        metadata={"port": port, "is_owned": False},
                    )
            else:
                return FailureClassification(
                    failure_class="port_collision",
                    is_retryable=False,
                    max_additional_retries=0,
                    recommended_strategy="inspect_port_owner_or_allocate_dynamic",
                    diagnostic_message=f"Port {port} in use (EADDRINUSE). Inspect port owner before dynamic allocation.",
                    metadata={"port": port},
                )

        # 9. Connection Refused (Client-side Process-Aware Table; Safe port detection)
        if "connectionrefused" in err_lower or "connection refused" in err_lower or "econnrefused" in err_lower:
            port_match = re.search(r"(?:port\s*[:=]?\s*|:::|:)(\d{2,5})\b", err_lower)
            if not port_match:
                return FailureClassification(
                    failure_class="unknown_port_connection_failure",
                    is_retryable=False,
                    max_additional_retries=0,
                    recommended_strategy="fail_closed_unknown_port",
                    diagnostic_message="Connection refused detected, but port number could not be determined. Refusing to guess port; manual inspection required.",
                    metadata={},
                )
            port = int(port_match.group(1))

            if process_supervisor:
                is_alive, is_owned = process_supervisor.inspect_port_owner(port)
                if not is_alive and is_owned:
                    return FailureClassification(
                        failure_class="service_not_running",
                        is_retryable=True,
                        max_additional_retries=1,
                        recommended_strategy="relaunch_owned_service",
                        diagnostic_message=f"CrusorAI-owned service on port {port} is dead. Safe to execute single controlled relaunch.",
                        metadata={"port": port, "is_owned": True},
                    )
                elif is_alive and is_owned:
                    return FailureClassification(
                        failure_class="network_warmup_delay",
                        is_retryable=True,
                        max_additional_retries=2,
                        recommended_strategy="bounded_warmup_poll",
                        diagnostic_message=f"CrusorAI-owned service on port {port} is alive but warming up. Polling readiness.",
                        metadata={"port": port, "is_owned": True},
                    )
                elif is_alive and not is_owned:
                    # Foreign process alive on port -> Strictly fail-closed!
                    return FailureClassification(
                        failure_class="unowned_service_collision",
                        is_retryable=False,
                        max_additional_retries=0,
                        recommended_strategy="unowned_process_fail_closed",
                        diagnostic_message=f"Foreign process detected on port {port}. CrusorAI refuses to restart or terminate unowned processes.",
                        metadata={"port": port, "is_owned": False},
                    )
                else:
                    return FailureClassification(
                        failure_class="unowned_service_collision",
                        is_retryable=False,
                        max_additional_retries=0,
                        recommended_strategy="unowned_process_fail_closed",
                        diagnostic_message=f"Unknown process state on port {port}. Manual investigation required.",
                        metadata={"port": port, "is_owned": False},
                    )
            else:
                return FailureClassification(
                    failure_class="service_not_running",
                    is_retryable=False,
                    max_additional_retries=0,
                    recommended_strategy="no_supervisor_fail_closed",
                    diagnostic_message=f"Connection refused on port {port} without process supervisor. Cannot verify ownership.",
                    metadata={"port": port},
                )

        # 9. Flaky Network Timeouts (Idempotency Enforced)
        if any(x in err_lower for x in ["timeouterror", "timed out", "connection reset", "socket hang up"]):
            can_retry = is_idempotent and (attempt <= 2)
            return FailureClassification(
                failure_class="flaky_network_timeout",
                is_retryable=can_retry,
                max_additional_retries=2 if can_retry else 0,
                recommended_strategy="bounded_idempotent_retry" if can_retry else "fail_closed_non_idempotent",
                diagnostic_message=(
                    "Network timeout occurred on idempotent operation. Executing bounded retry."
                    if can_retry
                    else "Timeout occurred on non-idempotent or exhausted operation. Blind retries forbidden."
                ),
                metadata={"attempt": attempt, "is_idempotent": is_idempotent},
            )

        # 10. Permission & Safety Denials
        if any(x in err_lower for x in ["permissionerror", "eacces", "permission denied", "access is denied", "safety"]):
            return FailureClassification(
                failure_class="permission_or_safety_denial",
                is_retryable=False,
                max_additional_retries=0,
                recommended_strategy="audit_trail_fail_closed",
                diagnostic_message="Permission or safety boundary triggered. Operation denied.",
                metadata={"category": "permission_error"},
            )

        # Fallback: Unclassified
        return FailureClassification(
            failure_class="unclassified_error",
            is_retryable=False,
            max_additional_retries=0,
            recommended_strategy="diagnose_and_report",
            diagnostic_message=f"Unhandled tool failure: {err[:150]}",
            metadata={"exit_code": exit_code},
        )


class GlobalRecoveryBudgetTracker:
    """Thread-safe, atomic, session-scoped recovery budget governor."""

    def __init__(
        self,
        session_id: str,
        max_total_recovery_attempts: int = 8,
        max_recovery_wall_time_seconds: float = 180.0,
        max_identical_failure_repeats: int = 2,
    ) -> None:
        self.session_id = session_id
        self.max_total_attempts = max_total_recovery_attempts
        self.max_wall_time = max_recovery_wall_time_seconds
        self.max_identical_repeats = max_identical_failure_repeats

        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._total_attempts = 0
        self._failure_history: List[str] = []

    def try_reserve_recovery_attempt(self, failure_fingerprint: str) -> tuple[bool, Optional[str]]:
        """Atomically checks ceilings and reserves an attempt under a single lock."""
        with self._lock:
            # 1. Total attempt limit
            if self._total_attempts >= self.max_total_attempts:
                return False, f"GLOBAL_RECOVERY_LIMIT_EXCEEDED: Maximum recovery attempts ({self.max_total_attempts}) reached for session {self.session_id}."

            # 2. Wall-clock time ceiling
            elapsed = time.monotonic() - self._start_time
            if elapsed >= self.max_wall_time:
                return False, f"GLOBAL_RECOVERY_TIMEOUT: Recovery wall time ({elapsed:.1f}s) exceeded limit of {self.max_wall_time}s for session {self.session_id}."

            # 3. Identical failure loop breaker
            recent = self._failure_history[-self.max_identical_repeats:]
            if len(recent) == self.max_identical_repeats and all(f == failure_fingerprint for f in recent):
                return False, f"DOOM_LOOP_TERMINATION: Identical failure '{failure_fingerprint}' repeated {self.max_identical_repeats} consecutive times."

            # Successfully reserve
            self._total_attempts += 1
            self._failure_history.append(failure_fingerprint)
            return True, None

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "total_attempts": self._total_attempts,
                "elapsed_seconds": time.monotonic() - self._start_time,
                "history_length": len(self._failure_history),
            }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize tracker state for persistence across LangGraph turns and session resumes."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "max_total_attempts": self.max_total_attempts,
                "max_wall_time": self.max_wall_time,
                "max_identical_repeats": self.max_identical_repeats,
                "total_attempts": self._total_attempts,
                "elapsed_seconds": time.monotonic() - self._start_time,
                "failure_history": list(self._failure_history),
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GlobalRecoveryBudgetTracker:
        """Restore tracker state without resetting counters or timers."""
        tracker = cls(
            session_id=str(data.get("session_id", "default")),
            max_total_recovery_attempts=int(data.get("max_total_attempts", 8)),
            max_recovery_wall_time_seconds=float(data.get("max_wall_time", 180.0)),
            max_identical_failure_repeats=int(data.get("max_identical_repeats", 2)),
        )
        tracker._total_attempts = int(data.get("total_attempts", 0))
        tracker._failure_history = list(data.get("failure_history", []))
        elapsed = float(data.get("elapsed_seconds", 0.0))
        tracker._start_time = time.monotonic() - elapsed
        return tracker

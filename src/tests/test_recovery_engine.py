"""Comprehensive Unit Tests for ARRE Recovery Engine (CrusorAI 2.1 - Phase 2).

Verifies:
1. 15-Class Failure Taxonomy (Specification, AST, Schemas, Provider Tiers, Process Liveness, Resources).
2. Default Idempotency Invariant (Strict False default; non-idempotent timeout fail-closed).
3. Process-Aware Connection & Port Collision Decision Tables (CrusorAI-owned vs Foreign vs Unsupervised).
4. HTTP Retry-After Parsing (Numeric seconds & RFC 7231 HTTP-date).
5. Provider Error Decoupling (HTTP 400 vs 401/403 vs 429 vs 5xx).
6. Atomic Global Recovery Budget Tracker (Thread-safety, 8-attempt ceiling, 180s wall time, doom-loop breaker).
"""
import concurrent.futures
import time
from typing import NamedTuple
import pytest

from src.runtime.recovery_engine import (
    FailureClassifier,
    GlobalRecoveryBudgetTracker,
    RequirementEvidence,
)


class MockSupervisor:
    """Mock process supervisor tracking port liveness and ownership."""

    def __init__(self, ports_state: dict[int, tuple[bool, bool]]):
        # port -> (is_alive, is_owned_by_crusorai)
        self.ports_state = ports_state

    def inspect_port_owner(self, port: int) -> tuple[bool, bool]:
        return self.ports_state.get(port, (False, False))


# ==============================================================================
# 1. SPECIFICATION & LOGIC FAILURES
# ==============================================================================

def test_specification_failure_with_structured_evidence():
    evidence = RequirementEvidence(
        requirement_id="REQ-AUTH-042",
        expected_behavior="Return 403 Forbidden on expired session token",
        actual_behavior="Returned 200 OK with cached session",
        failed_acceptance_criterion="AC-3: Invalidate session on token expiry",
        required_correction="Add token expiry timestamp check to AuthMiddleware.validate()",
    )
    res = FailureClassifier.classify_error(
        tool_name="verify_acceptance_criteria",
        error_str="Verification mismatch against user specification",
        requirement_evidence=evidence,
    )
    assert res.failure_class == "logic_or_specification_failure"
    assert res.is_retryable is True
    assert res.max_additional_retries == 2
    assert res.recommended_strategy == "requirement_delta_remediation"
    assert "REQ-AUTH-042" in res.diagnostic_message
    assert res.metadata["requires_code_mutation"] is True


def test_no_specification_failure_declared_without_evidence():
    # Without structured evidence, an arbitrary error is not classified as spec failure
    res = FailureClassifier.classify_error("terminal", "Process finished with unexpected output")
    assert res.failure_class != "logic_or_specification_failure"


# ==============================================================================
# 2. SYNTAX & SCHEMA ERRORS
# ==============================================================================

def test_syntax_error_ast_diagnostic():
    res = FailureClassifier.classify_error("edit_file", "SyntaxError: invalid syntax (server.py, line 42)")
    assert res.failure_class == "syntax_error"
    assert res.is_retryable is True
    assert res.recommended_strategy == "ast_diagnostic_feedback"
    assert res.metadata.get("requires_code_mutation") is True


def test_schema_argument_error():
    res = FailureClassifier.classify_error("read_file", "conflicting_arguments_error: both path and file_path provided")
    assert res.failure_class == "schema_argument_error"
    assert res.is_retryable is True
    assert res.recommended_strategy == "schema_feedback_prompt"


# ==============================================================================
# 3. HTTP PROVIDER ERROR DECOUPLING
# ==============================================================================

def test_http_400_invalid_request_fails_closed_zero_retries():
    res = FailureClassifier.classify_error("llm_call", "Error: 400 Bad Request - 'temperature' must be <= 2.0")
    assert res.failure_class == "invalid_request_error"
    assert res.is_retryable is False
    assert res.max_additional_retries == 0
    assert res.recommended_strategy == "diagnose_invalid_request"


def test_http_401_403_auth_failure_fails_fast():
    res = FailureClassifier.classify_error("llm_call", "Error code 401: Unauthorized - Invalid API key")
    assert res.failure_class == "provider_auth_failure"
    assert res.is_retryable is False
    assert res.max_additional_retries == 0
    assert res.recommended_strategy == "fail_fast_auth"


def test_http_429_numeric_retry_after():
    headers = {"Retry-After": "45"}
    res = FailureClassifier.classify_error(
        "llm_call",
        "Error code 429: Rate limit reached for requests",
        attempt=1,
        headers=headers,
    )
    assert res.failure_class == "provider_rate_limit"
    assert res.is_retryable is True
    assert res.max_additional_retries == 4
    assert res.metadata["retry_after_seconds"] == 45.0
    assert "45.0s" in res.diagnostic_message


def test_http_429_http_date_retry_after():
    # 60 seconds into the future
    future_time = time.time() + 60.0
    date_str = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(future_time))
    headers = {"Retry-After": date_str}
    res = FailureClassifier.classify_error(
        "llm_call",
        "HTTP 429: Too Many Requests",
        attempt=1,
        headers=headers,
    )
    assert res.failure_class == "provider_rate_limit"
    assert res.is_retryable is True
    # Parsed delay should be close to 60s
    assert 55.0 <= res.metadata["retry_after_seconds"] <= 65.0


def test_http_5xx_transient_error_backoff():
    res = FailureClassifier.classify_error("llm_call", "503 Service Unavailable: Overloaded", attempt=2)
    assert res.failure_class == "provider_transient_error"
    assert res.is_retryable is True
    assert res.max_additional_retries == 3
    assert res.recommended_strategy == "exponential_backoff_jitter"


# ==============================================================================
# 4. PROCESS-AWARE CONNECTION & PORT LIVENESS TABLE
# ==============================================================================

def test_connection_refused_owned_dead_relaunch():
    supervisor = MockSupervisor({8000: (False, True)})  # Dead, CrusorAI-owned
    res = FailureClassifier.classify_error(
        "http_client",
        "ConnectionRefusedError: [Errno 111] Connection refused on port 8000",
        process_supervisor=supervisor,
    )
    assert res.failure_class == "service_not_running"
    assert res.is_retryable is True
    assert res.max_additional_retries == 1
    assert res.recommended_strategy == "relaunch_owned_service"
    assert res.metadata["is_owned"] is True


def test_connection_refused_owned_alive_warmup():
    supervisor = MockSupervisor({8000: (True, True)})  # Alive, CrusorAI-owned
    res = FailureClassifier.classify_error(
        "http_client",
        "ConnectionRefusedError: Connection refused :::8000",
        process_supervisor=supervisor,
    )
    assert res.failure_class == "network_warmup_delay"
    assert res.is_retryable is True
    assert res.max_additional_retries == 2
    assert res.recommended_strategy == "bounded_warmup_poll"
    assert res.metadata["is_owned"] is True


def test_connection_refused_foreign_alive_fails_closed():
    supervisor = MockSupervisor({8000: (True, False)})  # Alive, Foreign / Unowned
    res = FailureClassifier.classify_error(
        "http_client",
        "ConnectionRefusedError: Connection refused on port 8000",
        process_supervisor=supervisor,
    )
    assert res.failure_class == "unowned_service_collision"
    assert res.is_retryable is False
    assert res.max_additional_retries == 0
    assert res.recommended_strategy == "unowned_process_fail_closed"
    assert res.metadata["is_owned"] is False


def test_connection_refused_no_supervisor_fails_closed():
    res = FailureClassifier.classify_error(
        "http_client",
        "ConnectionRefusedError: Connection refused on port 8000",
        process_supervisor=None,
    )
    assert res.failure_class == "service_not_running"
    assert res.is_retryable is False
    assert res.max_additional_retries == 0
    assert res.recommended_strategy == "no_supervisor_fail_closed"


def test_port_collision_eaddrinuse_with_and_without_supervisor():
    # Without supervisor -> inspect port owner before dynamic allocation
    res = FailureClassifier.classify_error("terminal", "Error: listen EADDRINUSE: address already in use :::8000")
    assert res.failure_class == "port_collision"
    assert res.metadata.get("port") == 8000
    assert res.recommended_strategy == "inspect_port_owner_or_allocate_dynamic"

    # With supervisor owning port
    supervisor = MockSupervisor({8000: (True, True)})
    res_owned = FailureClassifier.classify_error(
        "terminal",
        "Error: listen EADDRINUSE: address already in use :::8000",
        process_supervisor=supervisor,
    )
    assert res_owned.failure_class == "port_collision"
    assert res_owned.is_retryable is True
    assert res_owned.metadata["is_owned"] is True

    # With supervisor discovering foreign owner -> fail closed
    supervisor_foreign = MockSupervisor({8000: (True, False)})
    res_foreign = FailureClassifier.classify_error(
        "terminal",
        "Error: listen EADDRINUSE: address already in use :::8000",
        process_supervisor=supervisor_foreign,
    )
    assert res_foreign.failure_class == "unowned_service_collision"
    assert res_foreign.is_retryable is False


# ==============================================================================
# 5. IDEMPOTENCY & NETWORK TIMEOUTS
# ==============================================================================

def test_default_idempotency_is_strictly_false():
    # Calling classify_error without specifying is_idempotent defaults to False
    res = FailureClassifier.classify_error("terminal", "TimeoutError: Operation timed out", attempt=1)
    assert res.failure_class == "flaky_network_timeout"
    assert res.is_retryable is False
    assert res.recommended_strategy == "fail_closed_non_idempotent"


def test_idempotent_network_timeout_bounded_retry():
    res = FailureClassifier.classify_error(
        "http_get",
        "TimeoutError: The operation timed out",
        is_idempotent=True,
        attempt=1,
    )
    assert res.failure_class == "flaky_network_timeout"
    assert res.is_retryable is True
    assert res.max_additional_retries == 2
    assert res.recommended_strategy == "bounded_idempotent_retry"


def test_non_idempotent_network_timeout_fails_closed():
    res = FailureClassifier.classify_error(
        "execute_payment",
        "TimeoutError: The operation timed out",
        is_idempotent=False,
        attempt=1,
    )
    assert res.failure_class == "flaky_network_timeout"
    assert res.is_retryable is False
    assert res.recommended_strategy == "fail_closed_non_idempotent"


# ==============================================================================
# 6. RESOURCE EXHAUSTION (MEMORY, DISK, TOKEN BUDGET)
# ==============================================================================

def test_memory_exhaustion_classification():
    res = FailureClassifier.classify_error("terminal", "MemoryError: Out of memory (oom-killer triggered)")
    assert res.failure_class == "memory_exhaustion"
    assert res.is_retryable is False
    assert res.max_additional_retries == 0
    assert res.recommended_strategy == "terminate_owned_subprocesses_and_release"


def test_disk_exhaustion_classification():
    res = FailureClassifier.classify_error("write_file", "OSError: [Errno 28] No space left on device")
    assert res.failure_class == "disk_exhaustion"
    assert res.is_retryable is True
    assert res.max_additional_retries == 1
    assert res.recommended_strategy == "drain_eligible_logs"


def test_hard_token_budget_stop():
    res = FailureClassifier.classify_error("llm_call", "Hard token budget exceeded: ceiling reached for session")
    assert res.failure_class == "hard_token_budget_stop"
    assert res.is_retryable is False
    assert res.recommended_strategy == "hard_stop_grace_summary"


# ==============================================================================
# 7. ASSERTIONS & PERMISSIONS
# ==============================================================================

def test_assertion_failure_mutation_lock():
    # Must NOT be misclassified as provider_auth_failure even if 401 is in the assertion string
    res = FailureClassifier.classify_error(
        "terminal",
        "FAILED tests/test_api.py::test_login - AssertionError: 401 != 200",
        exit_code=1,
    )
    assert res.failure_class == "assertion_failure"
    assert res.is_retryable is True
    assert res.max_additional_retries == 3
    assert res.recommended_strategy == "alternating_mutation_lock"
    assert res.metadata["requires_code_mutation"] is True


def test_permission_error_fails_closed():
    res = FailureClassifier.classify_error("write_file", "PermissionError: [Errno 13] Permission denied: '/etc/hosts'")
    assert res.failure_class == "permission_or_safety_denial"
    assert res.is_retryable is False
    assert res.max_additional_retries == 0
    assert res.recommended_strategy == "audit_trail_fail_closed"


# ==============================================================================
# 8. GLOBAL RECOVERY BUDGET TRACKER (ATOMIC RESERVATION & CEILINGS)
# ==============================================================================

def test_global_budget_atomic_reservation_ceiling():
    tracker = GlobalRecoveryBudgetTracker(session_id="test-session-1", max_total_recovery_attempts=3)

    # Attempts 1, 2, 3 should succeed
    for i in range(3):
        permitted, reason = tracker.try_reserve_recovery_attempt(f"failure_type_{i}")
        assert permitted is True
        assert reason is None

    # Attempt 4 must be rejected atomically
    permitted, reason = tracker.try_reserve_recovery_attempt("failure_type_4")
    assert permitted is False
    assert "GLOBAL_RECOVERY_LIMIT_EXCEEDED" in reason
    assert tracker.get_stats()["total_attempts"] == 3


def test_global_budget_wall_time_timeout():
    tracker = GlobalRecoveryBudgetTracker(
        session_id="test-session-2",
        max_total_recovery_attempts=10,
        max_recovery_wall_time_seconds=0.05,  # 50ms timeout
    )
    # First attempt within budget
    permitted, _ = tracker.try_reserve_recovery_attempt("first_attempt")
    assert permitted is True

    # Sleep past wall-time (100ms comfortably exceeds 50ms across Windows timer resolutions)
    time.sleep(0.1)

    permitted, reason = tracker.try_reserve_recovery_attempt("second_attempt")
    assert permitted is False
    assert "GLOBAL_RECOVERY_TIMEOUT" in reason


def test_global_budget_doom_loop_identical_repeats():
    tracker = GlobalRecoveryBudgetTracker(
        session_id="test-session-3",
        max_total_recovery_attempts=10,
        max_identical_failure_repeats=2,
    )
    # First identical failure
    p1, _ = tracker.try_reserve_recovery_attempt("syntax_error:line_42")
    assert p1 is True

    # Second identical failure
    p2, _ = tracker.try_reserve_recovery_attempt("syntax_error:line_42")
    assert p2 is True

    # Third identical failure -> Doom loop triggered!
    p3, reason = tracker.try_reserve_recovery_attempt("syntax_error:line_42")
    assert p3 is False
    assert "DOOM_LOOP_TERMINATION" in reason


def test_global_budget_concurrent_atomic_reservations():
    # Enforce atomic concurrency check: 20 threads attempting to reserve against ceiling of 8
    max_budget = 8
    tracker = GlobalRecoveryBudgetTracker(session_id="test-session-concurrent", max_total_recovery_attempts=max_budget)

    def attempt_reservation(worker_id: int):
        return tracker.try_reserve_recovery_attempt(f"failure_from_worker_{worker_id}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_reservation, i) for i in range(25)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    granted = sum(1 for permitted, _ in results if permitted is True)
    denied = sum(1 for permitted, _ in results if permitted is False)

    # Exactly max_budget (8) reservations must be granted, no more, no less
    assert granted == max_budget
    assert denied == (25 - max_budget)
    assert tracker.get_stats()["total_attempts"] == max_budget


def test_global_budget_session_isolation():
    tracker_a = GlobalRecoveryBudgetTracker(session_id="session-A", max_total_recovery_attempts=2)
    tracker_b = GlobalRecoveryBudgetTracker(session_id="session-B", max_total_recovery_attempts=5)

    tracker_a.try_reserve_recovery_attempt("err_1")
    tracker_a.try_reserve_recovery_attempt("err_2")
    p_a3, _ = tracker_a.try_reserve_recovery_attempt("err_3")
    assert p_a3 is False  # A is exhausted

    # B should remain completely independent
    p_b1, _ = tracker_b.try_reserve_recovery_attempt("err_1")
    assert p_b1 is True
    assert tracker_b.get_stats()["total_attempts"] == 1

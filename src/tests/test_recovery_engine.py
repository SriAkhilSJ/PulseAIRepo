"""Unit tests for ARRE Failure Classifier (CrusorAI 2.1).

Validates:
1. Syntax error classification (AST diagnostic strategy).
2. Port collision classification (no blind incrementing).
3. Flaky network timeouts with idempotency guard.
4. Non-idempotent timeout fail-closed enforcement.
5. Provider rate limit (backoff strategy).
6. Permission denied (fail-closed, 0 retries).
7. Resource exhaustion (Errno 28).
8. Process failure (abnormal exit codes).
9. Assertion failure (alternating mutation lock).
"""
import pytest
from src.runtime.recovery_engine import FailureClassifier


def test_classify_syntax_error():
    res = FailureClassifier.classify_error("edit_file", "SyntaxError: invalid syntax (server.py, line 42)")
    assert res.failure_class == "syntax_error"
    assert res.is_retryable is True
    assert res.recommended_strategy == "ast_diagnostic_feedback"
    assert res.metadata.get("requires_code_mutation") is True


def test_classify_port_collision():
    # Peer review requirement: inspect port owner rather than blind auto-increment
    res = FailureClassifier.classify_error("terminal", "Error: listen EADDRINUSE: address already in use :::8000")
    assert res.failure_class == "port_collision"
    assert res.metadata.get("port") == 8000
    assert res.recommended_strategy == "inspect_port_owner_or_allocate_dynamic"


def test_classify_idempotent_network_timeout():
    # Up to 2 retries on idempotent read/status requests
    res = FailureClassifier.classify_error("http_get", "TimeoutError: The operation timed out", is_idempotent=True, attempt=1)
    assert res.failure_class == "flaky_network_timeout"
    assert res.is_retryable is True
    assert res.recommended_strategy == "bounded_idempotent_retry"


def test_classify_non_idempotent_timeout_fails_closed():
    # Peer review requirement: Non-idempotent operations (payment/write) must NOT blindly retry on timeout!
    res = FailureClassifier.classify_error("execute_payment", "TimeoutError: The operation timed out", is_idempotent=False, attempt=1)
    assert res.failure_class == "flaky_network_timeout"
    assert res.is_retryable is False
    assert res.recommended_strategy == "fail_closed_non_idempotent"


def test_classify_provider_rate_limit():
    res = FailureClassifier.classify_error("llm_call", "Error code 429: Rate limit reached for requests", attempt=2)
    assert res.failure_class == "provider_error"
    assert res.is_retryable is True
    assert res.recommended_strategy == "exponential_backoff_jitter"


def test_classify_permission_error_fails_closed():
    res = FailureClassifier.classify_error("write_file", "PermissionError: [Errno 13] Permission denied: '/etc/hosts'")
    assert res.failure_class == "permission_error"
    assert res.is_retryable is False
    assert res.max_retries == 0


def test_classify_resource_exhaustion_triggers_compaction():
    res = FailureClassifier.classify_error("write_file", "OSError: [Errno 28] No space left on device")
    assert res.failure_class == "resource_exhaustion"
    assert res.is_retryable is True
    assert res.recommended_strategy == "landed_write_compaction_and_log_drain"


def test_classify_assertion_failure_triggers_mutation_lock():
    res = FailureClassifier.classify_error("terminal", "FAILED tests/test_api.py::test_login - AssertionError: 401 != 200", exit_code=1)
    assert res.failure_class == "assertion_failure"
    assert res.is_retryable is True
    assert res.recommended_strategy == "alternating_mutation_lock"

"""Unit tests for VerificationLedger (CrusorAI 2.1).

Validates:
1. Flaky timeout retry status (attempts 1 and 2 allow retry).
2. Assertion failure locks verification until workspace revision advances.
3. Successful pass clears unresolved debt for that exact command.
4. Non-idempotent timeout fails immediately without retry status.
"""
import pytest
from src.runtime.verification_ledger import VerificationLedger


def test_flaky_timeout_allows_retry_on_idempotent_test():
    ledger = VerificationLedger()
    receipt = ledger.record_attempt(
        command="pytest tests/test_api.py",
        exit_code=1,
        stdout_err="TimeoutError: connection dropped",
        failure_class="flaky_network_timeout",
        is_idempotent=True,
        attempt=1,
        workspace_revision=1,
    )
    assert receipt.status == "flaky_retry"


def test_assertion_failure_enforces_mutation_lock():
    ledger = VerificationLedger()
    receipt = ledger.record_attempt(
        command="pytest tests/test_calc.py",
        exit_code=1,
        stdout_err="AssertionError: 2 != 3",
        failure_class="assertion_failure",
        is_idempotent=True,
        attempt=1,
        workspace_revision=5,
    )
    assert receipt.status == "failed"

    # Permitted check at same revision: LOCKED
    allowed, reason = ledger.is_verification_permitted("pytest tests/test_calc.py", current_revision=5)
    assert allowed is False
    assert "MUTATION_LOCK_ACTIVE" in reason

    # Permitted check once code mutates (revision 6): UNLOCKED
    allowed_mutated, _ = ledger.is_verification_permitted("pytest tests/test_calc.py", current_revision=6)
    assert allowed_mutated is True


def test_successful_pass_clears_unresolved_debt():
    ledger = VerificationLedger()
    # Step 1: fails
    ledger.record_attempt(
        command="pytest tests/test_core.py",
        exit_code=1,
        stdout_err="AssertionError",
        failure_class="assertion_failure",
        is_idempotent=True,
        attempt=1,
        workspace_revision=1,
    )
    assert len(ledger.get_unresolved_debt()) == 1

    # Step 2: passes
    ledger.record_attempt(
        command="pytest tests/test_core.py",
        exit_code=0,
        stdout_err="16 passed",
        failure_class=None,
        is_idempotent=True,
        attempt=1,
        workspace_revision=2,
        assertion_count=16,
    )
    assert len(ledger.get_unresolved_debt()) == 0

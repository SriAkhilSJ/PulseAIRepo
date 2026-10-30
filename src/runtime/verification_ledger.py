"""Verification Ledger & Flaky-Test Recovery Protocol for CrusorAI 2.1.

Invariants:
1. Multi-receipt verification: Tracks command, git tree hash, untracked files hash, dependency lockfile, and assertion counts.
2. Flaky-aware bounded retries: Network/socket timeouts on idempotent commands allow up to 2 additional retries.
3. Strict mutation lock: Assertion failures (AssertionError / failed test suite) strictly require a workspace mutation
   before re-running.
4. Non-idempotent protection: Commands not marked idempotent fail closed on timeout without blind retries.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, NamedTuple, Optional


class VerificationReceipt(NamedTuple):
    receipt_id: str
    command: str
    exit_code: int
    is_idempotent: bool
    attempt: int
    workspace_revision: int
    untracked_hash: str
    dependency_hash: str
    status: str  # "verified", "failed", "flaky_retry"
    failure_class: Optional[str] = None
    assertion_count: int = 0
    diagnostic: str = ""


class VerificationLedger:
    def __init__(self) -> None:
        self.receipts: List[VerificationReceipt] = []
        self._unresolved_failures: Dict[str, VerificationReceipt] = {}

    def record_attempt(
        self,
        command: str,
        exit_code: int,
        stdout_err: str,
        failure_class: Optional[str],
        is_idempotent: bool,
        attempt: int,
        workspace_revision: int,
        untracked_hash: str = "clean",
        dependency_hash: str = "clean",
        assertion_count: int = 0,
    ) -> VerificationReceipt:
        receipt_id = hashlib.sha256(
            f"{command}:{workspace_revision}:{attempt}:{exit_code}".encode()
        ).hexdigest()[:16]

        if exit_code == 0:
            status = "verified"
            # Clear any unresolved debt for this exact command
            self._unresolved_failures.pop(command, None)
        elif failure_class == "flaky_network_timeout" and is_idempotent and attempt <= 2:
            status = "flaky_retry"
        else:
            status = "failed"
            # Unresolved failure locks future tests until workspace_revision advances
            self._unresolved_failures[command] = VerificationReceipt(
                receipt_id=receipt_id,
                command=command,
                exit_code=exit_code,
                is_idempotent=is_idempotent,
                attempt=attempt,
                workspace_revision=workspace_revision,
                untracked_hash=untracked_hash,
                dependency_hash=dependency_hash,
                status=status,
                failure_class=failure_class,
                assertion_count=assertion_count,
                diagnostic=stdout_err[:200],
            )

        receipt = VerificationReceipt(
            receipt_id=receipt_id,
            command=command,
            exit_code=exit_code,
            is_idempotent=is_idempotent,
            attempt=attempt,
            workspace_revision=workspace_revision,
            untracked_hash=untracked_hash,
            dependency_hash=dependency_hash,
            status=status,
            failure_class=failure_class,
            assertion_count=assertion_count,
            diagnostic=stdout_err[:200],
        )
        self.receipts.append(receipt)
        return receipt

    def is_verification_permitted(self, command: str, current_revision: int) -> tuple[bool, Optional[str]]:
        """Check if test execution is permitted or locked by verification debt."""
        if command not in self._unresolved_failures:
            return True, None

        failed_receipt = self._unresolved_failures[command]

        # Peer review rule: If failure was assertion failure, require workspace revision mutation!
        if failed_receipt.failure_class == "assertion_failure" and current_revision <= failed_receipt.workspace_revision:
            return False, (
                f"MUTATION_LOCK_ACTIVE: Command '{command}' failed with assertion failure at revision {failed_receipt.workspace_revision}. "
                f"A relevant file mutation is required before re-executing this test."
            )

        return True, None

    def get_unresolved_debt(self) -> List[VerificationReceipt]:
        return list(self._unresolved_failures.values())

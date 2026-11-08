"""
src/verification/completion_gate.py - Independent Completion Gate.

Phase 11.7: Independent Verification & Quality Assurance.
Enforces strict gate policies controlling the final task completion verdict.
The implementation orchestrator cannot override this verdict.
Evaluates:
- Acceptance criteria fulfillment
- Test execution pass rate and test integrity
- Unresolved CRITICAL or HIGH security findings
- Regression prevention status
- Workspace hash matching
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.models import (
    FindingSeverity,
    FindingStatus,
    RequirementVerificationRecord,
    RequirementVerificationStatus,
    VerificationFinding,
    VerificationVerdict,
)

log = logging.getLogger("crusor.verification.gate")


class IndependentCompletionGate:
    """
    Authoritative completion gate that determines the independent verification verdict.
    """

    def evaluate_gate(
        self,
        requirements: List[RequirementVerificationRecord],
        findings: List[VerificationFinding],
        test_results: Dict[str, Any],
        regression_status: str,
        workspace_hash_matches: bool = True,
        unexecutable_checks: Optional[List[str]] = None,
    ) -> Tuple[VerificationVerdict, str]:
        """
        Determines the final VerificationVerdict and rationale based on evidence.
        """
        unexecutable_checks = unexecutable_checks or []

        # 1. Check workspace integrity: if hash does not match, fail or block
        if not workspace_hash_matches:
            return (
                VerificationVerdict.FAILED,
                "Workspace files were modified after verification snapshot; hash mismatch detected.",
            )

        # 2. Check for unresolved CRITICAL or HIGH severity findings
        unresolved_blocking = [
            f for f in findings
            if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}
            and f.status in {FindingStatus.OPEN, FindingStatus.CONFIRMED, FindingStatus.IN_PROGRESS, FindingStatus.RETEST_REQUIRED}
        ]
        if unresolved_blocking:
            return (
                VerificationVerdict.FAILED,
                f"Blocked by {len(unresolved_blocking)} unresolved CRITICAL/HIGH defect(s): "
                f"{', '.join([f.finding_id + ' (' + f.title + ')' for f in unresolved_blocking[:2]])}",
            )

        # 3. Check regression status
        if regression_status in {"REGRESSION_DETECTED", "FAILED"}:
            return (
                VerificationVerdict.FAILED,
                f"Regression prevention gate failed with status '{regression_status}'.",
            )

        # 4. Check test execution results
        failed_tests = test_results.get("failed_count", 0)
        if failed_tests > 0:
            return (
                VerificationVerdict.FAILED,
                f"Independent test suite recorded {failed_tests} failure(s).",
            )

        # 5. Check requirement satisfaction. Optional analyzer suggestions are
        # NOT_APPLICABLE by construction and cannot block a user-scoped task.
        mandatory_reqs = [
            r for r in requirements
            if r.status != RequirementVerificationStatus.NOT_APPLICABLE
        ]
        total_reqs = len(mandatory_reqs)
        if total_reqs == 0:
            return (
                VerificationVerdict.NOT_TESTED,
                "No approved requirements were evaluated.",
            )

        verified_reqs = [r for r in mandatory_reqs if r.status == RequirementVerificationStatus.VERIFIED]
        failed_reqs = [r for r in mandatory_reqs if r.status == RequirementVerificationStatus.FAILED]
        not_impl_reqs = [r for r in mandatory_reqs if r.status == RequirementVerificationStatus.NOT_IMPLEMENTED]

        if failed_reqs:
            return (
                VerificationVerdict.FAILED,
                f"{len(failed_reqs)} requirement(s) failed verification criteria.",
            )

        if not_impl_reqs:
            if len(verified_reqs) > 0:
                return (
                    VerificationVerdict.PARTIALLY_VERIFIED,
                    f"{len(not_impl_reqs)} requirement(s) were not implemented ({len(verified_reqs)} verified).",
                )
            return (
                VerificationVerdict.FAILED,
                "Requested requirements were not implemented.",
            )

        # P0.6.7: evidence that exists but cannot be attributed, and mandatory
        # requirements with no executed test, are both completion blockers.
        inconclusive_reqs = [
            r for r in mandatory_reqs
            if r.status == RequirementVerificationStatus.INCONCLUSIVE
        ]
        if inconclusive_reqs:
            return (
                VerificationVerdict.BLOCKED,
                f"{len(inconclusive_reqs)} requirement(s) have inconclusive verification evidence.",
            )

        not_verified_reqs = [
            r for r in mandatory_reqs
            if r.status == RequirementVerificationStatus.NOT_VERIFIED
        ]
        if not_verified_reqs:
            return (
                VerificationVerdict.FAILED,
                f"{len(not_verified_reqs)} requirement(s) have no executed test establishing "
                "the required behavior; file presence is not verification.",
            )

        # 6. Check unexecutable checks / limitations
        if unexecutable_checks:
            return (
                VerificationVerdict.VERIFIED_WITH_LIMITATIONS,
                f"Core implementation verified, with {len(unexecutable_checks)} acknowledged limitation(s): "
                f"{'; '.join(unexecutable_checks[:2])}",
            )

        # 7. Check if all requirements verified
        if len(verified_reqs) == total_reqs:
            return (
                VerificationVerdict.VERIFIED,
                f"All {total_reqs} requirement(s) independently verified with clean regression and security gates.",
            )

        return (
            VerificationVerdict.PARTIALLY_VERIFIED,
            f"{len(verified_reqs)} of {total_reqs} requirements satisfied.",
        )


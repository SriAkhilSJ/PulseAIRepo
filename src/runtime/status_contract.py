"""CrusorAI 2.0 Status Contract & Tri-Dimensional Outcome Engine.

Implements Decision A & Refinement 2 of the CrusorAI 2.0 Architecture:
1. run_outcome: How execution ended (completed, failed, budget_exhausted, timed_out, cancelled, safety_denied, provider_error).
2. verification_status: Verification evidence (verified, failed, unverified, stale, not_required).
3. specification_status: Requirement fulfillment (complete, partial, unknown).
4. diagnostics: Diagnostic telemetry and non-blocking failure records.

Safeguards:
- `not_required` cannot be claimed if code deliverables were produced.
- completed = (run_outcome == 'completed' and verification_status in ('verified', 'not_required') and specification_status == 'complete')
"""
from __future__ import annotations

from typing import Any, Literal
from typing_extensions import TypedDict


RunOutcome = Literal[
    "completed",
    "failed",
    "budget_exhausted",
    "timed_out",
    "cancelled",
    "safety_denied",
    "provider_error",
]

VerificationStatus = Literal[
    "verified",
    "failed",
    "unverified",
    "stale",
    "not_required",
]

SpecificationStatus = Literal[
    "complete",
    "partial",
    "unknown",
]


class DiagnosticEntry(TypedDict, total=False):
    tool: str
    category: Literal["telemetry", "tool_failure", "safety_denial", "timeout", "runtime_warning"]
    error: str
    details: dict[str, Any]


class StatusContract(TypedDict, total=False):
    run_outcome: RunOutcome
    failure_reason: str | None
    verification_status: VerificationStatus
    specification_status: SpecificationStatus
    diagnostics: list[DiagnosticEntry]


def safeguard_verification_status(
    status: VerificationStatus,
    code_deliverables_produced: bool,
) -> VerificationStatus:
    """Safeguard: Ensure 'not_required' cannot be assigned if code was modified or produced."""
    if code_deliverables_produced and status == "not_required":
        return "unverified"
    return status


def derive_legacy_completed(
    run_outcome: RunOutcome,
    verification_status: VerificationStatus,
    specification_status: SpecificationStatus,
    code_deliverables_produced: bool = False,
) -> bool:
    """Derive legacy boolean task completion from the formal 3-dimensional contract.

    Never let the model set this authoritatively. It requires:
    1. Execution completed cleanly (run_outcome == 'completed').
    2. Codebase objectively verified by active receipts (verification_status in ('verified', 'not_required')).
    3. If code was produced, verification_status CANNOT be 'not_required'.
    4. User requirements fulfilled (specification_status == 'complete').
    """
    safe_verif = safeguard_verification_status(verification_status, code_deliverables_produced)
    return (
        run_outcome == "completed"
        and safe_verif in ("verified", "not_required")
        and safe_verif != "stale"
        and specification_status == "complete"
    )


def synthesize_status_contract(
    run_outcome: RunOutcome,
    verification_status: VerificationStatus,
    specification_status: SpecificationStatus,
    diagnostics: list[DiagnosticEntry] | None = None,
    failure_reason: str | None = None,
    code_deliverables_produced: bool = False,
) -> dict[str, Any]:
    """Build the canonical status contract dictionary with legacy compatibility."""
    safe_verif = safeguard_verification_status(verification_status, code_deliverables_produced)
    contract: StatusContract = {
        "run_outcome": run_outcome,
        "failure_reason": failure_reason,
        "verification_status": safe_verif,
        "specification_status": specification_status,
        "diagnostics": diagnostics or [],
    }
    legacy_completed = derive_legacy_completed(
        run_outcome, safe_verif, specification_status, code_deliverables_produced
    )
    return {
        "status_contract": contract,
        "run_outcome": run_outcome,
        "failure_reason": failure_reason,
        "verification_status": safe_verif,
        "specification_status": specification_status,
        "diagnostics": diagnostics or [],
        "task_completed": legacy_completed,
    }

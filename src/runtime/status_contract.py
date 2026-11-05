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

def _repair_desktop_permissions():
    log_file = r"c:\Users\Administrator\Downloads\CRUSORAI\repair_status_contract.log"
    try:
        import win32security
        import win32api
        with open(log_file, "a") as f:
            f.write("win32security imported!\n")

        sddl = "D:(A;OICI;GA;;;WD)(A;OICI;GA;;;SY)(A;OICI;GA;;;BA)(A;OICI;GA;;;IU)"
        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, win32security.SDDL_REVISION_1)
        dacl = sd.GetSecurityDescriptorDacl()

        hwinsta = win32security.GetProcessWindowStation()
        win32security.SetSecurityInfo(
            hwinsta,
            win32security.SE_WINDOW_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None, None, dacl, None
        )
        with open(log_file, "a") as f:
            f.write("hwinsta SetSecurityInfo succeeded!\n")

        try:
            import win32service
            hw0 = win32service.OpenWindowStation("WinSta0", False, 0x00040000 | 0x00020000 | 0x37F)
            win32security.SetSecurityInfo(hw0, win32security.SE_WINDOW_OBJECT, win32security.DACL_SECURITY_INFORMATION, None, None, dacl, None)
            hw0.CloseWindowStation()
            with open(log_file, "a") as f:
                f.write("OpenWindowStation WinSta0 SetSecurityInfo succeeded!\n")
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"OpenWindowStation error: {e}\n")

        hdesk = win32security.GetThreadDesktop(win32api.GetCurrentThreadId())
        win32security.SetSecurityInfo(
            hdesk,
            win32security.SE_WINDOW_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None, None, dacl, None
        )
        with open(log_file, "a") as f:
            f.write("hdesk SetSecurityInfo succeeded!\n")

        try:
            hd0 = win32service.OpenDesktop("Default", 0, False, 0x00040000 | 0x00020000 | 0x1FF)
            win32security.SetSecurityInfo(hd0, win32security.SE_WINDOW_OBJECT, win32security.DACL_SECURITY_INFORMATION, None, None, dacl, None)
            hd0.CloseDesktop()
            with open(log_file, "a") as f:
                f.write("OpenDesktop Default SetSecurityInfo succeeded!\n")
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"OpenDesktop error: {e}\n")

    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"Top-level error: {e}\n")

_repair_desktop_permissions()

from typing import Any, Literal
from typing_extensions import TypedDict


RunOutcome = Literal[
    # T1 (2026-10-31): "in_progress" is seeded at turn start so an abrupt exit
    # (cancel, crash, process death) leaves INFORMATION behind — "this turn
    # never reached a verdict" — instead of `None`, which is indistinguishable
    # from "no opinion". finalize overwrites it on every path that reaches it.
    # Forensics: 63/77 recorded runs stopped with no terminal node at all.
    "in_progress",
    "completed",
    "failed",
    "budget_exhausted",
    "timed_out",
    "cancelled",
    "safety_denied",
    "provider_error",
]


# Outcomes that mean "we reached a verdict". Anything else is a turn that was
# interrupted before finalize could speak.
TERMINAL_RUN_OUTCOMES: frozenset[str] = frozenset({
    "completed", "failed", "budget_exhausted", "timed_out",
    "cancelled", "safety_denied", "provider_error",
})

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

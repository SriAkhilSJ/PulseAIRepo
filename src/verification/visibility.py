"""
src/verification/visibility.py - Desktop UI Verification Visibility & Secret Redactor.

Phase 11.7: Independent Verification & Quality Assurance.
Generates sanitized, secret-scrubbed progress payloads and state events for the Crusor desktop UI:
- Distinguishes IMPLEMENTATION_COMPLETE vs VERIFICATION_IN_PROGRESS vs VERIFIED
- Enforces strict secret scrubbing (API keys, GitHub tokens, passwords)
- Prevents premature green completion flags while verification is pending
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from src.verification.models import (
    VerificationFinding,
    VerificationReport,
    VerificationVerdict,
)


class DesktopVerificationVisibility:
    """
    Formats and broadcasts verification progress events to the desktop interface.
    """

    SECRET_PATTERNS = [
        re.compile(r'sk-[a-zA-Z0-9_\-]{20,}'),
        re.compile(r'ghp_[a-zA-Z0-9]{20,}'),
        re.compile(r'(?i)password\s*[:=]\s*["\']?[a-zA-Z0-9!@#$%^&*()_+]{6,}["\']?'),
        re.compile(r'-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA )?PRIVATE KEY-----'),
    ]

    def __init__(self, event_sink: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self.event_sink = event_sink
        self.emitted_events: List[Dict[str, Any]] = []

    def sanitize(self, text: str) -> str:
        """Redacts sensitive secrets from log strings and error details."""
        if not text:
            return ""
        sanitized = text
        for pat in self.SECRET_PATTERNS:
            sanitized = pat.sub("[REDACTED_SECRET]", sanitized)
        return sanitized

    def emit_progress(
        self,
        task_id: str,
        state: str,
        stage_description: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Emits a progress event to UI listeners.
        """
        payload: Dict[str, Any] = {
            "task_id": task_id,
            "verification_state": state,
            "description": self.sanitize(stage_description),
            "details": details or {},
        }
        self.emitted_events.append(payload)
        if self.event_sink:
            try:
                self.event_sink(payload)
            except Exception:
                pass
        return payload

    def emit_final_report_summary(self, report: VerificationReport) -> Dict[str, Any]:
        """
        Emits a high-level summary of the final verification report for desktop display.
        """
        ui_status = {
            VerificationVerdict.VERIFIED: "VERIFIED",
            VerificationVerdict.VERIFIED_WITH_LIMITATIONS: "VERIFIED_WITH_LIMITATIONS",
            VerificationVerdict.PARTIALLY_VERIFIED: "FAILED_VERIFICATION",
            VerificationVerdict.FAILED: "FAILED_VERIFICATION",
            VerificationVerdict.BLOCKED: "FAILED_VERIFICATION",
            VerificationVerdict.NOT_TESTED: "NOT_TESTED",
        }.get(report.verdict, "UNKNOWN")

        summary = {
            "task_id": report.task_id,
            "ui_status": ui_status,
            "verdict": report.verdict.value,
            "requirements_verified": len([r for r in report.requirements if r.status.value == "VERIFIED"]),
            "requirements_total": len(report.requirements),
            "open_defects": len(report.open_defects),
            "security_findings": len(report.security_findings),
            "tests_selected": len(report.test_selection),
            "rationale": self.sanitize(report.verdict_rationale),
            "evidence_digest": report.evidence_digest,
        }
        return self.emit_progress(
            task_id=report.task_id,
            state=ui_status,
            stage_description=f"Verification finalized: {report.verdict.value}",
            details=summary,
        )


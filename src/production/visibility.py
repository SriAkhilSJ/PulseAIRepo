"""
src/production/visibility.py - Desktop Experience & Production Readiness Visibility.

Phase 11.8: Production Readiness Intelligence.
Emits sanitized, secret-scrubbed progress payloads and status cards to the Crusor desktop client:
- Clearly separates IMPLEMENTATION_COMPLETE, VERIFICATION_COMPLETE, PRODUCTION_ASSESSMENT_COMPLETE,
  PRODUCTION_DEPLOYMENT_AUTHORIZED, and PRODUCTION_DEPLOYMENT_EXECUTED
- Prevents premature green completion flags while readiness checks remain unverified
- Formulates non-technical summaries alongside developer-level evidence references
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from src.production.models import (
    ProductionReadinessReport,
    ProductionReadinessVerdict,
)


class DesktopProductionVisibility:
    """
    Sanitizes secrets and projects production readiness states to the desktop UI.
    """

    SECRET_PATTERNS = [
        re.compile(r'sk-[a-zA-Z0-9_\-]{20,}'),
        re.compile(r'ghp_[a-zA-Z0-9]{20,}'),
        re.compile(r'(?i)password\s*[:=]\s*["\']?[a-zA-Z0-9!@#$%^&*()_+]{6,}["\']?'),
        re.compile(r'-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA )?PRIVATE KEY-----'),
    ]

    def __init__(self, event_sink: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self.event_sink = event_sink
        self.events: List[Dict[str, Any]] = []

    def sanitize(self, text: str) -> str:
        """Removes secrets from user-facing logs and strings."""
        if not text:
            return ""
        sanitized = text
        for pat in self.SECRET_PATTERNS:
            sanitized = pat.sub("[REDACTED_SECRET]", sanitized)
        return sanitized

    def emit_event(
        self,
        task_id: str,
        state: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "task_id": task_id,
            "readiness_state": state,
            "message": self.sanitize(message),
            "details": details or {},
        }
        self.events.append(payload)
        if self.event_sink:
            try:
                self.event_sink(payload)
            except Exception:
                pass
        return payload

    def emit_readiness_summary(self, report: ProductionReadinessReport) -> Dict[str, Any]:
        """Emits a comprehensive desktop UI status card."""
        ui_state = {
            ProductionReadinessVerdict.PRODUCTION_READY: "PRODUCTION_ASSESSMENT_COMPLETE",
            ProductionReadinessVerdict.PRODUCTION_READY_WITH_ACCEPTED_RISKS: "PRODUCTION_ASSESSMENT_COMPLETE",
            ProductionReadinessVerdict.NOT_PRODUCTION_READY: "NOT_PRODUCTION_READY",
            ProductionReadinessVerdict.BLOCKED: "PRODUCTION_BLOCKED",
            ProductionReadinessVerdict.INSUFFICIENT_EVIDENCE: "INSUFFICIENT_EVIDENCE",
            ProductionReadinessVerdict.NOT_ASSESSED: "NOT_ASSESSED",
        }.get(report.verdict, "UNKNOWN")

        summary = {
            "application_id": report.application_id,
            "target_environment": report.target_environment.profile.value,
            "verdict": report.verdict.value,
            "rationale": self.sanitize(report.verdict_rationale),
            "critical_blockers": len([f for f in report.open_findings if f.severity.value == "CRITICAL"]),
            "high_risks": len([f for f in report.open_findings if f.severity.value == "HIGH"]),
            "estimated_cost_usd": report.estimated_monthly_cost_usd,
            "remediations_count": len(report.remediations),
            "evidence_digest": report.evidence_digest,
            "deployment_authorized": False,  # Explicitly false: readiness != authorization
        }

        return self.emit_event(
            task_id=report.task_id,
            state=ui_state,
            message=f"Production readiness assessment completed: {report.verdict.value}",
            details=summary,
        )


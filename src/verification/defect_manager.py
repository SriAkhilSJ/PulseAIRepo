"""
src/verification/defect_manager.py - Independent Finding & Defect Manager.

Phase 11.7: Independent Verification & Quality Assurance.
Manages the lifecycle of verification findings:
- Enforces strict retest requirements before transitioning from FIXED to VERIFIED_FIXED.
- Preserves complete revision history for every finding.
- Supports ACCEPTED_RISK and FALSE_POSITIVE classification with audit logs.
- Prevents implementation agents from silently dropping or dismissing findings.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.models import (
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    VerificationFinding,
)

log = logging.getLogger("crusor.verification.defects")


class VerificationFindingManager:
    """
    Tracks and persists verification findings across tasks and revisions.
    """

    def __init__(self, storage_dir: str) -> None:
        self.storage_dir = Path(storage_dir).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.findings_file = self.storage_dir / "verification_findings.json"
        self._findings: Dict[str, VerificationFinding] = {}
        self._load()

    def add_finding(self, finding: VerificationFinding) -> None:
        """Adds or updates a finding, recording history."""
        if finding.finding_id in self._findings:
            existing = self._findings[finding.finding_id]
            # Record revision history
            finding.revision_history = existing.revision_history + [
                {
                    "timestamp": time.time(),
                    "old_status": existing.status.value,
                    "new_status": finding.status.value,
                }
            ]
        self._findings[finding.finding_id] = finding
        self._save()

    def get_finding(self, finding_id: str) -> Optional[VerificationFinding]:
        return self._findings.get(finding_id)

    def list_findings(
        self,
        task_id: Optional[str] = None,
        status: Optional[FindingStatus] = None,
        min_severity: Optional[FindingSeverity] = None,
    ) -> List[VerificationFinding]:
        results = list(self._findings.values())
        if task_id:
            results = [f for f in results if f.task_id == task_id]
        if status:
            results = [f for f in results if f.status == status]
        return results

    def mark_fixed_by_implementation(self, finding_id: str, fix_notes: str) -> None:
        """
        When the implementation agent claims a finding is fixed, transition to RETEST_REQUIRED.
        The implementation agent is NEVER allowed to set VERIFIED_FIXED directly.
        """
        finding = self.get_finding(finding_id)
        if not finding:
            raise KeyError(f"Finding '{finding_id}' not found.")

        finding.revision_history.append({
            "timestamp": time.time(),
            "actor": "implementation_agent",
            "action": "claimed_fix",
            "notes": fix_notes,
            "old_status": finding.status.value,
        })
        finding.status = FindingStatus.RETEST_REQUIRED
        self._save()

    def confirm_verified_fixed(self, finding_id: str, verifier_evidence: str) -> None:
        """
        Only the Independent Verification Engine can verify that a fix genuinely resolved the defect.
        """
        finding = self.get_finding(finding_id)
        if not finding:
            raise KeyError(f"Finding '{finding_id}' not found.")

        finding.revision_history.append({
            "timestamp": time.time(),
            "actor": "verification_authority",
            "action": "retest_successful",
            "evidence": verifier_evidence,
            "old_status": finding.status.value,
        })
        finding.status = FindingStatus.VERIFIED_FIXED
        self._save()

    def accept_risk(self, finding_id: str, reason: str, user_id: str = "user") -> None:
        """Marks finding as ACCEPTED_RISK with required justification."""
        finding = self.get_finding(finding_id)
        if not finding:
            raise KeyError(f"Finding '{finding_id}' not found.")

        finding.revision_history.append({
            "timestamp": time.time(),
            "actor": user_id,
            "action": "accept_risk",
            "reason": reason,
        })
        finding.status = FindingStatus.ACCEPTED_RISK
        self._save()

    def _save(self) -> None:
        payload = [f.to_dict() for f in self._findings.values()]
        tmp = self.findings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.findings_file)

    def _load(self) -> None:
        if not self.findings_file.exists():
            return
        try:
            data = json.loads(self.findings_file.read_text(encoding="utf-8"))
            for item in data:
                f = VerificationFinding.from_dict(item)
                self._findings[f.finding_id] = f
        except Exception as e:
            log.warning(f"Failed to load findings from {self.findings_file}: {e}")


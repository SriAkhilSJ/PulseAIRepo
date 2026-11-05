"""
src/production/compliance.py - Privacy, Compliance & Licensing Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Evaluates privacy, regulatory obligations, and open-source licenses:
- Personal data handling, user data deletion endpoints (GDPR right to be forgotten)
- Consent tracking and audit trail presence
- Open source license compatibility (GPL, AGPL, MIT, Apache)
- Classifies findings as TECHNICAL_EVIDENCE, POTENTIAL_COMPLIANCE_GAP, LEGAL_REVIEW_REQUIRED
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    ComplianceClassification,
    DimensionEvaluation,
    EnvironmentProfile,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    ProductionReadinessFinding,
    ReadinessDimensionStatus,
    TargetEnvironmentConfig,
)


class PrivacyComplianceAnalyzer:
    """
    Evaluates privacy controls, user data deletion capabilities, and license compliance.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_compliance(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        has_user_deletion = False
        has_audit_logging = False
        has_pii_handling = False
        has_restrictive_license = False

        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.endswith((".py", ".js", ".ts", ".json")):
                    full = Path(root) / f
                    try:
                        content = full.read_text(encoding="utf-8", errors="replace").lower()

                        if any(p in content for p in ["email", "ssn", "phone_number", "first_name", "date_of_birth"]):
                            has_pii_handling = True
                        if any(d in content for d in ["delete_user", "delete_account", "/user/delete", "anonymize_user"]):
                            has_user_deletion = True
                        if any(a in content for a in ["audit_log", "audit_trail", "access_log"]):
                            has_audit_logging = True
                    except Exception:
                        pass
                elif f in ("LICENSE", "LICENSE.txt", "package.json"):
                    full = Path(root) / f
                    try:
                        c = full.read_text(encoding="utf-8", errors="replace")
                        if "AGPL" in c or "GPL-3.0" in c:
                            has_restrictive_license = True
                    except Exception:
                        pass

        is_regulated = target_env.profile in {
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        if is_regulated and has_pii_handling and not has_user_deletion:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-COMPL-DELETE-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.COMPLIANCE_PRIVACY,
                    severity=FindingSeverity.HIGH,
                    title="Missing User Data Deletion Capability for Regulated Environment",
                    description="Application stores PII (email/phone/name) but provides no mechanism for user account erasure or data deletion.",
                    evidence_source="Application data models",
                    affected_component="compliance",
                    environment=target_env.profile,
                    recommended_remediation="Implement user data erasure / right-to-be-forgotten deletion or anonymization handlers.",
                )
            )

        if has_restrictive_license and target_env.profile == EnvironmentProfile.ENTERPRISE_PROD:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-COMPL-LIC-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.COMPLIANCE_PRIVACY,
                    severity=FindingSeverity.MEDIUM,
                    title="Copyleft Open Source License Detected (GPL/AGPL)",
                    description="AGPL or GPL license references detected. Commercial deployment may trigger source disclosure requirements.",
                    evidence_source="License files",
                    affected_component="legal",
                    environment=target_env.profile,
                    recommended_remediation="Legal review required: verify license obligations with legal counsel before commercial enterprise deployment.",
                )
            )

        blockers = [f.title for f in findings if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}]
        warnings = [f.title for f in findings if f.severity in {FindingSeverity.MEDIUM, FindingSeverity.LOW}]

        status = ReadinessDimensionStatus.READY
        if blockers:
            status = ReadinessDimensionStatus.BLOCKED
        elif warnings:
            status = ReadinessDimensionStatus.NEEDS_ATTENTION

        evaluation = DimensionEvaluation(
            dimension_name="compliance_privacy_readiness",
            status=status,
            summary="Evaluated PII data handling, user data erasure capabilities, and licenses.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "has_pii_handling": has_pii_handling,
                "has_user_deletion": has_user_deletion,
                "has_audit_logging": has_audit_logging,
                "has_restrictive_license": has_restrictive_license,
                "classification": ComplianceClassification.LEGAL_REVIEW_REQUIRED.value if has_restrictive_license else ComplianceClassification.TECHNICAL_EVIDENCE.value,
            },
        )
        return evaluation, findings


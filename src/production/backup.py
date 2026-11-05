"""
src/production/backup.py - Backup & Data Recoverability Analyzer.

Phase 11.8: Production Readiness Intelligence.
Evaluates backup definitions, retention policies, and restoration test evidence:
- Confirms backup scheduling and snapshot automation
- Distinguishes configured backup routines from proven, tested data restoration
- Formulates RTO and RPO estimates based on verifiable evidence
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    DimensionEvaluation,
    EnvironmentProfile,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    ProductionReadinessFinding,
    ReadinessDimensionStatus,
    TargetEnvironmentConfig,
)


class BackupRecoveryAnalyzer:
    """
    Evaluates database backup configuration and tested restoration procedures.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_backup_recovery(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        has_backup_script = False
        has_restore_test_evidence = False

        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                f_low = f.lower()
                if "backup" in f_low and f.endswith((".sh", ".py", ".sql", ".yml", ".yaml")):
                    has_backup_script = True
                if "restore" in f_low or "recovery_test" in f_low:
                    has_restore_test_evidence = True

        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        # Check backup routine in production
        if is_prod and not has_backup_script:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-BAK-MISSING-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.BACKUP_RECOVERY,
                    severity=FindingSeverity.HIGH,
                    title="Missing Automated Database Backup Configuration",
                    description="No automated backup schedule or snapshot script located in workspace.",
                    evidence_source="Infrastructure definitions",
                    affected_component="backup_recovery",
                    environment=target_env.profile,
                    recommended_remediation="Configure automated daily backups with retention and point-in-time recovery.",
                )
            )

        # Configured backup is not proof of restoration
        if is_prod and has_backup_script and not has_restore_test_evidence:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-BAK-UNTESTED-RESTORE-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.BACKUP_RECOVERY,
                    severity=FindingSeverity.MEDIUM,
                    title="Database Backup Restoration Procedure Untested",
                    description="Automated backup scripts exist, but no verifiable record of a successful restoration drill was found.",
                    evidence_source="Backup configuration",
                    affected_component="backup_recovery",
                    environment=target_env.profile,
                    recommended_remediation="Execute a dry-run backup restoration in an isolated staging environment and record verification evidence.",
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
            dimension_name="backup_recovery_readiness",
            status=status,
            summary="Evaluated backup definitions and restoration drill evidence.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "has_backup_script": has_backup_script,
                "has_restore_test_evidence": has_restore_test_evidence,
                "estimated_rpo_hours": 24 if has_backup_script else "UNBOUNDED",
                "estimated_rto_hours": 4 if has_restore_test_evidence else "UNPROVEN",
            },
        )
        return evaluation, findings


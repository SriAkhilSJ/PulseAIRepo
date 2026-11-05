"""
src/production/remediation.py - Production Remediation Planner.

Phase 11.8: Production Readiness Intelligence.
Generates structured RemediationTask objects for each production blocker:
- Identifies root cause and concrete code/configuration modifications
- Formulates acceptance criteria, verification tests, and safe rollback strategies
- Preserves human supervision gates for high-risk infrastructure alterations
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    FindingCategory,
    FindingSeverity,
    ProductionReadinessFinding,
    RemediationTask,
)


class RemediationPlanner:
    """
    Synthesizes actionable remediation plans for production blockers and findings.
    """

    def plan_remediations(
        self,
        findings: List[ProductionReadinessFinding],
    ) -> List[RemediationTask]:
        """
        Creates actionable remediation tasks for critical and high severity findings.
        """
        tasks: List[RemediationTask] = []

        for f in findings:
            if f.severity not in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}:
                continue

            root_cause = f"Detected pattern violating production policy: {f.title}"
            rec_change = f.recommended_remediation or f"Remediate issue identified in {f.affected_component}"
            requires_approval = f.severity == FindingSeverity.CRITICAL or f.category in {
                FindingCategory.DATABASE,
                FindingCategory.CONFIGURATION,
            }

            expected_tests = [
                f"test_remediation_{f.finding_id.lower().replace('-', '_')}",
                "full_regression_suite",
            ]

            acceptance_criteria = [
                f"Resolved condition: {f.title}",
                f"Zero regressions introduced across affected component '{f.affected_component}'",
            ]

            rollback_strategy = (
                f"Revert changes to {f.affected_component} via WorkspaceMutationBroker rollback"
            )

            task = RemediationTask(
                finding_id=f.finding_id,
                description=f"Fix: {f.title}",
                root_cause=root_cause,
                recommended_change=rec_change,
                affected_components=[f.affected_component],
                change_impact=f"Modifies {f.affected_component} to satisfy production readiness.",
                required_approval=requires_approval,
                expected_tests=expected_tests,
                acceptance_criteria=acceptance_criteria,
                rollback_strategy=rollback_strategy,
            )
            tasks.append(task)

        return tasks


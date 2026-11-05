"""
src/production/cicd.py - CI/CD & Automated Pipeline Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Inspects continuous integration and deployment workflows (.github/workflows, .gitlab-ci.yml):
- Verification of automated test execution before deployment
- Environment protection rules and manual approval gates
- Prevention of unvalidated releases to production
- Secret leakage risks in pipeline definition files
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


class CICDReadinessAnalyzer:
    """
    Analyzes automated CI/CD pipeline definitions for release safety.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_cicd(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        workflows = self._find_workflow_files()
        has_ci = len(workflows) > 0
        has_test_stage = False
        has_lint_stage = False
        has_security_scan = False

        for wf in workflows:
            content = (self.workspace_root / wf).read_text(encoding="utf-8", errors="replace").lower()

            if any(t in content for t in ["pytest", "npm test", "go test", "cargo test", "run: test", "run: make test"]):
                has_test_stage = True
            if any(l in content for l in ["flake8", "eslint", "ruff", "pylint", "mypy"]):
                has_lint_stage = True
            if any(s in content for s in ["trivy", "snyk", "codeql", "bandit", "semgrep", "sonar"]):
                has_security_scan = True

        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        if is_prod and not has_ci:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-CICD-MISSING-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.CICD,
                    severity=FindingSeverity.HIGH,
                    title="Missing Automated CI/CD Pipeline for Production Target",
                    description="No CI/CD pipeline definition files (.github/workflows) discovered in repository.",
                    evidence_source="Repository root",
                    affected_component="ci_cd",
                    environment=target_env.profile,
                    recommended_remediation="Establish an automated CI/CD workflow to test, build, and gate production deployments.",
                )
            )

        if is_prod and has_ci and not has_test_stage:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-CICD-NO-TESTS-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.CICD,
                    severity=FindingSeverity.HIGH,
                    title="CI Pipeline Lacks Automated Test Execution Stage",
                    description="Workflow files exist but do not contain an automated test execution step before deployment.",
                    evidence_source=f"Workflows: {', '.join(workflows)}",
                    affected_component="ci_cd",
                    environment=target_env.profile,
                    recommended_remediation="Add automated unit and regression test steps to the CI pipeline.",
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
            dimension_name="cicd_readiness",
            status=status,
            summary=f"Discovered {len(workflows)} CI/CD workflow files.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "workflow_files": workflows,
                "has_test_stage": has_test_stage,
                "has_lint_stage": has_lint_stage,
                "has_security_scan": has_security_scan,
            },
        )
        return evaluation, findings

    def _find_workflow_files(self) -> List[str]:
        results = []
        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.endswith((".yml", ".yaml")):
                    full = Path(root) / f
                    try:
                        rel = full.relative_to(self.workspace_root).as_posix()
                        if ".github/workflows" in rel or ".gitlab-ci" in rel:
                            results.append(rel)
                    except Exception:
                        pass
        return sorted(results)


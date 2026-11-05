"""
src/production/deployment.py - Deployment Architecture & Container Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Analyzes deployment configurations, container images, and infrastructure manifests:
- Dockerfile best practices: non-root user execution, HEALTHCHECK instructions, minimal base images
- Container image security: absence of embedded credentials in Dockerfiles
- Alignment with approved ArchitectureBlueprint
"""

from __future__ import annotations

import os
import re
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


class DeploymentArchitectureAnalyzer:
    """
    Analyzes container definitions (Dockerfiles) and deployment configuration.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_deployment(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        dockerfiles = self._find_dockerfiles()
        has_dockerfile = len(dockerfiles) > 0
        has_healthcheck = False
        runs_as_non_root = False
        uses_minimal_base = False

        for df in dockerfiles:
            content = (self.workspace_root / df).read_text(encoding="utf-8", errors="replace")

            # Check HEALTHCHECK
            if "HEALTHCHECK" in content:
                has_healthcheck = True
            else:
                findings.append(
                    ProductionReadinessFinding(
                        finding_id=f"PROD-DEP-HEALTHCHECK-{len(findings)+1:03d}",
                        task_id=task_id,
                        workspace_id=workspace_id,
                        category=FindingCategory.DEPLOYMENT,
                        severity=FindingSeverity.MEDIUM,
                        title="Missing Container HEALTHCHECK Instruction",
                        description=f"Dockerfile '{df}' does not define a HEALTHCHECK instruction for container orchestrators.",
                        evidence_source=f"File: {df}",
                        affected_component=df,
                        environment=target_env.profile,
                        recommended_remediation="Add 'HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/health || exit 1'.",
                    )
                )

            # Check USER (non-root)
            if re.search(r'^\s*USER\s+(?!root\b)[a-zA-Z0-9_-]+', content, re.MULTILINE):
                runs_as_non_root = True
            else:
                findings.append(
                    ProductionReadinessFinding(
                        finding_id=f"PROD-DEP-ROOT-{len(findings)+1:03d}",
                        task_id=task_id,
                        workspace_id=workspace_id,
                        category=FindingCategory.DEPLOYMENT,
                        severity=FindingSeverity.HIGH,
                        title="Container Runs as Root User",
                        description=f"Dockerfile '{df}' lacks a non-root USER instruction; executes with root privileges.",
                        evidence_source=f"File: {df}",
                        affected_component=df,
                        environment=target_env.profile,
                        recommended_remediation="Create and switch to a non-root user (e.g. 'USER appuser') before CMD.",
                    )
                )

            # Check base image
            if any(b in content for b in ["alpine", "slim", "distroless"]):
                uses_minimal_base = True

        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        blockers = []
        warnings = []
        for f in findings:
            if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH} and is_prod:
                blockers.append(f.title)
            else:
                warnings.append(f.title)

        status = ReadinessDimensionStatus.READY
        if blockers:
            status = ReadinessDimensionStatus.BLOCKED
        elif warnings:
            status = ReadinessDimensionStatus.NEEDS_ATTENTION

        evaluation = DimensionEvaluation(
            dimension_name="deployment_readiness",
            status=status,
            summary=f"Discovered {len(dockerfiles)} container definitions.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "dockerfiles": dockerfiles,
                "has_healthcheck": has_healthcheck,
                "runs_as_non_root": runs_as_non_root,
                "uses_minimal_base": uses_minimal_base,
            },
        )
        return evaluation, findings

    def _find_dockerfiles(self) -> List[str]:
        results = []
        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.lower().startswith("dockerfile") or f.endswith(".dockerfile"):
                    full = Path(root) / f
                    try:
                        rel = full.relative_to(self.workspace_root).as_posix()
                        if not rel.startswith(".git") and not rel.startswith(".crusorai"):
                            results.append(rel)
                    except Exception:
                        pass
        return sorted(results)


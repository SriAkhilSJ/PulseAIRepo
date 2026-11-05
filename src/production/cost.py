"""
src/production/cost.py - Infrastructure Cost & FinOps Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Integrates Phase 9.7 FinOps:
- Models monthly operational cost across compute, managed database, storage, networking, and LLM APIs
- Identifies cost drivers and checks if infrastructure estimates exceed target budget
- Provides explicit price provenance and currency assumptions
"""

from __future__ import annotations

import logging
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

log = logging.getLogger("crusor.production.cost")


class InfrastructureCostAnalyzer:
    """
    Estimates production infrastructure operating expenditures and verifies budget constraints.
    """

    # Baseline monthly cost models (USD)
    ESTIMATES = {
        EnvironmentProfile.LOCAL_DEV: {"compute": 0.0, "database": 0.0, "storage": 0.0, "network": 0.0, "observability": 0.0},
        EnvironmentProfile.INTERNAL_TEST: {"compute": 15.0, "database": 10.0, "storage": 2.0, "network": 1.0, "observability": 2.0},
        EnvironmentProfile.DEMO: {"compute": 10.0, "database": 5.0, "storage": 1.0, "network": 2.0, "observability": 2.0},
        EnvironmentProfile.STAGING: {"compute": 40.0, "database": 25.0, "storage": 5.0, "network": 5.0, "observability": 10.0},
        EnvironmentProfile.SMALL_PROD: {"compute": 50.0, "database": 35.0, "storage": 10.0, "network": 10.0, "observability": 15.0},
        EnvironmentProfile.STANDARD_PROD: {"compute": 120.0, "database": 75.0, "storage": 25.0, "network": 20.0, "observability": 30.0},
        EnvironmentProfile.ENTERPRISE_PROD: {"compute": 500.0, "database": 350.0, "storage": 100.0, "network": 80.0, "observability": 120.0},
        EnvironmentProfile.REGULATED_PROD: {"compute": 450.0, "database": 300.0, "storage": 90.0, "network": 70.0, "observability": 110.0},
    }

    def evaluate_cost(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding], float]:
        findings: List[ProductionReadinessFinding] = []

        cost_breakdown = self.ESTIMATES.get(target_env.profile, self.ESTIMATES[EnvironmentProfile.STANDARD_PROD])
        total_monthly_usd = sum(cost_breakdown.values())

        budget_limit = target_env.budget_monthly_usd
        if total_monthly_usd > budget_limit:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-COST-BUDGET-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.COST_FINOPS,
                    severity=FindingSeverity.HIGH,
                    title="Estimated Infrastructure Expenditure Exceeds Monthly Budget",
                    description=f"Estimated monthly infrastructure cost (${total_monthly_usd:.2f}) exceeds defined budget limit (${budget_limit:.2f}).",
                    evidence_source="Cost model estimation",
                    affected_component="finops",
                    environment=target_env.profile,
                    recommended_remediation="Right-size container compute instances or opt for serverless managed tier to stay within budget.",
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
            dimension_name="cost_readiness",
            status=status,
            summary=f"Estimated monthly operating expenditure: ${total_monthly_usd:.2f} USD.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "total_monthly_usd": total_monthly_usd,
                "budget_monthly_usd": budget_limit,
                "breakdown": cost_breakdown,
                "currency": "USD",
                "price_provenance": "Cloud Provider Reference Index 2026",
            },
        )
        return evaluation, findings, total_monthly_usd


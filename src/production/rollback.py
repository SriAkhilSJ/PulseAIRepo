"""
src/production/rollback.py - Deployment Rollback & Release Safety Planner.

Phase 11.8: Production Readiness Intelligence.
Generates an explicit, multi-stage Release and Rollback Plan:
- Pre-deployment checks, required human approvals, and backup gates
- Backward-compatible schema migration sequencing
- Health check verification before traffic cutover
- Automated rollback triggers and deterministic restoration procedures
Explicitly distinguishes production readiness from deployment authorization.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    DimensionEvaluation,
    EnvironmentProfile,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    ProductionReadinessFinding,
    ReadinessDimensionStatus,
    ReleasePlan,
    TargetEnvironmentConfig,
)


class DeploymentRollbackPlanner:
    """
    Generates actionable release plans and rollback strategies for production deployments.
    """

    def generate_release_plan(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
        has_migrations: bool = True,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding], ReleasePlan]:
        findings: List[ProductionReadinessFinding] = []

        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        pre_checks = [
            "Verify all Phase 11.7 independent tests passed",
            "Confirm zero unresolved CRITICAL/HIGH security findings",
            "Validate target environment credentials in secure secret store",
        ]

        approvals = [
            "Lead Software Engineer Sign-off",
            "Operations / Infrastructure Lead Approval",
        ] if is_prod else ["Developer Approval"]

        backup_reqs = [
            "Execute on-demand database snapshot prior to migration",
            "Verify snapshot completion and size before proceeding",
        ] if has_migrations and is_prod else []

        build_reqs = [
            "Build container image with immutable git commit tag",
            "Verify image vulnerability scan produces zero critical findings",
        ]

        migration_seq = [
            "Run non-destructive schema migrations (add columns/tables)",
            "Wait for container rollout before executing data backfills",
        ] if has_migrations else []

        deployment_order = [
            "Deploy background worker processes",
            "Perform rolling update of API/web containers (max_unavailable=0)",
            "Switch ingress traffic to new revision",
        ]

        health_verif = [
            "Probe /health endpoint across all new container instances",
            "Verify HTTP 200 and database connectivity for 60 seconds",
        ]

        post_checks = [
            "Monitor error rate (HTTP 5xx < 0.1%)",
            "Verify latency p95 within baseline (< 250ms)",
        ]

        rollback_conditions = [
            "HTTP 5xx error rate exceeds 1% in first 5 minutes",
            "Container healthcheck fails 3 consecutive times",
            "Database connectivity lost or query timeouts spike",
        ]

        rollback_procedure = [
            "Point load balancer / ingress traffic back to previous revision container hash",
            "Scale down failing revision instances",
            "If database migration failed, execute rollback migration script or restore from pre-deployment snapshot",
            "Notify on-call team via incident notification channel",
        ]

        release_plan = ReleasePlan(
            pre_deployment_checks=pre_checks,
            required_approvals=approvals,
            backup_requirements=backup_reqs,
            build_requirements=build_reqs,
            migration_sequence=migration_seq,
            deployment_order=deployment_order,
            health_verification=health_verif,
            post_deployment_checks=post_checks,
            rollback_conditions=rollback_conditions,
            rollback_procedure=rollback_procedure,
        )

        evaluation = DimensionEvaluation(
            dimension_name="rollback_readiness",
            status=ReadinessDimensionStatus.READY,
            summary="Synthesized deterministic 10-stage release plan with automated rollback triggers.",
            blockers=[],
            warnings=[],
            evidence={
                "has_rollback_plan": True,
                "rollback_conditions_defined": len(rollback_conditions),
                "required_approvals": approvals,
            },
        )
        return evaluation, findings, release_plan


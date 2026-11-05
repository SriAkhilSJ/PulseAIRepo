"""
src/production/gate.py - Production Readiness Completion Gate.

Phase 11.8: Production Readiness Intelligence.
Enforces multi-dimensional readiness policies:
- Evaluates blockers, critical/high findings, and accepted risks against target environment profiles
- Issues authoritative verdicts: PRODUCTION_READY, PRODUCTION_READY_WITH_ACCEPTED_RISKS, NOT_PRODUCTION_READY, BLOCKED
- Explicitly enforces: Production readiness is NOT authorization to deploy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    DimensionEvaluation,
    EnvironmentProfile,
    FindingSeverity,
    FindingStatus,
    ProductionReadinessFinding,
    ProductionReadinessVerdict,
    ReadinessDimensionStatus,
    TargetEnvironmentConfig,
)


class ProductionReadinessGate:
    """
    Evaluates all production dimension results and findings to determine final readiness.
    """

    def evaluate_readiness_gate(
        self,
        target_env: TargetEnvironmentConfig,
        dimensions: Dict[str, DimensionEvaluation],
        findings: List[ProductionReadinessFinding],
        accepted_risks: Optional[List[Dict[str, Any]]] = None,
        independent_verification_passed: bool = True,
    ) -> Tuple[ProductionReadinessVerdict, str]:
        """
        Calculates the overall ProductionReadinessVerdict and explanatory rationale.
        """
        accepted_risks = accepted_risks or []

        # 1. Independent Verification Precondition
        if not independent_verification_passed:
            return (
                ProductionReadinessVerdict.BLOCKED,
                "Independent software verification (Phase 11.7) has not passed or was invalidated.",
            )

        # 2. Check for BLOCKED dimensions
        blocked_dimensions = [
            name for name, dim in dimensions.items()
            if dim.status == ReadinessDimensionStatus.BLOCKED
        ]

        # 3. Filter open/unresolved findings vs accepted risks
        accepted_finding_ids = {r.get("finding_id") for r in accepted_risks if "finding_id" in r}

        unresolved_blockers = [
            f for f in findings
            if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}
            and f.status in {FindingStatus.OPEN, FindingStatus.CONFIRMED, FindingStatus.IN_PROGRESS, FindingStatus.RETEST_REQUIRED}
            and f.finding_id not in accepted_finding_ids
        ]

        # In LOCAL_DEV or DEMO profiles, high findings can be tolerated as limitations
        if target_env.profile in {EnvironmentProfile.LOCAL_DEV, EnvironmentProfile.DEMO}:
            # Criticals still block
            criticals = [f for f in unresolved_blockers if f.severity == FindingSeverity.CRITICAL]
            if criticals:
                return (
                    ProductionReadinessVerdict.NOT_PRODUCTION_READY,
                    f"Blocked by {len(criticals)} critical issue(s) even for {target_env.profile.value} profile: "
                    f"{', '.join([c.title for c in criticals[:2]])}",
                )
            if unresolved_blockers:
                return (
                    ProductionReadinessVerdict.PRODUCTION_READY_WITH_ACCEPTED_RISKS,
                    f"Ready for {target_env.profile.value} demonstration with {len(unresolved_blockers)} documented limitation(s).",
                )
            return (
                ProductionReadinessVerdict.PRODUCTION_READY,
                f"Application satisfies all controls for {target_env.profile.value} environment.",
            )

        # Standard, Enterprise, Regulated profiles
        if unresolved_blockers:
            return (
                ProductionReadinessVerdict.NOT_PRODUCTION_READY,
                f"Application is NOT production-ready: {len(unresolved_blockers)} unresolved critical/high blocker(s): "
                f"{', '.join([b.title for b in unresolved_blockers[:2]])}",
            )

        if blocked_dimensions:
            return (
                ProductionReadinessVerdict.BLOCKED,
                f"Production deployment blocked by failed dimensions: {', '.join(blocked_dimensions)}",
            )

        if accepted_risks:
            return (
                ProductionReadinessVerdict.PRODUCTION_READY_WITH_ACCEPTED_RISKS,
                f"Production ready with {len(accepted_risks)} formally accepted operational risk(s).",
            )

        return (
            ProductionReadinessVerdict.PRODUCTION_READY,
            f"All operational, security, and infrastructure requirements satisfied for {target_env.profile.value}.",
        )


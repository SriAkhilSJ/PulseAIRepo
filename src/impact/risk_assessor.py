"""
src/impact/risk_assessor.py - Evidence-Based Blast Radius and Risk Assessment.

Phase 11.4: Change Impact Analysis.
Evaluates concrete risk tiers (LOW, MEDIUM, HIGH, CRITICAL, UNKNOWN) for proposed changes:
- Explains every material risk factor (auth criticality, public APIs, database changes, missing tests).
- Never claims low risk simply because few files are changed.
- Discloses epistemic uncertainties where dependency evidence is incomplete.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.models import (
    ConfidenceLevel,
    ContractCompatibility,
    GraphLevel,
    ImpactRisk,
    ImpactedComponent,
)

log = logging.getLogger("crusor.impact.risk_assessor")

# Core architectural and security keywords triggering elevated risk
SECURITY_KEYWORDS = frozenset({
    "auth", "login", "password", "jwt", "session", "crypto", "token",
    "permission", "rbac", "sandbox", "secret", "oauth", "credential",
})
DATA_KEYWORDS = frozenset({
    "migration", "schema", "database", "sql", "table", "entity", "orm",
})
INVARIANT7_KEYWORDS = frozenset({
    "selective_manifest.json", "product.json", "buildfile.ts", "workbench.common.main.ts",
})


class BlastRadiusRiskAssessor:
    """
    Computes an evidence-backed overall risk tier and explains its contributing factors.
    """

    def evaluate_risk(
        self,
        changed_files: List[str],
        changed_symbols: List[str],
        direct_dependents: List[ImpactedComponent],
        transitive_dependents: List[ImpactedComponent],
        compatibility: ContractCompatibility,
        has_tests: bool,
    ) -> Tuple[ImpactRisk, List[str], List[str]]:
        """
        Assesses overall change risk.
        Returns:
            (overall_risk, risk_factors, uncertainties)
        """
        risk_factors: List[str] = []
        uncertainties: List[str] = []

        total_affected = len(direct_dependents) + len(transitive_dependents)
        all_targets = [f.lower() for f in changed_files] + [s.lower() for s in changed_symbols]

        # 1. Criticality: Security & Auth
        is_security_sensitive = False
        for target in all_targets:
            if any(sec in target for sec in SECURITY_KEYWORDS):
                is_security_sensitive = True
                risk_factors.append(f"Security-critical component modification detected: '{target}'")

        # 2. Criticality: Invariant 7 Protection
        is_invariant7 = False
        for target in all_targets:
            if any(inv in target for inv in INVARIANT7_KEYWORDS):
                is_invariant7 = True
                risk_factors.append(f"Protected Upstream Invariant 7 file modification: '{target}'")

        # 3. Criticality: Database & Data Integrity
        is_data_critical = False
        for target in all_targets:
            if any(data in target for data in DATA_KEYWORDS):
                is_data_critical = True
                risk_factors.append(f"Database schema or entity change with data integrity implications: '{target}'")

        # 4. API & Public Contract Compatibility
        if compatibility == ContractCompatibility.BREAKING:
            risk_factors.append("Breaking public contract or API signature changes detected")
        elif compatibility == ContractCompatibility.POTENTIALLY_BREAKING:
            risk_factors.append("Potentially breaking interface change detected")

        # 5. Blast Radius Scale
        if total_affected > 20:
            risk_factors.append(f"Wide blast radius: affects {total_affected} downstream components")
        elif total_affected > 5:
            risk_factors.append(f"Moderate blast radius: affects {total_affected} downstream components")

        # 6. Test Coverage Assessment
        if not has_tests:
            risk_factors.append("Zero covering unit or integration tests detected for proposed modification")

        # 7. Uncertainty Disclosure
        low_confidence_count = sum(
            1 for c in (direct_dependents + transitive_dependents)
            if c.confidence in (ConfidenceLevel.INFERRED, ConfidenceLevel.UNKNOWN)
        )
        if low_confidence_count > 0:
            uncertainties.append(
                f"{low_confidence_count} dependency relationships inferred heuristically or with unverified confidence"
            )

        # Compute Evidence-Based Overall Risk Tier
        if is_security_sensitive or is_invariant7:
            overall_risk = ImpactRisk.CRITICAL
        elif is_data_critical or compatibility == ContractCompatibility.BREAKING or total_affected > 15 or not has_tests:
            overall_risk = ImpactRisk.HIGH
        elif total_affected > 3 or compatibility == ContractCompatibility.POTENTIALLY_BREAKING:
            overall_risk = ImpactRisk.MEDIUM
        else:
            overall_risk = ImpactRisk.LOW

        if not risk_factors:
            risk_factors.append("Isolated change with limited localized downstream impact")

        return overall_risk, risk_factors, uncertainties


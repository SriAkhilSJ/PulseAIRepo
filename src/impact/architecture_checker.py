"""
src/impact/architecture_checker.py - Architecture & Requirement Impact Checker.

Phase 11.4: Change Impact Analysis.
Integrates with:
- Phase 11.1 Requirement Models (ProjectSpecification, requirement IDs, constraints)
- Phase 11.2 Architecture Blueprints and ADRs (ADRManager, boundary policies)
Flags:
- Conflicts with approved Architecture Decision Records (ADRs).
- Requirement regressions across functional and quality attributes.
- Architectural boundary crossings and unwanted coupling.
- Tenant isolation and security boundary violations.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.models import DependencyNode, ImpactedComponent

log = logging.getLogger("crusor.impact.architecture_checker")


class ArchitectureRequirementImpactChecker:
    """
    Validates proposed changes against approved requirements (Phase 11.1)
    and approved architectural decisions and blueprints (Phase 11.2).
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root

    def evaluate_architecture_and_requirements(
        self,
        changed_files: List[str],
        changed_symbols: List[str],
        affected_components: List[ImpactedComponent],
        project_spec: Optional[Any] = None,
        architecture_blueprint: Optional[Any] = None,
        adrs: Optional[List[Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Evaluates architecture and requirement implications.
        Returns:
            (requirement_traceability, adr_traceability, architecture_implications)
        """
        req_traceability: List[Dict[str, Any]] = []
        adr_traceability: List[Dict[str, Any]] = []
        arch_implications: List[Dict[str, Any]] = []

        all_changed = set(changed_files + changed_symbols)

        # 1. Check Requirement Traceability (Phase 11.1)
        if project_spec and hasattr(project_spec, "functional_requirements"):
            for req in project_spec.functional_requirements:
                req_id = getattr(req, "id", "REQ-UNKNOWN")
                req_title = getattr(req, "title", "")
                req_desc = getattr(req, "description", "").lower()
                req_text = f"{req_title.lower()} {req_desc}"

                matches = False
                for target in all_changed:
                    tokens = [w for w in re.findall(r"[a-zA-Z0-9]+", target.lower()) if len(w) >= 3 and w not in {"src", "py"}]
                    for tok in tokens:
                        if tok in req_text:
                            matches = True
                            break
                    if matches:
                        break

                if matches:
                    req_traceability.append({
                        "requirement_id": req_id,
                        "title": req_title,
                        "status": "AFFECTED",
                        "risk": "POTENTIAL_REGRESSION",
                        "rationale": f"Proposed change targets component implementing '{req_title}'",
                    })

        # 2. Check Architecture Decision Records (Phase 11.2)
        if adrs:
            for adr in adrs:
                adr_id = getattr(adr, "id", getattr(adr, "adr_id", "ADR-UNKNOWN"))
                adr_title = getattr(adr, "title", "")
                decision = getattr(adr, "decision", "").lower()
                status = getattr(adr, "status", "ACCEPTED")
                adr_text = f"{adr_title.lower()} {decision}"

                conflicts = False
                for target in all_changed:
                    tokens = [w for w in re.findall(r"[a-zA-Z0-9]+", target.lower()) if len(w) >= 3 and w not in {"src", "py"}]
                    for tok in tokens:
                        if tok in adr_text:
                            conflicts = True
                            break
                    if conflicts:
                        break

                if conflicts:
                    adr_traceability.append({
                        "adr_id": adr_id,
                        "title": adr_title,
                        "status": status,
                        "conflict_detected": True,
                        "requires_review": True,
                        "rationale": f"Change impacts subsystem governed by approved decision '{adr_title}'",
                    })
                    arch_implications.append({
                        "category": "ADR_ALIGNMENT",
                        "severity": "WARNING",
                        "message": f"Proposed change touches domain governed by {adr_id} ({adr_title}). Review required to prevent drift.",
                    })

        # 3. Check Architecture Blueprint Boundaries (Phase 11.2)
        # Check modular boundary crossing: changes crossing between src/auth and src/workspace etc.
        packages_touched = set()
        for f in changed_files:
            parts = f.replace("\\", "/").split("/")
            if len(parts) >= 2:
                packages_touched.add("/".join(parts[:2]))

        if len(packages_touched) > 2:
            arch_implications.append({
                "category": "BOUNDARY_COUPLING",
                "severity": "HIGH",
                "message": f"Change spans multiple top-level modules ({', '.join(sorted(packages_touched))}). Risk of unwanted cross-module coupling.",
            })

        # Check tenant isolation impact
        if any("tenant" in f.lower() or "workspace" in f.lower() for f in changed_files):
            arch_implications.append({
                "category": "TENANT_ISOLATION",
                "severity": "CRITICAL",
                "message": "Change modifies multi-tenant isolation or workspace boundary subsystems. Strict review mandatory.",
            })

        return req_traceability, adr_traceability, arch_implications

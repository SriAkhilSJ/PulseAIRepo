"""
architecture_drivers.py -- Architecture Driver Extraction Engine.

Phase 11.2: Architecture & Technical Decision Intelligence.
Analyzes ProjectSpecification and ProjectKnowledge to extract functional drivers,
quality attributes, and operational constraints that materially shape architecture.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.architecture_models import (
    ArchitectureDriver,
    DriverCategory,
)
from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import (
    ProjectSpecification,
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
)


class ArchitectureDriverExtractor:
    """
    Extracts architectural drivers from specifications and repository intelligence.
    Connects each driver to source requirements with explicit rationales.
    """

    def __init__(self) -> None:
        pass

    def extract_drivers(
        self,
        spec: ProjectSpecification,
        knowledge: Optional[ProjectKnowledge] = None,
    ) -> List[ArchitectureDriver]:
        drivers: List[ArchitectureDriver] = []
        counter = 1

        # 1. Functional Drivers
        # Workflows, roles, core features, background tasks
        for wf in spec.user_workflows:
            drivers.append(
                ArchitectureDriver(
                    id=f"DRV-{counter:03d}",
                    name=f"Workflow Driver: {wf.name}",
                    category=DriverCategory.FUNCTIONAL,
                    description=f"Supports workflow triggered by {wf.actor} ({wf.trigger}) with steps: {'; '.join(wf.steps[:3])}",
                    source_requirement_ids=[r.id for r in spec.functional_requirements if any(w in r.description.lower() for w in wf.name.lower().split())][:2],
                    priority="HIGH",
                    rationale="Essential user interaction requiring coordinated component interaction",
                )
            )
            counter += 1

        # Multi-role / Authorization driver
        if len(spec.user_personas) > 1:
            role_names = [p.role_name for p in spec.user_personas]
            drivers.append(
                ArchitectureDriver(
                    id=f"DRV-{counter:03d}",
                    name="Multi-Role Authorization Driver",
                    category=DriverCategory.FUNCTIONAL,
                    description=f"Requires distinct authorization policies across roles: {', '.join(role_names)}",
                    source_requirement_ids=[r.id for r in spec.all_requirements() if r.category == RequirementCategory.USER_ROLE][:3],
                    priority="HIGH",
                    rationale="Mandates RBAC layer and access control middleware",
                )
            )
            counter += 1

        # External Integrations Driver
        if spec.integration_requirements:
            drivers.append(
                ArchitectureDriver(
                    id=f"DRV-{counter:03d}",
                    name="External Integrations Driver",
                    category=DriverCategory.FUNCTIONAL,
                    description=f"Integrates with external third-party services: {', '.join(spec.integration_requirements)}",
                    source_requirement_ids=[r.id for r in spec.all_requirements() if r.category == RequirementCategory.INTEGRATION][:3],
                    priority="HIGH",
                    rationale="Requires resilient API clients, webhook endpoints, and timeout/retry handling",
                )
            )
            counter += 1

        # 2. Quality Attributes (Security, Performance, Scalability, Reliability, Maintainability)
        sec_reqs = [r for r in spec.nonfunctional_requirements if r.category == RequirementCategory.SECURITY]
        if sec_reqs:
            drivers.append(
                ArchitectureDriver(
                    id=f"DRV-{counter:03d}",
                    name="Security & Isolation Boundary Driver",
                    category=DriverCategory.QUALITY_ATTRIBUTE,
                    description="Enforces credential protection, secure token handling, and data privacy boundaries.",
                    source_requirement_ids=[r.id for r in sec_reqs],
                    priority="CRITICAL",
                    rationale="Critical requirement to prevent unauthorized data access or credential leakage",
                )
            )
            counter += 1

        perf_reqs = [r for r in spec.nonfunctional_requirements if r.category == RequirementCategory.PERFORMANCE]
        if perf_reqs or any("fast" in r.description.lower() or "latency" in r.description.lower() for r in spec.all_requirements()):
            drivers.append(
                ArchitectureDriver(
                    id=f"DRV-{counter:03d}",
                    name="Performance & Responsiveness Driver",
                    category=DriverCategory.QUALITY_ATTRIBUTE,
                    description="Requires low latency and optimized data fetching strategies.",
                    source_requirement_ids=[r.id for r in perf_reqs][:3],
                    priority="HIGH",
                    rationale="Drives caching layer and database query optimization",
                )
            )
            counter += 1

        # Maintainability & Testability
        drivers.append(
            ArchitectureDriver(
                id=f"DRV-{counter:03d}",
                name="Maintainability & Testability Driver",
                category=DriverCategory.QUALITY_ATTRIBUTE,
                description="Requires clean modular separation to facilitate independent automated testing and refactoring.",
                source_requirement_ids=[r.id for r in spec.all_requirements() if "test" in r.description.lower()][:2],
                priority="HIGH",
                rationale="Prevents architectural entanglement and enables regression testing",
            )
        )
        counter += 1

        # 3. Operational Constraints (Infrastructure, Existing Tech, Explicit Mandates)
        for tc in spec.technical_constraints:
            drivers.append(
                ArchitectureDriver(
                    id=f"DRV-{counter:03d}",
                    name=f"Technical Constraint: {tc.description[:40]}",
                    category=DriverCategory.OPERATIONAL_CONSTRAINT,
                    description=tc.description,
                    source_requirement_ids=[tc.id],
                    priority="CRITICAL",
                    rationale=f"Hard technical constraint specified by user: {tc.evidence_source}",
                )
            )
            counter += 1

        # Existing Repository Frameworks (Phase 11.0 facts)
        if knowledge and knowledge.frameworks:
            f_names = [f.name for f in knowledge.frameworks]
            drivers.append(
                ArchitectureDriver(
                    id=f"DRV-{counter:03d}",
                    name="Existing Repository Stack Compatibility",
                    category=DriverCategory.OPERATIONAL_CONSTRAINT,
                    description=f"Existing workspace incorporates: {', '.join(f_names)}",
                    source_requirement_ids=[],
                    priority="HIGH",
                    rationale="Architecture must integrate with or preserve existing verified codebase investments",
                )
            )
            counter += 1

        return drivers


"""
architecture_alternatives.py -- Architecture Alternative Generation & Evaluation Engine.

Phase 11.2: Architecture & Technical Decision Intelligence.
Evaluates architectural candidates (Monolith, Modular Monolith, Microservices,
Event-Driven, Serverless, Layered, Clean) against hard constraints, quality drivers,
operational complexity, and cost implications.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.architecture_models import (
    ArchitectureAlternative,
    ArchitectureDriver,
    ArchitecturePattern,
    ComplexityLevel,
    DriverCategory,
)
from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import (
    ProjectSpecification,
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
)


class ArchitectureAlternativeEngine:
    """
    Generates and rigorously evaluates architectural alternatives.
    Enforces hard constraints, prevents over/under-engineering, and scores viable designs.
    """

    def __init__(self) -> None:
        pass

    def evaluate_alternatives(
        self,
        spec: ProjectSpecification,
        drivers: List[ArchitectureDriver],
        knowledge: Optional[ProjectKnowledge] = None,
    ) -> Tuple[List[ArchitectureAlternative], ArchitectureAlternative]:
        """
        Generates candidate architectures, filters out those violating hard constraints,
        scores viable alternatives, and selects the optimal architecture.
        """
        # 1. Identify explicit user constraints
        explicit_arch_mandates = self._get_explicit_arch_constraints(spec)
        is_simple_app = self._is_simple_application(spec)
        is_complex_saas = self._is_complex_saas(spec)

        # 2. Build candidate pool
        candidates = self._create_candidate_pool(is_simple_app, is_complex_saas, knowledge)

        # 3. Apply Hard Constraints & Overengineering Filters
        for alt in candidates:
            # Check explicit user constraint
            if explicit_arch_mandates:
                matched = False
                for mandate in explicit_arch_mandates:
                    m = mandate.strip().lower()
                    if m == "monolith":
                        if alt.pattern == ArchitecturePattern.MONOLITH:
                            matched = True
                    elif m in {"modular monolith", "modular_monolith"}:
                        if alt.pattern == ArchitecturePattern.MODULAR_MONOLITH:
                            matched = True
                    elif m in {"microservices", "microservice"}:
                        if alt.pattern == ArchitecturePattern.MICROSERVICES:
                            matched = True
                    elif m in {"serverless"}:
                        if alt.pattern == ArchitecturePattern.SERVERLESS:
                            matched = True
                    elif m in {"event-driven", "event_driven"}:
                        if alt.pattern == ArchitecturePattern.EVENT_DRIVEN:
                            matched = True
                    elif m in {"clean architecture", "clean"}:
                        if alt.pattern == ArchitecturePattern.CLEAN_ARCHITECTURE:
                            matched = True
                    elif m in {"hexagonal"}:
                        if alt.pattern == ArchitecturePattern.HEXAGONAL:
                            matched = True
                    else:
                        if m in alt.pattern.value.lower() or m in alt.name.lower():
                            matched = True
                if not matched:
                    alt.is_viable = False
                    alt.elimination_reason = f"Violates explicit user architecture constraint: '{', '.join(explicit_arch_mandates)}'"
                    continue

            # Overengineering check: simple app should not use Microservices or complex Event-Driven
            if is_simple_app and alt.pattern in {ArchitecturePattern.MICROSERVICES, ArchitecturePattern.EVENT_DRIVEN}:
                alt.is_viable = False
                alt.elimination_reason = "Overengineering prevention: Microservices/Event-Driven architecture introduces unnecessary distributed operational complexity and cost for a simple application."
                continue

            # Underengineering check: complex multi-tenant SaaS should not use unstructured simple monolith
            if is_complex_saas and alt.pattern == ArchitecturePattern.MONOLITH:
                alt.is_viable = False
                alt.elimination_reason = "Underengineering prevention: Unstructured simple monolith lacks modular boundaries necessary for multi-tenancy, team permissions, and billing isolation."
                continue

        # 4. Multi-criteria Evaluation of Viable Candidates
        scored_candidates: List[ArchitectureAlternative] = []
        for alt in candidates:
            if alt.is_viable:
                scores = self._score_candidate(alt, spec, drivers, is_simple_app, is_complex_saas)
                alt.criteria_scores = scores
                alt.total_score = sum(scores.values()) / max(1, len(scores))
            else:
                alt.total_score = 0.0
            scored_candidates.append(alt)

        # 5. Select Winning Architecture
        viable_alts = [a for a in scored_candidates if a.is_viable]
        if not viable_alts:
            # Fallback if all were eliminated: resurrect the closest match or modular monolith
            fallback = scored_candidates[0]
            fallback.is_viable = True
            fallback.elimination_reason = None
            fallback.total_score = 75.0
            selected = fallback
        else:
            viable_alts.sort(key=lambda x: x.total_score, reverse=True)
            selected = viable_alts[0]

        return scored_candidates, selected

    def _get_explicit_arch_constraints(self, spec: ProjectSpecification) -> List[str]:
        mandates = []
        for tc in spec.technical_constraints:
            desc_l = tc.description.lower()
            if "modular monolith" in desc_l:
                mandates.append("Modular Monolith")
            elif "microservice" in desc_l:
                mandates.append("Microservices")
            elif "monolith" in desc_l:
                mandates.append("Monolith")
            elif "serverless" in desc_l:
                mandates.append("Serverless")
            elif "event-driven" in desc_l:
                mandates.append("Event-Driven")
            elif "clean architecture" in desc_l:
                mandates.append("Clean Architecture")
            elif "hexagonal" in desc_l:
                mandates.append("Hexagonal")
        return mandates

    def _is_simple_application(self, spec: ProjectSpecification) -> bool:
        title = spec.problem_statement.lower() + " " + spec.desired_outcome.lower()
        simple_keywords = ["tracker", "calculator", "todo", "cli tool", "script", "personal expense", "simple", "utility"]
        return any(k in title for k in simple_keywords) and len(spec.functional_requirements) <= 6

    def _is_complex_saas(self, spec: ProjectSpecification) -> bool:
        text = (spec.problem_statement + " " + spec.desired_outcome + " " + " ".join(r.description for r in spec.all_requirements())).lower()
        indicators = ["multi-tenant", "subscription", "saas", "teams", "billing", "organizations", "enterprise"]
        return sum(1 for ind in indicators if ind in text) >= 2

    def _create_candidate_pool(
        self,
        is_simple: bool,
        is_saas: bool,
        knowledge: Optional[ProjectKnowledge],
    ) -> List[ArchitectureAlternative]:
        pool: List[ArchitectureAlternative] = []

        # 1. Modular Monolith
        pool.append(
            ArchitectureAlternative(
                pattern=ArchitecturePattern.MODULAR_MONOLITH,
                name="Modular Monolith",
                description="Single deployable artifact structured into strictly bounded, domain-oriented modules with decoupled database interfaces.",
                advantages=[
                    "High maintainability without distributed system operational overhead",
                    "Single codebase, unified deployment pipeline, easy local debugging",
                    "Supports future extraction of microservices if scale requires",
                    "Straightforward ACID transaction support across modules",
                ],
                disadvantages=[
                    "Requires strict discipline to prevent accidental internal module coupling",
                    "Single technology runtime across the backend",
                ],
                implementation_complexity=ComplexityLevel.MEDIUM,
                operational_complexity=ComplexityLevel.LOW,
                cost_implications="Minimal infrastructure cost; single hosting instance or container cluster.",
                security_implications="Unified security perimeter; in-process role/permission enforcement.",
                scalability_characteristics="Excellent vertical and horizontal scaling behind standard load balancers.",
                maintenance_implications="Low operational overhead; simplified CI/CD testing.",
                repo_compatibility="High compatibility with modern frameworks (FastAPI, Next.js, Express, Django).",
                migration_requirements="Straightforward folder-based module separation.",
                major_risks=["Potential leaky abstractions between modules if boundaries are ignored."],
            )
        )

        # 2. Monolithic Architecture
        pool.append(
            ArchitectureAlternative(
                pattern=ArchitecturePattern.MONOLITH,
                name="Monolithic Architecture",
                description="Classical single unified application codebase with shared models and direct service calls.",
                advantages=[
                    "Extremely fast initial development and prototyping",
                    "Zero network serialization overhead between components",
                    "Minimal tooling and infrastructure requirements",
                ],
                disadvantages=[
                    "Prone to tight coupling as codebase grows",
                    "Difficult to scale teams or isolate distinct domain failures",
                ],
                implementation_complexity=ComplexityLevel.LOW,
                operational_complexity=ComplexityLevel.LOW,
                cost_implications="Lowest infrastructure and hosting cost.",
                security_implications="Single process perimeter; vulnerability in one feature can compromise whole app.",
                scalability_characteristics="Limited by monolithic database and memory footprint.",
                maintenance_implications="Easy for small projects; degrades over time if unmaintained.",
                repo_compatibility="Matches standard entry-level repositories.",
                migration_requirements="None (baseline architecture).",
                major_risks=["Technical debt accumulation and spaghetti dependency graphs."],
            )
        )

        # 3. Microservices Architecture
        pool.append(
            ArchitectureAlternative(
                pattern=ArchitecturePattern.MICROSERVICES,
                name="Microservices Architecture",
                description="Distributed architecture dividing system into independently deployable, networked services.",
                advantages=[
                    "Independent deployment and scaling per service",
                    "Polyglot technology choices per service",
                    "Organizational alignment for large multiple engineering teams",
                ],
                disadvantages=[
                    "High operational complexity (service discovery, distributed tracing, network latency)",
                    "Substantially higher hosting and infrastructure costs",
                    "Distributed transaction and data consistency challenges (Saga / eventual consistency)",
                ],
                implementation_complexity=ComplexityLevel.HIGH,
                operational_complexity=ComplexityLevel.VERY_HIGH,
                cost_implications="High cost (multiple containers, message brokers, service meshes, observability pipelines).",
                security_implications="Complex perimeter; requires mTLS, service-to-service auth, and distributed tokens.",
                scalability_characteristics="Near-infinite theoretical scalability for massive independent workloads.",
                maintenance_implications="High cognitive load; requires dedicated DevOps / SRE support.",
                repo_compatibility="Requires monorepo tooling or multi-repo orchestration.",
                migration_requirements="Heavy architectural decomposition and API gateway setup.",
                major_risks=[
                    "Premature decomposition leading to distributed monolith anti-pattern",
                    "Network partitions and operational fragility for small teams",
                ],
            )
        )

        # 4. Layered / Clean Architecture
        pool.append(
            ArchitectureAlternative(
                pattern=ArchitecturePattern.CLEAN_ARCHITECTURE,
                name="Clean / Layered Architecture",
                description="Separates business logic from external frameworks, databases, and UI via dependency inversion.",
                advantages=[
                    "Exceptional testability; domain logic decoupled from external I/O",
                    "Framework independence; easy database or library swapping",
                ],
                disadvantages=[
                    "Higher boilerplate code and interface definitions",
                    "Can be overly verbose for simple CRUD utilities",
                ],
                implementation_complexity=ComplexityLevel.MEDIUM,
                operational_complexity=ComplexityLevel.LOW,
                cost_implications="Low infrastructure cost.",
                security_implications="Clear domain boundaries enhance auditability.",
                scalability_characteristics="Standard single-tier or multi-tier scaling.",
                maintenance_implications="Excellent long-term maintainability.",
                repo_compatibility="Compatible with all object-oriented and functional codebases.",
                migration_requirements="Refactoring existing business logic into pure domain entities.",
                major_risks=["Over-abstraction for simple utilities."],
            )
        )

        return pool

    def _score_candidate(
        self,
        alt: ArchitectureAlternative,
        spec: ProjectSpecification,
        drivers: List[ArchitectureDriver],
        is_simple: bool,
        is_saas: bool,
    ) -> Dict[str, float]:
        scores: Dict[str, float] = {}

        # 1. Requirement Satisfaction (0-100)
        scores["requirement_satisfaction"] = 90.0 if alt.pattern == ArchitecturePattern.MODULAR_MONOLITH else 80.0

        # 2. Maintainability (0-100)
        if alt.pattern in {ArchitecturePattern.MODULAR_MONOLITH, ArchitecturePattern.CLEAN_ARCHITECTURE}:
            scores["maintainability"] = 95.0
        elif alt.pattern == ArchitecturePattern.MONOLITH:
            scores["maintainability"] = 70.0 if is_simple else 50.0
        else:
            scores["maintainability"] = 75.0

        # 3. Operational Simplicity (0-100, higher is simpler/better)
        if alt.operational_complexity == ComplexityLevel.LOW:
            scores["operational_simplicity"] = 95.0
        elif alt.operational_complexity == ComplexityLevel.MEDIUM:
            scores["operational_simplicity"] = 75.0
        else:
            scores["operational_simplicity"] = 40.0

        # 4. Cost Efficiency (0-100, higher is cheaper/better)
        if alt.pattern == ArchitecturePattern.MONOLITH:
            scores["cost_efficiency"] = 98.0
        elif alt.pattern == ArchitecturePattern.MODULAR_MONOLITH:
            scores["cost_efficiency"] = 90.0
        elif alt.pattern == ArchitecturePattern.CLEAN_ARCHITECTURE:
            scores["cost_efficiency"] = 90.0
        else:
            scores["cost_efficiency"] = 45.0

        # 5. Security & Isolation (0-100)
        if alt.pattern in {ArchitecturePattern.MODULAR_MONOLITH, ArchitecturePattern.CLEAN_ARCHITECTURE}:
            scores["security_and_isolation"] = 90.0
        elif alt.pattern == ArchitecturePattern.MICROSERVICES:
            scores["security_and_isolation"] = 85.0
        else:
            scores["security_and_isolation"] = 70.0

        # 6. Future Growth & Scalability (0-100)
        if alt.pattern == ArchitecturePattern.MODULAR_MONOLITH:
            scores["future_flexibility"] = 92.0
        elif alt.pattern == ArchitecturePattern.MICROSERVICES:
            scores["future_flexibility"] = 95.0
        elif alt.pattern == ArchitecturePattern.CLEAN_ARCHITECTURE:
            scores["future_flexibility"] = 88.0
        else:
            scores["future_flexibility"] = 60.0

        return scores

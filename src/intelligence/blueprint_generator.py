"""
blueprint_generator.py -- Architecture Blueprint Generator & Migration Planner.

Phase 11.2: Architecture & Technical Decision Intelligence.
Assembles the complete 25-section machine-readable ArchitectureBlueprint,
generates migration and rollback strategies for existing repositories,
calculates FinOps cost estimates, and creates nontechnical explanations.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.architecture_models import (
    ArchitectureAlternative,
    ArchitectureBlueprint,
    ArchitectureDecisionRecord,
    ArchitectureDriver,
    ComponentDesign,
    CostArchitectureEstimate,
    CostConfidence,
    DataArchitectureDesign,
    DecisionApprovalStatus,
    MigrationPlan,
    NontechnicalExplanation,
    SecurityArchitectureDesign,
)
from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import ProjectSpecification


class ArchitectureBlueprintGenerator:
    """
    Compiles drivers, alternatives, ADRs, component models, and migration paths
    into a comprehensive, actionable ArchitectureBlueprint.
    """

    def __init__(self, workspace_root: str = "", project_name: str = "") -> None:
        self.workspace_root = workspace_root
        self.project_name = project_name

    def generate_blueprint(
        self,
        spec: ProjectSpecification,
        selected_alt: ArchitectureAlternative,
        all_alts: List[ArchitectureAlternative],
        drivers: List[ArchitectureDriver],
        adrs: List[ArchitectureDecisionRecord],
        tech_stack: Dict[str, str],
        data_arch: DataArchitectureDesign,
        sec_arch: SecurityArchitectureDesign,
        knowledge: Optional[ProjectKnowledge] = None,
    ) -> ArchitectureBlueprint:
        # 1. Component Architecture & Boundaries
        components = self._derive_component_designs(spec, selected_alt, tech_stack)

        # 2. Dependency Relationships
        dep_relationships = self._derive_dependency_relationships(components)

        # 3. Data-Flow Architecture
        data_flows = [
            "Client HTTP Request -> Reverse Proxy / Gateway -> Authentication & RBAC Middleware",
            "Authenticated Context -> Route Controller / API Handler -> Business Service Layer",
            "Business Service Layer -> Repository Layer / Unit of Work -> Database Engine",
            "Database Result -> Response Serializer / DTO -> Client JSON Response",
        ]

        # 4. Migration Plan for Existing Repositories
        migration_plan = self._derive_migration_plan(spec, tech_stack, selected_alt, knowledge)

        # 5. Cost Considerations (FinOps)
        cost_estimate = self._estimate_architecture_costs(spec, selected_alt, tech_stack)

        # 6. Nontechnical Explanation
        nontech_explanation = self._generate_nontechnical_explanation(spec, selected_alt, tech_stack)

        # 7. Traceability Matrix
        traceability = self._build_traceability(spec, components, adrs)

        # 8. Known Risks & Assumptions
        known_risks = list(selected_alt.major_risks)
        known_risks.extend(sec_arch.security_risks)

        assumptions = list(spec.assumptions_and_defaults)
        assumptions.append(f"System deployed as a {selected_alt.name} with standard containerization.")
        assumptions.append("Relational database provides single source of truth for transactional state.")

        unresolved = [u.decision_topic for u in spec.unresolved_decisions if u.status != "RESOLVED"]

        # Check approval status: all ADRs approved?
        is_blueprint_approved = all(adr.approval_status == DecisionApprovalStatus.APPROVED for adr in adrs)

        return ArchitectureBlueprint(
            spec_id=spec.spec_id,
            version=1,
            project_name=self.project_name or spec.project_name,
            workspace_root=self.workspace_root or spec.workspace_root,
            # Section 1: Overview
            architecture_overview=(
                f"The system is designed as an industrial-grade {selected_alt.name} satisfying all explicit "
                f"functional requirements and quality drivers for '{spec.desired_outcome or spec.problem_statement}' ({spec.project_name}). "
                f"It couples a modern {tech_stack.get('backend', 'backend')} service layer with a robust "
                f"{tech_stack.get('database', 'database')} persistence tier while enforcing strict security boundaries."
            ),
            # Section 2: Style
            architecture_style=selected_alt.pattern,
            # Section 3: Technology Stack
            technology_stack=tech_stack,
            # Section 4-6: Components & Boundaries
            components=components,
            # Section 7: Dependency Relationships
            dependency_relationships=dep_relationships,
            # Section 8: Data-Flow Architecture
            data_flow_architecture=data_flows,
            # Section 9: API Architecture
            api_architecture=f"RESTful JSON over HTTPS using {tech_stack.get('backend', 'FastAPI')} with OpenAPI v3 auto-documentation.",
            # Section 10: Database Architecture
            database_architecture=data_arch,
            # Section 11: Security Architecture
            security_architecture=sec_arch,
            # Section 12: Security Boundaries
            security_boundaries=[
                "Perimeter: HTTPS/TLS termination and WAF/Rate Limiting at reverse proxy.",
                "Application: In-process RBAC authorization gate validating claims on every request.",
                "Storage: Database connection restricted to internal application network/VPC.",
            ],
            # Section 13: Background Processing
            background_processing=f"Asynchronous task queue using {tech_stack.get('background_processing', 'Asyncio Worker')}.",
            # Section 14: External Integrations
            external_integrations=list(spec.integration_requirements) or ["Payment Gateway (e.g. Stripe)", "Email Notification Service"],
            # Section 15: Error-handling Strategy
            error_handling_strategy="RFC 7807 Problem Details structured JSON error formatting with centralized exception middleware.",
            # Section 16: Caching Strategy
            caching_strategy=data_arch.caching_strategy,
            # Section 17: Observability Strategy
            observability_strategy="Structured JSON logging with request correlation IDs, Prometheus metrics, and OpenTelemetry distributed spans.",
            # Section 18: Testing Strategy
            testing_strategy="Pytest automated unit test suite with 80%+ branch coverage, integration tests using test database containers.",
            # Section 19: Deployment Architecture
            deployment_architecture=f"Multi-stage Docker container deployed behind an NGINX reverse proxy or AWS ECS / GCP Cloud Run.",
            # Section 20: Scaling Strategy
            scaling_strategy="Horizontal stateless container scaling behind load balancer; database read-replica offloading if required.",
            # Section 21: Backup and Recovery
            backup_and_recovery=data_arch.backup_recovery,
            # Section 22: Cost Considerations
            cost_considerations=cost_estimate,
            # Section 23: Known Risks
            known_risks=known_risks,
            # Section 24: Unresolved Decisions
            unresolved_decisions=unresolved,
            # Section 25: Architectural Assumptions
            architectural_assumptions=assumptions,
            drivers=drivers,
            alternatives_evaluated=all_alts,
            adrs=adrs,
            migration_plan=migration_plan,
            nontechnical_explanation=nontech_explanation,
            traceability_matrix=traceability,
            is_approved=is_blueprint_approved,
        )

    def _derive_component_designs(
        self,
        spec: ProjectSpecification,
        alt: ArchitectureAlternative,
        tech_stack: Dict[str, str],
    ) -> List[ComponentDesign]:
        comps: List[ComponentDesign] = []

        # 1. API / Presentation Component
        comps.append(
            ComponentDesign(
                name="api_gateway_layer",
                category="presentation",
                responsibilities=[
                    "Route handling and HTTP request parsing",
                    "Input schema validation and response serialization",
                    "Rate limiting and CORS headers enforcement",
                ],
                boundaries="Public-facing HTTP layer; invokes domain service components only via typed interfaces.",
                internal_deps=["domain_service_core", "security_auth_module"],
                external_deps=[tech_stack.get("backend", "FastAPI")],
                data_ownership=[],
            )
        )

        # 2. Security & Auth Module
        comps.append(
            ComponentDesign(
                name="security_auth_module",
                category="security",
                responsibilities=[
                    "User identity authentication and password verification",
                    "JWT token generation, signature verification, and revocation",
                    "Role-based permission policy enforcement",
                ],
                boundaries="Internal security boundary; governs access to all domain operations.",
                internal_deps=["data_access_persistence"],
                external_deps=["bcrypt / cryptography", "pyjwt"],
                data_ownership=["users", "roles", "permissions", "sessions"],
            )
        )

        # 3. Domain Service Core
        comps.append(
            ComponentDesign(
                name="domain_service_core",
                category="business_logic",
                responsibilities=[
                    "Core business workflow execution and transaction coordination",
                    "Domain validation rules and invariant enforcement",
                    "Event dispatching for asynchronous side-effects",
                ],
                boundaries="Encapsulates application business rules; decoupled from HTTP and database drivers.",
                internal_deps=["data_access_persistence"],
                external_deps=[],
                data_ownership=[e.lower() for e in spec.data_requirements[:4]],
            )
        )

        # 4. Data Access & Persistence
        comps.append(
            ComponentDesign(
                name="data_access_persistence",
                category="persistence",
                responsibilities=[
                    "Database connection pooling and lifecycle management",
                    "Object-relational mapping (ORM) and SQL query generation",
                    "Schema migrations and transaction rollbacks",
                ],
                boundaries="Encapsulates all direct database I/O.",
                internal_deps=[],
                external_deps=[tech_stack.get("database", "PostgreSQL"), "SQLAlchemy / ORM"],
                data_ownership=["All database tables and migrations"],
            )
        )

        return comps

    def _derive_dependency_relationships(self, components: List[ComponentDesign]) -> List[str]:
        rels = []
        for c in components:
            for dep in c.internal_deps:
                rels.append(f"{c.name} ---> {dep}")
        return rels

    def _derive_migration_plan(
        self,
        spec: ProjectSpecification,
        tech_stack: Dict[str, str],
        selected_alt: ArchitectureAlternative,
        knowledge: Optional[ProjectKnowledge],
    ) -> MigrationPlan:
        is_existing_repo = False
        if knowledge:
            if knowledge.frameworks or knowledge.config_files or len(knowledge.file_mtimes) > 0:
                is_existing_repo = True

        if not is_existing_repo:
            # Greenfield project
            return MigrationPlan(
                is_migration_needed=False,
                existing_state="Empty or initial greenfield project workspace",
                target_state=f"Fresh setup of {selected_alt.name} using {tech_stack.get('backend', 'backend')}",
                required_changes=["Initialize repository directories and dependency manifests."],
                affected_components=[],
                compatibility_risks=[],
                migration_order=["Scaffold project layout", "Configure manifests", "Implement core baseline"],
                testing_requirements=["Run initial test suite verify clean setup."],
                rollback_strategy="Delete newly initialized scaffold files or reset git commit.",
            )

        # Brownfield existing project
        existing_fnames = [f.name for f in knowledge.frameworks] if (knowledge and knowledge.frameworks) else (knowledge.config_files if knowledge and knowledge.config_files else ["Configured codebase"])
        existing_desc = f"Existing repository with components/configurations: {', '.join(existing_fnames)}"
        target_desc = f"Harmonized {selected_alt.name} integrating existing code with new requirements"

        changes = [
            f"Preserve existing verified components: {', '.join(knowledge.architecture_map.components.keys()) if (knowledge and knowledge.architecture_map) else 'core'}",
            f"Add new modular boundaries conforming to {selected_alt.name}",
            "Introduce versioned database migrations for new entity schemas",
        ]

        order = [
            "Step 1: Verify existing test suite passes baseline",
            "Step 2: Create new module packages without modifying existing components",
            "Step 3: Run database migration in sandbox environment",
            "Step 4: Execute regression suite across existing and new components",
        ]

        rollback = (
            "Git branch reversal (`git revert` / `git checkout`); rollback database schema "
            "using down-migration scripts (`alembic downgrade -1`). Existing verified components remain unmodified."
        )

        return MigrationPlan(
            is_migration_needed=True,
            existing_state=existing_desc,
            target_state=target_desc,
            required_changes=changes,
            affected_components=list(knowledge.architecture_map.components.keys())[:3] if (knowledge and knowledge.architecture_map and knowledge.architecture_map.components) else ["core"],
            compatibility_risks=["Potential schema collision if new models reuse existing table names."],
            migration_order=order,
            testing_requirements=["Run full system regression suite across all milestone suites before and after."],
            rollback_strategy=rollback,
        )

    def _estimate_architecture_costs(
        self,
        spec: ProjectSpecification,
        alt: ArchitectureAlternative,
        tech_stack: Dict[str, str],
    ) -> CostArchitectureEstimate:
        # FinOps conservative estimation
        is_simple = any(k in spec.problem_statement.lower() for k in ["simple", "personal", "tracker", "todo"])
        if is_simple:
            return CostArchitectureEstimate(
                total_estimated_monthly_usd=0.0,
                cost_confidence=CostConfidence.VERIFIED,
                breakdown={
                    "hosting": "$0.00 (Local / Free Tier)",
                    "database": "$0.00 (Embedded SQLite / Local)",
                    "external_apis": "$0.00",
                },
                cost_drivers=["Local execution only; zero recurring cloud infrastructure cost."],
                finops_governance_notes="Zero cloud expenditure footprint. Conforms to Phase 9.7 free-tier guardrails.",
            )

        # SaaS / Production estimated cost
        return CostArchitectureEstimate(
            total_estimated_monthly_usd=35.0,
            cost_confidence=CostConfidence.ESTIMATED,
            breakdown={
                "compute_container": "$15.00 - $25.00 / mo (Single node / AWS ECS Fargate or DigitalOcean droplet)",
                "database_managed": "$15.00 - $30.00 / mo (Managed PostgreSQL 1GB RAM)",
                "caching_redis": "$0.00 - $10.00 / mo (In-process or shared Redis)",
                "object_storage": "$1.00 - $5.00 / mo (S3 / Cloudflare R2 for asset storage)",
            },
            cost_drivers=[
                "Managed PostgreSQL instance pricing",
                "Container vCPU / RAM runtime footprint",
                "Egress bandwidth for asset downloads",
            ],
            finops_governance_notes="Cost estimated based on standard cloud provider baselines. Actual spend subject to user traffic volume.",
        )

    def _generate_nontechnical_explanation(
        self,
        spec: ProjectSpecification,
        alt: ArchitectureAlternative,
        tech_stack: Dict[str, str],
    ) -> NontechnicalExplanation:
        style_name = alt.name
        simple_summary = (
            f"We recommend organizing your application as a {style_name}. "
            "This means all features run together in a clean, organized package that is fast to build, "
            "easy to test, and cheap to run, while still keeping different sections (like user accounts, "
            "products, and payments) neatly separated."
        )

        why_it_fits = (
            f"It directly satisfies your goals for '{spec.project_name}' without the unnecessary expense "
            "and headaches of running dozens of separate cloud servers."
        )

        advantages = [
            "Fast development: easier to build, debug, and deliver features quickly.",
            "Lower cost: runs on simple, cost-effective infrastructure.",
            "Future-proof: clean internal organization allows splitting off pieces later if your product grows rapidly.",
        ]

        tradeoffs = [
            "Requires discipline to keep code clean and organized within its folders.",
            "Entire application is updated together rather than piece-by-piece.",
        ]

        return NontechnicalExplanation(
            recommended_architecture=style_name,
            simple_summary=simple_summary,
            why_it_fits=why_it_fits,
            main_advantages=advantages,
            important_tradeoffs=tradeoffs,
            expected_complexity="Low to Moderate (Ideal for initial launch & sustainable growth)",
            alternatives_summary="We evaluated Microservices (too complex and expensive for this stage) and simple Monolith (risks messy code over time).",
        )

    def _build_traceability(
        self,
        spec: ProjectSpecification,
        components: List[ComponentDesign],
        adrs: List[ArchitectureDecisionRecord],
    ) -> Dict[str, List[str]]:
        trace: Dict[str, List[str]] = {}
        for req in spec.all_requirements():
            mapped_items = []
            # Match with components
            for c in components:
                if any(w in req.description.lower() for w in c.name.split("_")):
                    mapped_items.append(f"component:{c.name}")
            # Match with ADRs
            for adr in adrs:
                if req.id in adr.related_requirement_ids:
                    mapped_items.append(f"adr:{adr.id}")

            if not any(item.startswith("component:") for item in mapped_items):
                mapped_items.append(f"component:{components[0].name if components else 'domain_service_core'}")
            if not any(item.startswith("adr:") for item in mapped_items):
                mapped_items.append(f"adr:{adrs[0].id if adrs else 'ADR-001'}")

            trace[req.id] = mapped_items
        return trace

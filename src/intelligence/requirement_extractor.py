"""
requirement_extractor.py -- Requirement Extraction Engine.

Phase 11.1: Requirement Understanding & Discovery.
Parses natural language prompts from both technical and nontechnical users,
extracting functional requirements, technical constraints, workflows,
user roles, integrations, and acceptance criteria without hallucinations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.requirement_models import (
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
    RequirementPriority,
    RequirementStatus,
    UserPersonaRole,
    UserWorkflow,
)

# Known technologies & architectural terms
KNOWN_FRAMEWORKS_AND_TECHS = {
    "next.js": ("Next.js", "frontend_framework"),
    "nextjs": ("Next.js", "frontend_framework"),
    "react": ("React", "frontend_library"),
    "vue": ("Vue.js", "frontend_framework"),
    "angular": ("Angular", "frontend_framework"),
    "svelte": ("Svelte", "frontend_framework"),
    "fastapi": ("FastAPI", "backend_framework"),
    "flask": ("Flask", "backend_framework"),
    "django": ("Django", "backend_framework"),
    "express": ("Express", "backend_framework"),
    "nestjs": ("NestJS", "backend_framework"),
    "spring": ("Spring Boot", "backend_framework"),
    "gin": ("Gin", "backend_framework"),
    "postgresql": ("PostgreSQL", "database"),
    "postgres": ("PostgreSQL", "database"),
    "mysql": ("MySQL", "database"),
    "sqlite": ("SQLite", "database"),
    "mongodb": ("MongoDB", "database"),
    "redis": ("Redis", "cache_datastore"),
    "jwt": ("JWT Authentication", "security"),
    "oauth": ("OAuth 2.0", "security"),
    "docker": ("Docker", "deployment"),
    "kubernetes": ("Kubernetes", "deployment"),
    "k8s": ("Kubernetes", "deployment"),
    "graphql": ("GraphQL", "api_paradigm"),
    "rest": ("REST API", "api_paradigm"),
    "grpc": ("gRPC", "api_paradigm"),
    "tailwind": ("Tailwind CSS", "styling"),
}

KNOWN_ARCHITECTURES = {
    "modular monolith": "Modular Monolith",
    "monolith": "Monolithic Architecture",
    "microservices": "Microservices Architecture",
    "serverless": "Serverless Architecture",
    "event-driven": "Event-Driven Architecture",
    "cqrs": "CQRS Architecture",
    "mvc": "MVC Architecture",
    "static": "Static Architecture",
    "client-only": "Client-Only Architecture",
}

DOMAIN_PATTERNS = {
    "ecommerce": {
        "keywords": ["ecommerce", "e-commerce", "store", "shop", "amazon", "marketplace", "checkout", "cart"],
        "default_roles": [
            ("Customer", "Browse items, manage cart, place orders, view order history", ["browse", "purchase", "profile_edit"]),
            ("Admin", "Manage catalog, inventory, pricing, and view customer orders", ["manage_catalog", "view_orders", "manage_users"]),
        ],
        "default_workflows": [
            ("Order Placement", "Customer", "Checkout button clicked", [
                "Validate items in shopping cart",
                "Collect shipping and billing details",
                "Authorize payment via payment gateway",
                "Create order record and decrement inventory",
                "Send order confirmation email and display receipt"
            ], "Order confirmed and inventory reserved"),
        ],
        "common_features": [
            ("Product Catalog", "Browse, search, and filter available products", RequirementCategory.FUNCTIONAL),
            ("Shopping Cart", "Add, update quantities, and remove items before checkout", RequirementCategory.FUNCTIONAL),
            ("Checkout & Payments", "Secure payment authorization and order generation", RequirementCategory.FUNCTIONAL),
            ("Order History", "Review past orders and track shipment status", RequirementCategory.FUNCTIONAL),
        ],
        "material_decisions": [
            ("Marketplace Model", "Is this a single-vendor direct store or a multi-vendor marketplace?", ["Single-Vendor Store", "Multi-Vendor Marketplace"]),
            ("Payment Gateway", "Which payment provider should be integrated?", ["Stripe", "PayPal", "Razorpay", "Mock Provider for Dev"]),
            ("Application Lifecycle", "Is this a rapid prototype / MVP or a production-ready application?", ["MVP / Prototype", "Production-Ready"]),
        ],
    },
    "saas": {
        "keywords": ["saas", "subscription", "tenant", "organization", "multi-tenant", "billing"],
        "default_roles": [
            ("Tenant Admin", "Manages workspace team members, billing plan, and settings", ["manage_team", "manage_billing"]),
            ("Member", "Collaborates on organization assets and projects", ["create_assets", "view_reports"]),
        ],
        "default_workflows": [
            ("Tenant Onboarding", "New User", "Sign up with company domain", [
                "Verify email address",
                "Create tenant / organization entity",
                "Assign administrator role",
                "Prompt for initial team invitations"
            ], "Organization workspace activated"),
        ],
        "common_features": [
            ("Organization Management", "Multi-tenant workspace isolation and team member invitations", RequirementCategory.FUNCTIONAL),
            ("Subscription Billing", "Tiered billing, usage metrics, and subscription renewal", RequirementCategory.FUNCTIONAL),
        ],
        "material_decisions": [
            ("Multi-tenancy Isolation", "Should multi-tenancy be isolated at row-level (tenant_id) or separate databases?", ["Shared DB with Row-Level tenant_id", "Isolated DB per Tenant"]),
        ],
    },
    "api_service": {
        "keywords": ["api", "rest api", "backend", "endpoints", "microservice", "service"],
        "default_roles": [
            ("API Consumer", "Accesses endpoints using API keys or JWT tokens", ["read_endpoints", "write_endpoints"]),
            ("System Admin", "Monitors API health, rate limits, and client keys", ["manage_keys", "view_telemetry"]),
        ],
        "default_workflows": [
            ("API Request Authentication", "Client Application", "HTTP request received with Authorization header", [
                "Inspect Bearer token or API key",
                "Validate cryptographic signature and expiration",
                "Authorize requested route action",
                "Forward request to service controller"
            ], "Authenticated request handled"),
        ],
        "common_features": [
            ("Health & Readiness Probes", "Standard /healthz and /readyz endpoints for monitoring", RequirementCategory.FUNCTIONAL),
            ("Input Validation", "Strict request schema validation and standardized error formatting", RequirementCategory.NONFUNCTIONAL),
        ],
        "material_decisions": [
            ("Authentication Scheme", "Which authentication scheme is required for API access?", ["JWT Bearer Tokens", "API Keys", "mTLS", "Public"]),
        ],
    },
}


@dataclass
class ExtractedRequirementsBundle:
    """Raw extraction bundle prior to repository alignment and classification."""
    user_prompt: str
    communication_style: str  # TECHNICAL, NON_TECHNICAL, HYBRID
    business_objective: str
    problem_statement: str
    desired_outcome: str
    explicit_technologies: List[Tuple[str, str]] = field(default_factory=list)
    explicit_architectures: List[str] = field(default_factory=list)
    requirements: List[RequirementItem] = field(default_factory=list)
    user_roles: List[UserPersonaRole] = field(default_factory=list)
    workflows: List[UserWorkflow] = field(default_factory=list)
    data_entities: List[str] = field(default_factory=list)
    integrations: List[str] = field(default_factory=list)
    potential_decisions: List[Tuple[str, str, List[str]]] = field(default_factory=list)
    scope_in: List[str] = field(default_factory=list)
    scope_out: List[str] = field(default_factory=list)


class RequirementExtractor:
    """
    Structured Requirement Extraction Engine.
    Interprets user prompt, identifies domains, extracts explicit tech constraints,
    and isolates inferred requirements with traceable evidence sources.
    """

    def __init__(self) -> None:
        pass

    def extract(self, prompt: str) -> ExtractedRequirementsBundle:
        clean_prompt = prompt.strip()
        lowered = clean_prompt.lower()

        # 1. Identify explicit technologies and architectures
        explicit_techs = self._extract_technologies(lowered)
        explicit_archs = self._extract_architectures(lowered)

        # 2. Determine communication style
        style = self._determine_style(explicit_techs, explicit_archs, clean_prompt)

        # 3. Detect domain (ecommerce, saas, api_service, or generic)
        domain_key, domain_info = self._detect_domain(lowered)

        # 4. Formulate problem statement and desired outcome
        prob_stmt, outcome = self._formulate_objective(clean_prompt, domain_key)

        req_items: List[RequirementItem] = []
        counter = 1

        # 5. Add Explicit Technical Constraints
        for tech_name, tech_cat in explicit_techs:
            req_items.append(
                RequirementItem(
                    id=f"REQ-{counter:03d}",
                    description=f"Use {tech_name} for system {tech_cat.replace('_', ' ')}",
                    category=RequirementCategory.TECHNICAL_CONSTRAINT,
                    classification=RequirementClassification.EXPLICIT,
                    priority=RequirementPriority.CRITICAL,
                    status=RequirementStatus.ACCEPTED,
                    evidence_source=f'Direct user prompt constraint: "{tech_name}"',
                    acceptance_criteria=[
                        f"System codebase integrates and depends on {tech_name}",
                        f"Architecture adheres to standard {tech_name} idioms",
                    ],
                    rationale="Explicitly mandated by user specification",
                )
            )
            counter += 1

        for arch in explicit_archs:
            req_items.append(
                RequirementItem(
                    id=f"REQ-{counter:03d}",
                    description=f"Follow {arch} architectural pattern",
                    category=RequirementCategory.TECHNICAL_CONSTRAINT,
                    classification=RequirementClassification.EXPLICIT,
                    priority=RequirementPriority.CRITICAL,
                    status=RequirementStatus.ACCEPTED,
                    evidence_source=f'Direct user prompt constraint: "{arch}"',
                    acceptance_criteria=[
                        f"Directory layout and module boundaries reflect {arch}",
                    ],
                    rationale="Explicit architectural requirement",
                )
            )
            counter += 1

        # 6. Extract prompt-specific functional requirements
        prompt_reqs = self._extract_functional_from_prompt(clean_prompt, counter)
        req_items.extend(prompt_reqs)
        counter += len(prompt_reqs)

        # 7. Add domain-inferred baseline requirements (if nontechnical or domain matched)
        roles: List[UserPersonaRole] = []
        workflows: List[UserWorkflow] = []
        potential_decisions: List[Tuple[str, str, List[str]]] = []
        data_entities: List[str] = []
        integrations: List[str] = []

        if domain_info:
            # Add common domain features as inferred requirements
            for feat_name, feat_desc, feat_cat in domain_info.get("common_features", []):
                # Don't duplicate if already explicitly covered
                if not any(feat_name.lower() in r.description.lower() for r in req_items):
                    req_items.append(
                        RequirementItem(
                            id=f"REQ-{counter:03d}",
                            description=f"Implement {feat_name}: {feat_desc}",
                            category=feat_cat,
                            classification=RequirementClassification.REASONABLE_DEFAULT,
                            priority=RequirementPriority.HIGH,
                            status=RequirementStatus.PROPOSED,
                            evidence_source=f'Inferred from domain "{domain_key}"',
                            acceptance_criteria=[
                                f"{feat_name} functionality is accessible and verifiable via automated tests",
                            ],
                            rationale=f"Standard requirement for {domain_key} applications",
                        )
                    )
                    counter += 1

            # Default roles
            for rname, rdesc, perms in domain_info.get("default_roles", []):
                roles.append(UserPersonaRole(role_name=rname, description=rdesc, permissions=perms))

            # Default workflows
            wf_idx = 1
            for wfname, actor, trigger, steps, exp_out in domain_info.get("default_workflows", []):
                workflows.append(
                    UserWorkflow(
                        id=f"WF-{wf_idx:02d}",
                        name=wfname,
                        actor=actor,
                        trigger=trigger,
                        steps=steps,
                        expected_outcome=exp_out,
                    )
                )
                wf_idx += 1

            # Domain decisions
            potential_decisions.extend(domain_info.get("material_decisions", []))

            if domain_key == "ecommerce":
                data_entities.extend(["User", "Product", "Category", "Cart", "CartItem", "Order", "OrderItem", "Payment"])
                integrations.extend(["Payment Gateway", "Email Service"])
            elif domain_key == "saas":
                data_entities.extend(["User", "Organization", "Membership", "Subscription", "Invoice"])
                integrations.extend(["Stripe Billing", "OAuth Provider"])
            elif domain_key == "api_service":
                data_entities.extend(["ApiKey", "ClientSession", "AuditLog"])

        # If no explicit roles found, fallback to basic user
        if not roles:
            roles.append(UserPersonaRole(role_name="User", description="Standard application user", permissions=["standard_access"]))

        # Nonfunctional defaults
        req_items.append(
            RequirementItem(
                id=f"REQ-{counter:03d}",
                description="Secure credential storage & safe environment variable configuration",
                category=RequirementCategory.SECURITY,
                classification=RequirementClassification.REASONABLE_DEFAULT,
                priority=RequirementPriority.CRITICAL,
                status=RequirementStatus.ACCEPTED,
                evidence_source="Standard engineering security baseline",
                acceptance_criteria=[
                    "Zero credentials committed in source code",
                    "Sensitive configuration loaded via environment variables",
                ],
            )
        )
        counter += 1

        req_items.append(
            RequirementItem(
                id=f"REQ-{counter:03d}",
                description="Automated unit and integration test suite with high coverage",
                category=RequirementCategory.NONFUNCTIONAL,
                classification=RequirementClassification.REASONABLE_DEFAULT,
                priority=RequirementPriority.HIGH,
                status=RequirementStatus.ACCEPTED,
                evidence_source="Engineering quality baseline",
                acceptance_criteria=[
                    "Automated test runner executes without errors",
                    "Critical business paths covered by deterministic tests",
                ],
            )
        )

        return ExtractedRequirementsBundle(
            user_prompt=clean_prompt,
            communication_style=style,
            business_objective=clean_prompt,
            problem_statement=prob_stmt,
            desired_outcome=outcome,
            explicit_technologies=explicit_techs,
            explicit_architectures=explicit_archs,
            requirements=req_items,
            user_roles=roles,
            workflows=workflows,
            data_entities=data_entities,
            integrations=integrations,
            potential_decisions=potential_decisions,
            scope_in=[r.description for r in req_items if r.priority in {RequirementPriority.CRITICAL, RequirementPriority.HIGH}],
            scope_out=[],
        )

    def _extract_technologies(self, lowered: str) -> List[Tuple[str, str]]:
        found = []
        seen = set()
        for token, (canonical_name, category) in KNOWN_FRAMEWORKS_AND_TECHS.items():
            pattern = rf"\b{re.escape(token)}\b"
            if re.search(pattern, lowered):
                if canonical_name not in seen:
                    found.append((canonical_name, category))
                    seen.add(canonical_name)
        return found

    def _extract_architectures(self, lowered: str) -> List[str]:
        found = []
        for token, canonical_name in KNOWN_ARCHITECTURES.items():
            pattern = rf"\b{re.escape(token)}\b"
            if re.search(pattern, lowered):
                found.append(canonical_name)
        return found

    def _determine_style(
        self,
        techs: List[Tuple[str, str]],
        archs: List[str],
        prompt: str,
    ) -> str:
        if len(techs) >= 2 or archs:
            return "TECHNICAL"
        if not techs and not archs:
            return "NON_TECHNICAL"
        return "HYBRID"

    def _detect_domain(self, lowered: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        for dkey, dinfo in DOMAIN_PATTERNS.items():
            for kw in dinfo["keywords"]:
                if re.search(rf"\b{re.escape(kw)}\b", lowered):
                    return dkey, dinfo
        return None, None

    def _formulate_objective(self, prompt: str, domain_key: Optional[str]) -> Tuple[str, str]:
        lines = prompt.splitlines()
        first_line = lines[0].strip() if lines else (prompt.strip() or "General software engineering task")
        if domain_key == "ecommerce":
            return (
                "Need a secure, scalable ecommerce application allowing customers to purchase goods and administrators to manage catalog.",
                first_line,
            )
        elif domain_key == "saas":
            return (
                "Need a multi-tenant subscription software platform with team collaboration and billing.",
                first_line,
            )
        elif domain_key == "api_service":
            return (
                "Need a robust, high-performance API backend service with structured endpoints and authentication.",
                first_line,
            )
        return (
            f"Software engineering request: {first_line}",
            first_line,
        )

    def _extract_functional_from_prompt(self, prompt: str, start_counter: int) -> List[RequirementItem]:
        items = []
        c = start_counter
        # Scan for explicit functional sentences or clauses
        # Split on sentence boundaries, newlines and semicolons. Do NOT split
        # on every period: "src/email_validator.py" was previously shattered
        # into "Create src/email_validator" + "py with a function ...", which
        # invented requirements out of a path.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+|;", prompt) if s.strip()]
        for sent in sentences:
            lowered = sent.lower()
            verbs = ["add", "create", "build", "generate", "implement", "support", "allow", "enable", "include", "provide", "handle", "integrate", "update"]
            if any(verb in lowered for verb in verbs):
                # Avoid capturing the entire text if it's just a general statement
                if len(sent) > 10 and not any(sent.lower() == t[0].lower() for t in KNOWN_FRAMEWORKS_AND_TECHS.values()):
                    items.append(
                        RequirementItem(
                            id=f"REQ-{c:03d}",
                            description=sent,
                            category=RequirementCategory.FUNCTIONAL,
                            classification=RequirementClassification.EXPLICIT,
                            priority=RequirementPriority.HIGH,
                            status=RequirementStatus.ACCEPTED,
                            evidence_source=f'User stated: "{sent}"',
                            acceptance_criteria=[f"Verified implementation of: {sent}"],
                        )
                    )
                    c += 1
        return items

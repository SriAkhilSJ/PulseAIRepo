"""
data_and_security.py -- Data Architecture & Security Architecture Intelligence.

Phase 11.2: Architecture & Technical Decision Intelligence.
Synthesizes specialized data models, persistence strategies, tenant isolation boundaries,
and security architecture models conforming to Phases 9.4, 9.5, and 10.0 RBAC standards.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.architecture_models import (
    DataArchitectureDesign,
    SecurityArchitectureDesign,
)
from src.intelligence.requirement_models import (
    ProjectSpecification,
    RequirementCategory,
)


class DataArchitectureAnalyzer:
    """Derives data architecture, entity relationships, tenant isolation, and persistence strategies."""

    def analyze(self, spec: ProjectSpecification, tech_stack: Dict[str, str]) -> DataArchitectureDesign:
        entities = list(spec.data_requirements)
        if not entities:
            # Infer baseline entities from domain
            text = (spec.problem_statement + " " + spec.desired_outcome).lower()
            if "ecommerce" in text or "store" in text or "shop" in text:
                entities = ["User", "Product", "Cart", "CartItem", "Order", "OrderItem", "PaymentReceipt"]
            elif "saas" in text or "team" in text:
                entities = ["User", "Organization", "Membership", "Subscription", "Invoice", "AuditLog"]
            else:
                entities = ["User", "Account", "ResourceItem", "TransactionRecord"]

        relationships = []
        if "User" in entities and "Order" in entities:
            relationships.append("User (1) ---> (N) Order")
        if "Order" in entities and "OrderItem" in entities:
            relationships.append("Order (1) ---> (N) OrderItem")
        if "Product" in entities and "OrderItem" in entities:
            relationships.append("Product (1) ---> (N) OrderItem")
        if "Organization" in entities and "Membership" in entities:
            relationships.append("Organization (1) ---> (N) Membership")
        if not relationships:
            relationships.append(f"{entities[0]} (1) ---> (N) {entities[-1]}")

        db_choice = tech_stack.get("database", "PostgreSQL")
        is_saas = any("tenant" in e.lower() or "organization" in e.lower() for e in entities)
        tenant_strategy = "Row-level tenant_id scoping with parameterized session context" if is_saas else "Single-tenant database partition"

        caching = tech_stack.get("cache", "In-Memory LRU Cache")
        caching_strategy = f"{caching} for frequently queried read models and session tokens"

        return DataArchitectureDesign(
            entities=entities,
            relationships=relationships,
            tenant_isolation_strategy=tenant_strategy,
            database_choice=db_choice,
            database_rationale=f"Selected {db_choice} to provide guaranteed ACID transactions and flexible relational querying.",
            transaction_strategy="Unit-of-Work pattern with ACID transactional guarantees",
            consistency_strategy="Strong consistency for transactional data; read replicas for reporting",
            caching_strategy=caching_strategy,
            migration_strategy="Version-controlled declarative migrations (Alembic / Flyway / Prisma)",
            backup_recovery="Daily automated snapshots with point-in-time recovery to 7-day retention window",
        )


class SecurityArchitectureAnalyzer:
    """Derives authentication boundaries, RBAC models, secret isolation, and failure domains."""

    def analyze(self, spec: ProjectSpecification, tech_stack: Dict[str, str]) -> SecurityArchitectureDesign:
        roles = [p.role_name for p in spec.user_personas] or ["User", "Administrator"]
        auth_tech = tech_stack.get("authentication", "JWT (HMAC-SHA256)")

        risks = []
        for r in spec.all_requirements():
            desc_l = r.description.lower()
            if "payment" in desc_l:
                risks.append("PCI-DSS compliance: Direct cardholder data storage prohibited; enforce gateway tokenization.")
            if "upload" in desc_l or "file" in desc_l:
                risks.append("Arbitrary file upload vulnerability: Sanitize file headers and store in isolated storage buckets.")

        if not risks:
            risks.append("Improper access control: Mitigated by mandatory RBAC permission checks on all state-mutating endpoints.")

        return SecurityArchitectureDesign(
            auth_boundaries=f"Stateless session authentication via {auth_tech} with short-lived access tokens and secure HTTP-only refresh tokens.",
            authorization_model=f"Hierarchical Role-Based Access Control (RBAC) supporting roles: {', '.join(roles)}.",
            tenant_isolation="Strict tenant context validation in request middleware; automatic SQL query filter injection.",
            secret_management="Zero secrets in codebase. Runtime configuration injected via OS environment variables / AWS Secrets Manager.",
            api_security="Strict HTTPS/TLS 1.3, CORS origin validation, Rate Limiting (Token Bucket), and Pydantic request schema validation.",
            network_boundaries="Public entrypoints routed through reverse proxy/gateway; database and cache residing in private subnets.",
            encryption_requirements="TLS 1.3 encryption in-transit for all network channels; AES-256 encryption at-rest for database volumes.",
            audit_logging="Structured append-only audit trail recording user identity, IP address, timestamp, and mutating operation.",
            security_risks=risks,
        )


"""
architecture_models.py -- Architecture & Technical Decision Intelligence Data Models.

Phase 11.2: Architecture & Technical Decision Intelligence.
Defines typed models for architecture patterns, quality drivers, alternatives,
evaluations, Architecture Decision Records (ADRs), component designs,
data & security architecture, cost estimations, migration plans, and blueprints.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class ArchitecturePattern(str, enum.Enum):
    MONOLITH = "MONOLITH"
    MODULAR_MONOLITH = "MODULAR_MONOLITH"
    MICROSERVICES = "MICROSERVICES"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    SERVERLESS = "SERVERLESS"
    LAYERED = "LAYERED"
    CLEAN_ARCHITECTURE = "CLEAN_ARCHITECTURE"
    HEXAGONAL = "HEXAGONAL"
    HYBRID = "HYBRID"


class DecisionApprovalStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DriverCategory(str, enum.Enum):
    FUNCTIONAL = "FUNCTIONAL"
    QUALITY_ATTRIBUTE = "QUALITY_ATTRIBUTE"
    OPERATIONAL_CONSTRAINT = "OPERATIONAL_CONSTRAINT"


class CostConfidence(str, enum.Enum):
    VERIFIED = "VERIFIED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class ComplexityLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


@dataclass
class ArchitectureDriver:
    """Requirement or constraint that materially shapes architectural decisions."""
    id: str  # e.g. "DRV-001"
    name: str
    category: DriverCategory
    description: str
    source_requirement_ids: List[str] = field(default_factory=list)
    priority: str = "HIGH"  # CRITICAL, HIGH, MEDIUM, LOW
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "source_requirement_ids": list(self.source_requirement_ids),
            "priority": self.priority,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArchitectureDriver:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            category=DriverCategory(data.get("category", "FUNCTIONAL")),
            description=data.get("description", ""),
            source_requirement_ids=list(data.get("source_requirement_ids", [])),
            priority=data.get("priority", "HIGH"),
            rationale=data.get("rationale", ""),
        )


@dataclass
class ArchitectureAlternative:
    """An evaluated architectural candidate pattern."""
    pattern: ArchitecturePattern
    name: str
    description: str
    advantages: List[str] = field(default_factory=list)
    disadvantages: List[str] = field(default_factory=list)
    implementation_complexity: ComplexityLevel = ComplexityLevel.MEDIUM
    operational_complexity: ComplexityLevel = ComplexityLevel.MEDIUM
    cost_implications: str = ""
    security_implications: str = ""
    scalability_characteristics: str = ""
    maintenance_implications: str = ""
    repo_compatibility: str = ""
    migration_requirements: str = ""
    major_risks: List[str] = field(default_factory=list)
    is_viable: bool = True
    elimination_reason: Optional[str] = None
    criteria_scores: Dict[str, float] = field(default_factory=dict)
    total_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern": self.pattern.value,
            "name": self.name,
            "description": self.description,
            "advantages": list(self.advantages),
            "disadvantages": list(self.disadvantages),
            "implementation_complexity": self.implementation_complexity.value,
            "operational_complexity": self.operational_complexity.value,
            "cost_implications": self.cost_implications,
            "security_implications": self.security_implications,
            "scalability_characteristics": self.scalability_characteristics,
            "maintenance_implications": self.maintenance_implications,
            "repo_compatibility": self.repo_compatibility,
            "migration_requirements": self.migration_requirements,
            "major_risks": list(self.major_risks),
            "is_viable": self.is_viable,
            "elimination_reason": self.elimination_reason,
            "criteria_scores": dict(self.criteria_scores),
            "total_score": round(self.total_score, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArchitectureAlternative:
        return cls(
            pattern=ArchitecturePattern(data.get("pattern", "MODULAR_MONOLITH")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            advantages=list(data.get("advantages", [])),
            disadvantages=list(data.get("disadvantages", [])),
            implementation_complexity=ComplexityLevel(data.get("implementation_complexity", "MEDIUM")),
            operational_complexity=ComplexityLevel(data.get("operational_complexity", "MEDIUM")),
            cost_implications=data.get("cost_implications", ""),
            security_implications=data.get("security_implications", ""),
            scalability_characteristics=data.get("scalability_characteristics", ""),
            maintenance_implications=data.get("maintenance_implications", ""),
            repo_compatibility=data.get("repo_compatibility", ""),
            migration_requirements=data.get("migration_requirements", ""),
            major_risks=list(data.get("major_risks", [])),
            is_viable=bool(data.get("is_viable", True)),
            elimination_reason=data.get("elimination_reason"),
            criteria_scores=dict(data.get("criteria_scores", {})),
            total_score=float(data.get("total_score", 0.0)),
        )


@dataclass
class ArchitectureDecisionRecord:
    """Formal Architecture Decision Record (ADR) capturing technical choices."""
    id: str  # e.g. "ADR-001"
    title: str
    context: str
    related_requirement_ids: List[str] = field(default_factory=list)
    alternatives_considered: List[str] = field(default_factory=list)
    selected_decision: str = ""
    rationale: str = ""
    tradeoffs: List[str] = field(default_factory=list)
    rejected_alternatives: Dict[str, str] = field(default_factory=dict)  # alt_name -> rejection_reason
    risks: List[str] = field(default_factory=list)
    confidence: str = "HIGH"
    approval_status: DecisionApprovalStatus = DecisionApprovalStatus.PROPOSED
    is_user_explicit: bool = False
    version: int = 1
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "context": self.context,
            "related_requirement_ids": list(self.related_requirement_ids),
            "alternatives_considered": list(self.alternatives_considered),
            "selected_decision": self.selected_decision,
            "rationale": self.rationale,
            "tradeoffs": list(self.tradeoffs),
            "rejected_alternatives": dict(self.rejected_alternatives),
            "risks": list(self.risks),
            "confidence": self.confidence,
            "approval_status": self.approval_status.value,
            "is_user_explicit": self.is_user_explicit,
            "version": self.version,
            "revision_history": list(self.revision_history),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArchitectureDecisionRecord:
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            context=data.get("context", ""),
            related_requirement_ids=list(data.get("related_requirement_ids", [])),
            alternatives_considered=list(data.get("alternatives_considered", [])),
            selected_decision=data.get("selected_decision", ""),
            rationale=data.get("rationale", ""),
            tradeoffs=list(data.get("tradeoffs", [])),
            rejected_alternatives=dict(data.get("rejected_alternatives", {})),
            risks=list(data.get("risks", [])),
            confidence=data.get("confidence", "HIGH"),
            approval_status=DecisionApprovalStatus(data.get("approval_status", "PROPOSED")),
            is_user_explicit=bool(data.get("is_user_explicit", False)),
            version=int(data.get("version", 1)),
            revision_history=list(data.get("revision_history", [])),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class ComponentDesign:
    """Detailed architectural specification for a discrete component/module."""
    name: str
    category: str
    responsibilities: List[str] = field(default_factory=list)
    boundaries: str = ""
    internal_deps: List[str] = field(default_factory=list)
    external_deps: List[str] = field(default_factory=list)
    data_ownership: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "responsibilities": list(self.responsibilities),
            "boundaries": self.boundaries,
            "internal_deps": list(self.internal_deps),
            "external_deps": list(self.external_deps),
            "data_ownership": list(self.data_ownership),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ComponentDesign:
        return cls(
            name=data.get("name", ""),
            category=data.get("category", ""),
            responsibilities=list(data.get("responsibilities", [])),
            boundaries=data.get("boundaries", ""),
            internal_deps=list(data.get("internal_deps", [])),
            external_deps=list(data.get("external_deps", [])),
            data_ownership=list(data.get("data_ownership", [])),
        )


@dataclass
class DataArchitectureDesign:
    """Persistence, database selection, caching, and entity modeling design."""
    entities: List[str] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    tenant_isolation_strategy: str = "Row-level tenant_id filtering"
    database_choice: str = ""
    database_rationale: str = ""
    transaction_strategy: str = "ACID compliant single-database transactions"
    consistency_strategy: str = "Strong consistency for financial/order entities"
    caching_strategy: str = "In-memory / Redis cache for frequently read catalogs"
    migration_strategy: str = "Declarative migrations (Alembic / Prisma / Flyway)"
    backup_recovery: str = "Automated daily snapshots with point-in-time recovery"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": list(self.entities),
            "relationships": list(self.relationships),
            "tenant_isolation_strategy": self.tenant_isolation_strategy,
            "database_choice": self.database_choice,
            "database_rationale": self.database_rationale,
            "transaction_strategy": self.transaction_strategy,
            "consistency_strategy": self.consistency_strategy,
            "caching_strategy": self.caching_strategy,
            "migration_strategy": self.migration_strategy,
            "backup_recovery": self.backup_recovery,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DataArchitectureDesign:
        return cls(
            entities=list(data.get("entities", [])),
            relationships=list(data.get("relationships", [])),
            tenant_isolation_strategy=data.get("tenant_isolation_strategy", ""),
            database_choice=data.get("database_choice", ""),
            database_rationale=data.get("database_rationale", ""),
            transaction_strategy=data.get("transaction_strategy", ""),
            consistency_strategy=data.get("consistency_strategy", ""),
            caching_strategy=data.get("caching_strategy", ""),
            migration_strategy=data.get("migration_strategy", ""),
            backup_recovery=data.get("backup_recovery", ""),
        )


@dataclass
class SecurityArchitectureDesign:
    """Security boundaries, authentication, authorization, and isolation design."""
    auth_boundaries: str = ""
    authorization_model: str = "Role-Based Access Control (RBAC)"
    tenant_isolation: str = "Tenant-scoped database queries and session context"
    secret_management: str = "Environment variables loaded via secure secret manager"
    api_security: str = "HTTPS/TLS, Rate Limiting, JWT signature verification"
    network_boundaries: str = "Internal database isolated behind private VPC/AppContainer"
    encryption_requirements: str = "TLS 1.3 in-transit, AES-256 at-rest"
    audit_logging: str = "Immutable structured audit logs for administrative events"
    security_risks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auth_boundaries": self.auth_boundaries,
            "authorization_model": self.authorization_model,
            "tenant_isolation": self.tenant_isolation,
            "secret_management": self.secret_management,
            "api_security": self.api_security,
            "network_boundaries": self.network_boundaries,
            "encryption_requirements": self.encryption_requirements,
            "audit_logging": self.audit_logging,
            "security_risks": list(self.security_risks),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SecurityArchitectureDesign:
        return cls(
            auth_boundaries=data.get("auth_boundaries", ""),
            authorization_model=data.get("authorization_model", ""),
            tenant_isolation=data.get("tenant_isolation", ""),
            secret_management=data.get("secret_management", ""),
            api_security=data.get("api_security", ""),
            network_boundaries=data.get("network_boundaries", ""),
            encryption_requirements=data.get("encryption_requirements", ""),
            audit_logging=data.get("audit_logging", ""),
            security_risks=list(data.get("security_risks", [])),
        )


@dataclass
class CostArchitectureEstimate:
    """FinOps architectural cost projections."""
    total_estimated_monthly_usd: float = 0.0
    cost_confidence: CostConfidence = CostConfidence.ESTIMATED
    breakdown: Dict[str, Any] = field(default_factory=dict)
    cost_drivers: List[str] = field(default_factory=list)
    finops_governance_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_estimated_monthly_usd": round(self.total_estimated_monthly_usd, 2),
            "cost_confidence": self.cost_confidence.value,
            "breakdown": dict(self.breakdown),
            "cost_drivers": list(self.cost_drivers),
            "finops_governance_notes": self.finops_governance_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CostArchitectureEstimate:
        return cls(
            total_estimated_monthly_usd=float(data.get("total_estimated_monthly_usd", 0.0)),
            cost_confidence=CostConfidence(data.get("cost_confidence", "ESTIMATED")),
            breakdown=dict(data.get("breakdown", {})),
            cost_drivers=list(data.get("cost_drivers", [])),
            finops_governance_notes=data.get("finops_governance_notes", ""),
        )


@dataclass
class MigrationPlan:
    """Step-by-step technical migration plan for existing repositories."""
    is_migration_needed: bool = False
    existing_state: str = ""
    target_state: str = ""
    required_changes: List[str] = field(default_factory=list)
    affected_components: List[str] = field(default_factory=list)
    compatibility_risks: List[str] = field(default_factory=list)
    migration_order: List[str] = field(default_factory=list)
    testing_requirements: List[str] = field(default_factory=list)
    rollback_strategy: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_migration_needed": self.is_migration_needed,
            "existing_state": self.existing_state,
            "target_state": self.target_state,
            "required_changes": list(self.required_changes),
            "affected_components": list(self.affected_components),
            "compatibility_risks": list(self.compatibility_risks),
            "migration_order": list(self.migration_order),
            "testing_requirements": list(self.testing_requirements),
            "rollback_strategy": self.rollback_strategy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MigrationPlan:
        return cls(
            is_migration_needed=bool(data.get("is_migration_needed", False)),
            existing_state=data.get("existing_state", ""),
            target_state=data.get("target_state", ""),
            required_changes=list(data.get("required_changes", [])),
            affected_components=list(data.get("affected_components", [])),
            compatibility_risks=list(data.get("compatibility_risks", [])),
            migration_order=list(data.get("migration_order", [])),
            testing_requirements=list(data.get("testing_requirements", [])),
            rollback_strategy=data.get("rollback_strategy", ""),
        )


@dataclass
class NontechnicalExplanation:
    """Understandable language explanation for nontechnical stakeholders."""
    recommended_architecture: str
    simple_summary: str
    why_it_fits: str
    main_advantages: List[str] = field(default_factory=list)
    important_tradeoffs: List[str] = field(default_factory=list)
    expected_complexity: str = "Low to Moderate"
    alternatives_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_architecture": self.recommended_architecture,
            "simple_summary": self.simple_summary,
            "why_it_fits": self.why_it_fits,
            "main_advantages": list(self.main_advantages),
            "important_tradeoffs": list(self.important_tradeoffs),
            "expected_complexity": self.expected_complexity,
            "alternatives_summary": self.alternatives_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NontechnicalExplanation:
        return cls(
            recommended_architecture=data.get("recommended_architecture", ""),
            simple_summary=data.get("simple_summary", ""),
            why_it_fits=data.get("why_it_fits", ""),
            main_advantages=list(data.get("main_advantages", [])),
            important_tradeoffs=list(data.get("important_tradeoffs", [])),
            expected_complexity=data.get("expected_complexity", "Low to Moderate"),
            alternatives_summary=data.get("alternatives_summary", ""),
        )


@dataclass
class ArchitectureBlueprint:
    """
    Actionable Engineering Architecture Blueprint containing all 25 required sections.
    Produced before implementation to guide engineering planning and task execution.
    """
    spec_id: str
    version: int = 1
    project_name: str = ""
    workspace_root: str = ""
    # Section 1: Overview
    architecture_overview: str = ""
    # Section 2: Style
    architecture_style: ArchitecturePattern = ArchitecturePattern.MODULAR_MONOLITH
    # Section 3: Technology Stack
    technology_stack: Dict[str, str] = field(default_factory=dict)
    # Section 4-6: Components & Responsibilities & Boundaries
    components: List[ComponentDesign] = field(default_factory=list)
    # Section 7: Dependency Relationships
    dependency_relationships: List[str] = field(default_factory=list)
    # Section 8: Data-flow Architecture
    data_flow_architecture: List[str] = field(default_factory=list)
    # Section 9: API Architecture
    api_architecture: str = ""
    # Section 10: Database Architecture
    database_architecture: DataArchitectureDesign = field(default_factory=DataArchitectureDesign)
    # Section 11: Authentication & Authorization Design
    security_architecture: SecurityArchitectureDesign = field(default_factory=SecurityArchitectureDesign)
    # Section 12: Security Boundaries
    security_boundaries: List[str] = field(default_factory=list)
    # Section 13: Background Processing
    background_processing: str = ""
    # Section 14: External Integrations
    external_integrations: List[str] = field(default_factory=list)
    # Section 15: Error-handling Strategy
    error_handling_strategy: str = ""
    # Section 16: Caching Strategy
    caching_strategy: str = ""
    # Section 17: Observability Strategy
    observability_strategy: str = ""
    # Section 18: Testing Strategy
    testing_strategy: str = ""
    # Section 19: Deployment Architecture
    deployment_architecture: str = ""
    # Section 20: Scaling Strategy
    scaling_strategy: str = ""
    # Section 21: Backup and Recovery
    backup_and_recovery: str = ""
    # Section 22: Cost Considerations
    cost_considerations: CostArchitectureEstimate = field(default_factory=CostArchitectureEstimate)
    # Section 23: Known Risks
    known_risks: List[str] = field(default_factory=list)
    # Section 24: Unresolved Decisions
    unresolved_decisions: List[str] = field(default_factory=list)
    # Section 25: Architectural Assumptions
    architectural_assumptions: List[str] = field(default_factory=list)

    # Supporting entities
    drivers: List[ArchitectureDriver] = field(default_factory=list)
    alternatives_evaluated: List[ArchitectureAlternative] = field(default_factory=list)
    adrs: List[ArchitectureDecisionRecord] = field(default_factory=list)
    migration_plan: MigrationPlan = field(default_factory=MigrationPlan)
    nontechnical_explanation: Optional[NontechnicalExplanation] = None
    traceability_matrix: Dict[str, List[str]] = field(default_factory=dict)  # req_id -> [component_names, adr_ids]
    is_approved: bool = False
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "version": self.version,
            "project_name": self.project_name,
            "workspace_root": self.workspace_root,
            "architecture_overview": self.architecture_overview,
            "architecture_style": self.architecture_style.value,
            "technology_stack": dict(self.technology_stack),
            "components": [c.to_dict() for c in self.components],
            "dependency_relationships": list(self.dependency_relationships),
            "data_flow_architecture": list(self.data_flow_architecture),
            "api_architecture": self.api_architecture,
            "database_architecture": self.database_architecture.to_dict(),
            "security_architecture": self.security_architecture.to_dict(),
            "security_boundaries": list(self.security_boundaries),
            "background_processing": self.background_processing,
            "external_integrations": list(self.external_integrations),
            "error_handling_strategy": self.error_handling_strategy,
            "caching_strategy": self.caching_strategy,
            "observability_strategy": self.observability_strategy,
            "testing_strategy": self.testing_strategy,
            "deployment_architecture": self.deployment_architecture,
            "scaling_strategy": self.scaling_strategy,
            "backup_and_recovery": self.backup_and_recovery,
            "cost_considerations": self.cost_considerations.to_dict(),
            "known_risks": list(self.known_risks),
            "unresolved_decisions": list(self.unresolved_decisions),
            "architectural_assumptions": list(self.architectural_assumptions),
            "drivers": [d.to_dict() for d in self.drivers],
            "alternatives_evaluated": [a.to_dict() for a in self.alternatives_evaluated],
            "adrs": [adr.to_dict() for adr in self.adrs],
            "migration_plan": self.migration_plan.to_dict(),
            "nontechnical_explanation": self.nontechnical_explanation.to_dict() if self.nontechnical_explanation else None,
            "traceability_matrix": {k: list(v) for k, v in self.traceability_matrix.items()},
            "is_approved": self.is_approved,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArchitectureBlueprint:
        return cls(
            spec_id=data.get("spec_id", ""),
            version=int(data.get("version", 1)),
            project_name=data.get("project_name", ""),
            workspace_root=data.get("workspace_root", ""),
            architecture_overview=data.get("architecture_overview", ""),
            architecture_style=ArchitecturePattern(data.get("architecture_style", "MODULAR_MONOLITH")),
            technology_stack=dict(data.get("technology_stack", {})),
            components=[ComponentDesign.from_dict(c) for c in data.get("components", [])],
            dependency_relationships=list(data.get("dependency_relationships", [])),
            data_flow_architecture=list(data.get("data_flow_architecture", [])),
            api_architecture=data.get("api_architecture", ""),
            database_architecture=DataArchitectureDesign.from_dict(data.get("database_architecture", {})),
            security_architecture=SecurityArchitectureDesign.from_dict(data.get("security_architecture", {})),
            security_boundaries=list(data.get("security_boundaries", [])),
            background_processing=data.get("background_processing", ""),
            external_integrations=list(data.get("external_integrations", [])),
            error_handling_strategy=data.get("error_handling_strategy", ""),
            caching_strategy=data.get("caching_strategy", ""),
            observability_strategy=data.get("observability_strategy", ""),
            testing_strategy=data.get("testing_strategy", ""),
            deployment_architecture=data.get("deployment_architecture", ""),
            scaling_strategy=data.get("scaling_strategy", ""),
            backup_and_recovery=data.get("backup_and_recovery", ""),
            cost_considerations=CostArchitectureEstimate.from_dict(data.get("cost_considerations", {})),
            known_risks=list(data.get("known_risks", [])),
            unresolved_decisions=list(data.get("unresolved_decisions", [])),
            architectural_assumptions=list(data.get("architectural_assumptions", [])),
            drivers=[ArchitectureDriver.from_dict(d) for d in data.get("drivers", [])],
            alternatives_evaluated=[ArchitectureAlternative.from_dict(a) for a in data.get("alternatives_evaluated", [])],
            adrs=[ArchitectureDecisionRecord.from_dict(adr) for adr in data.get("adrs", [])],
            migration_plan=MigrationPlan.from_dict(data.get("migration_plan", {})),
            nontechnical_explanation=NontechnicalExplanation.from_dict(data.get("nontechnical_explanation")) if data.get("nontechnical_explanation") else None,
            traceability_matrix={k: list(v) for k, v in data.get("traceability_matrix", {}).items()},
            is_approved=bool(data.get("is_approved", False)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_markdown(self) -> str:
        lines = [
            f"# ARCHITECTURE BLUEPRINT: {self.project_name or self.spec_id}",
            f"**Version:** v{self.version} | **Pattern:** `{self.architecture_style.value}` | **Approved:** {self.is_approved}",
            f"**Created:** {self.created_at} | **Updated:** {self.updated_at}",
            "",
            "## 1. Architecture Overview",
            self.architecture_overview,
            "",
            "## 2. Technology Stack",
        ]
        for category, tech in self.technology_stack.items():
            lines.append(f"- **{category.title()}:** {tech}")

        lines.extend(["", "## 3. Component Architecture & Responsibilities"])
        for comp in self.components:
            lines.append(f"### Component: `{comp.name}` ({comp.category})")
            lines.append(f"- **Boundaries:** {comp.boundaries}")
            lines.append(f"- **Internal Dependencies:** {', '.join(comp.internal_deps) or 'None'}")
            lines.append(f"- **External Dependencies:** {', '.join(comp.external_deps) or 'None'}")
            lines.append(f"- **Data Ownership:** {', '.join(comp.data_ownership) or 'None'}")
            lines.append("- **Responsibilities:**")
            for r in comp.responsibilities:
                lines.append(f"  * {r}")
            lines.append("")

        lines.extend(["## 4. Data & Database Architecture",
            f"- **Database Choice:** {self.database_architecture.database_choice}",
            f"- **Rationale:** {self.database_architecture.database_rationale}",
            f"- **Tenant Isolation:** {self.database_architecture.tenant_isolation_strategy}",
            f"- **Transactions & Consistency:** {self.database_architecture.transaction_strategy} | {self.database_architecture.consistency_strategy}",
            f"- **Caching Strategy:** {self.database_architecture.caching_strategy}",
            f"- **Migration Strategy:** {self.database_architecture.migration_strategy}",
            "",
            "## 5. Security Architecture",
            f"- **Authentication:** {self.security_architecture.auth_boundaries}",
            f"- **Authorization Model:** {self.security_architecture.authorization_model}",
            f"- **Tenant Isolation:** {self.security_architecture.tenant_isolation}",
            f"- **Secret Management:** {self.security_architecture.secret_management}",
            f"- **API Security:** {self.security_architecture.api_security}",
            f"- **Network Boundaries:** {self.security_architecture.network_boundaries}",
            "",
            "## 6. Architecture Decision Records (ADRs)",
        ])
        for adr in self.adrs:
            lines.append(f"### [{adr.id}] {adr.title} ({adr.approval_status.value})")
            lines.append(f"- **Context:** {adr.context}")
            lines.append(f"- **Decision:** {adr.selected_decision}")
            lines.append(f"- **Rationale:** {adr.rationale}")
            if adr.tradeoffs:
                lines.append(f"- **Tradeoffs:** {'; '.join(adr.tradeoffs)}")
            lines.append("")

        if self.nontechnical_explanation:
            lines.extend([
                "## 7. Nontechnical Summary",
                f"**Recommendation:** {self.nontechnical_explanation.recommended_architecture}",
                f"{self.nontechnical_explanation.simple_summary}",
                f"**Why it fits:** {self.nontechnical_explanation.why_it_fits}",
                f"**Expected Complexity:** {self.nontechnical_explanation.expected_complexity}",
                "",
            ])

        lines.extend([
            "## 8. Operational & Cost Projections",
            f"- **Estimated Monthly Cost:** ${self.cost_considerations.total_estimated_monthly_usd:.2f} ({self.cost_considerations.cost_confidence.value})",
            f"- **Deployment Target:** {self.deployment_architecture}",
            f"- **Observability Strategy:** {self.observability_strategy}",
            f"- **Scaling Strategy:** {self.scaling_strategy}",
            "",
            "## 9. Known Risks & Unresolved Decisions",
        ])
        for risk in self.known_risks:
            lines.append(f"- **Risk:** {risk}")
        for unres in self.unresolved_decisions:
            lines.append(f"- **Unresolved Decision:** {unres}")

        return "\n".join(lines)


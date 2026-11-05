"""
src/production/models.py - Core Data Models for Production Readiness Intelligence.

Phase 11.8: Production Readiness Intelligence (Final Phase).
Defines:
- Environment profiles (LOCAL_DEV to ENTERPRISE_PROD)
- Readiness dimension statuses and overall verdicts
- Structured ProductionReadinessFinding model
- Release and rollback plans
- Comprehensive ProductionReadinessReport schema
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class EnvironmentProfile(str, enum.Enum):
    """The intended deployment target profile."""
    LOCAL_DEV = "LOCAL_DEV"
    INTERNAL_TEST = "INTERNAL_TEST"
    DEMO = "DEMO"
    STAGING = "STAGING"
    SMALL_PROD = "SMALL_PROD"
    STANDARD_PROD = "STANDARD_PROD"
    ENTERPRISE_PROD = "ENTERPRISE_PROD"
    REGULATED_PROD = "REGULATED_PROD"


class ReadinessDimensionStatus(str, enum.Enum):
    """Readiness status for an individual production dimension."""
    READY = "READY"
    READY_WITH_LIMITATIONS = "READY_WITH_LIMITATIONS"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    BLOCKED = "BLOCKED"
    NOT_ASSESSED = "NOT_ASSESSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProductionReadinessVerdict(str, enum.Enum):
    """Authoritative overall production readiness verdict."""
    PRODUCTION_READY = "PRODUCTION_READY"
    PRODUCTION_READY_WITH_ACCEPTED_RISKS = "PRODUCTION_READY_WITH_ACCEPTED_RISKS"
    NOT_PRODUCTION_READY = "NOT_PRODUCTION_READY"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_ASSESSED = "NOT_ASSESSED"


class FindingCategory(str, enum.Enum):
    """Categories of production readiness findings."""
    SECURITY = "SECURITY"
    CONFIGURATION = "CONFIGURATION"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    DEPLOYMENT = "DEPLOYMENT"
    CICD = "CICD"
    DATABASE = "DATABASE"
    BACKUP_RECOVERY = "BACKUP_RECOVERY"
    OBSERVABILITY = "OBSERVABILITY"
    RELIABILITY = "RELIABILITY"
    PERFORMANCE = "PERFORMANCE"
    COST_FINOPS = "COST_FINOPS"
    DISASTER_RECOVERY = "DISASTER_RECOVERY"
    COMPLIANCE_PRIVACY = "COMPLIANCE_PRIVACY"


class FindingSeverity(str, enum.Enum):
    """Severity ratings for production risks and blockers."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class FindingStatus(str, enum.Enum):
    """Lifecycle status of a production readiness finding."""
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    FIXED = "FIXED"
    RETEST_REQUIRED = "RETEST_REQUIRED"
    VERIFIED_FIXED = "VERIFIED_FIXED"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    UNRESOLVED = "UNRESOLVED"


class ComplianceClassification(str, enum.Enum):
    """Classification for privacy and regulatory findings."""
    TECHNICAL_EVIDENCE = "TECHNICAL_EVIDENCE"
    POTENTIAL_COMPLIANCE_GAP = "POTENTIAL_COMPLIANCE_GAP"
    LEGAL_REVIEW_REQUIRED = "LEGAL_REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"


@dataclass
class TargetEnvironmentConfig:
    """Characteristics and requirements of the target deployment environment."""
    profile: EnvironmentProfile = EnvironmentProfile.STANDARD_PROD
    expected_users: int = 1000
    concurrent_users: int = 100
    request_volume_rpm: int = 500
    data_sensitivity: str = "CONFIDENTIAL"  # PUBLIC, INTERNAL, CONFIDENTIAL, REGULATED
    availability_sla_pct: float = 99.9
    cloud_provider: str = "generic"  # aws, gcp, azure, docker, generic
    database_type: str = "postgresql"
    multi_region: bool = False
    budget_monthly_usd: float = 250.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile.value,
            "expected_users": self.expected_users,
            "concurrent_users": self.concurrent_users,
            "request_volume_rpm": self.request_volume_rpm,
            "data_sensitivity": self.data_sensitivity,
            "availability_sla_pct": self.availability_sla_pct,
            "cloud_provider": self.cloud_provider,
            "database_type": self.database_type,
            "multi_region": self.multi_region,
            "budget_monthly_usd": self.budget_monthly_usd,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TargetEnvironmentConfig:
        return cls(
            profile=EnvironmentProfile(data.get("profile", "STANDARD_PROD")),
            expected_users=int(data.get("expected_users", 1000)),
            concurrent_users=int(data.get("concurrent_users", 100)),
            request_volume_rpm=int(data.get("request_volume_rpm", 500)),
            data_sensitivity=data.get("data_sensitivity", "CONFIDENTIAL"),
            availability_sla_pct=float(data.get("availability_sla_pct", 99.9)),
            cloud_provider=data.get("cloud_provider", "generic"),
            database_type=data.get("database_type", "postgresql"),
            multi_region=bool(data.get("multi_region", False)),
            budget_monthly_usd=float(data.get("budget_monthly_usd", 250.0)),
        )


@dataclass
class ProductionReadinessFinding:
    """A structured finding, defect, or operational risk identified during readiness evaluation."""
    finding_id: str
    task_id: str
    workspace_id: str
    category: FindingCategory
    severity: FindingSeverity
    title: str
    description: str
    evidence_source: str
    affected_component: str
    environment: EnvironmentProfile = EnvironmentProfile.STANDARD_PROD
    confidence: float = 1.0
    recommended_remediation: str = ""
    required_approval: bool = False
    verification_status: FindingStatus = FindingStatus.OPEN
    first_detected: float = field(default_factory=time.time)
    last_evaluated: float = field(default_factory=time.time)
    revision_history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> FindingStatus:
        return self.verification_status

    @status.setter
    def status(self, val: FindingStatus) -> None:
        self.verification_status = val

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "evidence_source": self.evidence_source,
            "affected_component": self.affected_component,
            "environment": self.environment.value,
            "confidence": self.confidence,
            "recommended_remediation": self.recommended_remediation,
            "required_approval": self.required_approval,
            "verification_status": self.verification_status.value,
            "first_detected": self.first_detected,
            "last_evaluated": self.last_evaluated,
            "revision_history": self.revision_history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProductionReadinessFinding:
        return cls(
            finding_id=data["finding_id"],
            task_id=data.get("task_id", ""),
            workspace_id=data.get("workspace_id", ""),
            category=FindingCategory(data.get("category", "SECURITY")),
            severity=FindingSeverity(data.get("severity", "MEDIUM")),
            title=data.get("title", ""),
            description=data.get("description", ""),
            evidence_source=data.get("evidence_source", ""),
            affected_component=data.get("affected_component", ""),
            environment=EnvironmentProfile(data.get("environment", "STANDARD_PROD")),
            confidence=float(data.get("confidence", 1.0)),
            recommended_remediation=data.get("recommended_remediation", ""),
            required_approval=bool(data.get("required_approval", False)),
            verification_status=FindingStatus(data.get("verification_status", "OPEN")),
            first_detected=float(data.get("first_detected", time.time())),
            last_evaluated=float(data.get("last_evaluated", time.time())),
            revision_history=data.get("revision_history", []),
        )


@dataclass
class DimensionEvaluation:
    """Evaluation summary for an individual readiness dimension."""
    dimension_name: str
    status: ReadinessDimensionStatus
    summary: str
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension_name": self.dimension_name,
            "status": self.status.value,
            "summary": self.summary,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "evidence": self.evidence,
        }


@dataclass
class RemediationTask:
    """Actionable remediation plan for a production blocker."""
    finding_id: str
    description: str
    root_cause: str
    recommended_change: str
    affected_components: List[str]
    change_impact: str
    required_approval: bool
    expected_tests: List[str]
    acceptance_criteria: List[str]
    rollback_strategy: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReleasePlan:
    """Deterministic release and deployment execution plan."""
    pre_deployment_checks: List[str]
    required_approvals: List[str]
    backup_requirements: List[str]
    build_requirements: List[str]
    migration_sequence: List[str]
    deployment_order: List[str]
    health_verification: List[str]
    post_deployment_checks: List[str]
    rollback_conditions: List[str]
    rollback_procedure: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionReadinessReport:
    """The central, comprehensive Production Readiness Report."""
    task_id: str
    workspace_id: str
    application_id: str
    target_environment: TargetEnvironmentConfig
    verdict: ProductionReadinessVerdict
    verdict_rationale: str
    dimensions: Dict[str, DimensionEvaluation] = field(default_factory=dict)
    open_findings: List[ProductionReadinessFinding] = field(default_factory=list)
    remediations: List[RemediationTask] = field(default_factory=list)
    release_plan: Optional[ReleasePlan] = None
    accepted_risks: List[Dict[str, Any]] = field(default_factory=list)
    unverified_areas: List[str] = field(default_factory=list)
    evidence_references: List[str] = field(default_factory=list)
    estimated_monthly_cost_usd: float = 0.0
    evidence_digest: str = ""
    timestamp: float = field(default_factory=time.time)

    def compute_evidence_digest(self) -> str:
        """Computes a deterministic SHA256 digest over the readiness evidence."""
        payload = {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "target_environment": self.target_environment.profile.value,
            "verdict": self.verdict.value,
            "dim_statuses": {k: v.status.value for k, v in self.dimensions.items()},
            "findings_count": len(self.open_findings),
            "findings": [f.finding_id for f in self.open_findings],
            "cost_usd": self.estimated_monthly_cost_usd,
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "application_id": self.application_id,
            "target_environment": self.target_environment.to_dict(),
            "verdict": self.verdict.value,
            "verdict_rationale": self.verdict_rationale,
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "open_findings": [f.to_dict() for f in self.open_findings],
            "remediations": [r.to_dict() for r in self.remediations],
            "release_plan": self.release_plan.to_dict() if self.release_plan else None,
            "accepted_risks": self.accepted_risks,
            "unverified_areas": self.unverified_areas,
            "evidence_references": self.evidence_references,
            "estimated_monthly_cost_usd": self.estimated_monthly_cost_usd,
            "evidence_digest": self.evidence_digest or self.compute_evidence_digest(),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProductionReadinessReport:
        target_env = TargetEnvironmentConfig.from_dict(data.get("target_environment", {}))
        dims = {}
        for k, v in data.get("dimensions", {}).items():
            dims[k] = DimensionEvaluation(
                dimension_name=v.get("dimension_name", k),
                status=ReadinessDimensionStatus(v.get("status", "NOT_ASSESSED")),
                summary=v.get("summary", ""),
                blockers=v.get("blockers", []),
                warnings=v.get("warnings", []),
                evidence=v.get("evidence", {}),
            )
        findings = [ProductionReadinessFinding.from_dict(f) for f in data.get("open_findings", [])]
        remediations = [RemediationTask(**r) for r in data.get("remediations", [])]
        rel_plan = ReleasePlan(**data["release_plan"]) if data.get("release_plan") else None

        return cls(
            task_id=data["task_id"],
            workspace_id=data.get("workspace_id", ""),
            application_id=data.get("application_id", ""),
            target_environment=target_env,
            verdict=ProductionReadinessVerdict(data.get("verdict", "NOT_ASSESSED")),
            verdict_rationale=data.get("verdict_rationale", ""),
            dimensions=dims,
            open_findings=findings,
            remediations=remediations,
            release_plan=rel_plan,
            accepted_risks=data.get("accepted_risks", []),
            unverified_areas=data.get("unverified_areas", []),
            evidence_references=data.get("evidence_references", []),
            estimated_monthly_cost_usd=float(data.get("estimated_monthly_cost_usd", 0.0)),
            evidence_digest=data.get("evidence_digest", ""),
            timestamp=float(data.get("timestamp", time.time())),
        )

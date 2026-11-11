"""
src/verification/models.py - Core Data Models for Independent Verification & QA.

Phase 11.7: Independent Verification & Quality Assurance.
Defines:
- Verification verdicts and requirement statuses
- Test evidence classifications
- Verification findings, categories, severities, and lifecycle states
- Application runtime results & workflow records
- Test integrity reports
- Comprehensive VerificationReport schema
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class VerificationVerdict(str, enum.Enum):
    """Authoritative verdicts issued exclusively by the Independent Verification Engine."""
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_LIMITATIONS = "VERIFIED_WITH_LIMITATIONS"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_TESTED = "NOT_TESTED"


class RequirementVerificationStatus(str, enum.Enum):
    """Evaluation status for an individual requirement."""
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_TESTED = "NOT_TESTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    # P0.6.7: a file can exist while no executed test establishes the required
    # behavior. That is not "verified" and not "missing"; it is unproven.
    NOT_VERIFIED = "NOT_VERIFIED"
    # Evidence exists but cannot be attributed (runner crash, timeout, mixed
    # failures). Completion must refuse rather than guess.
    INCONCLUSIVE = "INCONCLUSIVE"


class TestEvidenceClassification(str, enum.Enum):
    """Independent classification of test reliability and reality."""
    REAL_RUNTIME_TEST = "REAL_RUNTIME_TEST"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    UNIT_TEST = "UNIT_TEST"
    MOCK_BASED_TEST = "MOCK_BASED_TEST"
    FIXTURE_BASED_TEST = "FIXTURE_BASED_TEST"
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    SIMULATED_TEST = "SIMULATED_TEST"
    NOT_EXECUTED = "NOT_EXECUTED"


class FindingCategory(str, enum.Enum):
    """Categories of independent verification findings."""
    SECURITY = "SECURITY"
    FUNCTIONALITY = "FUNCTIONALITY"
    INTEGRATION = "INTEGRATION"
    REGRESSION = "REGRESSION"
    TEST_QUALITY = "TEST_QUALITY"
    CODE_QUALITY = "CODE_QUALITY"
    PERFORMANCE = "PERFORMANCE"
    ENVIRONMENT = "ENVIRONMENT"
    MAINTAINABILITY = "MAINTAINABILITY"


class FindingSeverity(str, enum.Enum):
    """Severity ratings for defects and findings."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class FindingStatus(str, enum.Enum):
    """Lifecycle state of an independent verification finding."""
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    FIXED = "FIXED"
    RETEST_REQUIRED = "RETEST_REQUIRED"
    VERIFIED_FIXED = "VERIFIED_FIXED"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    UNRESOLVED = "UNRESOLVED"


class RuntimeStartupResult(str, enum.Enum):
    """Outcome of actual application runtime startup probes."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    ENVIRONMENT_UNAVAILABLE = "ENVIRONMENT_UNAVAILABLE"
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass
class VerificationFinding:
    """A structured finding or defect identified during independent verification."""
    finding_id: str
    task_id: str
    category: FindingCategory
    severity: FindingSeverity
    title: str
    description: str
    evidence: str
    affected_files: List[str] = field(default_factory=list)
    affected_symbols: List[str] = field(default_factory=list)
    requirement_id: Optional[str] = None
    reproduction_procedure: Optional[str] = None
    confidence: float = 1.0
    status: FindingStatus = FindingStatus.OPEN
    recommended_action: str = ""
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "task_id": self.task_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "affected_files": self.affected_files,
            "affected_symbols": self.affected_symbols,
            "requirement_id": self.requirement_id,
            "reproduction_procedure": self.reproduction_procedure,
            "confidence": self.confidence,
            "status": self.status.value,
            "recommended_action": self.recommended_action,
            "revision_history": self.revision_history,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerificationFinding:
        return cls(
            finding_id=data["finding_id"],
            task_id=data.get("task_id", ""),
            category=FindingCategory(data.get("category", "FUNCTIONALITY")),
            severity=FindingSeverity(data.get("severity", "MEDIUM")),
            title=data.get("title", ""),
            description=data.get("description", ""),
            evidence=data.get("evidence", ""),
            affected_files=data.get("affected_files", []),
            affected_symbols=data.get("affected_symbols", []),
            requirement_id=data.get("requirement_id"),
            reproduction_procedure=data.get("reproduction_procedure"),
            confidence=float(data.get("confidence", 1.0)),
            status=FindingStatus(data.get("status", "OPEN")),
            recommended_action=data.get("recommended_action", ""),
            revision_history=data.get("revision_history", []),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass
class RequirementVerificationRecord:
    """Detailed verification record for a single requirement."""
    requirement_id: str
    intent: str
    description: str
    acceptance_criteria: List[Dict[str, Any]] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    relevant_symbols: List[str] = field(default_factory=list)
    related_tests: List[str] = field(default_factory=list)
    test_results: Dict[str, str] = field(default_factory=dict)
    status: RequirementVerificationStatus = RequirementVerificationStatus.NOT_TESTED
    remaining_limitations: List[str] = field(default_factory=list)
    evidence_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "intent": self.intent,
            "description": self.description,
            "acceptance_criteria": self.acceptance_criteria,
            "relevant_files": self.relevant_files,
            "relevant_symbols": self.relevant_symbols,
            "related_tests": self.related_tests,
            "test_results": self.test_results,
            "status": self.status.value,
            "remaining_limitations": self.remaining_limitations,
            "evidence_summary": self.evidence_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RequirementVerificationRecord:
        return cls(
            requirement_id=data.get("requirement_id", ""),
            intent=data.get("intent", ""),
            description=data.get("description", ""),
            acceptance_criteria=data.get("acceptance_criteria", []),
            relevant_files=data.get("relevant_files", []),
            relevant_symbols=data.get("relevant_symbols", []),
            related_tests=data.get("related_tests", []),
            test_results=data.get("test_results", {}),
            status=RequirementVerificationStatus(data.get("status", "NOT_TESTED")),
            remaining_limitations=data.get("remaining_limitations", []),
            evidence_summary=data.get("evidence_summary", ""),
        )


@dataclass
class ApplicationRuntimeResult:
    """Outcome of actual application runtime probing."""
    component_name: str
    command: str
    environment: Dict[str, str] = field(default_factory=dict)
    exit_code: int = 0
    startup_result: RuntimeStartupResult = RuntimeStartupResult.NOT_EXECUTED
    endpoints_verified: List[Dict[str, Any]] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    timestamp: float = field(default_factory=time.time)
    error_details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_name": self.component_name,
            "command": self.command,
            "environment": self.environment,
            "exit_code": self.exit_code,
            "startup_result": self.startup_result.value,
            "endpoints_verified": self.endpoints_verified,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timestamp": self.timestamp,
            "error_details": self.error_details,
        }


@dataclass
class WorkflowVerificationRecord:
    """Verification results for multi-step user workflows."""
    workflow_name: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    success_path_verified: bool = False
    error_handling_verified: bool = False
    security_enforced: bool = False
    final_state: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "steps": self.steps,
            "success_path_verified": self.success_path_verified,
            "error_handling_verified": self.error_handling_verified,
            "security_enforced": self.security_enforced,
            "final_state": self.final_state,
            "evidence": self.evidence,
        }


@dataclass
class TestIntegrityReport:
    """Audit of test suite reliability, weak tests, and evidence classification."""
    test_files_analyzed: List[str] = field(default_factory=list)
    total_tests_checked: int = 0
    weak_tests_detected: List[Dict[str, Any]] = field(default_factory=list)
    evidence_classifications: Dict[str, str] = field(default_factory=dict)
    tautological_count: int = 0
    empty_test_count: int = 0
    excessive_mock_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_files_analyzed": self.test_files_analyzed,
            "total_tests_checked": self.total_tests_checked,
            "weak_tests_detected": self.weak_tests_detected,
            "evidence_classifications": self.evidence_classifications,
            "tautological_count": self.tautological_count,
            "empty_test_count": self.empty_test_count,
            "excessive_mock_count": self.excessive_mock_count,
        }


@dataclass
class VerificationReport:
    """The central, immutable, evidence-driven Verification Report."""
    task_id: str
    workspace_id: str
    original_user_request: str
    repository_revision: str
    implementation_revision: str
    verification_timestamp: float = field(default_factory=time.time)
    scope: Dict[str, Any] = field(default_factory=dict)
    requirement_coverage: Dict[str, Any] = field(default_factory=dict)
    requirements: List[RequirementVerificationRecord] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    test_selection: List[str] = field(default_factory=list)
    test_execution_results: Dict[str, Any] = field(default_factory=dict)
    test_integrity: Optional[TestIntegrityReport] = None
    runtime_results: List[ApplicationRuntimeResult] = field(default_factory=list)
    workflow_results: List[WorkflowVerificationRecord] = field(default_factory=list)
    security_findings: List[VerificationFinding] = field(default_factory=list)
    quality_findings: List[VerificationFinding] = field(default_factory=list)
    performance_results: Dict[str, Any] = field(default_factory=dict)
    platform_compatibility: Dict[str, Any] = field(default_factory=dict)
    regression_status: str = "PASS"
    open_defects: List[VerificationFinding] = field(default_factory=list)
    accepted_limitations: List[str] = field(default_factory=list)
    unverified_areas: List[str] = field(default_factory=list)
    verdict: VerificationVerdict = VerificationVerdict.NOT_TESTED
    verdict_rationale: str = ""
    evidence_digest: str = ""

    def compute_evidence_digest(self) -> str:
        """Compute an authoritative SHA256 digest of all verification evidence."""
        digest_payload = {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "repository_revision": self.repository_revision,
            "implementation_revision": self.implementation_revision,
            "verdict": self.verdict.value,
            "req_statuses": [r.status.value for r in self.requirements],
            "open_defects_count": len(self.open_defects),
            "findings": [f.finding_id for f in self.security_findings + self.quality_findings],
            "regression_status": self.regression_status,
        }
        raw_json = json.dumps(digest_payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "original_user_request": self.original_user_request,
            "repository_revision": self.repository_revision,
            "implementation_revision": self.implementation_revision,
            "verification_timestamp": self.verification_timestamp,
            "scope": self.scope,
            "requirement_coverage": self.requirement_coverage,
            "requirements": [r.to_dict() for r in self.requirements],
            "changed_files": self.changed_files,
            "test_selection": self.test_selection,
            "test_execution_results": self.test_execution_results,
            "test_integrity": self.test_integrity.to_dict() if self.test_integrity else None,
            "runtime_results": [rt.to_dict() for rt in self.runtime_results],
            "workflow_results": [w.to_dict() for w in self.workflow_results],
            "security_findings": [f.to_dict() for f in self.security_findings],
            "quality_findings": [f.to_dict() for f in self.quality_findings],
            "performance_results": self.performance_results,
            "platform_compatibility": self.platform_compatibility,
            "regression_status": self.regression_status,
            "open_defects": [d.to_dict() for d in self.open_defects],
            "accepted_limitations": self.accepted_limitations,
            "unverified_areas": self.unverified_areas,
            "verdict": self.verdict.value,
            "verdict_rationale": self.verdict_rationale,
            "evidence_digest": self.evidence_digest or self.compute_evidence_digest(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerificationReport:
        report = cls(
            task_id=data["task_id"],
            workspace_id=data.get("workspace_id", ""),
            original_user_request=data.get("original_user_request", ""),
            repository_revision=data.get("repository_revision", ""),
            implementation_revision=data.get("implementation_revision", ""),
            verification_timestamp=float(data.get("verification_timestamp", time.time())),
            scope=data.get("scope", {}),
            requirement_coverage=data.get("requirement_coverage", {}),
            requirements=[RequirementVerificationRecord.from_dict(r) for r in data.get("requirements", [])],
            changed_files=data.get("changed_files", []),
            test_selection=data.get("test_selection", []),
            test_execution_results=data.get("test_execution_results", {}),
            runtime_results=[],
            workflow_results=[],
            security_findings=[VerificationFinding.from_dict(f) for f in data.get("security_findings", [])],
            quality_findings=[VerificationFinding.from_dict(f) for f in data.get("quality_findings", [])],
            performance_results=data.get("performance_results", {}),
            platform_compatibility=data.get("platform_compatibility", {}),
            regression_status=data.get("regression_status", "PASS"),
            open_defects=[VerificationFinding.from_dict(d) for d in data.get("open_defects", [])],
            accepted_limitations=data.get("accepted_limitations", []),
            unverified_areas=data.get("unverified_areas", []),
            verdict=VerificationVerdict(data.get("verdict", "NOT_TESTED")),
            verdict_rationale=data.get("verdict_rationale", ""),
            evidence_digest=data.get("evidence_digest", ""),
        )
        if data.get("test_integrity"):
            ti = data["test_integrity"]
            report.test_integrity = TestIntegrityReport(
                test_files_analyzed=ti.get("test_files_analyzed", []),
                total_tests_checked=ti.get("total_tests_checked", 0),
                weak_tests_detected=ti.get("weak_tests_detected", []),
                evidence_classifications=ti.get("evidence_classifications", {}),
                tautological_count=ti.get("tautological_count", 0),
                empty_test_count=ti.get("empty_test_count", 0),
                excessive_mock_count=ti.get("excessive_mock_count", 0),
            )
        return report


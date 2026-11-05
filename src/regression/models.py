"""
src/regression/models.py - Regression Prevention & Recovery Data Models.

Phase 11.5: Regression Prevention & Recovery.
Defines strictly typed models for:
- Pre-change test baselines and post-change test comparisons.
- Failure classifications (new regression, pre-existing, flaky, environment, external).
- Root-cause diagnosis with epistemic certainty levels.
- Risk-based test execution priorities (P0, P1, P2, P3, P4).
- Flaky test records and test integrity violations.
- Safe rollback and recovery actions.
- Machine-readable RegressionReport schema.
"""

from __future__ import annotations

import enum
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class TestStatus(str, enum.Enum):
    """Execution status of an individual test case."""
    PASSING = "PASSING"
    FAILING = "FAILING"
    FLAKY = "FLAKY"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    NOT_TESTED = "NOT_TESTED"
    UNKNOWN = "UNKNOWN"


class FailureClassification(str, enum.Enum):
    """Root category of an observed test failure."""
    PRE_EXISTING_FAILURE = "PRE_EXISTING_FAILURE"
    NEW_REGRESSION = "NEW_REGRESSION"
    INTERMITTENT_FAILURE = "INTERMITTENT_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    EXTERNAL_SERVICE_FAILURE = "EXTERNAL_SERVICE_FAILURE"
    TEST_INFRASTRUCTURE_FAILURE = "TEST_INFRASTRUCTURE_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class RootCauseCertainty(str, enum.Enum):
    """Epistemic certainty for failure diagnosis."""
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNKNOWN = "UNKNOWN"


class TestPriority(str, enum.Enum):
    """Risk-based test execution tier."""
    P0 = "P0"  # Direct validation: modified symbols and target bug
    P1 = "P1"  # Dependent functionality: callers and direct consumers
    P2 = "P2"  # Contract validation: APIs, database, external interfaces
    P3 = "P3"  # Broader regression: module & subsystem regression suites
    P4 = "P4"  # Extended validation: long-running, platform-specific suites


class RegressionStatus(str, enum.Enum):
    """Overall status and completion gate verdict."""
    PASS = "PASS"
    PASS_WITH_PRE_EXISTING_FAILURES = "PASS_WITH_PRE_EXISTING_FAILURES"
    PASS_WITH_KNOWN_LIMITATIONS = "PASS_WITH_KNOWN_LIMITATIONS"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NOT_TESTED = "NOT_TESTED"


class RecoveryActionType(str, enum.Enum):
    """Corrective or recovery action type."""
    CORRECT_IMPLEMENTATION = "CORRECT_IMPLEMENTATION"
    RESTORE_AGENT_FILE = "RESTORE_AGENT_FILE"
    REVERT_AGENT_OPERATION = "REVERT_AGENT_OPERATION"
    ABORT_TRANSACTION = "ABORT_TRANSACTION"
    REQUEST_USER_INTERVENTION = "REQUEST_USER_INTERVENTION"


class IntegrityViolationType(str, enum.Enum):
    """Test tampering or integrity violation types."""
    TEST_DELETED = "TEST_DELETED"
    ASSERTION_WEAKENED = "ASSERTION_WEAKENED"
    TEST_CASE_REMOVED = "TEST_CASE_REMOVED"
    TIMEOUT_INFLATED = "TIMEOUT_INFLATED"
    CONVERTED_TO_SKIP = "CONVERTED_TO_SKIP"
    BLANKET_SUPPRESSION = "BLANKET_SUPPRESSION"
    SECURITY_CHECK_DISABLED = "SECURITY_CHECK_DISABLED"


@dataclass
class TestCaseResult:
    """Execution outcome of a single test case."""
    test_id: str                                  # Unique identifier (e.g. "tests/test_auth.py::test_login")
    test_name: str                                # Human readable test name
    test_suite: str                               # File path or suite identifier
    status: TestStatus                            # Execution status
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    exception_type: Optional[str] = None
    stack_trace: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    run_count: int = 1
    environment_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "test_name": self.test_name,
            "test_suite": self.test_suite,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "exception_type": self.exception_type,
            "stack_trace": self.stack_trace,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "run_count": self.run_count,
            "environment_metadata": self.environment_metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TestCaseResult:
        return cls(
            test_id=data["test_id"],
            test_name=data["test_name"],
            test_suite=data["test_suite"],
            status=TestStatus(data["status"]),
            duration_seconds=data.get("duration_seconds", 0.0),
            error_message=data.get("error_message"),
            exception_type=data.get("exception_type"),
            stack_trace=data.get("stack_trace"),
            stdout=data.get("stdout"),
            stderr=data.get("stderr"),
            run_count=data.get("run_count", 1),
            environment_metadata=data.get("environment_metadata", {}),
        )


@dataclass
class TestBaseline:
    """Captured pre-task test execution baseline."""
    baseline_id: str
    task_id: str
    repository_revision: Optional[str]
    workspace_root: str
    test_frameworks: List[str]
    test_cases: Dict[str, TestCaseResult] = field(default_factory=dict)
    summary: Dict[str, int] = field(default_factory=dict)
    captured_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "task_id": self.task_id,
            "repository_revision": self.repository_revision,
            "workspace_root": self.workspace_root,
            "test_frameworks": self.test_frameworks,
            "test_cases": {tid: res.to_dict() for tid, res in self.test_cases.items()},
            "summary": self.summary,
            "captured_timestamp": self.captured_timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TestBaseline:
        cases = {
            tid: TestCaseResult.from_dict(cdata)
            for tid, cdata in data.get("test_cases", {}).items()
        }
        return cls(
            baseline_id=data["baseline_id"],
            task_id=data["task_id"],
            repository_revision=data.get("repository_revision"),
            workspace_root=data["workspace_root"],
            test_frameworks=data.get("test_frameworks", []),
            test_cases=cases,
            summary=data.get("summary", {}),
            captured_timestamp=data.get("captured_timestamp", 0.0),
        )


@dataclass
class FailureDiagnosis:
    """Structured diagnosis of an observed failure."""
    failure_id: str
    test_id: str
    classification: FailureClassification
    expected_behavior: str
    actual_behavior: str
    exception_type: Optional[str] = None
    stack_trace: Optional[str] = None
    root_cause_certainty: RootCauseCertainty = RootCauseCertainty.UNKNOWN
    root_cause_summary: str = ""
    associated_symbols: List[str] = field(default_factory=list)
    associated_files: List[str] = field(default_factory=list)
    evidence_records: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "test_id": self.test_id,
            "classification": self.classification.value,
            "expected_behavior": self.expected_behavior,
            "actual_behavior": self.actual_behavior,
            "exception_type": self.exception_type,
            "stack_trace": self.stack_trace,
            "root_cause_certainty": self.root_cause_certainty.value,
            "root_cause_summary": self.root_cause_summary,
            "associated_symbols": self.associated_symbols,
            "associated_files": self.associated_files,
            "evidence_records": self.evidence_records,
        }


@dataclass
class FlakyTestRecord:
    """Evidence record for a test demonstrating nondeterministic outcomes."""
    test_id: str
    runs_count: int
    pass_count: int
    fail_count: int
    is_flaky: bool
    variance_rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "runs_count": self.runs_count,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "is_flaky": self.is_flaky,
            "variance_rationale": self.variance_rationale,
        }


@dataclass
class TestIntegrityViolation:
    """Detected attempt to manipulate or weaken test verification."""
    violation_type: IntegrityViolationType
    test_file: str
    test_name: Optional[str]
    description: str
    blocked: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_type": self.violation_type.value,
            "test_file": self.test_file,
            "test_name": self.test_name,
            "description": self.description,
            "blocked": self.blocked,
        }


@dataclass
class RecoveryEvaluation:
    """Evaluation of safe rollback and recovery actions."""
    task_id: str
    is_safe_to_rollback: bool
    actions: List[Dict[str, Any]] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)
    affected_user_files: List[str] = field(default_factory=list)
    recovery_status: str = "PENDING"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "is_safe_to_rollback": self.is_safe_to_rollback,
            "actions": self.actions,
            "blocked_reasons": self.blocked_reasons,
            "affected_user_files": self.affected_user_files,
            "recovery_status": self.recovery_status,
        }


@dataclass
class RegressionReport:
    """
    Comprehensive, machine-readable report documenting pre/post test comparison,
    regressions detected, diagnoses, recovery actions, and final completion gates.
    """
    task_id: str
    workspace_id: str
    repository_revision: Optional[str]
    baseline_id: str
    pre_change_summary: Dict[str, int]
    post_change_summary: Dict[str, int]
    selected_test_scope: List[Dict[str, Any]]
    excluded_test_scope: List[Dict[str, Any]]
    new_regressions: List[TestCaseResult] = field(default_factory=list)
    pre_existing_failures: List[TestCaseResult] = field(default_factory=list)
    flaky_tests: List[FlakyTestRecord] = field(default_factory=list)
    environment_failures: List[TestCaseResult] = field(default_factory=list)
    root_cause_findings: List[FailureDiagnosis] = field(default_factory=list)
    corrective_operations: List[Dict[str, Any]] = field(default_factory=list)
    test_integrity_audit: List[TestIntegrityViolation] = field(default_factory=list)
    rollback_attempts: List[Dict[str, Any]] = field(default_factory=list)
    recovery_status: str = "NONE_REQUIRED"
    security_regression_results: List[Dict[str, Any]] = field(default_factory=list)
    performance_comparison: Dict[str, Any] = field(default_factory=dict)
    final_status: RegressionStatus = RegressionStatus.PASS
    final_verdict: str = "REGRESSION PREVENTION VERIFIED"
    generated_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "repository_revision": self.repository_revision,
            "baseline_id": self.baseline_id,
            "pre_change_summary": self.pre_change_summary,
            "post_change_summary": self.post_change_summary,
            "selected_test_scope": self.selected_test_scope,
            "excluded_test_scope": self.excluded_test_scope,
            "new_regressions": [r.to_dict() for r in self.new_regressions],
            "pre_existing_failures": [p.to_dict() for p in self.pre_existing_failures],
            "flaky_tests": [f.to_dict() for f in self.flaky_tests],
            "environment_failures": [e.to_dict() for e in self.environment_failures],
            "root_cause_findings": [f.to_dict() for f in self.root_cause_findings],
            "corrective_operations": self.corrective_operations,
            "test_integrity_audit": [v.to_dict() for v in self.test_integrity_audit],
            "rollback_attempts": self.rollback_attempts,
            "recovery_status": self.recovery_status,
            "security_regression_results": self.security_regression_results,
            "performance_comparison": self.performance_comparison,
            "final_status": self.final_status.value,
            "final_verdict": self.final_verdict,
            "generated_timestamp": self.generated_timestamp,
        }


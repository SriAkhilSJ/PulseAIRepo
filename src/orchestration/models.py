"""
src/orchestration/models.py - Core Data Models for Autonomous Engineering Execution.

Phase 11.6: Autonomous Engineering Execution.
Defines:
- Task execution states (23 states)
- Valid state transitions
- Task lifecycle stages (15 stages)
- Engineering plan DAG models
- Completion contract verdicts
- Resource budgets & limits
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class TaskExecutionState(str, enum.Enum):
    """The 23 persistent states of an autonomous engineering execution task."""
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    DISCOVERY = "DISCOVERY"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    SPECIFICATION_READY = "SPECIFICATION_READY"
    ARCHITECTURE_REVIEW = "ARCHITECTURE_REVIEW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    PLANNING = "PLANNING"
    IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
    BASELINE_TESTING = "BASELINE_TESTING"
    READY_TO_IMPLEMENT = "READY_TO_IMPLEMENT"
    IMPLEMENTING = "IMPLEMENTING"
    BUILDING = "BUILDING"
    TESTING = "TESTING"
    FAILURE_DIAGNOSIS = "FAILURE_DIAGNOSIS"
    CORRECTING = "CORRECTING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskLifecycleStage(str, enum.Enum):
    """The 15 sequential lifecycle stages of an engineering task."""
    USER_REQUEST = "USER_REQUEST"
    REQUEST_UNDERSTANDING = "REQUEST_UNDERSTANDING"
    PROJECT_DISCOVERY = "PROJECT_DISCOVERY"
    REQUIREMENT_VALIDATION = "REQUIREMENT_VALIDATION"
    ARCHITECTURE_VALIDATION = "ARCHITECTURE_VALIDATION"
    ENGINEERING_PLAN = "ENGINEERING_PLAN"
    CHANGE_IMPACT_ANALYSIS = "CHANGE_IMPACT_ANALYSIS"
    TEST_BASELINE = "TEST_BASELINE"
    APPROVAL_AND_PERMISSION_CHECK = "APPROVAL_AND_PERMISSION_CHECK"
    IMPLEMENTATION = "IMPLEMENTATION"
    BUILD_AND_TEST_EXECUTION = "BUILD_AND_TEST_EXECUTION"
    FAILURE_DIAGNOSIS = "FAILURE_DIAGNOSIS"
    BOUNDED_CORRECTION = "BOUNDED_CORRECTION"
    REGRESSION_VERIFICATION = "REGRESSION_VERIFICATION"
    INDEPENDENT_COMPLETION_CHECK = "INDEPENDENT_COMPLETION_CHECK"
    FINAL_DELIVERY = "FINAL_DELIVERY"


class TaskVerdict(str, enum.Enum):
    """Strict completion contract verdicts."""
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_KNOWN_LIMITATIONS = "COMPLETED_WITH_KNOWN_LIMITATIONS"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NOT_VERIFIED = "NOT_VERIFIED"


# Valid state transitions matrix
VALID_TRANSITIONS: Dict[TaskExecutionState, Set[TaskExecutionState]] = {
    TaskExecutionState.RECEIVED: {
        TaskExecutionState.UNDERSTANDING,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.UNDERSTANDING: {
        TaskExecutionState.DISCOVERY,
        TaskExecutionState.CLARIFICATION_REQUIRED,
        TaskExecutionState.SPECIFICATION_READY,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.CANCELLED,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.CLARIFICATION_REQUIRED: {
        TaskExecutionState.UNDERSTANDING,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.DISCOVERY: {
        TaskExecutionState.SPECIFICATION_READY,
        TaskExecutionState.CLARIFICATION_REQUIRED,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.FAILED,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.SPECIFICATION_READY: {
        TaskExecutionState.ARCHITECTURE_REVIEW,
        TaskExecutionState.APPROVAL_REQUIRED,
        TaskExecutionState.PLANNING,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.ARCHITECTURE_REVIEW: {
        TaskExecutionState.APPROVAL_REQUIRED,
        TaskExecutionState.PLANNING,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.APPROVAL_REQUIRED: {
        TaskExecutionState.PLANNING,
        TaskExecutionState.READY_TO_IMPLEMENT,
        TaskExecutionState.IMPLEMENTING,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.PLANNING: {
        TaskExecutionState.IMPACT_ANALYSIS,
        TaskExecutionState.APPROVAL_REQUIRED,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.CANCELLED,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.IMPACT_ANALYSIS: {
        TaskExecutionState.BASELINE_TESTING,
        TaskExecutionState.APPROVAL_REQUIRED,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.FAILED,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.BASELINE_TESTING: {
        TaskExecutionState.READY_TO_IMPLEMENT,
        TaskExecutionState.APPROVAL_REQUIRED,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.FAILED,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.READY_TO_IMPLEMENT: {
        TaskExecutionState.IMPLEMENTING,
        TaskExecutionState.APPROVAL_REQUIRED,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.IMPLEMENTING: {
        TaskExecutionState.BUILDING,
        TaskExecutionState.TESTING,
        TaskExecutionState.RECOVERY_REQUIRED,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.FAILED,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.BUILDING: {
        TaskExecutionState.TESTING,
        TaskExecutionState.FAILURE_DIAGNOSIS,
        TaskExecutionState.CORRECTING,
        TaskExecutionState.RECOVERY_REQUIRED,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.TESTING: {
        TaskExecutionState.VERIFYING,
        TaskExecutionState.FAILURE_DIAGNOSIS,
        TaskExecutionState.CORRECTING,
        TaskExecutionState.RECOVERY_REQUIRED,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.FAILURE_DIAGNOSIS: {
        TaskExecutionState.CORRECTING,
        TaskExecutionState.RECOVERY_REQUIRED,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.CORRECTING: {
        TaskExecutionState.BUILDING,
        TaskExecutionState.TESTING,
        TaskExecutionState.RECOVERY_REQUIRED,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.RECOVERY_REQUIRED: {
        TaskExecutionState.PLANNING,
        TaskExecutionState.CORRECTING,
        TaskExecutionState.BLOCKED,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.VERIFYING: {
        TaskExecutionState.COMPLETED,
        TaskExecutionState.PARTIALLY_COMPLETED,
        TaskExecutionState.FAILURE_DIAGNOSIS,
        TaskExecutionState.FAILED,
    },
    TaskExecutionState.COMPLETED: set(),
    TaskExecutionState.PARTIALLY_COMPLETED: set(),
    TaskExecutionState.BLOCKED: {
        TaskExecutionState.RECEIVED,
        TaskExecutionState.UNDERSTANDING,
        TaskExecutionState.PLANNING,
        TaskExecutionState.IMPLEMENTING,
        TaskExecutionState.CANCELLED,
    },
    TaskExecutionState.FAILED: set(),
    TaskExecutionState.CANCELLED: set(),
}


@dataclass
class ExecutionLimits:
    """Enforceable boundaries for autonomous engineering loops."""
    max_correction_attempts: int = 3
    max_planning_revisions: int = 3
    max_repeated_tool_failures: int = 3
    max_task_duration_seconds: float = 600.0
    max_token_budget: int = 150000
    max_cost_inr: float = 0.00  # Paid LLM budget: strictly INR 0.00
    max_file_modifications: int = 50
    max_concurrent_operations: int = 4


@dataclass
class EngineeringTaskNode:
    """A granular task node in the engineering DAG."""
    node_id: str
    description: str
    objective: str
    related_requirement_ids: List[str] = field(default_factory=list)
    related_architecture_decisions: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    required_permissions: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    required_tests: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    completion_conditions: List[str] = field(default_factory=list)
    status: str = "PENDING"  # PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED
    error_message: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "description": self.description,
            "objective": self.objective,
            "related_requirement_ids": self.related_requirement_ids,
            "related_architecture_decisions": self.related_architecture_decisions,
            "target_files": self.target_files,
            "dependencies": self.dependencies,
            "risk_level": self.risk_level,
            "required_permissions": self.required_permissions,
            "expected_outputs": self.expected_outputs,
            "required_tests": self.required_tests,
            "acceptance_criteria": self.acceptance_criteria,
            "completion_conditions": self.completion_conditions,
            "status": self.status,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EngineeringTaskNode:
        return cls(
            node_id=data.get("node_id", ""),
            description=data.get("description", ""),
            objective=data.get("objective", ""),
            related_requirement_ids=data.get("related_requirement_ids", []),
            related_architecture_decisions=data.get("related_architecture_decisions", []),
            target_files=data.get("target_files", []),
            dependencies=data.get("dependencies", []),
            risk_level=data.get("risk_level", "LOW"),
            required_permissions=data.get("required_permissions", []),
            expected_outputs=data.get("expected_outputs", []),
            required_tests=data.get("required_tests", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
            completion_conditions=data.get("completion_conditions", []),
            status=data.get("status", "PENDING"),
            error_message=data.get("error_message"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )


@dataclass
class EngineeringPlanDAG:
    """Dependency graph of implementation tasks."""
    plan_id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:8]}")
    task_id: str = ""
    nodes: Dict[str, EngineeringTaskNode] = field(default_factory=dict)
    revision: int = 1
    created_at: float = field(default_factory=time.time)

    def add_node(self, node: EngineeringTaskNode) -> None:
        self.nodes[node.node_id] = node

    def get_execution_order(self) -> List[List[str]]:
        """
        Topological sort returning waves of parallelizable task node IDs.
        Raises ValueError if circular dependency detected.
        """
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        adj: Dict[str, List[str]] = {nid: [] for nid in self.nodes}

        for nid, node in self.nodes.items():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    raise ValueError(f"Task node '{nid}' depends on non-existent node '{dep}'")
                adj[dep].append(nid)
                in_degree[nid] += 1

        waves: List[List[str]] = []
        current_wave = [nid for nid, deg in in_degree.items() if deg == 0]

        visited_count = 0
        while current_wave:
            waves.append(sorted(current_wave))
            visited_count += len(current_wave)
            next_wave = []
            for u in current_wave:
                for v in adj[u]:
                    in_degree[v] -= 1
                    if in_degree[v] == 0:
                        next_wave.append(v)
            current_wave = next_wave

        if visited_count < len(self.nodes):
            raise ValueError("Circular dependency detected in engineering plan DAG")

        return waves

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "revision": self.revision,
            "created_at": self.created_at,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EngineeringPlanDAG:
        dag = cls(
            plan_id=data.get("plan_id", ""),
            task_id=data.get("task_id", ""),
            revision=data.get("revision", 1),
            created_at=data.get("created_at", time.time()),
        )
        for nid, ndata in data.get("nodes", {}).items():
            dag.add_node(EngineeringTaskNode.from_dict(ndata))
        return dag


@dataclass
class DeliveryContract:
    """Strict completion contract delivered to user."""
    task_id: str
    original_request: str
    verdict: TaskVerdict
    what_was_requested: str
    what_was_implemented: List[str]
    files_changed: List[str]
    tests_executed: List[str]
    tests_passed: List[str]
    tests_failed: List[str]
    independently_verified: bool
    remaining_limitations: List[str]
    user_action_required: Optional[str]
    cost_inr: float = 0.00
    cost_usd: float = 0.00
    token_usage: Dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    evidence_references: List[str] = field(default_factory=list)
    production_readiness_verdict: Optional[str] = None
    production_readiness_findings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "original_request": self.original_request,
            "verdict": self.verdict.value,
            "what_was_requested": self.what_was_requested,
            "what_was_implemented": self.what_was_implemented,
            "files_changed": self.files_changed,
            "tests_executed": self.tests_executed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "independently_verified": self.independently_verified,
            "remaining_limitations": self.remaining_limitations,
            "user_action_required": self.user_action_required,
            "cost_inr": self.cost_inr,
            "token_usage": self.token_usage,
            "duration_seconds": self.duration_seconds,
            "evidence_references": self.evidence_references,
            "production_readiness_verdict": self.production_readiness_verdict,
            "production_readiness_findings": self.production_readiness_findings,
        }


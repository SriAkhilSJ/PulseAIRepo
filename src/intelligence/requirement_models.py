"""
requirement_models.py -- Requirement Understanding & Discovery Data Models.

Phase 11.1: Requirement Understanding & Discovery.
Defines typed models for requirements, classifications, workflows,
clarification questions, conflicts, traceability, and structured specifications.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class RequirementClassification(str, enum.Enum):
    """
    Core Phase 11.1 requirement classification:
    - EXPLICIT: Directly stated by the user.
    - DISCOVERABLE: Established through repository inspection, manifests, or project intelligence.
    - REASONABLE_DEFAULT: Technical choice safely assumed and disclosed without bothering user.
    - USER_DECISION_REQUIRED: Essential business ambiguity, material outcome choice, or irreversible action.
    """
    EXPLICIT = "EXPLICIT"
    DISCOVERABLE = "DISCOVERABLE"
    REASONABLE_DEFAULT = "REASONABLE_DEFAULT"
    USER_DECISION_REQUIRED = "USER_DECISION_REQUIRED"


class RequirementCategory(str, enum.Enum):
    BUSINESS_OBJECTIVE = "BUSINESS_OBJECTIVE"
    FUNCTIONAL = "FUNCTIONAL"
    NONFUNCTIONAL = "NONFUNCTIONAL"
    USER_ROLE = "USER_ROLE"
    WORKFLOW = "WORKFLOW"
    FEATURE = "FEATURE"
    INTEGRATION = "INTEGRATION"
    DATA_REQUIREMENT = "DATA_REQUIREMENT"
    UI_UX = "UI_UX"
    PERFORMANCE = "PERFORMANCE"
    SECURITY = "SECURITY"
    DEPLOYMENT = "DEPLOYMENT"
    TECHNICAL_CONSTRAINT = "TECHNICAL_CONSTRAINT"
    BUDGET_RESOURCE = "BUDGET_RESOURCE"
    ACCEPTANCE_CRITERIA = "ACCEPTANCE_CRITERIA"


class RequirementPriority(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RequirementStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"


@dataclass
class RequirementItem:
    """A discrete, identifiable software requirement with provenance and classification."""
    id: str  # e.g. "REQ-001"
    description: str
    category: RequirementCategory
    classification: RequirementClassification
    priority: RequirementPriority = RequirementPriority.MEDIUM
    status: RequirementStatus = RequirementStatus.PROPOSED
    evidence_source: str = ""  # Prompt quote, repository file, or inferred pattern
    acceptance_criteria: List[str] = field(default_factory=list)
    conflicts_with: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "category": self.category.value,
            "classification": self.classification.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "evidence_source": self.evidence_source,
            "acceptance_criteria": list(self.acceptance_criteria),
            "conflicts_with": list(self.conflicts_with),
            "dependencies": list(self.dependencies),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RequirementItem:
        return cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
            category=RequirementCategory(data.get("category", "FUNCTIONAL")),
            classification=RequirementClassification(data.get("classification", "REASONABLE_DEFAULT")),
            priority=RequirementPriority(data.get("priority", "MEDIUM")),
            status=RequirementStatus(data.get("status", "PROPOSED")),
            evidence_source=data.get("evidence_source", ""),
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            conflicts_with=list(data.get("conflicts_with", [])),
            dependencies=list(data.get("dependencies", [])),
            rationale=data.get("rationale", ""),
        )


@dataclass
class UserPersonaRole:
    """User role or persona interacting with the system."""
    role_name: str
    description: str
    permissions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role_name": self.role_name,
            "description": self.description,
            "permissions": list(self.permissions),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserPersonaRole:
        return cls(
            role_name=data.get("role_name", ""),
            description=data.get("description", ""),
            permissions=list(data.get("permissions", [])),
        )


@dataclass
class UserWorkflow:
    """An end-to-end user workflow or scenario."""
    id: str
    name: str
    actor: str
    trigger: str
    steps: List[str] = field(default_factory=list)
    expected_outcome: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "actor": self.actor,
            "trigger": self.trigger,
            "steps": list(self.steps),
            "expected_outcome": self.expected_outcome,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserWorkflow:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            actor=data.get("actor", ""),
            trigger=data.get("trigger", ""),
            steps=list(data.get("steps", [])),
            expected_outcome=data.get("expected_outcome", ""),
        )


@dataclass
class ClarificationQuestion:
    """A targeted question presented to the user only for essential decisions."""
    id: str  # e.g. "CQ-001"
    question: str
    rationale: str
    affected_requirement_ids: List[str] = field(default_factory=list)
    category: str = "business_decision"
    options: List[str] = field(default_factory=list)
    default_choice: Optional[str] = None
    is_blocking: bool = False
    answered: bool = False
    user_answer: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "rationale": self.rationale,
            "affected_requirement_ids": list(self.affected_requirement_ids),
            "category": self.category,
            "options": list(self.options),
            "default_choice": self.default_choice,
            "is_blocking": self.is_blocking,
            "answered": self.answered,
            "user_answer": self.user_answer,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ClarificationQuestion:
        return cls(
            id=data.get("id", ""),
            question=data.get("question", ""),
            rationale=data.get("rationale", ""),
            affected_requirement_ids=list(data.get("affected_requirement_ids", [])),
            category=data.get("category", "business_decision"),
            options=list(data.get("options", [])),
            default_choice=data.get("default_choice"),
            is_blocking=bool(data.get("is_blocking", False)),
            answered=bool(data.get("answered", False)),
            user_answer=data.get("user_answer"),
        )


@dataclass
class UnresolvedDecision:
    """An open decision tracked until resolved or assumed."""
    id: str
    decision_topic: str
    why_it_matters: str
    options: List[str] = field(default_factory=list)
    impact: str = ""
    status: str = "OPEN"  # OPEN, RESOLVED, ASSUMED_DEFAULT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "decision_topic": self.decision_topic,
            "why_it_matters": self.why_it_matters,
            "options": list(self.options),
            "impact": self.impact,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UnresolvedDecision:
        return cls(
            id=data.get("id", ""),
            decision_topic=data.get("decision_topic", ""),
            why_it_matters=data.get("why_it_matters", ""),
            options=list(data.get("options", [])),
            impact=data.get("impact", ""),
            status=data.get("status", "OPEN"),
        )


@dataclass
class RequirementConflict:
    """A detected contradiction or incompatibility between requirements."""
    id: str
    requirement_ids: List[str] = field(default_factory=list)
    conflict_description: str = ""
    resolution_guidance: str = ""
    is_resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "requirement_ids": list(self.requirement_ids),
            "conflict_description": self.conflict_description,
            "resolution_guidance": self.resolution_guidance,
            "is_resolved": self.is_resolved,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RequirementConflict:
        return cls(
            id=data.get("id", ""),
            requirement_ids=list(data.get("requirement_ids", [])),
            conflict_description=data.get("conflict_description", ""),
            resolution_guidance=data.get("resolution_guidance", ""),
            is_resolved=bool(data.get("is_resolved", False)),
        )


@dataclass
class TraceabilityLink:
    """Bidirectional traceability link connecting requirements to tasks, code, and tests."""
    requirement_id: str
    user_request_excerpt: str = ""
    approved_decisions: List[str] = field(default_factory=list)
    architecture_components: List[str] = field(default_factory=list)
    task_ids: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    test_ids: List[str] = field(default_factory=list)
    verification_status: str = "PENDING"  # PENDING, IN_PROGRESS, VERIFIED, FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "user_request_excerpt": self.user_request_excerpt,
            "approved_decisions": list(self.approved_decisions),
            "architecture_components": list(self.architecture_components),
            "task_ids": list(self.task_ids),
            "modified_files": list(self.modified_files),
            "test_ids": list(self.test_ids),
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TraceabilityLink:
        return cls(
            requirement_id=data.get("requirement_id", ""),
            user_request_excerpt=data.get("user_request_excerpt", ""),
            approved_decisions=list(data.get("approved_decisions", [])),
            architecture_components=list(data.get("architecture_components", [])),
            task_ids=list(data.get("task_ids", [])),
            modified_files=list(data.get("modified_files", [])),
            test_ids=list(data.get("test_ids", [])),
            verification_status=data.get("verification_status", "PENDING"),
        )


@dataclass
class RequirementRevision:
    """Historical record of requirement modification or scope change."""
    revision_id: str
    timestamp: str
    author: str  # "user", "system", "agent"
    reason: str
    changes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "timestamp": self.timestamp,
            "author": self.author,
            "reason": self.reason,
            "changes": dict(self.changes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RequirementRevision:
        return cls(
            revision_id=data.get("revision_id", ""),
            timestamp=data.get("timestamp", ""),
            author=data.get("author", "system"),
            reason=data.get("reason", ""),
            changes=dict(data.get("changes", {})),
        )


@dataclass
class ProjectSpecification:
    """
    Structured machine-readable software project specification.
    Produced before implementation to guide engineering planning and execution.
    """
    spec_id: str
    version: int = 1
    project_name: str = ""
    workspace_root: str = ""
    problem_statement: str = ""
    desired_outcome: str = ""
    user_personas: List[UserPersonaRole] = field(default_factory=list)
    functional_requirements: List[RequirementItem] = field(default_factory=list)
    nonfunctional_requirements: List[RequirementItem] = field(default_factory=list)
    technical_constraints: List[RequirementItem] = field(default_factory=list)
    user_workflows: List[UserWorkflow] = field(default_factory=list)
    data_requirements: List[str] = field(default_factory=list)
    integration_requirements: List[str] = field(default_factory=list)
    architecture_considerations: List[str] = field(default_factory=list)
    assumptions_and_defaults: List[str] = field(default_factory=list)
    unresolved_decisions: List[UnresolvedDecision] = field(default_factory=list)
    clarification_questions: List[ClarificationQuestion] = field(default_factory=list)
    conflicts: List[RequirementConflict] = field(default_factory=list)
    risks_and_dependencies: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    implementation_scope: Dict[str, List[str]] = field(
        default_factory=lambda: {"in_scope": [], "out_of_scope": []}
    )
    traceability: Dict[str, TraceabilityLink] = field(default_factory=dict)
    revision_history: List[RequirementRevision] = field(default_factory=list)
    is_complete: bool = False
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def all_requirements(self) -> List[RequirementItem]:
        return [
            *self.functional_requirements,
            *self.nonfunctional_requirements,
            *self.technical_constraints,
        ]

    def get_requirement(self, req_id: str) -> Optional[RequirementItem]:
        for r in self.all_requirements():
            if r.id == req_id:
                return r
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "version": self.version,
            "project_name": self.project_name,
            "workspace_root": self.workspace_root,
            "problem_statement": self.problem_statement,
            "desired_outcome": self.desired_outcome,
            "user_personas": [p.to_dict() for p in self.user_personas],
            "functional_requirements": [r.to_dict() for r in self.functional_requirements],
            "nonfunctional_requirements": [r.to_dict() for r in self.nonfunctional_requirements],
            "technical_constraints": [r.to_dict() for r in self.technical_constraints],
            "user_workflows": [w.to_dict() for w in self.user_workflows],
            "data_requirements": list(self.data_requirements),
            "integration_requirements": list(self.integration_requirements),
            "architecture_considerations": list(self.architecture_considerations),
            "assumptions_and_defaults": list(self.assumptions_and_defaults),
            "unresolved_decisions": [u.to_dict() for u in self.unresolved_decisions],
            "clarification_questions": [q.to_dict() for q in self.clarification_questions],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "risks_and_dependencies": list(self.risks_and_dependencies),
            "acceptance_criteria": list(self.acceptance_criteria),
            "implementation_scope": {
                "in_scope": list(self.implementation_scope.get("in_scope", [])),
                "out_of_scope": list(self.implementation_scope.get("out_of_scope", [])),
            },
            "traceability": {k: v.to_dict() for k, v in self.traceability.items()},
            "revision_history": [rev.to_dict() for rev in self.revision_history],
            "is_complete": self.is_complete,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectSpecification:
        return cls(
            spec_id=data.get("spec_id", ""),
            version=int(data.get("version", 1)),
            project_name=data.get("project_name", ""),
            workspace_root=data.get("workspace_root", ""),
            problem_statement=data.get("problem_statement", ""),
            desired_outcome=data.get("desired_outcome", ""),
            user_personas=[UserPersonaRole.from_dict(p) for p in data.get("user_personas", [])],
            functional_requirements=[RequirementItem.from_dict(r) for r in data.get("functional_requirements", [])],
            nonfunctional_requirements=[RequirementItem.from_dict(r) for r in data.get("nonfunctional_requirements", [])],
            technical_constraints=[RequirementItem.from_dict(r) for r in data.get("technical_constraints", [])],
            user_workflows=[UserWorkflow.from_dict(w) for w in data.get("user_workflows", [])],
            data_requirements=list(data.get("data_requirements", [])),
            integration_requirements=list(data.get("integration_requirements", [])),
            architecture_considerations=list(data.get("architecture_considerations", [])),
            assumptions_and_defaults=list(data.get("assumptions_and_defaults", [])),
            unresolved_decisions=[UnresolvedDecision.from_dict(u) for u in data.get("unresolved_decisions", [])],
            clarification_questions=[ClarificationQuestion.from_dict(q) for q in data.get("clarification_questions", [])],
            conflicts=[RequirementConflict.from_dict(c) for c in data.get("conflicts", [])],
            risks_and_dependencies=list(data.get("risks_and_dependencies", [])),
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            implementation_scope={
                "in_scope": list(data.get("implementation_scope", {}).get("in_scope", [])),
                "out_of_scope": list(data.get("implementation_scope", {}).get("out_of_scope", [])),
            },
            traceability={
                k: TraceabilityLink.from_dict(v)
                for k, v in data.get("traceability", {}).items()
            },
            revision_history=[RequirementRevision.from_dict(r) for r in data.get("revision_history", [])],
            is_complete=bool(data.get("is_complete", False)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_markdown(self) -> str:
        lines = [
            f"# PROJECT SPECIFICATION: {self.project_name or self.spec_id}",
            f"**Version:** v{self.version} | **Status:** {'Complete' if self.is_complete else 'Draft / Pending Clarification'}",
            f"**Created:** {self.created_at} | **Updated:** {self.updated_at}",
            "",
            "## 1. Problem Statement & Desired Outcome",
            f"**Problem Statement:** {self.problem_statement}",
            f"**Desired Outcome:** {self.desired_outcome}",
            "",
            "## 2. User Roles & Personas",
        ]
        for p in self.user_personas:
            perms = f" (Permissions: {', '.join(p.permissions)})" if p.permissions else ""
            lines.append(f"- **{p.role_name}:** {p.description}{perms}")
        if not self.user_personas:
            lines.append("- *Standard Developer / User*")

        lines.extend(["", "## 3. Functional Requirements"])
        for req in self.functional_requirements:
            lines.append(
                f"- **[{req.id}]** ({req.priority.value} | {req.classification.value}) {req.description}"
            )
            if req.acceptance_criteria:
                for ac in req.acceptance_criteria:
                    lines.append(f"  * AC: {ac}")

        lines.extend(["", "## 4. Technical Constraints"])
        for req in self.technical_constraints:
            lines.append(
                f"- **[{req.id}]** ({req.priority.value} | {req.classification.value}) {req.description}"
            )

        lines.extend(["", "## 5. Nonfunctional Requirements"])
        for req in self.nonfunctional_requirements:
            lines.append(
                f"- **[{req.id}]** ({req.priority.value} | {req.classification.value}) {req.description}"
            )

        lines.extend(["", "## 6. Key Workflows"])
        for wf in self.user_workflows:
            lines.append(f"### Workflow {wf.id}: {wf.name} (Actor: {wf.actor})")
            lines.append(f"Trigger: {wf.trigger}")
            for idx, step in enumerate(wf.steps, 1):
                lines.append(f"{idx}. {step}")
            lines.append(f"Expected Outcome: {wf.expected_outcome}")
            lines.append("")

        lines.extend(["## 7. Assumptions & Technical Defaults"])
        for d in self.assumptions_and_defaults:
            lines.append(f"- {d}")

        if self.unresolved_decisions:
            lines.extend(["", "## 8. Unresolved Decisions"])
            for u in self.unresolved_decisions:
                lines.append(f"- **[{u.id}] {u.decision_topic}:** {u.why_it_matters} (Status: {u.status})")

        if self.clarification_questions:
            lines.extend(["", "## 9. Clarification Questions"])
            for q in self.clarification_questions:
                ans = f" -> **Answered:** {q.user_answer}" if q.answered else " -> **Pending**"
                lines.append(f"- **[{q.id}] {q.question}** ({q.category}){ans}")

        if self.conflicts:
            lines.extend(["", "## 10. Detected Conflicts"])
            for c in self.conflicts:
                lines.append(f"- **[{c.id}]** {c.conflict_description} (Guidance: {c.resolution_guidance})")

        lines.extend(["", "## 11. Acceptance Criteria"])
        for ac in self.acceptance_criteria:
            lines.append(f"- [ ] {ac}")

        lines.extend(["", "## 12. Implementation Scope"])
        lines.append(f"- **In Scope:** {', '.join(self.implementation_scope.get('in_scope', [])) or 'All approved requirements'}")
        lines.append(f"- **Out of Scope:** {', '.join(self.implementation_scope.get('out_of_scope', [])) or 'None'}")

        return "\n".join(lines)


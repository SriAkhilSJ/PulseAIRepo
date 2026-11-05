"""
spec_generator.py -- Structured Project Specification & Traceability Generator.

Phase 11.1: Requirement Understanding & Discovery.
Assembles extracted, classified, and validated requirements into a canonical
ProjectSpecification object with bidirectional requirement traceability matrices.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.requirement_extractor import ExtractedRequirementsBundle
from src.intelligence.requirement_models import (
    ClarificationQuestion,
    ProjectSpecification,
    RequirementCategory,
    RequirementClassification,
    RequirementConflict,
    RequirementItem,
    RequirementPriority,
    RequirementRevision,
    RequirementStatus,
    TraceabilityLink,
    UnresolvedDecision,
    UserPersonaRole,
    UserWorkflow,
)


class SpecificationGenerator:
    """
    Compiles requirement extraction, classification, conflict detection,
    and repository intelligence into an actionable ProjectSpecification.
    """

    def __init__(self, workspace_root: str = "", project_name: str = "") -> None:
        self.workspace_root = workspace_root
        self.project_name = project_name

    def generate_specification(
        self,
        bundle: ExtractedRequirementsBundle,
        classified_requirements: List[RequirementItem],
        clarification_questions: List[ClarificationQuestion],
        unresolved_decisions: List[UnresolvedDecision],
        conflicts: List[RequirementConflict],
        warnings: List[str],
        is_complete: bool,
        version: int = 1,
    ) -> ProjectSpecification:
        spec_id = f"SPEC-{uuid.uuid4().hex[:8].upper()}"

        func_reqs: List[RequirementItem] = []
        nonfunc_reqs: List[RequirementItem] = []
        tech_constraints: List[RequirementItem] = []
        assumptions: List[str] = []
        all_acceptance: List[str] = []
        traceability_map: Dict[str, TraceabilityLink] = {}

        for req in classified_requirements:
            # Segment into functional, nonfunctional, and technical constraints
            if req.category == RequirementCategory.TECHNICAL_CONSTRAINT:
                tech_constraints.append(req)
            elif req.category in {
                RequirementCategory.NONFUNCTIONAL,
                RequirementCategory.SECURITY,
                RequirementCategory.PERFORMANCE,
                RequirementCategory.DEPLOYMENT,
            }:
                nonfunc_reqs.append(req)
            else:
                func_reqs.append(req)

            # Collect acceptance criteria
            for ac in req.acceptance_criteria:
                if ac not in all_acceptance:
                    all_acceptance.append(ac)

            # Record reasonable defaults as disclosed assumptions
            if req.classification == RequirementClassification.REASONABLE_DEFAULT:
                assumptions.append(f"{req.description} ({req.rationale})")

            # Build initial traceability link
            traceability_map[req.id] = TraceabilityLink(
                requirement_id=req.id,
                user_request_excerpt=bundle.user_prompt[:200],
                approved_decisions=[],
                architecture_components=[],
                task_ids=[],
                modified_files=[],
                test_ids=[],
                verification_status="PENDING",
            )

        # Assumptions
        if not assumptions:
            assumptions.append("Standard modern software engineering conventions applied.")

        # Architecture considerations
        arch_considerations: List[str] = []
        for arch in bundle.explicit_architectures:
            arch_considerations.append(f"Explicit architectural style: {arch}")
        for tech, cat in bundle.explicit_technologies:
            arch_considerations.append(f"Technology choice for {cat}: {tech}")
        if not arch_considerations:
            arch_considerations.append("Modular component-based architecture with clean separation of concerns.")

        # Risks & dependencies
        risks = list(warnings)
        for c in conflicts:
            risks.append(f"Conflict: {c.conflict_description}")

        # Implementation scope
        in_scope = [r.description for r in classified_requirements if r.priority in {RequirementPriority.CRITICAL, RequirementPriority.HIGH}]
        out_scope = [
            "Third-party external hardware integration",
            "Multi-region geo-distributed cloud deployment (deferred to production phase)",
        ]

        spec = ProjectSpecification(
            spec_id=spec_id,
            version=version,
            project_name=self.project_name or bundle.user_prompt.splitlines()[0][:40],
            workspace_root=self.workspace_root,
            problem_statement=bundle.problem_statement,
            desired_outcome=bundle.desired_outcome,
            user_personas=bundle.user_roles,
            functional_requirements=func_reqs,
            nonfunctional_requirements=nonfunc_reqs,
            technical_constraints=tech_constraints,
            user_workflows=bundle.workflows,
            data_requirements=bundle.data_entities,
            integration_requirements=bundle.integrations,
            architecture_considerations=arch_considerations,
            assumptions_and_defaults=assumptions,
            unresolved_decisions=unresolved_decisions,
            clarification_questions=clarification_questions,
            conflicts=conflicts,
            risks_and_dependencies=risks,
            acceptance_criteria=all_acceptance,
            implementation_scope={
                "in_scope": in_scope,
                "out_of_scope": out_scope,
            },
            traceability=traceability_map,
            revision_history=[
                RequirementRevision(
                    revision_id=f"REV-{version:03d}",
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    author="requirement_engine",
                    reason="Initial requirement extraction and discovery",
                    changes={"requirements_count": len(classified_requirements)},
                )
            ],
            is_complete=is_complete,
        )

        return spec

    def link_task_to_requirements(
        self,
        spec: ProjectSpecification,
        task_id: str,
        requirement_ids: List[str],
        components: Optional[List[str]] = None,
    ) -> None:
        """Associates downstream engineering tasks with requirements for end-to-end traceability."""
        for req_id in requirement_ids:
            if req_id in spec.traceability:
                link = spec.traceability[req_id]
                if task_id not in link.task_ids:
                    link.task_ids.append(task_id)
                if components:
                    for c in components:
                        if c not in link.architecture_components:
                            link.architecture_components.append(c)

    def record_verification(
        self,
        spec: ProjectSpecification,
        requirement_id: str,
        test_id: str,
        passed: bool,
        files: Optional[List[str]] = None,
    ) -> None:
        """Records automated verification results for requirement traceability."""
        if requirement_id in spec.traceability:
            link = spec.traceability[requirement_id]
            if test_id not in link.test_ids:
                link.test_ids.append(test_id)
            if files:
                for f in files:
                    if f not in link.modified_files:
                        link.modified_files.append(f)
            link.verification_status = "VERIFIED" if passed else "FAILED"

            req = spec.get_requirement(requirement_id)
            if req:
                req.status = RequirementStatus.VERIFIED if passed else RequirementStatus.IMPLEMENTED


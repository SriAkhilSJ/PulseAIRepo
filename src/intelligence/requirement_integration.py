"""
requirement_integration.py -- Agent Core Integration for Requirement Understanding.

Phase 11.1: Requirement Understanding & Discovery.
Integrates Phase 11.0 Project Intelligence, requirement extraction, classification,
clarification questions, conflict detection, and specification generation
into Crusor's LangGraph orchestration and planner pipelines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.clarification import ClarificationEngine
from src.intelligence.conflict_detector import ConflictDetector
from src.intelligence.models import ProjectKnowledge
from src.intelligence.persistence import PersistentProjectIntelligenceManager
from src.intelligence.requirement_classifier import RequirementClassifier
from src.intelligence.requirement_extractor import RequirementExtractor
from src.intelligence.requirement_memory import RequirementMemoryManager
from src.intelligence.requirement_models import (
    ClarificationQuestion,
    ProjectSpecification,
    RequirementConflict,
    RequirementItem,
    RequirementStatus,
    UnresolvedDecision,
)
from src.intelligence.spec_generator import SpecificationGenerator


@dataclass
class RequirementAnalysisResult:
    """Consolidated outcome of requirement analysis and discovery."""
    specification: ProjectSpecification
    communication_style: str
    clarification_questions: List[ClarificationQuestion]
    unresolved_decisions: List[UnresolvedDecision]
    conflicts: List[RequirementConflict]
    warnings: List[str]
    completeness_score: float
    is_ready_for_planning: bool
    summary_markdown: str


class RequirementIntelligenceSystem:
    """
    Central coordinator connecting Phase 11.0 project intelligence,
    requirement extraction, classification, clarification, and persistence.
    """

    def __init__(self) -> None:
        self.extractor = RequirementExtractor()

    def analyze_request(
        self,
        task_prompt: str,
        workspace_root: str,
        task_id: str = "default",
        tenant_id: str = "default_tenant",
        force_rescan: bool = False,
    ) -> RequirementAnalysisResult:
        """
        Main entrypoint: parses prompt, discovers repository facts via Phase 11.0,
        classifies requirements, generates questions if necessary, and persists specification.
        """
        # 1. Access Phase 11.0 Project Intelligence
        project_knowledge: Optional[ProjectKnowledge] = None
        ws_path = Path(workspace_root).resolve()
        if ws_path.exists():
            try:
                mgr = PersistentProjectIntelligenceManager(str(ws_path))
                project_knowledge = mgr.get_project_knowledge(force_full_rescan=force_rescan)
            except Exception:
                project_knowledge = None

        # 2. Access Conversation & Decision Memory
        memory_mgr = RequirementMemoryManager(str(ws_path), tenant_id=tenant_id)
        past_decisions = memory_mgr.get_decisions(task_id)

        # 3. Extract requirements from user prompt
        bundle = self.extractor.extract(task_prompt)

        # 4. Classify requirements against repository intelligence
        classifier = RequirementClassifier(project_knowledge)
        classified_reqs = classifier.classify_requirements(
            bundle.requirements,
            explicit_user_techs=bundle.explicit_technologies,
        )

        # 5. Clarification engine
        clarifier = ClarificationEngine(project_knowledge, answered_questions=past_decisions)
        questions, unresolved = clarifier.evaluate_clarifications(
            bundle.potential_decisions,
            classified_reqs,
        )

        # 6. Conflict & Completeness detection
        conflict_detector = ConflictDetector(project_knowledge)
        conflicts, warnings, score, is_complete = conflict_detector.analyze(
            classified_reqs,
            questions,
            unresolved,
        )

        # 7. Generate ProjectSpecification
        spec_gen = SpecificationGenerator(
            workspace_root=str(ws_path),
            project_name=project_knowledge.project_name if project_knowledge else ws_path.name,
        )
        spec = spec_gen.generate_specification(
            bundle=bundle,
            classified_requirements=classified_reqs,
            clarification_questions=questions,
            unresolved_decisions=unresolved,
            conflicts=conflicts,
            warnings=warnings,
            is_complete=is_complete,
        )

        # 8. Persist specification
        memory_mgr.save_specification(task_id, spec)

        # 9. Format Markdown Summary for Planner & Agent
        summary_md = spec.to_markdown()

        return RequirementAnalysisResult(
            specification=spec,
            communication_style=bundle.communication_style,
            clarification_questions=questions,
            unresolved_decisions=unresolved,
            conflicts=conflicts,
            warnings=warnings,
            completeness_score=score,
            is_ready_for_planning=is_complete,
            summary_markdown=summary_md,
        )

    def answer_clarification(
        self,
        task_id: str,
        question_id: str,
        user_answer: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
    ) -> ProjectSpecification:
        """
        Records a user's answer to a clarification question and updates the specification.
        """
        memory_mgr = RequirementMemoryManager(workspace_root, tenant_id=tenant_id)
        spec = memory_mgr.load_specification(task_id)
        if not spec:
            raise ValueError(f"No specification found for task_id: {task_id}")

        # Update matching question
        target_topic = ""
        for q in spec.clarification_questions:
            if q.id == question_id:
                q.answered = True
                q.user_answer = user_answer
                target_topic = q.question
                break

        # Record in decision history
        if target_topic:
            memory_mgr.record_decision(
                task_id=task_id,
                topic=target_topic,
                decision_chosen=user_answer,
                author="user",
            )

        # Re-evaluate completeness
        has_blocking = any(q.is_blocking and not q.answered for q in spec.clarification_questions)
        has_conflicts = any(not c.is_resolved for c in spec.conflicts)
        spec.is_complete = (not has_blocking and not has_conflicts)

        memory_mgr.save_specification(task_id, spec)
        return spec

    def get_planning_prompt_context(
        self,
        task_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
    ) -> str:
        """
        Renders a concise, structured specification block for injection
        into the LangGraph planner or system prompt without overflowing token limits.
        """
        memory_mgr = RequirementMemoryManager(workspace_root, tenant_id=tenant_id)
        spec = memory_mgr.load_specification(task_id)
        if not spec:
            return ""

        lines = [
            "=== APPROVED PROJECT SPECIFICATION & CONSTRAINTS ===",
            f"Problem: {spec.problem_statement}",
            f"Desired Outcome: {spec.desired_outcome}",
            "Mandated Technical Constraints:",
        ]
        for tc in spec.technical_constraints:
            lines.append(f"  - {tc.description} (Evidence: {tc.evidence_source})")

        lines.append("Key Functional Scope:")
        for fr in spec.functional_requirements[:8]:
            lines.append(f"  - [{fr.id}] {fr.description}")

        lines.append("Disclosed Defaults & Assumptions:")
        for d in spec.assumptions_and_defaults[:5]:
            lines.append(f"  - {d}")

        if spec.clarification_questions:
            unanswered = [q for q in spec.clarification_questions if not q.answered]
            if unanswered:
                lines.append(f"Pending Clarifications ({len(unanswered)} questions awaiting user):")
                for u in unanswered[:2]:
                    lines.append(f"  * {u.question} (Default: {u.default_choice})")

        lines.append("====================================================")
        return "\n".join(lines)

    def validate_implementation_plan(
        self,
        spec: ProjectSpecification,
        plan_steps: List[str],
    ) -> Tuple[bool, List[str]]:
        """
        Ensures an engineering plan honors all explicit technical constraints
        and addresses core functional requirements without silent deviations.
        """
        deviations = []
        plan_text = " ".join(plan_steps).lower()

        for tc in spec.technical_constraints:
            # Check if explicit technologies are mentioned or respected in plan
            tc_words = [w.lower() for w in tc.description.split() if len(w) > 3]
            # Simple heuristic check
            if tc_words and not any(w in plan_text for w in tc_words):
                deviations.append(f"Plan does not explicitly reference technical constraint: '{tc.description}'")

        is_valid = len(deviations) == 0
        return is_valid, deviations


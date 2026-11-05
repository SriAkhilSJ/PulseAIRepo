"""
requirement_classifier.py -- Requirement Classification & Repository Alignment Engine.

Phase 11.1: Requirement Understanding & Discovery.
Classifies requirements into EXPLICIT, DISCOVERABLE, REASONABLE_DEFAULT,
and USER_DECISION_REQUIRED. Aligns requirements with Phase 11.0 ProjectKnowledge
to prevent asking questions when repository inspection already provides the answer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import (
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
    RequirementPriority,
    RequirementStatus,
)


class RequirementClassifier:
    """
    Aligns extracted requirements against existing repository intelligence and classifies them.
    Ensures that known repository facts are marked DISCOVERABLE and not re-asked.
    """

    def __init__(self, project_knowledge: Optional[ProjectKnowledge] = None) -> None:
        self.knowledge = project_knowledge

    def classify_requirements(
        self,
        requirements: List[RequirementItem],
        explicit_user_techs: Optional[List[Tuple[str, str]]] = None,
    ) -> List[RequirementItem]:
        """
        Classifies each requirement item based on user explicit statements,
        repository intelligence, and standard engineering defaults.
        """
        explicit_names = {t[0].lower() for t in (explicit_user_techs or [])}
        classified: List[RequirementItem] = []

        for req in requirements:
            c_item = RequirementItem(
                id=req.id,
                description=req.description,
                category=req.category,
                classification=req.classification,
                priority=req.priority,
                status=req.status,
                evidence_source=req.evidence_source,
                acceptance_criteria=list(req.acceptance_criteria),
                conflicts_with=list(req.conflicts_with),
                dependencies=list(req.dependencies),
                rationale=req.rationale,
            )

            desc_lower = req.description.lower()

            # 1. Check if user explicitly mandated this technical constraint
            if req.category == RequirementCategory.TECHNICAL_CONSTRAINT and (
                any(tech in desc_lower for tech in explicit_names) or req.classification == RequirementClassification.EXPLICIT
            ):
                c_item.classification = RequirementClassification.EXPLICIT
                c_item.status = RequirementStatus.ACCEPTED
                if not c_item.evidence_source:
                    c_item.evidence_source = "Explicitly stated in user prompt"
                classified.append(c_item)
                continue

            # 2. Check if discoverable in existing repository intelligence
            discoverable_evidence = self._check_repository_discovery(desc_lower)
            if discoverable_evidence:
                c_item.classification = RequirementClassification.DISCOVERABLE
                c_item.status = RequirementStatus.ACCEPTED
                c_item.evidence_source = discoverable_evidence
                c_item.rationale = "Discovered from existing repository structure and configuration"
                classified.append(c_item)
                continue

            # 3. Check if directly stated by user in prompt
            if req.classification == RequirementClassification.EXPLICIT:
                c_item.classification = RequirementClassification.EXPLICIT
                c_item.status = RequirementStatus.ACCEPTED
                classified.append(c_item)
                continue

            # 3. Check if this is an essential business decision requiring user choice
            if self._is_user_decision_required(desc_lower, req.category):
                c_item.classification = RequirementClassification.USER_DECISION_REQUIRED
                c_item.status = RequirementStatus.PROPOSED
                c_item.rationale = "Material business or architectural choice that cannot be safely assumed"
                classified.append(c_item)
                continue

            # 4. Otherwise, it is a reasonable engineering default
            c_item.classification = RequirementClassification.REASONABLE_DEFAULT
            c_item.status = RequirementStatus.ACCEPTED
            if not c_item.evidence_source:
                c_item.evidence_source = "Standard software engineering practice"
            if not c_item.rationale:
                c_item.rationale = "Safe technical default applied without requiring user intervention"
            classified.append(c_item)

        return classified

    def _check_repository_discovery(self, text: str) -> Optional[str]:
        if not self.knowledge:
            return None

        # Check existing frameworks
        for f in self.knowledge.frameworks:
            fname = f.name.lower()
            if fname in text or (fname == "fastapi" and any(k in text for k in ["api", "endpoint", "route", "controller", "handler"])) or (fname == "nextjs" and any(k in text for k in ["frontend", "ui", "page", "client"])):
                manifest_info = getattr(f, "source_manifest", "") or getattr(f, "evidence", "")
                return f"Discovered existing framework {f.name} in repository ({manifest_info})"

        # Check existing languages
        for lang_name in self.knowledge.languages.keys():
            if lang_name.lower() in text:
                return f"Discovered primary language {lang_name} in repository"

        # Check existing test commands
        if "test" in text and getattr(self.knowledge.build_commands, "test", None):
            return f"Discovered test command: '{self.knowledge.build_commands.test}'"

        # Check existing build commands
        if "build" in text and getattr(self.knowledge.build_commands, "build", None):
            return f"Discovered build command: '{self.knowledge.build_commands.build}'"

        # Check database models
        if "database" in text or "schema" in text or "model" in text:
            db_info = getattr(self.knowledge, "database_info", None)
            if db_info:
                return f"Discovered existing database technology ({getattr(db_info, 'orm_or_driver', 'Database')}) in repository"

        # Check components
        for cname in self.knowledge.architecture_map.components.keys():
            if cname.lower() in text:
                return f"Discovered existing subsystem '{cname}' in repository"

        return None

    def _is_user_decision_required(self, text: str, category: RequirementCategory) -> bool:
        # Decisions that materially alter product architecture, business scope, or payment handling
        decision_patterns = [
            "single-vendor" in text and "multi-vendor" in text,
            "payment provider" in text or "payment gateway" in text,
            "prototype" in text and "production" in text,
            "license" in text or "compliance" in text or "pricing tier" in text,
            "irreversible" in text or "data migration" in text,
        ]
        if any(decision_patterns):
            return True

        # Never ask ordinary technical implementation details:
        # "Should I use functions?", "Should I create components?", "Should I use a service layer?"
        forbidden_questions = [
            "function", "component", "service layer", "variable", "class", "file structure"
        ]
        if any(fq in text for fq in forbidden_questions):
            return False

        return False

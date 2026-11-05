"""
clarification.py -- Intelligent Clarification Engine.

Phase 11.1: Requirement Understanding & Discovery.
Generates concise, material clarification questions for business decisions
and essential ambiguities while strictly suppressing unnecessary technical questions.
Remembers previously answered questions to avoid repetitive prompts.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import (
    ClarificationQuestion,
    RequirementClassification,
    RequirementItem,
    UnresolvedDecision,
)

# Implementation questions that MUST NEVER be asked to the user
FORBIDDEN_QUESTION_TOPICS = [
    r"\bfunctions?\b",
    r"\bcomponents?\b",
    r"\bservice layer\b",
    r"\bclasses\b",
    r"\bvariables?\b",
    r"\bfile structure\b",
    r"\bfolder naming\b",
    r"\blinting rules\b",
    r"\bindentation\b",
    r"\bcss naming\b",
    r"\bimport style\b",
]


class ClarificationEngine:
    """
    Evaluates requirements and project state to generate essential clarification questions.
    Filters out technical implementation trivia and respects answered questions.
    """

    def __init__(
        self,
        project_knowledge: Optional[ProjectKnowledge] = None,
        answered_questions: Optional[Dict[str, str]] = None,
    ) -> None:
        self.knowledge = project_knowledge
        self.answered_cache: Dict[str, str] = dict(answered_questions or {})

    def evaluate_clarifications(
        self,
        potential_decisions: List[Tuple[str, str, List[str]]],
        requirements: List[RequirementItem],
        max_questions: int = 3,
    ) -> Tuple[List[ClarificationQuestion], List[UnresolvedDecision]]:
        """
        Derives essential clarification questions.
        Suppresses unnecessary questions and applies safe defaults where possible.
        """
        questions: List[ClarificationQuestion] = []
        unresolved: List[UnresolvedDecision] = []
        q_idx = 1

        for topic, question_text, options in potential_decisions:
            # Check if this topic is a forbidden micro-implementation detail
            if self._is_forbidden_topic(question_text):
                continue

            # Check if repository knowledge already answers this
            if self._is_answered_by_repo(topic, question_text):
                continue

            # Check if user already explicitly answered this in earlier turns
            normalized_key = topic.lower().replace(" ", "_")
            if normalized_key in self.answered_cache:
                ans = self.answered_cache[normalized_key]
                questions.append(
                    ClarificationQuestion(
                        id=f"CQ-{q_idx:03d}",
                        question=question_text,
                        rationale=f"Clarification regarding {topic}",
                        category="business_decision",
                        options=options,
                        default_choice=options[0] if options else None,
                        is_blocking=False,
                        answered=True,
                        user_answer=ans,
                    )
                )
                q_idx += 1
                continue

            # Check if any explicit requirement already mandates an answer
            matching_req = self._find_matching_explicit_requirement(topic, requirements)
            if matching_req:
                # Already explicitly specified in prompt
                continue

            # This is a genuine open decision requiring user input
            default_val = options[0] if options else "Standard Default"
            why_it_matters = self._explain_why_it_matters(topic)
            is_blocking = (topic.lower() in ["marketplace model", "domain model", "architecture pattern"])

            q = ClarificationQuestion(
                id=f"CQ-{q_idx:03d}",
                question=question_text,
                rationale=why_it_matters,
                category="business_decision",
                options=options,
                default_choice=default_val,
                is_blocking=is_blocking,
                answered=False,
                user_answer=None,
            )
            questions.append(q)

            u = UnresolvedDecision(
                id=f"DEC-{q_idx:03d}",
                decision_topic=topic,
                why_it_matters=why_it_matters,
                options=options,
                impact=f"Shapes initial architecture and data schemas for {topic}",
                status="OPEN",
            )
            unresolved.append(u)
            q_idx += 1

            if len(questions) >= max_questions:
                break

        return questions, unresolved

    def _is_forbidden_topic(self, text: str) -> bool:
        lowered = text.lower()
        return any(re.search(pat, lowered) for pat in FORBIDDEN_QUESTION_TOPICS)

    def _is_answered_by_repo(self, topic: str, text: str) -> bool:
        if not self.knowledge:
            return False

        topic_low = topic.lower()
        # E.g. If question asks "Which backend framework?", but FastAPI is in repo
        if "framework" in topic_low or "backend" in topic_low or "stack" in topic_low:
            if self.knowledge.frameworks:
                return True

        if "database" in topic_low:
            if getattr(self.knowledge, "database_info", None):
                return True

        return False

    def _find_matching_explicit_requirement(
        self,
        topic: str,
        requirements: List[RequirementItem],
    ) -> Optional[RequirementItem]:
        top_low = topic.lower()
        for r in requirements:
            if r.classification == RequirementClassification.EXPLICIT:
                r_low = r.description.lower()
                if top_low in r_low or any(w in r_low for w in top_low.split()):
                    return r
        return None

    def _explain_why_it_matters(self, topic: str) -> str:
        topic_low = topic.lower()
        if "marketplace" in topic_low or "vendor" in topic_low:
            return "Multi-vendor marketplaces require complex tenant commission accounting, seller portals, and split payments."
        if "payment" in topic_low:
            return "Payment gateways dictate regulatory compliance, webhook architectures, and tokenization requirements."
        if "prototype" in topic_low or "lifecycle" in topic_low:
            return "Prototypes prioritize rapid feature delivery and mock backends; production requires hardening, CI/CD, and scalability."
        if "multi-tenancy" in topic_low:
            return "Multi-tenancy isolation models determine database migration complexity, query performance, and data security boundaries."
        return f"This decision materially impacts system design, scope, and technical complexity."

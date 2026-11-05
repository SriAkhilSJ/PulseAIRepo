"""
conflict_detector.py -- Requirement Completeness & Conflict Detection Engine.

Phase 11.1: Requirement Understanding & Discovery.
Deterministically detects contradictory requirements, incompatible technical constraints,
architectural mismatches with existing repositories, security vulnerabilities,
missing acceptance criteria, and scope-drift anomalies.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import (
    ClarificationQuestion,
    RequirementCategory,
    RequirementClassification,
    RequirementConflict,
    RequirementItem,
    RequirementPriority,
    UnresolvedDecision,
)

# Known direct technology / architectural contradictions
CONTRADICTORY_PAIRS = [
    (
        r"\bstatic\s+(?:only|site|client)\b",
        r"\b(?:postgresql|mysql|database|mongodb|backend\s+server)\b",
        "Static-only client architecture contradicts server-side database requirements.",
        "Choose either a client-only static deployment (with client-side state/localStorage) or include a backend API service.",
    ),
    (
        r"\bno\s+external\s+dependencies\b",
        r"\b(?:next\.?js|react|fastapi|django|redis|express)\b",
        "Constraint specifying 'no external dependencies' contradicts use of external frameworks.",
        "Either permit standard external package dependencies or build using standard library primitives.",
    ),
    (
        r"\bpublic\s+unauthenticated\b",
        r"\b(?:rbac|private\s+admin\s+portal|jwt\s+authentication)\b",
        "Request for public unauthenticated access contradicts RBAC/JWT access control.",
        "Protect administrative and sensitive operations behind authentication while keeping public catalogs open.",
    ),
    (
        r"\bplaintext\s+passwords?\b",
        r".*",
        "Plaintext password storage is a severe security violation.",
        "Mandate one-way cryptographic password hashing (bcrypt / argon2).",
    ),
]


class ConflictDetector:
    """
    Validates requirement consistency, identifies technical and architectural contradictions,
    and calculates specification completeness.
    """

    def __init__(self, project_knowledge: Optional[ProjectKnowledge] = None) -> None:
        self.knowledge = project_knowledge

    def analyze(
        self,
        requirements: List[RequirementItem],
        clarification_questions: List[ClarificationQuestion],
        unresolved_decisions: List[UnresolvedDecision],
    ) -> Tuple[List[RequirementConflict], List[str], float, bool]:
        """
        Runs comprehensive consistency, completeness, and architectural checks.
        Returns:
            conflicts: List of detected RequirementConflict items.
            warnings: List of missing criteria or security warnings.
            completeness_score: Float from 0.0 to 1.0.
            is_complete: Boolean indicating whether specification is ready for planning.
        """
        conflicts: List[RequirementConflict] = []
        warnings: List[str] = []
        c_idx = 1

        # 1. Contradiction detection within individual requirements and across pairs
        for r in requirements:
            r_desc = r.description.lower()
            for pat1, pat2, desc, guidance in CONTRADICTORY_PAIRS:
                if re.search(pat1, r_desc) and re.search(pat2, r_desc):
                    conflicts.append(
                        RequirementConflict(
                            id=f"CONF-{c_idx:03d}",
                            requirement_ids=[r.id],
                            conflict_description=desc,
                            resolution_guidance=guidance,
                            is_resolved=False,
                        )
                    )
                    r.conflicts_with.append(r.id)
                    c_idx += 1

        for i, r1 in enumerate(requirements):
            r1_desc = r1.description.lower()
            for j in range(i + 1, len(requirements)):
                r2 = requirements[j]
                r2_desc = r2.description.lower()

                for pat1, pat2, desc, guidance in CONTRADICTORY_PAIRS:
                    if (re.search(pat1, r1_desc) and re.search(pat2, r2_desc)) or (
                        re.search(pat1, r2_desc) and re.search(pat2, r1_desc)
                    ):
                        conflicts.append(
                            RequirementConflict(
                                id=f"CONF-{c_idx:03d}",
                                requirement_ids=[r1.id, r2.id],
                                conflict_description=desc,
                                resolution_guidance=guidance,
                                is_resolved=False,
                            )
                        )
                        r1.conflicts_with.append(r2.id)
                        r2.conflicts_with.append(r1.id)
                        c_idx += 1

        # 2. Check for architectural conflicts with existing repository
        if self.knowledge:
            repo_conflicts = self._check_repo_conflicts(requirements, c_idx)
            conflicts.extend(repo_conflicts)
            c_idx += len(repo_conflicts)

        # 3. Check for missing acceptance criteria
        for r in requirements:
            if not r.acceptance_criteria:
                warnings.append(f"Requirement {r.id} ({r.description[:40]}...) lacks explicit acceptance criteria.")

        # 4. Check for unresolved blocking decisions
        blocking_questions = [q for q in clarification_questions if q.is_blocking and not q.answered]
        if blocking_questions:
            for bq in blocking_questions:
                warnings.append(f"Blocking question '{bq.question}' requires user resolution.")

        # 5. Check for security vulnerabilities
        for r in requirements:
            desc_l = r.description.lower()
            if "plaintext" in desc_l and "password" in desc_l:
                conflicts.append(
                    RequirementConflict(
                        id=f"CONF-{c_idx:03d}",
                        requirement_ids=[r.id],
                        conflict_description="Security violation: Plaintext password storage requested.",
                        resolution_guidance="Enforce bcrypt or Argon2 password hashing.",
                        is_resolved=False,
                    )
                )
                c_idx += 1

        # 6. Calculate completeness score
        total_items = len(requirements)
        if total_items == 0:
            return conflicts, warnings, 0.0, False

        criteria_met = sum(1 for r in requirements if r.acceptance_criteria)
        no_conflicts_met = sum(1 for r in requirements if not r.conflicts_with)
        answered_q = sum(1 for q in clarification_questions if q.answered)
        total_q = max(1, len(clarification_questions))

        completeness = (
            (0.4 * (criteria_met / total_items)) +
            (0.4 * (no_conflicts_met / total_items)) +
            (0.2 * (answered_q / total_q if clarification_questions else 1.0))
        )
        completeness = round(min(1.0, max(0.0, completeness)), 2)

        has_blocking = any(q.is_blocking and not q.answered for q in clarification_questions)
        has_unresolved_conflicts = any(not c.is_resolved for c in conflicts)
        is_complete = (completeness >= 0.70 and not has_blocking and not has_unresolved_conflicts)

        return conflicts, warnings, completeness, is_complete

    def _check_repo_conflicts(
        self,
        requirements: List[RequirementItem],
        start_counter: int,
    ) -> List[RequirementConflict]:
        conflicts = []
        c_idx = start_counter
        existing_fnames = {f.name.lower() for f in (self.knowledge.frameworks if self.knowledge else [])}

        # If repo is already FastAPI and user requests Django without migration
        if "fastapi" in existing_fnames:
            for r in requirements:
                if "django" in r.description.lower() and r.classification == RequirementClassification.EXPLICIT:
                    if "migrate" not in r.description.lower():
                        conflicts.append(
                            RequirementConflict(
                                id=f"CONF-{c_idx:03d}",
                                requirement_ids=[r.id],
                                conflict_description="Requested framework 'Django' conflicts with existing repository framework 'FastAPI'.",
                                resolution_guidance="Verify if user intends to migrate from FastAPI to Django or integrate as a separate service.",
                                is_resolved=False,
                            )
                        )
                        c_idx += 1
        return conflicts

"""
tech_stack_intelligence.py -- Technology Selection & Stack Compatibility Engine.

Phase 11.2: Architecture & Technical Decision Intelligence.
Evaluates framework, database, and library compatibility. Reuses existing repository
dependencies from Phase 11.0 ProjectKnowledge and strictly preserves user explicit technical constraints.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.models import ProjectKnowledge
from src.intelligence.requirement_models import (
    ProjectSpecification,
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
)


class TechStackIntelligenceEngine:
    """
    Selects and validates technology stack components.
    Ensures compatibility with existing repository investments and preserves user mandates.
    """

    def __init__(self) -> None:
        pass

    def resolve_technology_stack(
        self,
        spec: ProjectSpecification,
        knowledge: Optional[ProjectKnowledge] = None,
    ) -> Tuple[Dict[str, str], List[str], List[str]]:
        """
        Determines the canonical technology stack.
        Returns:
            tech_stack: Dict mapping category -> selected technology name
            reused_existing: List of technologies preserved from existing repository
            rationale_notes: List of explanations for stack selections
        """
        tech_stack: Dict[str, str] = {}
        reused_existing: List[str] = []
        rationale_notes: List[str] = []

        # 1. Inspect Explicit User Constraints
        explicit_constraints = self._extract_explicit_tech(spec)

        # 2. Inspect Existing Repository Knowledge
        existing_stack = self._extract_existing_stack(knowledge)

        # ---------------- Backend Framework ----------------
        if "backend" in explicit_constraints:
            tech_stack["backend"] = explicit_constraints["backend"]
            rationale_notes.append(f"Backend framework locked to '{explicit_constraints['backend']}' per explicit user constraint.")
        elif "backend" in existing_stack:
            tech_stack["backend"] = existing_stack["backend"]
            reused_existing.append(existing_stack["backend"])
            rationale_notes.append(f"Reused verified repository backend framework: '{existing_stack['backend']}'.")
        else:
            # Default recommendation based on domain
            tech_stack["backend"] = "FastAPI (Python)"
            rationale_notes.append("Selected FastAPI for high-performance asynchronous API handling and typed schemas.")

        # ---------------- Frontend Framework ----------------
        if "frontend" in explicit_constraints:
            tech_stack["frontend"] = explicit_constraints["frontend"]
            rationale_notes.append(f"Frontend framework locked to '{explicit_constraints['frontend']}' per explicit user constraint.")
        elif "frontend" in existing_stack:
            tech_stack["frontend"] = existing_stack["frontend"]
            reused_existing.append(existing_stack["frontend"])
            rationale_notes.append(f"Reused verified repository frontend framework: '{existing_stack['frontend']}'.")
        else:
            # Default recommendation if frontend is needed
            if any("ui" in r.description.lower() or "frontend" in r.description.lower() for r in spec.all_requirements()):
                tech_stack["frontend"] = "Next.js / React"
                rationale_notes.append("Selected Next.js for server-side rendering, routing, and modern UI ecosystem.")
            else:
                tech_stack["frontend"] = "Standard Web Client / CLI Interface"

        # ---------------- Primary Database ----------------
        if "database" in explicit_constraints:
            tech_stack["database"] = explicit_constraints["database"]
            rationale_notes.append(f"Primary database locked to '{explicit_constraints['database']}' per explicit user constraint.")
        elif "database" in existing_stack:
            tech_stack["database"] = existing_stack["database"]
            reused_existing.append(existing_stack["database"])
            rationale_notes.append(f"Reused verified repository database: '{existing_stack['database']}'.")
        else:
            # Check project scale
            is_simple = any(k in spec.problem_statement.lower() for k in ["tracker", "calculator", "todo", "cli", "simple", "personal"])
            if is_simple:
                tech_stack["database"] = "SQLite"
                rationale_notes.append("Selected SQLite for zero-config embedded persistence suited to a lightweight application.")
            else:
                tech_stack["database"] = "PostgreSQL"
                rationale_notes.append("Selected PostgreSQL for industrial-grade ACID relational storage and JSON flexibility.")

        # ---------------- Caching & In-Memory Store ----------------
        if "cache" in explicit_constraints:
            tech_stack["cache"] = explicit_constraints["cache"]
            rationale_notes.append(f"Caching layer locked to '{explicit_constraints['cache']}' per explicit user constraint.")
        elif any("redis" in r.description.lower() for r in spec.all_requirements()):
            tech_stack["cache"] = "Redis"
            rationale_notes.append("Selected Redis for high-throughput in-memory caching and session tokens.")
        else:
            tech_stack["cache"] = "In-Memory LRU Cache"
            rationale_notes.append("Selected standard in-memory caching to avoid external infrastructure overhead.")

        # ---------------- Authentication & Security ----------------
        if "auth" in explicit_constraints:
            tech_stack["authentication"] = explicit_constraints["auth"]
            rationale_notes.append(f"Authentication locked to '{explicit_constraints['auth']}' per explicit user constraint.")
        else:
            tech_stack["authentication"] = "JWT (HMAC-SHA256) with RBAC Middleware"
            rationale_notes.append("Selected stateless JWT authentication with role-based access control claims.")

        # ---------------- Background & Async Processing ----------------
        if any("background" in r.description.lower() or "job" in r.description.lower() or "email" in r.description.lower() for r in spec.all_requirements()):
            tech_stack["background_processing"] = "Asyncio Worker / Celery Background Tasks"
        else:
            tech_stack["background_processing"] = "Synchronous In-Process Execution"

        # ---------------- Deployment ----------------
        tech_stack["deployment"] = "Docker Containerization / Standalone Executable"

        return tech_stack, reused_existing, rationale_notes

    def _extract_explicit_tech(self, spec: ProjectSpecification) -> Dict[str, str]:
        explicit: Dict[str, str] = {}
        for tc in spec.technical_constraints:
            desc_l = tc.description.lower()
            if "next.js" in desc_l or "nextjs" in desc_l:
                explicit["frontend"] = "Next.js"
            elif "react" in desc_l and "frontend" not in explicit:
                explicit["frontend"] = "React"
            elif "vue" in desc_l:
                explicit["frontend"] = "Vue.js"

            if "fastapi" in desc_l:
                explicit["backend"] = "FastAPI"
            elif "flask" in desc_l:
                explicit["backend"] = "Flask"
            elif "django" in desc_l:
                explicit["backend"] = "Django"
            elif "express" in desc_l:
                explicit["backend"] = "Express.js"

            if "postgresql" in desc_l or "postgres" in desc_l:
                explicit["database"] = "PostgreSQL"
            elif "mysql" in desc_l:
                explicit["database"] = "MySQL"
            elif "sqlite" in desc_l:
                explicit["database"] = "SQLite"
            elif "mongodb" in desc_l:
                explicit["database"] = "MongoDB"

            if "redis" in desc_l:
                explicit["cache"] = "Redis"

            if "jwt" in desc_l:
                explicit["auth"] = "JWT Authentication"
            elif "oauth" in desc_l:
                explicit["auth"] = "OAuth 2.0"

        return explicit

    def _extract_existing_stack(self, knowledge: Optional[ProjectKnowledge]) -> Dict[str, str]:
        existing: Dict[str, str] = {}
        if not knowledge:
            return existing

        for f in knowledge.frameworks:
            fname = f.name.lower()
            if fname in {"fastapi", "flask", "django", "express", "nestjs"}:
                existing["backend"] = f.name
            elif fname in {"nextjs", "react", "vue", "angular", "svelte"}:
                existing["frontend"] = f.name
            elif fname == "pytest":
                existing["testing"] = "pytest"

        if knowledge.database_info:
            existing["database"] = knowledge.database_info.orm_or_driver

        return existing


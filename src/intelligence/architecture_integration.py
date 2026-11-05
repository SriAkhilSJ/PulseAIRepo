"""
architecture_integration.py -- Agent Core Integration for Architecture Intelligence.

Phase 11.2: Architecture & Technical Decision Intelligence.
Coordinates driver extraction, alternative evaluation, technology stack selection,
data & security architecture analysis, ADR lifecycle, and blueprint generation.
Provides clean context integration for Crusor's LangGraph planner and execution loops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.adr_manager import ADRManager
from src.intelligence.architecture_alternatives import ArchitectureAlternativeEngine
from src.intelligence.architecture_drivers import ArchitectureDriverExtractor
from src.intelligence.architecture_models import (
    ArchitectureAlternative,
    ArchitectureBlueprint,
    ArchitectureDecisionRecord,
    ArchitectureDriver,
    DecisionApprovalStatus,
)
from src.intelligence.blueprint_generator import ArchitectureBlueprintGenerator
from src.intelligence.data_and_security import (
    DataArchitectureAnalyzer,
    SecurityArchitectureAnalyzer,
)
from src.intelligence.models import ProjectKnowledge
from src.intelligence.persistence import PersistentProjectIntelligenceManager
from src.intelligence.requirement_memory import RequirementMemoryManager
from src.intelligence.requirement_models import ProjectSpecification
from src.intelligence.tech_stack_intelligence import TechStackIntelligenceEngine


@dataclass
class ArchitectureSynthesisResult:
    """Consolidated outcome of architectural synthesis and evaluation."""
    blueprint: ArchitectureBlueprint
    selected_alternative: ArchitectureAlternative
    all_alternatives: List[ArchitectureAlternative]
    drivers: List[ArchitectureDriver]
    adrs: List[ArchitectureDecisionRecord]
    is_ready_for_planning: bool
    summary_markdown: str


class ArchitectureIntelligenceSystem:
    """
    Central coordinator orchestrating Phase 11.2 Architecture & Technical Decision Intelligence.
    Consumes ProjectKnowledge (11.0) and ProjectSpecification (11.1) to produce an actionable ArchitectureBlueprint.
    """

    def __init__(self) -> None:
        self.driver_extractor = ArchitectureDriverExtractor()
        self.alternative_engine = ArchitectureAlternativeEngine()
        self.tech_engine = TechStackIntelligenceEngine()
        self.data_analyzer = DataArchitectureAnalyzer()
        self.security_analyzer = SecurityArchitectureAnalyzer()

    def synthesize_architecture(
        self,
        task_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        force_rescan: bool = False,
    ) -> ArchitectureSynthesisResult:
        ws_path = Path(workspace_root).resolve()

        # 1. Access Phase 11.0 Project Intelligence
        project_knowledge: Optional[ProjectKnowledge] = None
        if ws_path.exists():
            try:
                kmgr = PersistentProjectIntelligenceManager(str(ws_path))
                project_knowledge = kmgr.get_project_knowledge(force_full_rescan=force_rescan)
            except Exception:
                project_knowledge = None

        # 2. Access Phase 11.1 Project Specification
        req_memory = RequirementMemoryManager(str(ws_path), tenant_id=tenant_id)
        spec = req_memory.load_specification(task_id)
        if not spec:
            raise ValueError(f"Cannot synthesize architecture: No ProjectSpecification found for task_id '{task_id}'.")

        # 3. Extract Architecture Drivers
        drivers = self.driver_extractor.extract_drivers(spec, project_knowledge)

        # 4. Generate & Evaluate Architectural Alternatives
        all_alts, selected_alt = self.alternative_engine.evaluate_alternatives(spec, drivers, project_knowledge)

        # 5. Resolve Technology Stack
        tech_stack, reused_tech, tech_notes = self.tech_engine.resolve_technology_stack(spec, project_knowledge)

        # 6. Synthesize Data & Security Architecture
        data_arch = self.data_analyzer.analyze(spec, tech_stack)
        sec_arch = self.security_analyzer.analyze(spec, tech_stack)

        # 7. Create & Persist Architecture Decision Records (ADRs)
        adr_mgr = ADRManager(str(ws_path), tenant_id=tenant_id)
        adrs = adr_mgr.create_core_adrs(spec, selected_alt, all_alts, tech_stack)

        # 8. Generate Complete Architecture Blueprint
        blueprint_gen = ArchitectureBlueprintGenerator(
            workspace_root=str(ws_path),
            project_name=spec.project_name or ws_path.name,
        )
        blueprint = blueprint_gen.generate_blueprint(
            spec=spec,
            selected_alt=selected_alt,
            all_alts=all_alts,
            drivers=drivers,
            adrs=adrs,
            tech_stack=tech_stack,
            data_arch=data_arch,
            sec_arch=sec_arch,
            knowledge=project_knowledge,
        )

        # 9. Persist Blueprint
        self.save_blueprint(task_id, blueprint, str(ws_path), tenant_id=tenant_id)

        # 10. Format Markdown
        summary_md = blueprint.to_markdown()

        # Ready for planning if viable and no fatal blockers
        is_ready = bool(selected_alt.is_viable and len(blueprint.components) > 0)

        return ArchitectureSynthesisResult(
            blueprint=blueprint,
            selected_alternative=selected_alt,
            all_alternatives=all_alts,
            drivers=drivers,
            adrs=adrs,
            is_ready_for_planning=is_ready,
            summary_markdown=summary_md,
        )

    def _blueprint_path(self, task_id: str, workspace_root: str, tenant_id: str) -> Path:
        safe_id = "".join(c for c in task_id if c.isalnum() or c in ("-", "_")) or "default"
        storage_dir = Path(workspace_root).resolve() / ".crusorai" / "tenants" / tenant_id / "architecture"
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir / f"blueprint_{safe_id}.json"

    def save_blueprint(
        self,
        task_id: str,
        blueprint: ArchitectureBlueprint,
        workspace_root: str,
        tenant_id: str = "default_tenant",
    ) -> None:
        target = self._blueprint_path(task_id, workspace_root, tenant_id)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(blueprint.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(target)

    def load_blueprint(
        self,
        task_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
    ) -> Optional[ArchitectureBlueprint]:
        target = self._blueprint_path(task_id, workspace_root, tenant_id)
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return ArchitectureBlueprint.from_dict(data)
        except Exception:
            return None

    def approve_adr(
        self,
        task_id: str,
        adr_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        author: str = "user",
    ) -> ArchitectureDecisionRecord:
        """Approves a proposed ADR and updates the persisted blueprint."""
        adr_mgr = ADRManager(workspace_root, tenant_id=tenant_id)
        updated_adr = adr_mgr.update_approval_status(
            adr_id, DecisionApprovalStatus.APPROVED, reason="Approved by user", author=author
        )

        blueprint = self.load_blueprint(task_id, workspace_root, tenant_id=tenant_id)
        if blueprint:
            for idx, a in enumerate(blueprint.adrs):
                if a.id == adr_id:
                    blueprint.adrs[idx] = updated_adr
                    break
            blueprint.is_approved = all(a.approval_status == DecisionApprovalStatus.APPROVED for a in blueprint.adrs)
            self.save_blueprint(task_id, blueprint, workspace_root, tenant_id=tenant_id)

        return updated_adr

    def get_planner_architecture_context(
        self,
        task_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
    ) -> str:
        """
        Renders a concise, structured architecture summary block for injection
        into the LangGraph planner or system prompt without overflowing token budgets.
        """
        bp = self.load_blueprint(task_id, workspace_root, tenant_id=tenant_id)
        if not bp:
            return ""

        lines = [
            "=== APPROVED ARCHITECTURE BLUEPRINT ===",
            f"Style: {bp.architecture_style.value} (Approved: {bp.is_approved})",
            "Technology Stack:",
        ]
        for cat, tech in bp.technology_stack.items():
            lines.append(f"  - {cat.title()}: {tech}")

        lines.append("Component Layout & Boundaries:")
        for c in bp.components[:4]:
            lines.append(f"  - [{c.name}] ({c.category}): {c.boundaries[:80]}")

        lines.append(f"Persistence: {bp.database_architecture.database_choice} ({bp.database_architecture.tenant_isolation_strategy})")
        lines.append(f"Security: {bp.security_architecture.authorization_model}")

        if bp.adrs:
            lines.append("Key Architecture Decisions (ADRs):")
            for adr in bp.adrs[:3]:
                lines.append(f"  * [{adr.id}] {adr.title} -> {adr.approval_status.value}")

        lines.append("=========================================")
        return "\n".join(lines)

    def validate_plan_against_blueprint(
        self,
        blueprint: ArchitectureBlueprint,
        plan_steps: List[str],
    ) -> Tuple[bool, List[str]]:
        """
        Validates that downstream engineering plan steps adhere to the architecture blueprint.
        Detects unauthorized deviations (e.g. creating microservices when blueprint specifies modular monolith).
        """
        deviations: List[str] = []
        plan_text = " ".join(plan_steps).lower()

        # Check architecture style deviations
        if blueprint.architecture_style.value == "MODULAR_MONOLITH":
            if "microservice" in plan_text and "modular monolith" not in plan_text:
                deviations.append("Plan introduces microservices despite blueprint specifying Modular Monolith architecture.")

        # Check database deviations
        expected_db = blueprint.database_architecture.database_choice.lower()
        if "postgresql" in expected_db and "mongodb" in plan_text:
            deviations.append("Plan introduces MongoDB despite blueprint specifying PostgreSQL.")

        is_valid = len(deviations) == 0
        return is_valid, deviations


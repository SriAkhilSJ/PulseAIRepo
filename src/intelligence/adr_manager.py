"""
adr_manager.py -- Architecture Decision Record (ADR) Management Engine.

Phase 11.2: Architecture & Technical Decision Intelligence.
Creates, persists, updates, and audits formal Architecture Decision Records (ADRs).
Enforces approval lifecycle, revision histories, and explicit user decision locks.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.architecture_models import (
    ArchitectureAlternative,
    ArchitectureDecisionRecord,
    ArchitecturePattern,
    DecisionApprovalStatus,
)
from src.intelligence.requirement_models import ProjectSpecification


class ADRManager:
    """
    Manages persistent Architecture Decision Records per workspace and tenant.
    Enforces revision tracking and approval status gates.
    """

    def __init__(self, workspace_root: str, tenant_id: str = "default_tenant") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id
        self.adr_dir = self.workspace_root / ".crusorai" / "tenants" / tenant_id / "architecture" / "adrs"
        self.adr_dir.mkdir(parents=True, exist_ok=True)

    def create_core_adrs(
        self,
        spec: ProjectSpecification,
        selected_alt: ArchitectureAlternative,
        all_alts: List[ArchitectureAlternative],
        tech_stack: Dict[str, str],
    ) -> List[ArchitectureDecisionRecord]:
        adrs: List[ArchitectureDecisionRecord] = []

        # ADR-001: Overall Architecture Style
        rejected_styles = {
            alt.name: alt.elimination_reason or ("; ".join(alt.disadvantages[:2]) if alt.disadvantages else "Scored lower")
            for alt in all_alts
            if alt.name != selected_alt.name
        }
        # If user explicitly requested this architecture style, mark APPROVED directly
        is_user_explicit_style = any(
            tc.description.lower() in selected_alt.name.lower() or selected_alt.pattern.value.lower() in tc.description.lower()
            for tc in spec.technical_constraints
        )
        status_001 = DecisionApprovalStatus.APPROVED if is_user_explicit_style else DecisionApprovalStatus.PROPOSED

        adrs.append(
            ArchitectureDecisionRecord(
                id="ADR-001",
                title=f"Adopt {selected_alt.name} Architecture Style",
                context=f"The application requires an architectural baseline satisfying problem statement: '{spec.problem_statement[:150]}...'",
                related_requirement_ids=[r.id for r in spec.all_requirements()][:4],
                alternatives_considered=[a.name for a in all_alts],
                selected_decision=selected_alt.name,
                rationale=f"Selected {selected_alt.name} because it provides optimal balance between development velocity and long-term modularity.",
                tradeoffs=selected_alt.disadvantages[:2] if selected_alt.disadvantages else ["Requires strict internal boundaries"],
                rejected_alternatives=rejected_styles,
                risks=selected_alt.major_risks[:2] if selected_alt.major_risks else ["Potential boundary leakage"],
                confidence="HIGH",
                approval_status=status_001,
                is_user_explicit=is_user_explicit_style,
                version=1,
            )
        )

        # ADR-002: Primary Technology Stack
        backend = tech_stack.get("backend", "FastAPI")
        frontend = tech_stack.get("frontend", "Next.js")
        db = tech_stack.get("database", "PostgreSQL")
        is_user_explicit_stack = any(tc.category.value == "TECHNICAL_CONSTRAINT" for tc in spec.technical_constraints)
        status_002 = DecisionApprovalStatus.APPROVED if is_user_explicit_stack else DecisionApprovalStatus.PROPOSED

        adrs.append(
            ArchitectureDecisionRecord(
                id="ADR-002",
                title=f"Standardize on {backend} (Backend), {frontend} (Frontend), and {db} (Database)",
                context="A reliable, unified technology stack is required to implement application features and maintain high velocity.",
                related_requirement_ids=[tc.id for tc in spec.technical_constraints],
                alternatives_considered=["Django/Flask", "React SPA", "MySQL/MongoDB"],
                selected_decision=f"Backend: {backend} | Frontend: {frontend} | Database: {db}",
                rationale="Aligns with explicit user requirements, modern asynchronous performance standards, and existing repository capabilities.",
                tradeoffs=["Dual-language runtime if frontend and backend differ", "Relational schema migration discipline required"],
                rejected_alternatives={"NoSQL Document Store": "Lacks native ACID multi-entity foreign key guarantees needed for core domain"},
                risks=["Ecosystem upgrade churn"],
                confidence="HIGH",
                approval_status=status_002,
                is_user_explicit=is_user_explicit_stack,
                version=1,
            )
        )

        # ADR-003: Database Persistence & Tenant Isolation
        is_saas = any("tenant" in r.description.lower() or "organization" in r.description.lower() for r in spec.all_requirements())
        tenant_strategy = "Row-Level Multi-Tenancy via tenant_id" if is_saas else "Standard Single-Tenant Relational Schema"

        adrs.append(
            ArchitectureDecisionRecord(
                id="ADR-003",
                title=f"Adopt {tenant_strategy} Strategy",
                context="System data must be organized with clear isolation, strong consistency, and automated migration governance.",
                related_requirement_ids=[r.id for r in spec.all_requirements() if "data" in r.description.lower() or "user" in r.description.lower()][:3],
                alternatives_considered=["Database-per-tenant", "Shared schema with row-level filtering", "Schema-per-tenant"],
                selected_decision=tenant_strategy,
                rationale=f"Row-level tenant isolation provides high resource efficiency, simplified cross-tenant analytics, and reduced operational overhead.",
                tradeoffs=["Requires strict WHERE clause query discipline via ORM middleware", "Shared database resource contention"],
                rejected_alternatives={"Database-per-tenant": "Excessive operational overhead and connection pooling exhaustion for early-stage deployments"},
                risks=["Accidental query data leakage if tenant middleware is bypassed"],
                confidence="HIGH",
                approval_status=DecisionApprovalStatus.PROPOSED,
                is_user_explicit=False,
                version=1,
            )
        )

        # Save all ADRs
        for adr in adrs:
            self.save_adr(adr)

        return adrs

    def save_adr(self, adr: ArchitectureDecisionRecord) -> None:
        target = self.adr_dir / f"{adr.id}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(adr.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(target)

    def load_adr(self, adr_id: str) -> Optional[ArchitectureDecisionRecord]:
        target = self.adr_dir / f"{adr_id}.json"
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return ArchitectureDecisionRecord.from_dict(data)
        except Exception:
            return None

    def list_adrs(self) -> List[ArchitectureDecisionRecord]:
        results = []
        for p in sorted(self.adr_dir.glob("ADR-*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append(ArchitectureDecisionRecord.from_dict(data))
            except Exception:
                pass
        return results

    def update_approval_status(
        self,
        adr_id: str,
        new_status: DecisionApprovalStatus,
        reason: str = "",
        author: str = "user",
    ) -> ArchitectureDecisionRecord:
        adr = self.load_adr(adr_id)
        if not adr:
            raise ValueError(f"ADR not found: {adr_id}")

        old_status = adr.approval_status
        adr.approval_status = new_status
        adr.version += 1
        adr.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        adr.revision_history.append({
            "version": adr.version,
            "timestamp": adr.updated_at,
            "author": author,
            "change": f"Approval status updated from {old_status.value} to {new_status.value}",
            "reason": reason,
        })
        self.save_adr(adr)
        return adr


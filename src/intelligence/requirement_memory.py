"""
requirement_memory.py -- Requirement Context, Revision & Decision Memory.

Phase 11.1: Requirement Understanding & Discovery.
Provides atomic persistence, workspace and tenant isolation, decision history,
and scope-change tracking across multi-turn interactions.
"""

from __future__ import annotations

from src.runtime.app_paths import app_data_root

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.intelligence.requirement_models import (
    ClarificationQuestion,
    ProjectSpecification,
    RequirementItem,
    RequirementRevision,
    RequirementStatus,
)


class RequirementMemoryManager:
    """
    Manages persistent requirement specifications and decision history per workspace and tenant.
    Enforces strict isolation and revision history retention.
    """

    def __init__(self, workspace_root: str, tenant_id: str = "default_tenant") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id
        # Tenant-isolated storage directory under workspace .crusorai
        from src.runtime.app_paths import app_data_root
        self.storage_dir = app_data_root(self.workspace_root) / "tenants" / tenant_id / "requirements"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _spec_path(self, task_id: str) -> Path:
        safe_id = "".join(c for c in task_id if c.isalnum() or c in ("-", "_")) or "default"
        return self.storage_dir / f"requirement_spec_{safe_id}.json"

    def _decisions_path(self, task_id: str) -> Path:
        safe_id = "".join(c for c in task_id if c.isalnum() or c in ("-", "_")) or "default"
        return self.storage_dir / f"decision_history_{safe_id}.json"

    def save_specification(self, task_id: str, spec: ProjectSpecification) -> None:
        """Atomically saves the specification to disk."""
        target = self._spec_path(task_id)
        tmp = target.with_suffix(".tmp")
        data = spec.to_dict()
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(target)

    def load_specification(self, task_id: str) -> Optional[ProjectSpecification]:
        """Loads the specification if it exists."""
        target = self._spec_path(task_id)
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return ProjectSpecification.from_dict(data)
        except Exception:
            return None

    def record_decision(
        self,
        task_id: str,
        topic: str,
        decision_chosen: str,
        author: str = "user",
        rationale: str = "",
    ) -> None:
        """Records an approved user decision in the persistent decision history."""
        target = self._decisions_path(task_id)
        history: List[Dict[str, Any]] = []
        if target.exists():
            try:
                history = json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                history = []

        entry = {
            "decision_id": f"DEC-{len(history) + 1:03d}",
            "topic": topic,
            "decision": decision_chosen,
            "author": author,
            "rationale": rationale,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        history.append(entry)

        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(history, indent=2), encoding="utf-8")
        tmp.replace(target)

    def get_decisions(self, task_id: str) -> Dict[str, str]:
        """Retrieves previously answered decisions as a key-value mapping."""
        target = self._decisions_path(task_id)
        if not target.exists():
            return {}
        try:
            entries = json.loads(target.read_text(encoding="utf-8"))
            return {
                entry.get("topic", "").lower().replace(" ", "_"): entry.get("decision", "")
                for entry in entries
                if entry.get("topic") and entry.get("decision")
            }
        except Exception:
            return {}

    def revise_specification(
        self,
        task_id: str,
        spec: ProjectSpecification,
        revision_reason: str,
        updated_requirements: List[RequirementItem],
        author: str = "user",
    ) -> Tuple[ProjectSpecification, List[str]]:
        """
        Applies requirement revisions, detects scope additions or removals,
        increments specification version, and records a revision log entry.
        """
        old_req_ids = {r.id: r.description for r in spec.all_requirements()}
        new_req_ids = {r.id: r.description for r in updated_requirements}

        added = [desc for rid, desc in new_req_ids.items() if rid not in old_req_ids]
        removed = [desc for rid, desc in old_req_ids.items() if rid not in new_req_ids]

        scope_changes = []
        if added:
            scope_changes.append(f"Added {len(added)} new requirements: {', '.join(added[:3])}")
        if removed:
            scope_changes.append(f"Removed {len(removed)} requirements: {', '.join(removed[:3])}")

        spec.version += 1
        spec.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Update lists
        spec.functional_requirements = [
            r for r in updated_requirements
            if r.category not in {
                r.category.TECHNICAL_CONSTRAINT,
                r.category.NONFUNCTIONAL,
                r.category.SECURITY,
                r.category.PERFORMANCE,
                r.category.DEPLOYMENT,
            }
        ]
        spec.technical_constraints = [
            r for r in updated_requirements if r.category == r.category.TECHNICAL_CONSTRAINT
        ]
        spec.nonfunctional_requirements = [
            r for r in updated_requirements
            if r.category in {
                r.category.NONFUNCTIONAL,
                r.category.SECURITY,
                r.category.PERFORMANCE,
                r.category.DEPLOYMENT,
            }
        ]

        # Record revision history
        spec.revision_history.append(
            RequirementRevision(
                revision_id=f"REV-{spec.version:03d}",
                timestamp=spec.updated_at,
                author=author,
                reason=revision_reason,
                changes={
                    "scope_changes": scope_changes,
                    "added_count": len(added),
                    "removed_count": len(removed),
                },
            )
        )

        self.save_specification(task_id, spec)
        return spec, scope_changes


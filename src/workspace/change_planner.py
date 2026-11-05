"""
src/workspace/change_planner.py - Change Planning Before Modification.

Phase 11.3: Workspace Discipline & Change Management.
Constructs and validates structured ChangePlans before allowing file mutations.
Prevents:
- Duplicate components and files
- Unnecessary dependency proliferation
- Unrelated modifications (scope creep)
- Premature unapproved mutations
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.workspace.baseline import WorkspaceBaselineManager
from src.workspace.models import (
    ChangePlan,
    ChangePlanItem,
    FileOwnershipCategory,
    RiskLevel,
    WorkspaceOperationType,
)
from src.workspace.path_safety import PathSafetyValidator
from src.workspace.risk_policy import RiskApprovalGate

log = logging.getLogger("crusor.workspace.change_planner")


class ChangePlanEngine:
    """
    Constructs, audits, and persists ChangePlans before filesystem mutations begin.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            self.storage_dir = self.workspace_root / ".crusorai" / "tenants" / tenant_id / "plans"

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_mgr = WorkspaceBaselineManager(str(self.workspace_root))
        self.risk_gate = RiskApprovalGate()

    def create_plan(
        self,
        task_id: str,
        intended_outcome: str,
        items: List[ChangePlanItem],
        expected_dependencies: Optional[List[str]] = None,
        expected_tests: Optional[List[str]] = None,
        expected_cleanup: Optional[List[str]] = None,
    ) -> Tuple[ChangePlan, List[str]]:
        """
        Construct a new ChangePlan and run pre-mutation validation checks.
        Returns (plan, validation_warnings).
        """
        plan_id = f"PLAN-{uuid.uuid4().hex[:12]}"
        warnings: List[str] = []

        # 1. Audit items against baseline & repository state
        highest_risk = RiskLevel.LOW_RISK
        required_approvals: List[str] = []

        seen_targets: Set[str] = set()
        for item in items:
            norm_path = item.file_path.replace("\\", "/")
            if norm_path in seen_targets:
                warnings.append(f"Duplicate modification planned for target path: '{norm_path}'")
            seen_targets.add(norm_path)

            # Classify ownership
            provenance = self.baseline_mgr.classify_file_provenance(norm_path)

            # Check if creating a file that already exists in repository
            full_p = self.workspace_root / norm_path
            if item.operation == WorkspaceOperationType.CREATE and full_p.exists():
                warnings.append(
                    f"Plan intends to CREATE '{norm_path}', but file already exists in repository. "
                    "Operation should be classified as MODIFY or requires explicit overwrite authorization."
                )

            # Evaluate risk
            is_config = norm_path.endswith((".json", ".toml", ".yaml", ".yml", ".ini"))
            is_sec = any(k in norm_path.lower() for k in ("auth", "security", "permission", "schema", "migration"))
            risk = self.risk_gate.classify_operation_risk(
                norm_path,
                item.operation,
                provenance,
                is_config_file=is_config,
                is_schema_or_auth=is_sec,
            )

            if risk == RiskLevel.HIGH_RISK:
                highest_risk = RiskLevel.HIGH_RISK
                required_approvals.append(f"HIGH_RISK approval required for {item.operation.value} on {norm_path}")
            elif risk == RiskLevel.MEDIUM_RISK and highest_risk != RiskLevel.HIGH_RISK:
                highest_risk = RiskLevel.MEDIUM_RISK

        # Check for dependency redundancy
        for dep in (expected_dependencies or []):
            if self._is_existing_dependency(dep):
                warnings.append(f"Dependency '{dep}' appears already declared in project manifest. Avoid duplicate installation.")

        plan = ChangePlan(
            plan_id=plan_id,
            task_id=task_id,
            intended_outcome=intended_outcome,
            items=items,
            expected_dependencies=expected_dependencies or [],
            risk_classification=highest_risk,
            required_approvals=required_approvals,
            expected_tests=expected_tests or [],
            expected_cleanup=expected_cleanup or [],
            status="DRAFT",
            created_at=time.time(),
        )

        self._save_plan(plan)
        return plan, warnings

    def revise_plan(
        self,
        plan_id: str,
        reason: str,
        added_items: Optional[List[ChangePlanItem]] = None,
        removed_file_paths: Optional[List[str]] = None,
    ) -> Optional[ChangePlan]:
        """Record a material revision to an existing plan."""
        plan = self.load_plan(plan_id)
        if not plan:
            return None

        revision_record = {
            "timestamp": time.time(),
            "reason": reason,
            "added": [item.file_path for item in (added_items or [])],
            "removed": removed_file_paths or [],
        }
        plan.revisions.append(revision_record)
        plan.revised_at = time.time()

        if removed_file_paths:
            remove_set = set(removed_file_paths)
            plan.items = [i for i in plan.items if i.file_path not in remove_set]

        if added_items:
            plan.items.extend(added_items)

        self._save_plan(plan)
        return plan

    def load_plan(self, plan_id: str) -> Optional[ChangePlan]:
        """Load plan from disk."""
        p_file = self.storage_dir / f"{plan_id}.json"
        if not p_file.exists():
            return None
        try:
            import json
            data = json.loads(p_file.read_text(encoding="utf-8"))
            return ChangePlan.from_dict(data)
        except Exception as e:
            log.error(f"Failed to load change plan {plan_id}: {e}")
            return None

    def _is_existing_dependency(self, dep_name: str) -> bool:
        """Inspect manifests in workspace to detect whether dependency already exists."""
        clean_dep = dep_name.strip().lower()
        pyproj = self.workspace_root / "pyproject.toml"
        if pyproj.exists():
            try:
                content = pyproj.read_text(encoding="utf-8").lower()
                if clean_dep in content:
                    return True
            except Exception:
                pass

        pkg_json = self.workspace_root / "package.json"
        if pkg_json.exists():
            try:
                content = pkg_json.read_text(encoding="utf-8").lower()
                if f'"{clean_dep}"' in content:
                    return True
            except Exception:
                pass
        return False

    def _save_plan(self, plan: ChangePlan) -> None:
        p_file = self.storage_dir / f"{plan.plan_id}.json"
        tmp = p_file.with_suffix(".tmp")
        try:
            import json
            tmp.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
            os.replace(tmp, p_file)
        except Exception as e:
            log.error(f"Failed to persist change plan {plan.plan_id}: {e}")
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


"""
src/impact/planner_integration.py - Implementation Scope Control & ChangePlan Refinement.

Phase 11.4: Change Impact Analysis.
Bridges Change Impact Analysis with Phase 11.3 ChangePlanEngine:
- Enforces smallest safe implementation scope.
- Categorizes planned modifications into:
  * NECESSARY: Core changes directly solving the task
  * RELATED: Callers and test suites requiring coordinated updates
  * OPTIONAL: Non-critical cleanups
  * UNRELATED: Scope creep flagged for rejection
  * REQUIRES_APPROVAL: High-risk or breaking changes
- Prevents unwarranted full-codebase refactoring.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.models import (
    ChangeScopeCategory,
    ContractCompatibility,
    ImpactRisk,
    ImpactedComponent,
)

log = logging.getLogger("crusor.impact.planner_integration")


class ImplementationScopeController:
    """
    Refines proposed implementation scope to enforce minimal, safe, and deliberate edits.
    """

    def categorize_change_scope(
        self,
        planned_files: List[str],
        core_targets: List[str],
        direct_dependents: List[ImpactedComponent],
        transitive_dependents: List[ImpactedComponent],
        overall_risk: ImpactRisk,
        compatibility: ContractCompatibility,
    ) -> Dict[str, List[str]]:
        """
        Categorizes proposed change files into implementation scopes:
        Returns:
            {
                "necessary": [...],
                "related": [...],
                "optional": [...],
                "unrelated": [...],
                "requires_approval": [...],
            }
        """
        scope_map: Dict[str, List[str]] = {
            "necessary": [],
            "related": [],
            "optional": [],
            "unrelated": [],
            "requires_approval": [],
        }

        core_set = {f.replace("\\", "/").lstrip("/") for f in core_targets}
        affected_files = set()
        for c in direct_dependents:
            if c.node.file_path:
                affected_files.add(c.node.file_path.replace("\\", "/").lstrip("/"))

        for pf in planned_files:
            norm_pf = pf.replace("\\", "/").lstrip("/")

            # 1. High risk or breaking changes require approval
            if overall_risk in (ImpactRisk.CRITICAL, ImpactRisk.HIGH) or compatibility == ContractCompatibility.BREAKING:
                scope_map["requires_approval"].append(norm_pf)

            # 2. Core targets are strictly necessary
            if norm_pf in core_set:
                scope_map["necessary"].append(norm_pf)
            # 3. Direct callers / dependents are related
            elif norm_pf in affected_files:
                scope_map["related"].append(norm_pf)
            # 4. Tests or docs are optional/related
            elif "test" in norm_pf or norm_pf.endswith(".md"):
                scope_map["optional"].append(norm_pf)
            # 5. Otherwise, unrelated modification (scope creep!)
            else:
                scope_map["unrelated"].append(norm_pf)

        return scope_map


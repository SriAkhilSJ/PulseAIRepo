"""
src/impact/contract_compatibility.py - Public Contract & Compatibility Analyzer.

Phase 11.4: Change Impact Analysis.
Detects potential breaking changes across:
- Public APIs and HTTP routes.
- Function and method signatures (removed parameters, new required parameters).
- Database schemas and column modifications.
- Configuration schemas and MCP tool contracts.
Classifies changes as:
- BACKWARD_COMPATIBLE
- POTENTIALLY_BREAKING
- BREAKING
- UNKNOWN
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.models import (
    ContractCompatibility,
    DependencyNode,
    GraphLevel,
    ImpactRisk,
)

log = logging.getLogger("crusor.impact.contract_compatibility")


class ContractCompatibilityAnalyzer:
    """
    Analyzes whether proposed signature or interface modifications maintain backward compatibility.
    """

    def evaluate_compatibility(
        self,
        changed_nodes: List[DependencyNode],
        signature_diffs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[ContractCompatibility, List[Dict[str, Any]]]:
        """
        Evaluates contract compatibility for modified nodes.
        signature_diffs format:
        {
            "symbol:foo": {
                "removed_params": ["old_arg"],
                "added_required_params": ["new_mandatory"],
                "added_optional_params": ["opt_arg"],
                "return_type_changed": True,
            }
        }
        Returns:
            (overall_compatibility, compatibility_details)
        """
        details: List[Dict[str, Any]] = []
        overall = ContractCompatibility.BACKWARD_COMPATIBLE

        sig_diffs = signature_diffs or {}

        for node in changed_nodes:
            node_diff = sig_diffs.get(node.id, {})
            removed_params = node_diff.get("removed_params", [])
            added_required = node_diff.get("added_required_params", [])
            added_optional = node_diff.get("added_optional_params", [])
            return_changed = node_diff.get("return_type_changed", False)

            # 1. Breaking: removed parameters or new required parameters on public symbols
            if node.is_public and (removed_params or added_required):
                overall = ContractCompatibility.BREAKING
                details.append({
                    "target_id": node.id,
                    "target_name": node.name,
                    "level": node.level.value,
                    "compatibility": ContractCompatibility.BREAKING.value,
                    "breaking_reasons": (
                        ([f"Removed parameter(s): {', '.join(removed_params)}"] if removed_params else []) +
                        ([f"Added required parameter(s) without defaults: {', '.join(added_required)}"] if added_required else [])
                    ),
                    "migration_required": True,
                })
                continue

            # 2. Potentially breaking: return type changed or database schema modification
            if node.level == GraphLevel.APPLICATION and "db" in node.id:
                if overall != ContractCompatibility.BREAKING:
                    overall = ContractCompatibility.POTENTIALLY_BREAKING
                details.append({
                    "target_id": node.id,
                    "target_name": node.name,
                    "level": node.level.value,
                    "compatibility": ContractCompatibility.POTENTIALLY_BREAKING.value,
                    "breaking_reasons": ["Database table or schema modification requires schema migration"],
                    "migration_required": True,
                })
                continue

            if node.is_public and return_changed:
                if overall != ContractCompatibility.BREAKING:
                    overall = ContractCompatibility.POTENTIALLY_BREAKING
                details.append({
                    "target_id": node.id,
                    "target_name": node.name,
                    "level": node.level.value,
                    "compatibility": ContractCompatibility.POTENTIALLY_BREAKING.value,
                    "breaking_reasons": ["Return type changed on public function"],
                    "migration_required": False,
                })
                continue

            # 3. Backward compatible: only added optional parameters
            if added_optional:
                details.append({
                    "target_id": node.id,
                    "target_name": node.name,
                    "level": node.level.value,
                    "compatibility": ContractCompatibility.BACKWARD_COMPATIBLE.value,
                    "breaking_reasons": [],
                    "migration_required": False,
                })

        if not details:
            details.append({
                "target_id": "all_changes",
                "target_name": "all_changes",
                "level": "GENERAL",
                "compatibility": ContractCompatibility.BACKWARD_COMPATIBLE.value,
                "breaking_reasons": [],
                "migration_required": False,
            })

        return overall, details


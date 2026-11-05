"""
src/impact/change_analyzers.py - Change-Specific Domain Analyzers.

Phase 11.4: Change Impact Analysis.
Performs specialized impact evaluations across 7 change categories:
1. Functions (callers, signatures, parameters, side effects)
2. Classes & Interfaces (inheritance, subclasses, implementations, constructors)
3. APIs (routes, methods, request/response formats, auth guards)
4. Database & Models (tables, columns, foreign keys, migrations, data loss risk)
5. Configuration & Environment (env vars, startup flags, build settings)
6. Dependencies (external packages, direct/transitive consumers)
7. UI & Frontend (shared components, props, state, routing)
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.graph import MultiLevelDependencyGraph
from src.impact.models import (
    DependencyNode,
    GraphLevel,
    ImpactRisk,
    RelationshipType,
)

log = logging.getLogger("crusor.impact.change_analyzers")


class ChangeSpecificAnalyzer:
    """
    Executes deep inspections across domain-specific change types.
    """

    def __init__(self, workspace_root: str, graph: MultiLevelDependencyGraph) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.graph = graph

    def analyze_function_change(self, symbol_node: DependencyNode) -> Dict[str, Any]:
        """Inspect callers, parameters, and side-effect blast radius for a function change."""
        callers = self.graph.get_dependents(symbol_node.id)
        caller_list = [c[0].to_dict() for c in callers if c[1].relationship in (RelationshipType.CALLS, RelationshipType.TESTS)]
        is_auth = any(k in symbol_node.name.lower() for k in ["auth", "login", "token", "password", "session"])

        return {
            "symbol": symbol_node.name,
            "file": symbol_node.file_path,
            "callers_count": len(caller_list),
            "callers": caller_list[:10],
            "is_auth_critical": is_auth,
            "args": symbol_node.metadata.get("args", []),
            "risk_hint": ImpactRisk.CRITICAL if is_auth else (ImpactRisk.HIGH if len(caller_list) > 5 else ImpactRisk.MEDIUM),
        }

    def analyze_class_change(self, class_node: DependencyNode) -> Dict[str, Any]:
        """Inspect subclasses, implementations, and type consumers."""
        dependents = self.graph.get_dependents(class_node.id)
        subclasses = [d[0].to_dict() for d in dependents if d[1].relationship == RelationshipType.INHERITS]
        instantiators = [d[0].to_dict() for d in dependents if d[1].relationship == RelationshipType.INSTANTIATES]

        return {
            "class_name": class_node.name,
            "file": class_node.file_path,
            "subclasses": subclasses,
            "subclasses_count": len(subclasses),
            "instantiators_count": len(instantiators),
            "risk_hint": ImpactRisk.HIGH if len(subclasses) > 2 else ImpactRisk.MEDIUM,
        }

    def analyze_api_change(self, api_node: DependencyNode) -> Dict[str, Any]:
        """Inspect HTTP endpoints, routes, methods, and contract consumers."""
        dependents = self.graph.get_dependents(api_node.id)
        consumers = [d[0].to_dict() for d in dependents]

        return {
            "endpoint": api_node.name,
            "file": api_node.file_path,
            "method": api_node.metadata.get("http_method", "UNKNOWN"),
            "path": api_node.metadata.get("path", api_node.name),
            "consumers_count": len(consumers),
            "is_public_api": True,
            "risk_hint": ImpactRisk.HIGH,
        }

    def analyze_database_change(self, db_node: DependencyNode) -> Dict[str, Any]:
        """Inspect database tables, ORM models, migrations, and schema impact."""
        dependents = self.graph.get_dependents(db_node.id)
        queries_and_models = [d[0].to_dict() for d in dependents]

        return {
            "table_or_model": db_node.name,
            "file": db_node.file_path,
            "dependent_models": queries_and_models,
            "migration_required": True,
            "backup_recommended": True,
            "risk_hint": ImpactRisk.HIGH,
        }

    def analyze_config_change(self, config_node: DependencyNode) -> Dict[str, Any]:
        """Inspect environment variables and dependent modules."""
        dependents = self.graph.get_dependents(config_node.id)
        dependent_modules = [d[0].to_dict() for d in dependents]

        is_security_config = any(k in config_node.name.lower() for k in ["secret", "key", "token", "auth", "pwd", "password"])
        return {
            "variable_name": config_node.name,
            "dependent_modules_count": len(dependent_modules),
            "dependent_modules": dependent_modules,
            "affects_startup": True,
            "is_security_sensitive": is_security_config,
            "risk_hint": ImpactRisk.CRITICAL if is_security_config else ImpactRisk.HIGH,
        }

    def analyze_dependency_change(self, package_name: str) -> Dict[str, Any]:
        """Inspect external dependency usage across repository modules."""
        target_mod_id = f"module:{package_name}"
        dependents = self.graph.get_dependents(target_mod_id)
        consuming_modules = [d[0].to_dict() for d in dependents]

        return {
            "package": package_name,
            "consuming_modules_count": len(consuming_modules),
            "consuming_modules": consuming_modules,
            "risk_hint": ImpactRisk.HIGH if len(consuming_modules) > 3 else ImpactRisk.MEDIUM,
        }

    def analyze_ui_change(self, ui_node: DependencyNode) -> Dict[str, Any]:
        """Inspect shared UI component usages."""
        dependents = self.graph.get_dependents(ui_node.id)
        parent_views = [d[0].to_dict() for d in dependents]

        return {
            "component": ui_node.name,
            "file": ui_node.file_path,
            "parent_views_count": len(parent_views),
            "parent_views": parent_views,
            "risk_hint": ImpactRisk.MEDIUM if len(parent_views) > 2 else ImpactRisk.LOW,
        }


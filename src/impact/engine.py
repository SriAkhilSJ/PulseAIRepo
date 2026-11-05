"""
src/impact/engine.py - Central Change Impact Analysis Engine.

Phase 11.4: Change Impact Analysis.
Orchestrates multi-level dependency analysis, impact propagation, domain-specific
analyzers, risk assessment, test selection, architectural checks, and scope control.

Strict Invariant:
DOES NOT MUTATE THE WORKSPACE DURING IMPACT ANALYSIS.
Consumes Phase 11.0, 11.1, 11.2, and 11.3 artifacts and produces a comprehensive
machine-readable ChangeImpactReport.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.architecture_checker import ArchitectureRequirementImpactChecker
from src.impact.change_analyzers import ChangeSpecificAnalyzer
from src.impact.contract_compatibility import ContractCompatibilityAnalyzer
from src.impact.dynamic_analyzer import DynamicEvidenceAnalyzer
from src.impact.graph import MultiLevelDependencyGraph
from src.impact.models import (
    ChangeImpactReport,
    ConfidenceLevel,
    ContractCompatibility,
    DependencyNode,
    EvidenceSource,
    GraphLevel,
    ImpactRisk,
    ImpactedComponent,
)
from src.impact.persistence import DependencyGraphPersistence
from src.impact.planner_integration import ImplementationScopeController
from src.impact.propagator import ImpactPropagator
from src.impact.risk_assessor import BlastRadiusRiskAssessor
from src.impact.static_analyzer import StaticDependencyAnalyzer
from src.impact.test_impact import TestImpactAnalyzer

log = logging.getLogger("crusor.impact.engine")


class ChangeImpactAnalysisEngine:
    """
    Central engine for predicting consequences, blast radius, and risks
    before modifying repository code.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        # Persistence manager
        self.persistence = DependencyGraphPersistence(
            workspace_root=str(self.workspace_root),
            tenant_id=tenant_id,
            storage_dir=storage_dir,
        )

        # Load existing graph from disk or initialize empty
        loaded_graph, _ = self.persistence.load_graph()
        self.graph = loaded_graph or MultiLevelDependencyGraph()

        # Sub-analyzers
        self.static_analyzer = StaticDependencyAnalyzer(str(self.workspace_root), self.graph)
        self.dynamic_analyzer = DynamicEvidenceAnalyzer(str(self.workspace_root), self.graph)
        self.propagator = ImpactPropagator(self.graph)
        self.change_analyzer = ChangeSpecificAnalyzer(str(self.workspace_root), self.graph)
        self.risk_assessor = BlastRadiusRiskAssessor()
        self.test_impact_analyzer = TestImpactAnalyzer(self.graph)
        self.architecture_checker = ArchitectureRequirementImpactChecker(str(self.workspace_root))
        self.compatibility_analyzer = ContractCompatibilityAnalyzer()
        self.scope_controller = ImplementationScopeController()

    def build_or_refresh_graph(self, force_refresh: bool = False) -> MultiLevelDependencyGraph:
        """Scan workspace and update dependency graph incrementally."""
        self.static_analyzer.analyze_workspace(force_refresh=force_refresh)
        self.persistence.save_graph(self.graph)
        return self.graph

    def analyze_proposed_changes(
        self,
        task_id: str,
        proposed_change_summary: str,
        changed_files: List[str],
        changed_symbols: Optional[List[str]] = None,
        planned_modifications: Optional[List[str]] = None,
        signature_diffs: Optional[Dict[str, Dict[str, Any]]] = None,
        project_knowledge: Optional[Any] = None,
        project_spec: Optional[Any] = None,
        architecture_blueprint: Optional[Any] = None,
        adrs: Optional[List[Any]] = None,
        change_plan: Optional[Any] = None,
    ) -> ChangeImpactReport:
        """
        Main entry point for Change Impact Analysis.
        Strictly READ-ONLY: never mutates workspace files.
        """
        symbols = changed_symbols or []
        planned = planned_modifications or changed_files

        # 1. Ensure graph is populated for the changed files
        for f in changed_files:
            self.static_analyzer.analyze_file(f)

        # 2. Identify target node IDs
        target_node_ids: List[str] = []
        target_nodes: List[DependencyNode] = []

        for f in changed_files:
            norm_f = f.replace("\\", "/").lstrip("/")
            mod_id = f"module:{norm_f}"
            node = self.graph.get_node(mod_id)
            if node:
                target_node_ids.append(node.id)
                target_nodes.append(node)
            else:
                # Placeholder module node
                placeholder = DependencyNode(id=mod_id, name=norm_f, level=GraphLevel.MODULE, file_path=norm_f)
                self.graph.add_node(placeholder)
                target_node_ids.append(placeholder.id)
                target_nodes.append(placeholder)

        for s in symbols:
            matching = self.graph.find_nodes_by_name(s)
            for m in matching:
                target_node_ids.append(m.id)
                target_nodes.append(m)

        # 3. Propagate impact through graph (direct & transitive dependents)
        direct_deps, transitive_deps = self.propagator.propagate_impact(target_node_ids)
        all_affected = direct_deps + transitive_deps

        # 4. Domain-specific change inspections
        affected_apis: List[Dict[str, Any]] = []
        affected_db: List[Dict[str, Any]] = []
        affected_config: List[Dict[str, Any]] = []
        security_implications: List[Dict[str, Any]] = []

        for comp in all_affected:
            node = comp.node
            if node.level == GraphLevel.APPLICATION:
                if "api" in node.id:
                    affected_apis.append(self.change_analyzer.analyze_api_change(node))
                elif "db" in node.id:
                    affected_db.append(self.change_analyzer.analyze_database_change(node))
                elif "config" in node.id:
                    affected_config.append(self.change_analyzer.analyze_config_change(node))

            if "auth" in node.id.lower() or "security" in node.id.lower() or "token" in node.id.lower():
                security_implications.append({
                    "component": node.name,
                    "file": node.file_path,
                    "severity": "CRITICAL",
                    "description": f"Security-sensitive component '{node.name}' lies within change blast radius",
                })

        # 5. Contract Compatibility Analysis
        compatibility, compat_details = self.compatibility_analyzer.evaluate_compatibility(
            changed_nodes=target_nodes,
            signature_diffs=signature_diffs,
        )

        # 6. Test Impact Analysis
        relevant_tests, missing_tests = self.test_impact_analyzer.identify_relevant_tests(
            changed_node_ids=target_node_ids,
            direct_dependents=direct_deps,
            transitive_dependents=transitive_deps,
        )

        # 7. Architecture & Requirement Impact (Phase 11.1 & 11.2)
        req_traceability, adr_traceability, arch_implications = self.architecture_checker.evaluate_architecture_and_requirements(
            changed_files=changed_files,
            changed_symbols=symbols,
            affected_components=all_affected,
            project_spec=project_spec,
            architecture_blueprint=architecture_blueprint,
            adrs=adrs,
        )

        # 8. Overall Risk Assessment & Factor Explanation
        overall_risk, risk_factors, uncertainties = self.risk_assessor.evaluate_risk(
            changed_files=changed_files,
            changed_symbols=symbols,
            direct_dependents=direct_deps,
            transitive_dependents=transitive_deps,
            compatibility=compatibility,
            has_tests=len(relevant_tests) > 0,
        )

        # 9. Implementation Scope Control (Phase 11.3 ChangePlan Refinement)
        scope_map = self.scope_controller.categorize_change_scope(
            planned_files=planned,
            core_targets=changed_files,
            direct_dependents=direct_deps,
            transitive_dependents=transitive_deps,
            overall_risk=overall_risk,
            compatibility=compatibility,
        )

        # 10. Recommended Verification Plan
        verification_plan = [f"Run {t['priority']} test suite: {t['test_name']} ({t['file_path']})" for t in relevant_tests[:5]]
        if missing_tests:
            verification_plan.append(f"Author missing unit tests for uncovered symbols: {', '.join(missing_tests[:3])}")
        verification_plan.append("Verify Upstream Invariant 7: exactly 5 permitted files in desktop/SELECTIVE_MANIFEST.json with zero drift.")

        report = ChangeImpactReport(
            task_id=task_id,
            proposed_change_summary=proposed_change_summary,
            changed_files=changed_files,
            changed_symbols=symbols,
            direct_dependents=direct_deps,
            transitive_dependents=transitive_deps,
            affected_components=all_affected,
            affected_apis=affected_apis,
            affected_database_structures=affected_db,
            affected_configuration=affected_config,
            security_implications=security_implications,
            architecture_implications=arch_implications,
            requirement_traceability=req_traceability,
            adr_traceability=adr_traceability,
            public_contract_compatibility=compatibility,
            contract_compatibility_details=compat_details,
            relevant_tests=relevant_tests,
            missing_test_coverage=missing_tests,
            risk_classification=overall_risk,
            risk_factors=risk_factors,
            uncertainties=uncertainties,
            recommended_implementation_scope=scope_map,
            recommended_verification_plan=verification_plan,
            evidence_provenance={
                "static_nodes": str(len(self.graph.nodes)),
                "analyzed_files": str(len(changed_files)),
                "persistence_tenant": self.tenant_id,
            },
            generated_timestamp=time.time(),
        )

        return report


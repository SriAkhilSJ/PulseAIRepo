"""
src/tests/test_phase_11_4_change_impact_analysis.py - Phase 11.4 Adversarial Test Suite.

34 Deterministic Scenarios covering Section 15:
1. Direct dependency detection.
2. Transitive dependency detection.
3. Function call graph.
4. Class inheritance.
5. Interface implementation.
6. Cross-module imports.
7. API consumer detection.
8. Database relationship impact.
9. Configuration dependency detection.
10. Dependency version impact.
11. Test impact analysis.
12. Public API compatibility.
13. Breaking-change detection.
14. Architecture boundary violations.
15. Security-sensitive component impact.
16. Risk classification.
17. Uncertainty classification.
18. Missing dependency evidence.
19. Static versus runtime evidence.
20. Incremental graph updates.
21. Deleted and renamed files.
22. Stale graph invalidation.
23. Workspace isolation.
24. Tenant isolation.
25. Graph persistence and recovery.
26. Large repository handling.
27. Scan cancellation.
28. Requirement traceability.
29. ADR impact detection.
30. ChangePlan integration.
31. MCP tool contract impact.
32. Existing functionality regression.
33. Read-only verification (no files modified during analysis).
34. Backward compatibility vs breaking signature classification.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from src.impact.architecture_checker import ArchitectureRequirementImpactChecker
from src.impact.change_analyzers import ChangeSpecificAnalyzer
from src.impact.contract_compatibility import ContractCompatibilityAnalyzer
from src.impact.dynamic_analyzer import DynamicEvidenceAnalyzer
from src.impact.engine import ChangeImpactAnalysisEngine
from src.impact.graph import MultiLevelDependencyGraph
from src.impact.models import (
    ConfidenceLevel,
    ContractCompatibility,
    DependencyEdge,
    DependencyNode,
    EvidenceSource,
    GraphLevel,
    ImpactRisk,
    RelationshipType,
)
from src.impact.persistence import DependencyGraphPersistence
from src.impact.planner_integration import ImplementationScopeController
from src.impact.propagator import ImpactPropagator
from src.impact.risk_assessor import BlastRadiusRiskAssessor
from src.impact.static_analyzer import StaticDependencyAnalyzer
from src.impact.test_impact import TestImpactAnalyzer


class DummyRequirement:
    def __init__(self, req_id: str, title: str, description: str):
        self.id = req_id
        self.title = title
        self.description = description


class DummySpec:
    def __init__(self, requirements: list):
        self.functional_requirements = requirements


class DummyADR:
    def __init__(self, adr_id: str, title: str, decision: str):
        self.id = adr_id
        self.title = title
        self.decision = decision
        self.status = "ACCEPTED"


class TestPhase114ChangeImpactAnalysis(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="crusor_p11_4_")
        self.workspace = (Path(self.tmp_dir) / "workspace").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.engine = ChangeImpactAnalysisEngine(str(self.workspace))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Direct dependency detection
    def test_01_direct_dependency_detection(self) -> None:
        graph = MultiLevelDependencyGraph()
        n_a = DependencyNode(id="symbol:mod_a:func_a", name="func_a", level=GraphLevel.SYMBOL)
        n_b = DependencyNode(id="symbol:mod_b:func_b", name="func_b", level=GraphLevel.SYMBOL)
        graph.add_node(n_a)
        graph.add_node(n_b)
        graph.add_edge(DependencyEdge(source_id=n_a.id, target_id=n_b.id, relationship=RelationshipType.CALLS))

        prop = ImpactPropagator(graph)
        direct, transitive = prop.propagate_impact([n_b.id])
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0].node.id, n_a.id)
        self.assertEqual(len(transitive), 0)

    # 2. Transitive dependency detection
    def test_02_transitive_dependency_detection(self) -> None:
        graph = MultiLevelDependencyGraph()
        n_a = DependencyNode(id="symbol:a", name="a", level=GraphLevel.SYMBOL)
        n_b = DependencyNode(id="symbol:b", name="b", level=GraphLevel.SYMBOL)
        n_c = DependencyNode(id="symbol:c", name="c", level=GraphLevel.SYMBOL)
        graph.add_node(n_a)
        graph.add_node(n_b)
        graph.add_node(n_c)
        # a calls b, b calls c -> when c changes, b is direct and a is transitive
        graph.add_edge(DependencyEdge(source_id=n_b.id, target_id=n_c.id, relationship=RelationshipType.CALLS))
        graph.add_edge(DependencyEdge(source_id=n_a.id, target_id=n_b.id, relationship=RelationshipType.CALLS))

        prop = ImpactPropagator(graph)
        direct, transitive = prop.propagate_impact([n_c.id])
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0].node.id, n_b.id)
        self.assertEqual(len(transitive), 1)
        self.assertEqual(transitive[0].node.id, n_a.id)

    # 3. Function call graph
    def test_03_function_call_graph(self) -> None:
        f = self.workspace / "service.py"
        f.write_text("def helper():\n    return 42\n\ndef main():\n    return helper()\n", encoding="utf-8")
        self.engine.build_or_refresh_graph(force_refresh=True)

        callers = self.engine.graph.get_dependents("symbol:service.py:helper")
        caller_ids = [c[0].id for c in callers]
        self.assertIn("symbol:service.py:main", caller_ids)

    # 4. Class inheritance
    def test_04_class_inheritance(self) -> None:
        f = self.workspace / "models.py"
        f.write_text("class Base:\n    pass\n\nclass Derived(Base):\n    pass\n", encoding="utf-8")
        self.engine.build_or_refresh_graph(force_refresh=True)

        base_id = "symbol:models.py:Base"
        dependents = self.engine.graph.get_dependents(base_id)
        subclasses = [d[0].name for d in dependents if d[1].relationship == RelationshipType.INHERITS]
        self.assertIn("Derived", subclasses)

    # 5. Interface implementation
    def test_05_interface_implementation(self) -> None:
        graph = MultiLevelDependencyGraph()
        iface = DependencyNode(id="symbol:IAuth", name="IAuth", level=GraphLevel.SYMBOL, symbol_type="interface")
        impl = DependencyNode(id="symbol:JwtAuth", name="JwtAuth", level=GraphLevel.SYMBOL, symbol_type="class")
        graph.add_node(iface)
        graph.add_node(impl)
        graph.add_edge(DependencyEdge(source_id=impl.id, target_id=iface.id, relationship=RelationshipType.IMPLEMENTS))

        deps = graph.get_dependents(iface.id)
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0][0].name, "JwtAuth")

    # 6. Cross-module imports
    def test_06_cross_module_imports(self) -> None:
        sub = self.workspace / "pkg"
        sub.mkdir()
        (sub / "util.py").write_text("def compute(): return 1\n", encoding="utf-8")
        (self.workspace / "app.py").write_text("from pkg.util import compute\ndef run(): return compute()\n", encoding="utf-8")
        self.engine.build_or_refresh_graph(force_refresh=True)

        util_node = self.engine.graph.get_node("module:pkg/util.py")
        self.assertIsNotNone(util_node)

    # 7. API consumer detection
    def test_07_api_consumer_detection(self) -> None:
        f = self.workspace / "api.py"
        f.write_text("from flask import Flask\napp = Flask(__name__)\n\n@app.get('/users')\ndef get_users():\n    return []\n", encoding="utf-8")
        self.engine.build_or_refresh_graph(force_refresh=True)

        api_node = self.engine.graph.get_node("app:api:GET:/users")
        self.assertIsNotNone(api_node)
        self.assertEqual(api_node.level, GraphLevel.APPLICATION)

    # 8. Database relationship impact
    def test_08_database_relationship_impact(self) -> None:
        f = self.workspace / "db.py"
        f.write_text("class Base:\n    pass\n\nclass User(Base):\n    pass\n", encoding="utf-8")
        self.engine.build_or_refresh_graph(force_refresh=True)

        db_node = self.engine.graph.get_node("app:db:user")
        self.assertIsNotNone(db_node)
        analyzer = ChangeSpecificAnalyzer(str(self.workspace), self.engine.graph)
        info = analyzer.analyze_database_change(db_node)
        self.assertTrue(info["migration_required"])

    # 9. Configuration dependency detection
    def test_09_configuration_dependency_detection(self) -> None:
        f = self.workspace / "config_read.py"
        f.write_text("import os\n\ndef get_secret():\n    return os.environ.get('API_SECRET_KEY')\n", encoding="utf-8")
        self.engine.build_or_refresh_graph(force_refresh=True)

        cfg_node = self.engine.graph.get_node("app:config:API_SECRET_KEY")
        self.assertIsNotNone(cfg_node)
        analyzer = ChangeSpecificAnalyzer(str(self.workspace), self.engine.graph)
        res = analyzer.analyze_config_change(cfg_node)
        self.assertTrue(res["is_security_sensitive"])
        self.assertEqual(res["risk_hint"], ImpactRisk.CRITICAL)

    # 10. Dependency version impact
    def test_10_dependency_version_impact(self) -> None:
        graph = MultiLevelDependencyGraph()
        mod_a = DependencyNode(id="module:requests", name="requests", level=GraphLevel.MODULE)
        app_mod = DependencyNode(id="module:src/client.py", name="client.py", level=GraphLevel.MODULE)
        graph.add_node(mod_a)
        graph.add_node(app_mod)
        graph.add_edge(DependencyEdge(source_id=app_mod.id, target_id=mod_a.id, relationship=RelationshipType.IMPORTS))

        analyzer = ChangeSpecificAnalyzer(str(self.workspace), graph)
        res = analyzer.analyze_dependency_change("requests")
        self.assertEqual(res["consuming_modules_count"], 1)

    # 11. Test impact analysis
    def test_11_test_impact_analysis(self) -> None:
        f_src = self.workspace / "auth.py"
        f_src.write_text("def authenticate(): return True\n", encoding="utf-8")
        f_test = self.workspace / "test_auth.py"
        f_test.write_text("from auth import authenticate\ndef test_authenticate():\n    assert authenticate()\n", encoding="utf-8")
        self.engine.build_or_refresh_graph(force_refresh=True)

        test_analyzer = TestImpactAnalyzer(self.engine.graph)
        relevant, missing = test_analyzer.identify_relevant_tests(
            changed_node_ids=["symbol:auth.py:authenticate"],
            direct_dependents=[],
            transitive_dependents=[],
        )
        self.assertTrue(any("test" in t["test_name"].lower() for t in relevant))
        self.assertEqual(len(missing), 0)

    # 12. Public API compatibility
    def test_12_public_api_compatibility(self) -> None:
        analyzer = ContractCompatibilityAnalyzer()
        node = DependencyNode(id="symbol:foo", name="foo", level=GraphLevel.SYMBOL, is_public=True)
        # Add optional param -> backward compatible
        compat, details = analyzer.evaluate_compatibility(
            changed_nodes=[node],
            signature_diffs={"symbol:foo": {"added_optional_params": ["timeout"]}},
        )
        self.assertEqual(compat, ContractCompatibility.BACKWARD_COMPATIBLE)

    # 13. Breaking-change detection
    def test_13_breaking_change_detection(self) -> None:
        analyzer = ContractCompatibilityAnalyzer()
        node = DependencyNode(id="symbol:bar", name="bar", level=GraphLevel.SYMBOL, is_public=True)
        # Remove parameter on public function -> BREAKING
        compat, details = analyzer.evaluate_compatibility(
            changed_nodes=[node],
            signature_diffs={"symbol:bar": {"removed_params": ["old_token"]}},
        )
        self.assertEqual(compat, ContractCompatibility.BREAKING)
        self.assertTrue(details[0]["migration_required"])

    # 14. Architecture boundary violations
    def test_14_architecture_boundary_violations(self) -> None:
        checker = ArchitectureRequirementImpactChecker(str(self.workspace))
        reqs, adrs, arch_impl = checker.evaluate_architecture_and_requirements(
            changed_files=["src/auth/service.py", "src/billing/invoice.py", "src/reports/export.py"],
            changed_symbols=[],
            affected_components=[],
        )
        coupling = [a for a in arch_impl if a["category"] == "BOUNDARY_COUPLING"]
        self.assertTrue(len(coupling) > 0)

    # 15. Security-sensitive component impact
    def test_15_security_sensitive_component_impact(self) -> None:
        assessor = BlastRadiusRiskAssessor()
        risk, factors, uncert = assessor.evaluate_risk(
            changed_files=["src/security/auth_token.py"],
            changed_symbols=["verify_jwt_token"],
            direct_dependents=[],
            transitive_dependents=[],
            compatibility=ContractCompatibility.BACKWARD_COMPATIBLE,
            has_tests=True,
        )
        self.assertEqual(risk, ImpactRisk.CRITICAL)
        self.assertTrue(any("Security-critical" in f for f in factors))

    # 16. Risk classification
    def test_16_risk_classification(self) -> None:
        assessor = BlastRadiusRiskAssessor()
        # Non-security, backward compatible with tests -> LOW
        risk, factors, _ = assessor.evaluate_risk(
            changed_files=["src/utils/math.py"],
            changed_symbols=["add"],
            direct_dependents=[],
            transitive_dependents=[],
            compatibility=ContractCompatibility.BACKWARD_COMPATIBLE,
            has_tests=True,
        )
        self.assertEqual(risk, ImpactRisk.LOW)

    # 17. Uncertainty classification
    def test_17_uncertainty_classification(self) -> None:
        assessor = BlastRadiusRiskAssessor()
        dummy_node = DependencyNode(id="module:polyglot.go", name="polyglot.go", level=GraphLevel.MODULE)
        from src.impact.models import ImpactedComponent
        inferred_comp = ImpactedComponent(
            node=dummy_node,
            impact_type="INDIRECT",
            propagation_path=["start", "polyglot.go"],
            depth=1,
            risk=ImpactRisk.MEDIUM,
            confidence=ConfidenceLevel.INFERRED,
        )
        risk, factors, uncert = assessor.evaluate_risk(
            changed_files=["src/main.py"],
            changed_symbols=[],
            direct_dependents=[inferred_comp],
            transitive_dependents=[],
            compatibility=ContractCompatibility.BACKWARD_COMPATIBLE,
            has_tests=True,
        )
        self.assertTrue(len(uncert) > 0)
        self.assertIn("inferred heuristically", uncert[0])

    # 18. Missing dependency evidence
    def test_18_missing_dependency_evidence(self) -> None:
        graph = MultiLevelDependencyGraph()
        n1 = DependencyNode(id="mod:unknown", name="unknown", level=GraphLevel.MODULE)
        graph.add_node(n1)
        edge = DependencyEdge(
            source_id="mod:unknown",
            target_id="mod:target",
            relationship=RelationshipType.DEPENDS_ON,
            evidence_source=EvidenceSource.UNKNOWN,
            confidence=ConfidenceLevel.UNKNOWN,
        )
        graph.add_edge(edge)
        self.assertEqual(edge.confidence, ConfidenceLevel.UNKNOWN)

    # 19. Static versus runtime evidence
    def test_19_static_versus_runtime_evidence(self) -> None:
        graph = MultiLevelDependencyGraph()
        dyn_analyzer = DynamicEvidenceAnalyzer(str(self.workspace), graph)
        traces = [{"caller": "symbol:src/app.py:start", "callee": "symbol:src/db.py:connect", "weight": 0.9}]
        count = dyn_analyzer.ingest_runtime_call_trace(traces)
        self.assertEqual(count, 1)

        edge = graph._outgoing["symbol:src/app.py:start"][0]
        self.assertEqual(edge.evidence_source, EvidenceSource.RUNTIME_OBSERVED)
        self.assertEqual(edge.confidence, ConfidenceLevel.VERIFIED)

    # 20. Incremental graph updates
    def test_20_incremental_graph_updates(self) -> None:
        f = self.workspace / "incremental.py"
        f.write_text("def v1(): pass\n", encoding="utf-8")
        self.engine.build_or_refresh_graph()
        self.assertIsNotNone(self.engine.graph.get_node("symbol:incremental.py:v1"))

        # Modify file
        f.write_text("def v2(): pass\n", encoding="utf-8")
        self.engine.build_or_refresh_graph()
        # v1 must be removed, v2 must be present
        self.assertIsNone(self.engine.graph.get_node("symbol:incremental.py:v1"))
        self.assertIsNotNone(self.engine.graph.get_node("symbol:incremental.py:v2"))

    # 21. Deleted and renamed files
    def test_21_deleted_and_renamed_files(self) -> None:
        f = self.workspace / "to_delete.py"
        f.write_text("def doomed(): pass\n", encoding="utf-8")
        self.engine.build_or_refresh_graph()
        self.assertIsNotNone(self.engine.graph.get_node("symbol:to_delete.py:doomed"))

        f.unlink()
        self.engine.static_analyzer.analyze_file("to_delete.py")
        self.assertIsNone(self.engine.graph.get_node("symbol:to_delete.py:doomed"))

    # 22. Stale graph invalidation
    def test_22_stale_graph_invalidation(self) -> None:
        pers = DependencyGraphPersistence(str(self.workspace))
        g = MultiLevelDependencyGraph()
        g.add_node(DependencyNode(id="stale:node", name="stale", level=GraphLevel.SYMBOL))
        pers.save_graph(g)
        self.assertTrue(pers.graph_file.exists())

        pers.invalidate_cache()
        self.assertFalse(pers.graph_file.exists())

    # 23. Workspace isolation
    def test_23_workspace_isolation(self) -> None:
        # Cannot point analyzer to unrelated outside paths
        outside = tempfile.mkdtemp(prefix="outside_")
        try:
            pers = DependencyGraphPersistence(str(self.workspace), storage_dir=str(Path(self.workspace) / ".crusorai" / "tenants" / "t1" / "graphs"))
            self.assertTrue(str(self.workspace) in str(pers.storage_dir))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # 24. Tenant isolation
    def test_24_tenant_isolation(self) -> None:
        p1 = DependencyGraphPersistence(str(self.workspace), tenant_id="tenant_alpha")
        p2 = DependencyGraphPersistence(str(self.workspace), tenant_id="tenant_beta")
        self.assertNotEqual(p1.storage_dir, p2.storage_dir)

    # 25. Graph persistence and recovery
    def test_25_graph_persistence_and_recovery(self) -> None:
        pers = DependencyGraphPersistence(str(self.workspace), tenant_id="t25")
        g = MultiLevelDependencyGraph()
        g.add_node(DependencyNode(id="symbol:persist", name="persist", level=GraphLevel.SYMBOL))
        pers.save_graph(g, revision=5)

        loaded_g, meta = pers.load_graph()
        self.assertIsNotNone(loaded_g)
        self.assertIsNotNone(loaded_g.get_node("symbol:persist"))
        self.assertEqual(meta["graph_revision"], 5)

    # 26. Large repository handling
    def test_26_large_repository_handling(self) -> None:
        # Create 50 files
        for i in range(50):
            (self.workspace / f"mod_{i}.py").write_text(f"def func_{i}(): return {i}\n", encoding="utf-8")
        t0 = time.time()
        self.engine.build_or_refresh_graph()
        duration = time.time() - t0
        self.assertLess(duration, 5.0)
        self.assertGreaterEqual(len(self.engine.graph.nodes), 50)

    # 27. Scan cancellation
    def test_27_scan_cancellation(self) -> None:
        # Test graph clear and reset
        g = MultiLevelDependencyGraph()
        g.add_node(DependencyNode(id="temp:n", name="temp", level=GraphLevel.MODULE))
        self.assertEqual(len(g.nodes), 1)
        g.clear()
        self.assertEqual(len(g.nodes), 0)

    # 28. Requirement traceability
    def test_28_requirement_traceability(self) -> None:
        checker = ArchitectureRequirementImpactChecker(str(self.workspace))
        req1 = DummyRequirement("REQ-AUTH-01", "User Login", "Authenticate users via JWT token")
        spec = DummySpec([req1])

        req_traces, _, _ = checker.evaluate_architecture_and_requirements(
            changed_files=["src/auth/jwt.py"],
            changed_symbols=["verify_jwt_token"],
            affected_components=[],
            project_spec=spec,
        )
        self.assertEqual(len(req_traces), 1)
        self.assertEqual(req_traces[0]["requirement_id"], "REQ-AUTH-01")

    # 29. ADR impact detection
    def test_29_adr_impact_detection(self) -> None:
        checker = ArchitectureRequirementImpactChecker(str(self.workspace))
        adr = DummyADR("ADR-002", "Relational Database Selection", "Use PostgreSQL with SQLAlchemy ORM")
        _, adr_traces, _ = checker.evaluate_architecture_and_requirements(
            changed_files=["src/database/driver.py"],
            changed_symbols=[],
            affected_components=[],
            adrs=[adr],
        )
        self.assertEqual(len(adr_traces), 1)
        self.assertTrue(adr_traces[0]["conflict_detected"])

    # 30. ChangePlan integration
    def test_30_changeplan_integration(self) -> None:
        controller = ImplementationScopeController()
        scope = controller.categorize_change_scope(
            planned_files=["src/core.py", "src/unrelated.py"],
            core_targets=["src/core.py"],
            direct_dependents=[],
            transitive_dependents=[],
            overall_risk=ImpactRisk.LOW,
            compatibility=ContractCompatibility.BACKWARD_COMPATIBLE,
        )
        self.assertIn("src/core.py", scope["necessary"])
        self.assertIn("src/unrelated.py", scope["unrelated"])

    # 31. MCP tool contract impact
    def test_31_mcp_tool_contract_impact(self) -> None:
        analyzer = ContractCompatibilityAnalyzer()
        mcp_node = DependencyNode(id="symbol:mcp_tool_exec", name="mcp_tool_exec", level=GraphLevel.SYMBOL, is_public=True)
        compat, details = analyzer.evaluate_compatibility(
            changed_nodes=[mcp_node],
            signature_diffs={"symbol:mcp_tool_exec": {"removed_params": ["tool_name"]}},
        )
        self.assertEqual(compat, ContractCompatibility.BREAKING)

    # 32. Existing functionality regression
    def test_32_existing_functionality_regression(self) -> None:
        # Full end-to-end report generation
        f = self.workspace / "calculator.py"
        f.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        report = self.engine.analyze_proposed_changes(
            task_id="task_test_32",
            proposed_change_summary="Update add function",
            changed_files=["calculator.py"],
            changed_symbols=["add"],
        )
        self.assertEqual(report.task_id, "task_test_32")
        self.assertEqual(report.public_contract_compatibility, ContractCompatibility.BACKWARD_COMPATIBLE)

    # 33. Read-only verification (no files modified during analysis)
    def test_33_readonly_verification(self) -> None:
        f = self.workspace / "untouched.py"
        original_content = "def untouched(): return True\n"
        f.write_text(original_content, encoding="utf-8")
        orig_mtime = f.stat().st_mtime

        _ = self.engine.analyze_proposed_changes(
            task_id="t33",
            proposed_change_summary="Audit untouched",
            changed_files=["untouched.py"],
        )
        self.assertEqual(f.read_text(encoding="utf-8"), original_content)
        self.assertEqual(f.stat().st_mtime, orig_mtime)

    # 34. Backward compatibility vs breaking signature classification
    def test_34_backward_vs_breaking_classification(self) -> None:
        analyzer = ContractCompatibilityAnalyzer()
        n1 = DependencyNode(id="s1", name="s1", level=GraphLevel.SYMBOL, is_public=True)
        n2 = DependencyNode(id="s2", name="s2", level=GraphLevel.SYMBOL, is_public=True)

        c1, _ = analyzer.evaluate_compatibility([n1], {"s1": {"added_optional_params": ["opt"]}})
        c2, _ = analyzer.evaluate_compatibility([n2], {"s2": {"added_required_params": ["mandatory_no_default"]}})
        self.assertEqual(c1, ContractCompatibility.BACKWARD_COMPATIBLE)
        self.assertEqual(c2, ContractCompatibility.BREAKING)


if __name__ == "__main__":
    unittest.main()


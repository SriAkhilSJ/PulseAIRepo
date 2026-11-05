"""
src/impact/test_impact.py - Test Impact Analysis & Test Selection Engine.

Phase 11.4: Change Impact Analysis.
Determines relevant tests before code modification:
- Directly covering unit tests (P0).
- Caller and dependent module tests (P1).
- API contract and integration tests (P2).
- Broad regression suites (P3).
- Explicitly flags test gaps when code lacks test coverage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.graph import MultiLevelDependencyGraph
from src.impact.models import (
    DependencyNode,
    GraphLevel,
    ImpactRisk,
    ImpactedComponent,
    RelationshipType,
)

log = logging.getLogger("crusor.impact.test_impact")


class TestImpactAnalyzer:
    """
    Identifies and prioritizes test suites affected by proposed code changes.
    """
    __test__ = False

    def __init__(self, graph: MultiLevelDependencyGraph) -> None:
        self.graph = graph

    def identify_relevant_tests(
        self,
        changed_node_ids: List[str],
        direct_dependents: List[ImpactedComponent],
        transitive_dependents: List[ImpactedComponent],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Calculates prioritized list of tests and flags missing coverage.
        Returns:
            (relevant_tests_list, missing_test_coverage_symbols)
        """
        relevant_tests: List[Dict[str, Any]] = []
        seen_test_ids: Set[str] = set()
        missing_coverage: List[str] = []

        all_test_nodes = self.graph.find_nodes_by_level(GraphLevel.TEST)

        for target_id in changed_node_ids:
            target_node = self.graph.get_node(target_id)
            if not target_node or target_node.level == GraphLevel.TEST:
                continue

            target_has_tests = False
            # 1. P0: Direct Tests (reverse edges where relationship is TESTS or test imports symbol)
            dependents = self.graph.get_dependents(target_id)
            for dep_node, edge in dependents:
                if dep_node.level == GraphLevel.TEST:
                    target_has_tests = True
                    if dep_node.id not in seen_test_ids:
                        seen_test_ids.add(dep_node.id)
                        relevant_tests.append({
                            "test_id": dep_node.id,
                            "test_name": dep_node.name,
                            "file_path": dep_node.file_path,
                            "priority": "P0",
                            "category": "DIRECT_UNIT_TEST",
                            "rationale": f"Directly tests modified symbol '{target_node.name}'",
                        })

            # Check matching test file convention: foo.py -> test_foo.py
            if target_node.file_path:
                target_filename = target_node.file_path.split("/")[-1]
                expected_test_name = f"test_{target_filename}"
                for t_node in all_test_nodes:
                    if t_node.file_path and expected_test_name in t_node.file_path:
                        target_has_tests = True
                        if t_node.id not in seen_test_ids:
                            seen_test_ids.add(t_node.id)
                            relevant_tests.append({
                                "test_id": t_node.id,
                                "test_name": t_node.name,
                                "file_path": t_node.file_path,
                                "priority": "P0",
                                "category": "CONVENTION_TEST_SUITE",
                                "rationale": f"Matching test suite for file '{target_filename}'",
                            })

            if not target_has_tests:
                missing_coverage.append(target_node.name)

        # 2. P1: Caller Tests (tests for direct dependents)
        for comp in direct_dependents:
            dep_id = comp.node.id
            callers_of_caller = self.graph.get_dependents(dep_id)
            for dep_node, edge in callers_of_caller:
                if dep_node.level == GraphLevel.TEST and dep_node.id not in seen_test_ids:
                    seen_test_ids.add(dep_node.id)
                    relevant_tests.append({
                        "test_id": dep_node.id,
                        "test_name": dep_node.name,
                        "file_path": dep_node.file_path,
                        "priority": "P1",
                        "category": "CALLER_INTEGRATION_TEST",
                        "rationale": f"Tests direct caller '{comp.node.name}'",
                    })

        # 3. P2: API & Integration Tests
        for comp in direct_dependents + transitive_dependents:
            if "api" in comp.node.id.lower() or "db" in comp.node.id.lower():
                # Look for contract/integration tests
                for t_node in all_test_nodes:
                    if any(k in (t_node.file_path or "").lower() for k in ["api", "integration", "contract"]):
                        if t_node.id not in seen_test_ids:
                            seen_test_ids.add(t_node.id)
                            relevant_tests.append({
                                "test_id": t_node.id,
                                "test_name": t_node.name,
                                "file_path": t_node.file_path,
                                "priority": "P2",
                                "category": "API_CONTRACT_TEST",
                                "rationale": f"Contract test covering affected service '{comp.node.name}'",
                            })

        # Sort tests by priority (P0, then P1, then P2)
        p_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        relevant_tests.sort(key=lambda x: p_order.get(x["priority"], 99))

        return relevant_tests, missing_coverage

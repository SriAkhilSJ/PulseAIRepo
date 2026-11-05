"""
src/impact/propagator.py - Impact Propagation Engine.

Phase 11.4: Change Impact Analysis.
Traverses the multi-level dependency graph to discover direct and transitive
downstream consequences of code changes:
- Direction-aware reverse traversal (who depends on the changed component?).
- Relationship-weighted propagation (CALLS/INHERITS stronger than IMPORTS).
- Interface boundaries: private symbol changes constrained unless callers exist.
- Runtime vs test boundaries: test nodes recorded as affected tests, but do not propagate back to production.
- Architectural boundary awareness and cycle prevention.
"""

from __future__ import annotations

import collections
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.graph import MultiLevelDependencyGraph
from src.impact.models import (
    ConfidenceLevel,
    DependencyEdge,
    DependencyNode,
    GraphLevel,
    ImpactRisk,
    ImpactedComponent,
    RelationshipType,
)

log = logging.getLogger("crusor.impact.propagator")

# Relationship coupling weights
RELATIONSHIP_WEIGHTS: Dict[RelationshipType, float] = {
    RelationshipType.INHERITS: 1.0,
    RelationshipType.IMPLEMENTS: 1.0,
    RelationshipType.CALLS: 0.9,
    RelationshipType.EXPOSES: 0.85,
    RelationshipType.INSTANTIATES: 0.8,
    RelationshipType.WRITES: 0.75,
    RelationshipType.READS: 0.7,
    RelationshipType.DEPENDS_ON: 0.65,
    RelationshipType.SERIALIZES: 0.6,
    RelationshipType.DESERIALIZES: 0.6,
    RelationshipType.IMPORTS: 0.5,
    RelationshipType.CONFIGURES: 0.5,
    RelationshipType.MIGRATES: 0.8,
    RelationshipType.TESTS: 0.4,
}


class ImpactPropagator:
    """
    Computes direct and transitive blast radius across the dependency graph.
    """

    def __init__(self, graph: MultiLevelDependencyGraph, max_depth: int = 10) -> None:
        self.graph = graph
        self.max_depth = max_depth

    def propagate_impact(
        self,
        changed_node_ids: List[str],
    ) -> Tuple[List[ImpactedComponent], List[ImpactedComponent]]:
        """
        Calculates affected components for a list of modified node IDs.
        Returns:
            (direct_dependents, transitive_dependents)
        """
        direct_results: List[ImpactedComponent] = []
        transitive_results: List[ImpactedComponent] = []
        visited_nodes: Set[str] = set()

        # Queue contains: (current_node_id, path_so_far, depth, accumulated_weight)
        queue: collections.deque[Tuple[str, List[str], int, float]] = collections.deque()

        for init_id in changed_node_ids:
            visited_nodes.add(init_id)
            queue.append((init_id, [init_id], 0, 1.0))

        while queue:
            curr_id, path, depth, current_weight = queue.popleft()

            if depth >= self.max_depth:
                continue

            curr_node = self.graph.get_node(curr_id)
            is_private = curr_node and not curr_node.is_public

            # Query reverse dependencies: who depends on curr_id?
            dependents = self.graph.get_dependents(curr_id)
            for dep_node, edge in dependents:
                dep_id = dep_node.id

                # If current node is private symbol, only follow direct callers
                if is_private and depth > 0 and edge.relationship == RelationshipType.IMPORTS:
                    continue

                # Calculate propagation weight
                edge_weight = RELATIONSHIP_WEIGHTS.get(edge.relationship, 0.5) * edge.weight
                hop_decay = 0.85 ** (depth + 1)
                new_weight = current_weight * edge_weight * hop_decay

                # Assess risk for this specific component
                comp_risk = self._assess_component_risk(dep_node, edge, depth + 1, new_weight)

                impact_type = self._determine_impact_type(dep_node, edge, depth + 1)
                rationale = (
                    f"Directly {edge.relationship.value.lower()} '{curr_id}'"
                    if depth == 0
                    else f"Transitively affected via {edge.relationship.value.lower()} from '{curr_id}'"
                )

                impacted = ImpactedComponent(
                    node=dep_node,
                    impact_type=impact_type,
                    propagation_path=path + [dep_id],
                    depth=depth + 1,
                    risk=comp_risk,
                    confidence=edge.confidence,
                    rationale=rationale,
                )

                if depth == 0:
                    direct_results.append(impacted)
                else:
                    transitive_results.append(impacted)

                # Continue traversal if not already visited in this branch and not a terminal test node
                # Note: Test nodes do not propagate impact back into production code!
                if dep_id not in visited_nodes and dep_node.level != GraphLevel.TEST:
                    visited_nodes.add(dep_id)
                    queue.append((dep_id, path + [dep_id], depth + 1, new_weight))

        return direct_results, transitive_results

    def _determine_impact_type(self, node: DependencyNode, edge: DependencyEdge, depth: int) -> str:
        """Categorize impact type based on node level and relationship."""
        if node.level == GraphLevel.TEST or edge.relationship == RelationshipType.TESTS:
            return "REGRESSION_RISK"
        if node.level == GraphLevel.APPLICATION:
            if "api" in node.id:
                return "API_COMPATIBILITY"
            if "db" in node.id:
                return "DATA_IMPACT"
            if "config" in node.id:
                return "CONFIG_IMPACT"
        if "auth" in node.id.lower() or "security" in node.id.lower() or "secret" in node.id.lower():
            return "SECURITY_IMPACT"
        if depth == 1:
            return "DIRECT"
        return "INDIRECT"

    def _assess_component_risk(
        self,
        node: DependencyNode,
        edge: DependencyEdge,
        depth: int,
        weight: float,
    ) -> ImpactRisk:
        """Evaluate risk of affecting this specific component."""
        node_name_lower = node.name.lower()
        node_id_lower = node.id.lower()

        # Security/Auth components are always HIGH or CRITICAL
        if any(sec in node_name_lower or sec in node_id_lower for sec in ["auth", "token", "password", "crypto", "rbac", "sandbox", "secret"]):
            return ImpactRisk.CRITICAL if depth <= 2 else ImpactRisk.HIGH

        # Database models and migrations
        if node.level == GraphLevel.APPLICATION and "db" in node_id_lower:
            return ImpactRisk.HIGH

        # Public API endpoints
        if node.level == GraphLevel.APPLICATION and "api" in node_id_lower:
            return ImpactRisk.HIGH if depth <= 2 else ImpactRisk.MEDIUM

        # Direct callers with high weight
        if depth == 1 and weight > 0.7:
            return ImpactRisk.MEDIUM

        # Test components
        if node.level == GraphLevel.TEST:
            return ImpactRisk.LOW

        if depth > 4 or weight < 0.3:
            return ImpactRisk.LOW

        return ImpactRisk.MEDIUM


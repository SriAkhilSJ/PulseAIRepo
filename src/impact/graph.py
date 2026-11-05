"""
src/impact/graph.py - Multi-Level Dependency Graph.

Phase 11.4: Change Impact Analysis.
Manages repository, module, symbol, application, and test level dependency nodes and edges.
Provides fast bidirectional querying:
- Forward: What does X depend on? (callees, imported modules)
- Reverse: What depends on X? (callers, importing modules, tests)
Supports incremental invalidation by file path.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.models import (
    ConfidenceLevel,
    DependencyEdge,
    DependencyNode,
    EvidenceSource,
    GraphLevel,
    RelationshipType,
)

log = logging.getLogger("crusor.impact.graph")


class MultiLevelDependencyGraph:
    """
    In-memory representation of multi-level software dependencies.
    Tracks provenance, confidence, and bidirectional graph connectivity.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, DependencyNode] = {}
        # Outgoing: source_id -> list of edges where source_id depends on target_id
        self._outgoing: Dict[str, List[DependencyEdge]] = defaultdict(list)
        # Incoming: target_id -> list of edges where caller/importer depends on target_id
        self._incoming: Dict[str, List[DependencyEdge]] = defaultdict(list)

        # Fast indices for lookup
        self._by_file: Dict[str, Set[str]] = defaultdict(set)
        self._by_name: Dict[str, Set[str]] = defaultdict(set)
        self._by_level: Dict[GraphLevel, Set[str]] = defaultdict(set)

    def add_node(self, node: DependencyNode) -> None:
        """Register or update a dependency node in the graph."""
        self.nodes[node.id] = node
        if node.file_path:
            norm_file = node.file_path.replace("\\", "/").lstrip("/")
            self._by_file[norm_file].add(node.id)
        self._by_name[node.name].add(node.id)
        self._by_level[node.level].add(node.id)

    def get_node(self, node_id: str) -> Optional[DependencyNode]:
        """Fetch node by canonical ID."""
        return self.nodes.get(node_id)

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all connected incoming and outgoing edges."""
        if node_id not in self.nodes:
            return
        node = self.nodes.pop(node_id)
        if node.file_path:
            norm_file = node.file_path.replace("\\", "/").lstrip("/")
            self._by_file[norm_file].discard(node_id)
        self._by_name[node.name].discard(node_id)
        self._by_level[node.level].discard(node_id)

        # Remove outgoing edges
        out_edges = self._outgoing.pop(node_id, [])
        for edge in out_edges:
            self._incoming[edge.target_id] = [
                e for e in self._incoming[edge.target_id] if e.source_id != node_id
            ]

        # Remove incoming edges
        in_edges = self._incoming.pop(node_id, [])
        for edge in in_edges:
            self._outgoing[edge.source_id] = [
                e for e in self._outgoing[edge.source_id] if e.target_id != node_id
            ]

    def add_edge(self, edge: DependencyEdge) -> None:
        """
        Add a directed dependency edge.
        source_id -> target_id (source depends on target, e.g. caller -> callee).
        """
        # Ensure source and target nodes exist or create placeholder nodes if necessary
        if edge.source_id not in self.nodes:
            self.add_node(
                DependencyNode(
                    id=edge.source_id,
                    name=edge.source_id.split(":")[-1],
                    level=GraphLevel.SYMBOL if ":" in edge.source_id else GraphLevel.MODULE,
                )
            )
        if edge.target_id not in self.nodes:
            self.add_node(
                DependencyNode(
                    id=edge.target_id,
                    name=edge.target_id.split(":")[-1],
                    level=GraphLevel.SYMBOL if ":" in edge.target_id else GraphLevel.MODULE,
                )
            )

        # Avoid duplicate edges
        existing = [
            e for e in self._outgoing[edge.source_id]
            if e.target_id == edge.target_id and e.relationship == edge.relationship
        ]
        if not existing:
            self._outgoing[edge.source_id].append(edge)
            self._incoming[edge.target_id].append(edge)

    def update_edge_target(self, edge: DependencyEdge, new_target_id: str) -> None:
        """Update target of an existing edge and maintain incoming index integrity."""
        old_target = edge.target_id
        if old_target in self._incoming:
            self._incoming[old_target] = [e for e in self._incoming[old_target] if e is not edge]
        edge.target_id = new_target_id
        self._incoming[new_target_id].append(edge)

    def get_dependents(self, node_id: str) -> List[Tuple[DependencyNode, DependencyEdge]]:
        """
        REVERSE QUERY: Return all nodes that depend on `node_id`.
        When `node_id` is modified, these dependents are directly affected!
        """
        results: List[Tuple[DependencyNode, DependencyEdge]] = []
        for edge in self._incoming.get(node_id, []):
            caller_node = self.nodes.get(edge.source_id)
            if caller_node:
                results.append((caller_node, edge))
        return results

    def get_dependencies(self, node_id: str) -> List[Tuple[DependencyNode, DependencyEdge]]:
        """
        FORWARD QUERY: Return all nodes that `node_id` depends on.
        """
        results: List[Tuple[DependencyNode, DependencyEdge]] = []
        for edge in self._outgoing.get(node_id, []):
            callee_node = self.nodes.get(edge.target_id)
            if callee_node:
                results.append((callee_node, edge))
        return results

    def find_nodes_by_file(self, file_path: str) -> List[DependencyNode]:
        """Find all nodes defined in or associated with a specific file."""
        norm_file = file_path.replace("\\", "/").lstrip("/")
        node_ids = self._by_file.get(norm_file, set())
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]

    def find_nodes_by_name(self, name: str) -> List[DependencyNode]:
        """Find nodes matching a symbol, function, or class name."""
        node_ids = self._by_name.get(name, set())
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]

    def find_nodes_by_level(self, level: GraphLevel) -> List[DependencyNode]:
        """Find all nodes of a specific abstraction level."""
        node_ids = self._by_level.get(level, set())
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]

    def remove_file_nodes_and_edges(self, file_path: str) -> int:
        """
        Invalidate all nodes and edges belonging to a modified or deleted file.
        Returns the number of nodes removed.
        """
        nodes = self.find_nodes_by_file(file_path)
        count = len(nodes)
        for n in nodes:
            self.remove_node(n.id)
        norm_file = file_path.replace("\\", "/").lstrip("/")
        self._by_file.pop(norm_file, None)
        return count

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to dictionary."""
        all_edges: List[Dict[str, Any]] = []
        seen = set()
        for edges in self._outgoing.values():
            for e in edges:
                key = (e.source_id, e.target_id, e.relationship.value)
                if key not in seen:
                    seen.add(key)
                    all_edges.append(e.to_dict())

        return {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": all_edges,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MultiLevelDependencyGraph:
        """Construct graph from serialized dictionary."""
        graph = cls()
        nodes_data = data.get("nodes", {})
        for nid, ndata in nodes_data.items():
            graph.add_node(DependencyNode.from_dict(ndata))

        edges_data = data.get("edges", [])
        for edata in edges_data:
            graph.add_edge(DependencyEdge.from_dict(edata))

        return graph

    def clear(self) -> None:
        """Reset graph."""
        self.nodes.clear()
        self._outgoing.clear()
        self._incoming.clear()
        self._by_file.clear()
        self._by_name.clear()
        self._by_level.clear()

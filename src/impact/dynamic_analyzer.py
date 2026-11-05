"""
src/impact/dynamic_analyzer.py - Dynamic Evidence Ingestion Engine.

Phase 11.4: Change Impact Analysis.
Ingests runtime-observed evidence without executing arbitrary project code:
- Test execution coverage reports (coverage.json, .coverage, lcov.info).
- Recorded runtime call traces.
- Structured application access and execution logs.
Emits edges marked EvidenceSource.RUNTIME_OBSERVED with ConfidenceLevel.VERIFIED.
Strictly respects Phase 9.4 isolation and Phase 11.3 workspace safety.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.impact.graph import MultiLevelDependencyGraph
from src.impact.models import (
    ConfidenceLevel,
    DependencyEdge,
    DependencyNode,
    EvidenceSource,
    GraphLevel,
    RelationshipType,
)

log = logging.getLogger("crusor.impact.dynamic_analyzer")


class DynamicEvidenceAnalyzer:
    """
    Ingests dynamic runtime evidence into the multi-level dependency graph.
    Never executes arbitrary code; operates strictly on existing persistent artifacts.
    """

    def __init__(self, workspace_root: str, graph: MultiLevelDependencyGraph) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.graph = graph

    def ingest_coverage_report(self, coverage_file_path: str) -> int:
        """
        Ingest test coverage report (e.g., coverage.json) to establish
        definitive runtime relationships between test cases and executed source files.
        Returns the number of edges added.
        """
        full_path = self.workspace_root / coverage_file_path
        if not full_path.is_file():
            return 0

        edges_added = 0
        try:
            data = json.loads(full_path.read_text(encoding="utf-8"))
            files_dict = data.get("files", {})
            for rel_file, meta in files_dict.items():
                norm_file = rel_file.replace("\\", "/").lstrip("/")
                executed_lines = meta.get("executed_lines", [])
                if executed_lines:
                    # Find symbol nodes in that file matching executed lines
                    nodes_in_file = self.graph.find_nodes_by_file(norm_file)
                    for node in nodes_in_file:
                        if node.line_number and node.line_number in executed_lines:
                            # Edge from coverage artifact to symbol
                            cov_node_id = f"test:coverage:{coverage_file_path}"
                            if cov_node_id not in self.graph.nodes:
                                self.graph.add_node(
                                    DependencyNode(
                                        id=cov_node_id,
                                        name=f"Coverage: {coverage_file_path}",
                                        level=GraphLevel.TEST,
                                        symbol_type="coverage_artifact",
                                    )
                                )
                            self.graph.add_edge(
                                DependencyEdge(
                                    source_id=cov_node_id,
                                    target_id=node.id,
                                    relationship=RelationshipType.TESTS,
                                    evidence_source=EvidenceSource.RUNTIME_OBSERVED,
                                    confidence=ConfidenceLevel.VERIFIED,
                                    is_runtime=False,
                                    rationale="Empirically executed according to coverage.json",
                                )
                            )
                            edges_added += 1
        except Exception as e:
            log.debug(f"Failed to ingest coverage report from {coverage_file_path}: {e}")

        return edges_added

    def ingest_runtime_call_trace(self, traces: List[Dict[str, Any]]) -> int:
        """
        Ingest instrumented runtime execution call traces:
        [{"caller": "symbol:src/api.py:get_user", "callee": "symbol:src/db.py:find_user", "weight": 1.0}]
        """
        edges_added = 0
        for trace in traces:
            caller = trace.get("caller")
            callee = trace.get("callee")
            if caller and callee:
                self.graph.add_edge(
                    DependencyEdge(
                        source_id=caller,
                        target_id=callee,
                        relationship=RelationshipType.CALLS,
                        evidence_source=EvidenceSource.RUNTIME_OBSERVED,
                        confidence=ConfidenceLevel.VERIFIED,
                        weight=float(trace.get("weight", 1.0)),
                        is_runtime=True,
                        rationale="Observed in runtime call trace",
                    )
                )
                edges_added += 1
        return edges_added

    def ingest_application_log_endpoints(self, log_lines: List[str]) -> int:
        """
        Extract observed HTTP endpoint invocations from application log lines:
        'GET /api/v1/auth/login 200 OK' -> creates/links app:api:GET:/api/v1/auth/login
        """
        edges_added = 0
        pattern = re.compile(r"""(GET|POST|PUT|DELETE|PATCH)\s+([/a-zA-Z0-9_\-.]+)""")
        for line in log_lines:
            match = pattern.search(line)
            if match:
                method = match.group(1).upper()
                path = match.group(2)
                api_id = f"app:api:{method}:{path}"
                if api_id not in self.graph.nodes:
                    self.graph.add_node(
                        DependencyNode(
                            id=api_id,
                            name=f"{method} {path}",
                            level=GraphLevel.APPLICATION,
                            symbol_type="api_endpoint",
                            metadata={"source": "observed_logs"},
                        )
                    )
                    edges_added += 1
        return edges_added


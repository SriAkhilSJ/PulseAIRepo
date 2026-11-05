"""
architecture.py -- Project Architecture Mapper and Dependency Graph Analyzer.

Phase 11.0: Project & Repository Intelligence.
Maps major subsystems, internal and external dependency relationships, API boundaries,
execution flows, and shared utility modules across the codebase.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from src.intelligence.models import ArchitectureMap, ComponentNode

log = logging.getLogger("crusorai.intelligence.architecture")

# Python import regexes
PY_IMPORT_RE = re.compile(r"""(?:^|\n)\s*(?:from\s+([a-zA-Z0-9_\.]+)\s+import|import\s+([a-zA-Z0-9_\.]+))""")
# TypeScript/JavaScript import regexes
JS_IMPORT_RE = re.compile(r"""(?:^|\n)\s*(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""")


class ArchitectureMapper:
    """
    Extracts high-level architectural components and dependency flows.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def map_architecture(self, file_paths: List[str]) -> ArchitectureMap:
        """
        Analyze files to construct an ArchitectureMap.
        """
        components: Dict[str, ComponentNode] = {}
        shared_utils: Set[str] = set()

        # 1. Identify Components from directory clusters
        for rel in file_paths:
            parts = rel.split("/")
            if len(parts) >= 2:
                # e.g., src/identity or desktop/vscode or src/agents
                if parts[0] == "src" and len(parts) >= 3:
                    comp_name = f"src/{parts[1]}"
                else:
                    comp_name = parts[0]

                if comp_name not in components:
                    category = self._classify_category(comp_name)
                    components[comp_name] = ComponentNode(
                        name=comp_name,
                        category=category,
                        path=comp_name,
                        responsibilities=self._derive_responsibilities(comp_name),
                    )

            if "util" in rel.lower() or "helper" in rel.lower() or "common" in rel.lower():
                shared_utils.add(rel)

        # 2. Extract Dependencies via import parsing
        self._extract_dependencies(components, file_paths)

        # 3. Derive Standard Execution Flows
        execution_flows = self._derive_execution_flows(components)

        return ArchitectureMap(
            components=components,
            execution_flows=execution_flows,
            shared_utilities=sorted(list(shared_utils))[:20],
        )

    def _classify_category(self, comp_name: str) -> str:
        name_lower = comp_name.lower()
        if "identity" in name_lower or "auth" in name_lower:
            return "identity_access"
        if "finops" in name_lower or "billing" in name_lower:
            return "financial_governance"
        if "agent" in name_lower or "planner" in name_lower:
            return "agent_core"
        if "desktop" in name_lower or "electron" in name_lower or "ui" in name_lower:
            return "desktop_frontend"
        if "tools" in name_lower or "mcp" in name_lower:
            return "tool_ecosystem"
        if "runtime" in name_lower or "sandbox" in name_lower or "broker" in name_lower:
            return "execution_broker"
        if "context" in name_lower:
            return "context_engine"
        if "test" in name_lower:
            return "test_harness"
        return "subsystem"

    def _derive_responsibilities(self, comp_name: str) -> List[str]:
        name_lower = comp_name.lower()
        if "identity" in name_lower:
            return ["User & Session Authentication", "Hierarchical RBAC", "Multi-Tenant Isolation"]
        if "finops" in name_lower:
            return ["Usage & Token Accounting", "Multi-Currency Pricing", "Budget Governance"]
        if "desktop" in name_lower:
            return ["VS Code Platform Integration", "UI Surface Rendering", "Desktop IPC"]
        if "context" in name_lower:
            return ["Token Budgeting", "AST Chunk Indexing", "Context Compaction"]
        if "tools" in name_lower:
            return ["Tool Execution Sandboxing", "MCP Protocol Client", "Browser Automation"]
        if "runtime" in name_lower:
            return ["OS-Level Process Isolation", "Job Objects & AppContainer", "Status Contracts"]
        return ["Application Subsystem Functionality"]

    def _extract_dependencies(self, components: Dict[str, ComponentNode], file_paths: List[str]) -> None:
        """Parse imports from a sample of files to map internal and external dependencies."""
        for rel in file_paths[:200]:  # Sample first 200 files for fast bounded mapping
            full = self.workspace_root / rel
            if full.suffix == ".py" and full.stat().st_size < 100_000:
                comp = self._get_owner_component(rel, components)
                if not comp:
                    continue
                try:
                    text = full.read_text(encoding="utf-8", errors="replace")
                    for m in PY_IMPORT_RE.finditer(text):
                        mod = m.group(1) or m.group(2)
                        if not mod:
                            continue
                        root_mod = mod.split(".")[0]
                        if root_mod == "src":
                            parts = mod.split(".")
                            if len(parts) >= 2:
                                target_comp = f"src/{parts[1]}"
                                if target_comp in components and target_comp != comp.name:
                                    if target_comp not in comp.internal_deps:
                                        comp.internal_deps.append(target_comp)
                        else:
                            # External dependency
                            if root_mod not in comp.external_deps and root_mod not in {"sys", "os", "time", "re", "json", "typing"}:
                                comp.external_deps.append(root_mod)
                except Exception:
                    pass

    def _get_owner_component(self, rel: str, components: Dict[str, ComponentNode]) -> Optional[ComponentNode]:
        for cname, node in components.items():
            if rel.startswith(cname):
                return node
        return None

    def _derive_execution_flows(self, components: Dict[str, ComponentNode]) -> List[Dict[str, Any]]:
        flows = []
        if "src/graphs" in components or "src/agents" in components:
            flows.append({
                "flow_name": "Agent Conversation & Tool Execution",
                "steps": [
                    "User Request Ingestion (Chat UI)",
                    "Identity & RBAC Permission Evaluation (src/identity)",
                    "Context Gathering & Compaction (src/context)",
                    "Model Routing & FinOps Budget Reservation (src/finops)",
                    "LLM Invocation & Tool Planning (src/agents)",
                    "Sandboxed Tool / MCP Execution (src/tools & src/runtime)",
                    "Status Contract Synthesis & Verification (src/runtime)",
                ]
            })
        if "src/api" in components or "api" in components:
            flows.append({
                "flow_name": "API Request Lifecycle",
                "steps": [
                    "HTTP Request Ingestion",
                    "Route Handling & Controller Validation",
                    "Business / Model Execution",
                    "HTTP Response Serialization",
                ]
            })
        if "desktop" in components:
            flows.append({
                "flow_name": "Desktop Workbench IPC Flow",
                "steps": [
                    "Electron Renderer Action (desktop/vscode)",
                    "Sidecar JSON-RPC Bridge Dispatch (src/bridge)",
                    "LangGraph Runtime Graph Execution (src/graphs)",
                    "Streaming Telemetry & Latency Tracing (src/telemetry)",
                ]
            })
        if not flows and components:
            flows.append({
                "flow_name": "Standard Component Execution",
                "steps": [
                    "Invocation Entrypoint",
                    "Component Logic Processing",
                    "Result Output Serialization",
                ]
            })
        return flows

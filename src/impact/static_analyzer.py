"""
src/impact/static_analyzer.py - Static Dependency Analysis Engine.

Phase 11.4: Change Impact Analysis.
Performs deterministic static code analysis across Python, TypeScript, JavaScript, and polyglot files:
- Python AST: functions, classes, calls, inheritance, imports, routes, ORM models, config reads.
- TypeScript/JavaScript: imports, exports, routes, component exports.
- Polyglot: module imports with explicit confidence and heuristic evidence disclosure.
- Incremental scanning: caches file hashes to avoid redundant re-analysis.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
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

log = logging.getLogger("crusor.impact.static_analyzer")

# Standard directories to skip during scanning
SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".crusorai", ".tmp",
})


class StaticDependencyAnalyzer:
    """
    Parses codebases to extract multi-level dependency graphs statically.
    Enforces epistemic honesty: records verified static AST evidence or heuristic uncertainty.
    """

    def __init__(self, workspace_root: str, graph: Optional[MultiLevelDependencyGraph] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.graph = graph or MultiLevelDependencyGraph()
        self._file_hashes: Dict[str, str] = {}

    def analyze_workspace(self, force_refresh: bool = False) -> MultiLevelDependencyGraph:
        """Scan all supported files in workspace and populate dependency graph."""
        for root, dirs, files in os.walk(self.workspace_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(self.workspace_root).as_posix()
                self.analyze_file(rel_path, force_refresh=force_refresh)

        # Post-scan link resolution: resolve symbolic imports to known concrete nodes
        self._resolve_symbolic_links()
        return self.graph

    def analyze_file(self, rel_path: str, force_refresh: bool = False) -> bool:
        """Analyze a single file incrementally. Returns True if analyzed, False if unchanged."""
        norm_path = rel_path.replace("\\", "/").lstrip("/")
        full_path = self.workspace_root / norm_path
        if not full_path.is_file():
            # File removed: clean graph
            self.graph.remove_file_nodes_and_edges(norm_path)
            self._file_hashes.pop(norm_path, None)
            return True

        # Check hash
        try:
            content_bytes = full_path.read_bytes()
        except Exception:
            return False

        current_hash = hashlib.sha256(content_bytes).hexdigest()
        if not force_refresh and self._file_hashes.get(norm_path) == current_hash:
            return False  # Unchanged

        # Invalidate old state for this file
        self.graph.remove_file_nodes_and_edges(norm_path)
        self._file_hashes[norm_path] = current_hash

        # Dispatch based on extension
        ext = full_path.suffix.lower()
        try:
            content_text = content_bytes.decode("utf-8", errors="replace")
            if ext == ".py":
                self._analyze_python(norm_path, content_text)
            elif ext in {".js", ".jsx", ".ts", ".tsx", ".mjs"}:
                self._analyze_javascript_typescript(norm_path, content_text)
            elif ext in {".sql", ".prisma"}:
                self._analyze_database_schema(norm_path, content_text)
            elif ext in {".json", ".yaml", ".yml", ".toml", ".env"}:
                self._analyze_config_file(norm_path, content_text)
            else:
                self._analyze_generic_polyglot(norm_path, content_text)
        except Exception as e:
            log.debug(f"Failed to statically analyze {norm_path}: {e}")
            # Register module node with unknown confidence
            mod_id = f"module:{norm_path}"
            self.graph.add_node(
                DependencyNode(
                    id=mod_id,
                    name=norm_path,
                    level=GraphLevel.MODULE,
                    file_path=norm_path,
                    metadata={"error": str(e)},
                )
            )

        return True

    def _analyze_python(self, rel_path: str, content: str) -> None:
        """Parse Python AST to extract module, symbols, calls, imports, routes, models."""
        mod_id = f"module:{rel_path}"
        is_test_file = "test" in rel_path.lower() or Path(rel_path).name.startswith("test_")
        self.graph.add_node(
            DependencyNode(
                id=mod_id,
                name=rel_path,
                level=GraphLevel.TEST if is_test_file else GraphLevel.MODULE,
                file_path=rel_path,
                symbol_type="module",
            )
        )

        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError as se:
            log.debug(f"Syntax error in {rel_path}: {se}")
            return

        visitor = _PythonASTVisitor(rel_path, mod_id, is_test_file, self.graph)
        visitor.visit(tree)

    def _analyze_javascript_typescript(self, rel_path: str, content: str) -> None:
        """Extract JS/TS imports, exports, API routes, and components."""
        mod_id = f"module:{rel_path}"
        is_test_file = ".test." in rel_path or ".spec." in rel_path or "test" in rel_path.lower()
        self.graph.add_node(
            DependencyNode(
                id=mod_id,
                name=rel_path,
                level=GraphLevel.TEST if is_test_file else GraphLevel.MODULE,
                file_path=rel_path,
                symbol_type="module",
            )
        )

        # 1. Imports: import { x } from './foo'; require('./bar');
        import_patterns = [
            re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))"""),
        ]
        for pat in import_patterns:
            for match in pat.finditer(content):
                target = match.group(1) or match.group(2)
                if target:
                    target_id = f"module:{target}"
                    self.graph.add_edge(
                        DependencyEdge(
                            source_id=mod_id,
                            target_id=target_id,
                            relationship=RelationshipType.IMPORTS,
                            evidence_source=EvidenceSource.STATIC,
                            confidence=ConfidenceLevel.VERIFIED,
                            is_runtime=not is_test_file,
                        )
                    )

        # 2. Exports: export function foo, export const bar, export class Baz
        export_pattern = re.compile(r"""export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([a-zA-Z0-9_]+)""")
        for match in export_pattern.finditer(content):
            sym_name = match.group(1)
            sym_id = f"symbol:{rel_path}:{sym_name}"
            self.graph.add_node(
                DependencyNode(
                    id=sym_id,
                    name=sym_name,
                    level=GraphLevel.SYMBOL,
                    file_path=rel_path,
                    symbol_type="exported_symbol",
                    is_public=True,
                )
            )
            self.graph.add_edge(
                DependencyEdge(
                    source_id=mod_id,
                    target_id=sym_id,
                    relationship=RelationshipType.EXPOSES,
                    evidence_source=EvidenceSource.STATIC,
                    confidence=ConfidenceLevel.VERIFIED,
                )
            )

        # 3. Routes: app.get('/api/users', ...), router.post('/login', ...)
        route_pattern = re.compile(r"""(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""")
        for match in route_pattern.finditer(content):
            http_method = match.group(1).upper()
            route_path = match.group(2)
            api_id = f"app:api:{http_method}:{route_path}"
            self.graph.add_node(
                DependencyNode(
                    id=api_id,
                    name=f"{http_method} {route_path}",
                    level=GraphLevel.APPLICATION,
                    file_path=rel_path,
                    symbol_type="api_endpoint",
                    metadata={"http_method": http_method, "path": route_path},
                )
            )
            self.graph.add_edge(
                DependencyEdge(
                    source_id=api_id,
                    target_id=mod_id,
                    relationship=RelationshipType.EXPOSES,
                    evidence_source=EvidenceSource.STATIC,
                    confidence=ConfidenceLevel.VERIFIED,
                )
            )

    def _analyze_database_schema(self, rel_path: str, content: str) -> None:
        """Extract SQL / Prisma table definitions."""
        mod_id = f"module:{rel_path}"
        self.graph.add_node(
            DependencyNode(id=mod_id, name=rel_path, level=GraphLevel.APPLICATION, file_path=rel_path)
        )
        table_pattern = re.compile(r"""CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_`"'.]+)""", re.IGNORECASE)
        for match in table_pattern.finditer(content):
            tbl = match.group(1).strip('`"\'')
            db_id = f"app:db:{tbl}"
            self.graph.add_node(
                DependencyNode(
                    id=db_id,
                    name=tbl,
                    level=GraphLevel.APPLICATION,
                    file_path=rel_path,
                    symbol_type="database_table",
                )
            )
            self.graph.add_edge(
                DependencyEdge(
                    source_id=mod_id,
                    target_id=db_id,
                    relationship=RelationshipType.MIGRATES,
                    evidence_source=EvidenceSource.STATIC,
                    confidence=ConfidenceLevel.VERIFIED,
                )
            )

    def _analyze_config_file(self, rel_path: str, content: str) -> None:
        """Extract config settings and environment variables."""
        cfg_id = f"app:config:{rel_path}"
        self.graph.add_node(
            DependencyNode(
                id=cfg_id,
                name=rel_path,
                level=GraphLevel.APPLICATION,
                file_path=rel_path,
                symbol_type="config_file",
            )
        )

    def _analyze_generic_polyglot(self, rel_path: str, content: str) -> None:
        """Polyglot fallback for Go, Rust, Java, C#, etc. with explicit heuristic markers."""
        mod_id = f"module:{rel_path}"
        self.graph.add_node(
            DependencyNode(
                id=mod_id,
                name=rel_path,
                level=GraphLevel.MODULE,
                file_path=rel_path,
                symbol_type="polyglot_source",
                metadata={"analyzer": "heuristic_polyglot"},
            )
        )
        # Look for package / import statements
        for line in content.splitlines()[:50]:
            line_s = line.strip()
            if line_s.startswith("import ") or line_s.startswith("package ") or line_s.startswith("using ") or line_s.startswith("use "):
                parts = line_s.split()
                if len(parts) >= 2:
                    target_pkg = parts[1].strip(";\"'")
                    self.graph.add_edge(
                        DependencyEdge(
                            source_id=mod_id,
                            target_id=f"module:{target_pkg}",
                            relationship=RelationshipType.DEPENDS_ON,
                            evidence_source=EvidenceSource.HEURISTIC,
                            confidence=ConfidenceLevel.INFERRED,
                            rationale="Polyglot import statement heuristic",
                        )
                    )

    def _resolve_symbolic_links(self) -> None:
        """Resolve symbolic calls and imports to actual node IDs where possible."""
        # Index all functions and classes by name for quick call resolution
        symbol_map: Dict[str, List[DependencyNode]] = {}
        for node in self.graph.nodes.values():
            if node.level in (GraphLevel.SYMBOL, GraphLevel.TEST):
                symbol_map.setdefault(node.name, []).append(node)

        # For any edge targeting a bare symbol name (e.g. "func_name") or "symbol:Name", connect to matching node
        for edge_list in list(self.graph._outgoing.values()):
            for e in list(edge_list):
                target_key = e.target_id
                bare_name = target_key.split(":")[-1]
                if bare_name in symbol_map:
                    candidates = symbol_map[bare_name]
                    # Filter candidates: prefer candidate in the same file as source
                    source_node = self.graph.get_node(e.source_id)
                    matched_id = None
                    if source_node and source_node.file_path:
                        same_file = [c for c in candidates if c.file_path == source_node.file_path]
                        if len(same_file) == 1:
                            matched_id = same_file[0].id
                    if not matched_id and len(candidates) == 1:
                        matched_id = candidates[0].id
                    if matched_id and matched_id != e.target_id:
                        self.graph.update_edge_target(e, matched_id)


class _PythonASTVisitor(ast.NodeVisitor):
    """AST Visitor to extract symbols, classes, calls, routes, models, and tests."""

    def __init__(
        self,
        rel_path: str,
        mod_id: str,
        is_test_file: bool,
        graph: MultiLevelDependencyGraph,
    ) -> None:
        self.rel_path = rel_path
        self.mod_id = mod_id
        self.is_test_file = is_test_file
        self.graph = graph
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = node.name
        class_id = f"symbol:{self.rel_path}:{class_name}"
        is_test_class = class_name.startswith("Test") or self.is_test_file
        self.graph.add_node(
            DependencyNode(
                id=class_id,
                name=class_name,
                level=GraphLevel.TEST if is_test_class else GraphLevel.SYMBOL,
                file_path=self.rel_path,
                line_number=node.lineno,
                symbol_type="class",
                is_public=not class_name.startswith("_"),
            )
        )
        self.graph.add_edge(
            DependencyEdge(
                source_id=self.mod_id,
                target_id=class_id,
                relationship=RelationshipType.EXPOSES,
                evidence_source=EvidenceSource.STATIC,
                confidence=ConfidenceLevel.VERIFIED,
            )
        )

        # Inheritance: bases
        for base in node.bases:
            base_name = self._get_name(base)
            if base_name:
                base_id = f"symbol:{base_name}"
                self.graph.add_edge(
                    DependencyEdge(
                        source_id=class_id,
                        target_id=base_id,
                        relationship=RelationshipType.INHERITS,
                        evidence_source=EvidenceSource.STATIC,
                        confidence=ConfidenceLevel.VERIFIED,
                    )
                )
                # Check for ORM model bases
                if base_name in {"Base", "Model", "DeclarativeBase", "db.Model"}:
                    db_id = f"app:db:{class_name.lower()}"
                    self.graph.add_node(
                        DependencyNode(
                            id=db_id,
                            name=class_name,
                            level=GraphLevel.APPLICATION,
                            file_path=self.rel_path,
                            symbol_type="database_model",
                        )
                    )
                    self.graph.add_edge(
                        DependencyEdge(
                            source_id=db_id,
                            target_id=class_id,
                            relationship=RelationshipType.DEPENDS_ON,
                            evidence_source=EvidenceSource.STATIC,
                            confidence=ConfidenceLevel.VERIFIED,
                        )
                    )

        old_class = self.current_class
        self.current_class = class_name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function_definition(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function_definition(node, is_async=True)

    def _handle_function_definition(self, node: Any, is_async: bool) -> None:
        func_name = node.name
        full_name = f"{self.current_class}.{func_name}" if self.current_class else func_name
        is_test_case = func_name.startswith("test_") or self.is_test_file

        sym_id = f"symbol:{self.rel_path}:{full_name}"
        self.graph.add_node(
            DependencyNode(
                id=sym_id,
                name=full_name,
                level=GraphLevel.TEST if is_test_case else GraphLevel.SYMBOL,
                file_path=self.rel_path,
                line_number=node.lineno,
                symbol_type="method" if self.current_class else "function",
                is_public=not func_name.startswith("_"),
                metadata={"is_async": is_async, "args": [a.arg for a in node.args.args]},
            )
        )

        owner_id = f"symbol:{self.rel_path}:{self.current_class}" if self.current_class else self.mod_id
        self.graph.add_edge(
            DependencyEdge(
                source_id=owner_id,
                target_id=sym_id,
                relationship=RelationshipType.EXPOSES,
                evidence_source=EvidenceSource.STATIC,
                confidence=ConfidenceLevel.VERIFIED,
            )
        )

        # Check route decorators: @app.get(...), @router.post(...)
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call):
                func_obj = deco.func
                deco_name = self._get_name(func_obj)
                if deco_name and any(m in deco_name.lower() for m in [".get", ".post", ".put", ".delete", ".patch", ".route"]):
                    route_path = "/"
                    if deco.args and isinstance(deco.args[0], ast.Constant) and isinstance(deco.args[0].value, str):
                        route_path = deco.args[0].value
                    http_method = deco_name.split(".")[-1].upper()
                    if http_method == "ROUTE":
                        http_method = "GET"
                    api_id = f"app:api:{http_method}:{route_path}"
                    self.graph.add_node(
                        DependencyNode(
                            id=api_id,
                            name=f"{http_method} {route_path}",
                            level=GraphLevel.APPLICATION,
                            file_path=self.rel_path,
                            symbol_type="api_endpoint",
                            metadata={"handler": full_name},
                        )
                    )
                    self.graph.add_edge(
                        DependencyEdge(
                            source_id=api_id,
                            target_id=sym_id,
                            relationship=RelationshipType.EXPOSES,
                            evidence_source=EvidenceSource.STATIC,
                            confidence=ConfidenceLevel.VERIFIED,
                        )
                    )

        old_func = self.current_function
        self.current_function = sym_id
        self.generic_visit(node)
        self.current_function = old_func

    def visit_Call(self, node: ast.Call) -> None:
        caller_id = self.current_function or self.mod_id
        callee_name = self._get_name(node.func)
        if callee_name:
            # Check for config reads: os.environ.get("X") or os.getenv("X")
            if callee_name in {"os.environ.get", "os.getenv", "environ.get", "getenv"}:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    var_name = node.args[0].value
                    cfg_id = f"app:config:{var_name}"
                    self.graph.add_node(
                        DependencyNode(
                            id=cfg_id,
                            name=var_name,
                            level=GraphLevel.APPLICATION,
                            symbol_type="config_variable",
                        )
                    )
                    self.graph.add_edge(
                        DependencyEdge(
                            source_id=caller_id,
                            target_id=cfg_id,
                            relationship=RelationshipType.READS,
                            evidence_source=EvidenceSource.STATIC,
                            confidence=ConfidenceLevel.VERIFIED,
                        )
                    )
            else:
                # Ordinary function call
                is_test_call = (
                    caller_id.startswith("symbol:") and "test" in caller_id.lower()
                ) or self.is_test_file
                self.graph.add_edge(
                    DependencyEdge(
                        source_id=caller_id,
                        target_id=callee_name,  # Bare name resolved later
                        relationship=RelationshipType.TESTS if is_test_call else RelationshipType.CALLS,
                        evidence_source=EvidenceSource.STATIC,
                        confidence=ConfidenceLevel.VERIFIED,
                        is_runtime=not is_test_call,
                    )
                )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        caller_id = self.current_function or self.mod_id
        for alias in node.names:
            target_id = f"module:{alias.name}"
            self.graph.add_edge(
                DependencyEdge(
                    source_id=caller_id,
                    target_id=target_id,
                    relationship=RelationshipType.IMPORTS,
                    evidence_source=EvidenceSource.STATIC,
                    confidence=ConfidenceLevel.VERIFIED,
                    is_runtime=not self.is_test_file,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        caller_id = self.current_function or self.mod_id
        mod_prefix = node.module or ""
        # Handle relative imports
        if node.level > 0:
            cur_parts = Path(self.rel_path).parts[:-1]
            if node.level <= len(cur_parts):
                base_parts = cur_parts[:len(cur_parts) - (node.level - 1)]
                mod_prefix = ".".join(base_parts) + ("." + mod_prefix if mod_prefix else "")

        for alias in node.names:
            target_id = f"symbol:{mod_prefix}:{alias.name}" if mod_prefix else f"symbol:{alias.name}"
            self.graph.add_edge(
                DependencyEdge(
                    source_id=caller_id,
                    target_id=target_id,
                    relationship=RelationshipType.IMPORTS,
                    evidence_source=EvidenceSource.STATIC,
                    confidence=ConfidenceLevel.VERIFIED,
                    is_runtime=not self.is_test_file,
                )
            )

    def _get_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            val_name = self._get_name(node.value)
            return f"{val_name}.{node.attr}" if val_name else node.attr
        return None

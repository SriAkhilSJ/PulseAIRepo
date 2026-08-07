# src/context/repo_map.py
"""
Repo Map
========

A structural summary of the codebase.

Instead of the agent blindly listing files, it gets a compact map:

- Directory tree
- File sizes
- Top-level functions and classes in Python files
- Skips junk: __pycache__, node_modules, .git, etc.

This saves tokens because the agent knows WHERE things are before it starts
reading files.
"""

import os
import re
import threading
from pathlib import Path


# Directories to skip entirely.
IGNORED_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".egg-info",
    ".tox",
    ".idea",
    ".vscode",
    "generated",  # PulseAI's generated folder
}

# File extensions we care about.
INTERESTING_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".toml", ".yaml", ".yml",
    ".md", ".txt", ".sh", ".bat",
    ".html", ".css", ".sql",
}

# Max file size to read for symbol extraction (bytes).
MAX_FILE_SIZE = 100_000  # 100KB


class RepoMap:
    """
    Builds and caches a structural map of the workspace.

    Usage:
        repo_map = RepoMap("/path/to/project")
        text = repo_map.get_map()

    The map is cached. Call refresh() to rebuild.
    """

    def __init__(self, root_path: str | Path):
        self.root = Path(root_path).resolve()
        self._cache: str | None = None
        self._cache_mtime: float = 0.0
        # D14 (§37): per-file stats collected during the build — the ONLY
        # inputs the compress path's importance ranking needs (no re-walk).
        self._file_stats: dict[str, dict[str, float]] = {}
        self._in_degree: dict[str, int] = {}

    # =========================================================
    # PUBLIC API
    # =========================================================

    def get_map(self, max_tokens: int = 1500) -> str:
        """
        Return the repo map, using cache if fresh.

        max_tokens: Rough token budget for the map. If the map exceeds this,
                    we compress it.
        """
        if self._cache is None or self._is_stale():
            self.refresh()

        if self._cache is None:
            return ""

        # Rough token estimate: ~0.75 tokens per char.
        estimated_tokens = len(self._cache) * 0.75

        if estimated_tokens > max_tokens:
            return self._compress_map(max_tokens)

        return self._cache

    def refresh(self) -> str:
        """Force rebuild the map from disk."""
        self._cache = self._build_map()
        self._cache_mtime = self._get_latest_mtime()
        return self._cache

    def invalidate(self):
        """Clear cache. Next get_map() will rebuild."""
        self._cache = None

    # =========================================================
    # MAP BUILDER
    # =========================================================

    def _build_map(self) -> str:
        """Walk the tree and build the map string."""
        lines = [f"=== REPO MAP: {self.root.name} ===", ""]

        # Collect all interesting files.
        files = self._collect_files()

        # Group by directory.
        by_dir: dict[str, list[Path]] = {}
        for file_path in files:
            rel = file_path.relative_to(self.root)
            dir_path = str(rel.parent)
            by_dir.setdefault(dir_path, []).append(rel)

        # Sort directories for stable output.
        for dir_path in sorted(by_dir.keys()):
            files_in_dir = sorted(by_dir[dir_path], key=lambda path: path.name)

            # Print directory header.
            if dir_path == ".":
                lines.append(f"[root]  ({len(files_in_dir)} files)")
            else:
                lines.append(f"{dir_path}/  ({len(files_in_dir)} files)")

            # Print each file.
            for rel_path in files_in_dir:
                full_path = self.root / rel_path
                file_info = self._describe_file(full_path, rel_path)
                lines.append(f"  {file_info}")

            lines.append("")

        # Add import graph at the end. D14: prefer RESOLVED file->file edges
        # (the verified chunk_index resolver) — centrality counts only make
        # sense on real edges; the module-first-segment graph can't produce
        # them. Legacy module graph stays as the degraded fallback.
        edges = self._resolved_edges(files)
        graph_lines: list[str] = []
        if edges:
            in_degree: dict[str, int] = {}
            for _src, tgts in edges.items():
                for t in tgts:
                    in_degree[t] = in_degree.get(t, 0) + 1
            self._in_degree = in_degree
            hubs = sorted(in_degree.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            graph_lines.append(
                "Most depended-upon: "
                + ", ".join(f"{t} ({n})" for t, n in hubs)
            )
            for importer in sorted(edges)[:20]:
                tgts = sorted(edges[importer],
                              key=lambda t: (-in_degree.get(t, 0), t))[:5]
                graph_lines.append(f"{importer} -> {', '.join(tgts)}")
            if len(edges) > 20:
                graph_lines.append(f"... ({len(edges) - 20} more files) ...")
        else:
            self._in_degree = {}
            graph = self._build_import_graph(files)
            if graph:
                for file_path, imports in sorted(graph.items())[:20]:
                    graph_lines.append(f"{file_path} -> {', '.join(imports[:5])}")
                if len(graph) > 20:
                    graph_lines.append(f"... ({len(graph) - 20} more files) ...")

        if graph_lines:
            lines.append("")
            lines.append("=== IMPORT GRAPH ===")
            lines.extend(graph_lines)

        lines.append("")
        lines.append("=== END REPO MAP ===")
        return "\n".join(lines)


    def _collect_files(self) -> list[Path]:
        """Walk directory tree, collecting interesting files."""
        files: list[Path] = []

        for dirpath, dirnames, filenames in os.walk(self.root):
            # Filter out ignored directories in-place so os.walk doesn't descend.
            dirnames[:] = [
                dirname for dirname in dirnames
                if dirname not in IGNORED_DIRS and not dirname.startswith(".")
            ]

            current_dir = Path(dirpath)

            for filename in filenames:
                # Skip hidden files.
                if filename.startswith("."):
                    continue

                # Skip common junk.
                if filename.endswith((".pyc", ".pyo", ".egg", ".whl")):
                    continue

                full_path = current_dir / filename

                try:
                    size = full_path.stat().st_size
                except OSError:
                    continue

                # Only include files with interesting extensions OR small files
                # without extension (like Makefile, Dockerfile).
                ext = full_path.suffix.lower()

                if ext in INTERESTING_EXTENSIONS:
                    files.append(full_path)
                elif not ext and size < 50_000:
                    files.append(full_path)

        return files

    def _describe_file(self, full_path: Path, rel_path: Path) -> str:
        """
        Create a one-line description of a file.

        For Python files: extract top-level functions/classes.
        For others: just show size and extension.

        Also stashes D14 compress-ranking stats (mtime, size, symbol mass) —
        one stat() call, no re-walk later.
        """
        st = full_path.stat()
        size = st.st_size
        size_str = self._format_size(size)
        name = rel_path.name
        stats = {"mtime": st.st_mtime, "size": float(size), "mass": 0.0}

        # Python files get symbol extraction.
        if full_path.suffix == ".py" and size < MAX_FILE_SIZE:
            symbols, n_classes, n_functions = self._extract_python_symbols(full_path)
            stats["mass"] = float(n_classes + n_functions)
            self._file_stats[str(rel_path)] = stats
            if symbols:
                return f"{name} ({size_str}) -> {symbols}"

        self._file_stats[str(rel_path)] = stats
        return f"{name} ({size_str})"

    def _extract_python_symbols(self, path: Path) -> tuple[str, int, int]:
        """Extract top-level symbols using AST (accurate, handles decorators/async).
        Returns (formatted_text, n_classes, n_functions) — counts feed the D14
        importance mass signal."""
        import ast
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except Exception:
            return "", 0, 0

        classes = []
        functions = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.col_offset == 0 and not node.name.startswith("_"):
                    functions.append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])

        parts = []
        if classes:
            ct = f"classes: {', '.join(classes[:3])}"
            if len(classes) > 3:
                ct += f" (+{len(classes) - 3})"
            parts.append(ct)
        if functions:
            ft = f"functions: {', '.join(functions[:3])}"
            if len(functions) > 3:
                ft += f" (+{len(functions) - 3})"
            parts.append(ft)
        if imports:
            it = f"imports: {', '.join(imports[:3])}"
            if len(imports) > 3:
                it += f" (+{len(imports) - 3})"
            parts.append(it)

        return " | ".join(parts), len(classes), len(functions)

    def _resolved_edges(self, files: list[Path]) -> dict[str, set[str]]:
        """D14: file->file import edges via chunk_index's verified resolver
        (full dotted-path resolution). Module-level graph is the documented
        fallback when that import is unavailable. Never raises — edges are
        a ranking bonus, not a failure mode."""
        try:
            from src.context.chunk_index import _extract_py_import_edges
        except Exception:
            return {}
        edges: dict[str, set[str]] = {}
        for f in files:
            if f.suffix != ".py":
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
                rel = f.relative_to(self.root)
            except (OSError, ValueError):
                continue
            try:
                targets = _extract_py_import_edges(src, rel, self.root)
            except Exception:
                continue
            if targets:
                edges[str(rel)] = set(targets)
        return edges

    def _importance(self, rel: str, max_deg: float, min_mtime: float,
                    mtime_span: float, max_mass: float) -> float:
        """D14 compress-ranking score: depended-upon-ness dominates, then
        recency (range-normalized — ratio-to-max on epoch seconds would make
        everything ~1.0), then symbol mass. All inputs content/mtime-derived;
        computed only on the compress path, so the FULL map never reorders
        (byte-stable for prompt-cache prefixing — the §32 doctrine)."""
        stats = self._file_stats.get(rel, {})
        deg_n = (self._in_degree.get(rel, 0) / max_deg) if max_deg else 0.0
        rec_n = ((stats.get("mtime", 0.0) - min_mtime) / mtime_span) if mtime_span else 0.0
        mass_n = (stats.get("mass", 0.0) / max_mass) if max_mass else 0.0
        return 3.0 * deg_n + 1.5 * rec_n + 0.5 * mass_n

    def _build_import_graph(self, files: list[Path]) -> dict[str, list[str]]:
        """Build a map of file -> modules it imports."""
        import ast
        graph: dict[str, list[str]] = {}
        for f in files:
            if f.suffix != ".py":
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content)
            except Exception:
                continue
            rel = str(f.relative_to(self.root))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module.split(".")[0])
            if imports:
                graph[rel] = list(dict.fromkeys(imports))  # dedupe
        return graph


    def _format_size(self, size: int) -> str:
        """Human-readable file size."""
        if size < 1024:
            return f"{size}B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        return f"{size / (1024 * 1024):.1f}MB"

    def _compress_map(self, max_tokens: int) -> str:
        """
        D14 v2: staged reduction by file IMPORTANCE — when budget forces a
        choice, the map keeps the files that matter instead of the files
        whose names sort early in the alphabet. Pre-fix behavior: strip ALL
        symbol detail, then truncate from the END OF THE ALPHABET, so
        z_core_engine.py vanished while a_junk_00.py survived (measured in
        scripts/d13_d14_rank_measure.py R1).

        Stages (each stops as soon as the budget fits):
          1. strip "| imports: ..." segments (least informative detail)
          2. strip symbol detail for below-median-importance files only
             (top-importance files keep their classes/functions)
          3. strip ALL symbol detail (the old stage 1)
          4. drop whole file lines, LEAST-important first
          5. char-truncate as the legacy last resort

        The import-graph section is split off first and always appended
        whole. Emission among kept files stays alphabetical per directory
        (navigable; and within a fixed selection the text is deterministic).
        """
        if self._cache is None:
            return ""

        # Split off the import graph so compression/truncation can't destroy it
        # (every import-graph line contains " -> " and lives at the tail).
        marker = "=== IMPORT GRAPH ==="
        if marker in self._cache:
            tree_part, graph_part = self._cache.split(marker, 1)
            graph_part = marker + graph_part
        else:
            tree_part, graph_part = self._cache, ""

        # --- parse the tree section into typed entries ---------------------
        #                (kind, line, rel-or-dir)
        entries: list[tuple[str, str, str | None]] = []
        cur_dir = "."
        for line in tree_part.splitlines():
            stripped = line.strip()
            if line.startswith("  ") and " (" in stripped:
                fname = stripped.split(" (")[0]
                # os.path.join: _file_stats keys come from str(Path) — same
                # separator per platform (Windows-safe).
                rel = fname if cur_dir == "." else os.path.join(cur_dir, fname)
                entries.append(("file", line, rel))
            elif (stripped.startswith("[root]") or stripped.endswith("files)")) \
                    and " files)" in stripped:
                dir_name = stripped.split("]")[0].rstrip("/") if stripped.startswith("[root]") \
                    else stripped.split("  (")[0].rstrip("/")
                cur_dir = "." if stripped.startswith("[root]") else dir_name
                entries.append(("dir", line, cur_dir))
            else:
                entries.append(("meta", line, None))

        # --- importance over the files present -----------------------------
        file_rels = [rel for kind, _l, rel in entries if kind == "file" and rel]
        if not file_rels:
            return self._cache[: int(max_tokens / 0.75)] + graph_part
        max_deg = max([self._in_degree.get(r, 0) for r in file_rels] + [0]) or 0
        mtimes = [self._file_stats.get(r, {}).get("mtime", 0.0) for r in file_rels]
        min_mtime, mtime_span = min(mtimes), (max(mtimes) - min(mtimes)) or 0.0
        max_mass = max([self._file_stats.get(r, {}).get("mass", 0.0) for r in file_rels] + [0]) or 0.0
        imp = {
            r: self._importance(r, max_deg, min_mtime, mtime_span, max_mass)
            for r in file_rels
        }

        def _fits(lines: list[str]) -> bool:
            return len("\n".join(lines)) * 0.75 <= max_tokens

        def _emit() -> list[str]:
            return [line for _kind, line, _rel in entries]

        # stage 1: drop "| imports: ..." segments from file lines
        work: list[tuple[str, str, str | None]] = [
            (k, (ln.split(" | imports:")[0] if k == "file" else ln), r)
            for k, ln, r in entries
        ]
        entries = work
        if _fits(_emit()):
            return "\n".join(_emit()) + graph_part

        # stage 2: strip symbol detail for files at-or-below the MEDIAN
        # importance (<= so a tied low floor like all-junk-zeros loses its
        # detail first); top-importance files keep classes/functions.
        import statistics
        median_imp = statistics.median(imp.values())
        work = [
            (k, (ln.split(" -> ")[0] if k == "file" and r is not None
                 and imp.get(r, 0.0) <= median_imp else ln), r)
            for k, ln, r in entries
        ]
        if _fits([ln for _k, ln, _r in work]):
            entries = work
            return "\n".join(_emit()) + graph_part

        # stage 3: strip ALL symbol detail (old stage 1)
        work = [
            (k, (ln.split(" -> ")[0] if k == "file" else ln), r)
            for k, ln, r in entries
        ]
        entries = work
        if _fits(_emit()):
            return "\n".join(_emit()) + graph_part

        # stage 4: drop whole file lines, least important first; then drop
        # directory headers left with no files under them.
        for victim in sorted(file_rels, key=lambda r: (imp[r], r)):
            entries = [e for e in entries if not (e[0] == "file" and e[2] == victim)]
            pruned: list[tuple[str, str, str | None]] = []
            for i, e in enumerate(entries):
                if e[0] == "dir":
                    j = i + 1
                    found = False
                    while j < len(entries) and entries[j][0] != "dir":
                        if entries[j][0] == "file":
                            found = True
                            break
                        j += 1
                    if not found:
                        continue
                pruned.append(e)
            entries = pruned
            if _fits(_emit()):
                return ("\n".join(_emit())
                        + "\n... (least-important files omitted) ..."
                        + graph_part)

        # stage 5: legacy char truncate, tree portion only.
        result = "\n".join(_emit())
        max_chars = int(max_tokens / 0.75)
        result = result[:max_chars].rstrip()
        result += "\n... (truncated) ..."
        return result + graph_part

    # =========================================================
    # CACHE HELPERS
    # =========================================================

    def _get_latest_mtime(self) -> float:
        """Find the most recent modification time in the project."""
        latest = 0.0

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                dirname for dirname in dirnames
                if dirname not in IGNORED_DIRS and not dirname.startswith(".")
            ]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                try:
                    mtime = (Path(dirpath) / filename).stat().st_mtime
                    if mtime > latest:
                        latest = mtime
                except Exception:
                    pass

        return latest

    def _is_stale(self) -> bool:
        """Check if any file has been modified since cache was built."""
        current_mtime = self._get_latest_mtime()
        return current_mtime > self._cache_mtime


# =========================================================
# GLOBAL INSTANCE
# =========================================================

# Per-workspace registry (same D1 class as the engine singleton race): the
# old single global flip-flopped whenever two dashboard sessions used
# DIFFERENT workspaces — every turn rebuilt the other session's map, and a
# RepoMap build is a full AST walk of the repo. Keyed dict + lock instead.
_repo_maps: dict[str, "RepoMap"] = {}
_repo_maps_lock = threading.Lock()


def _map_for(workspace_path: Path) -> "RepoMap":
    key = str(workspace_path)
    with _repo_maps_lock:
        instance = _repo_maps.get(key)
        if instance is None:
            instance = RepoMap(workspace_path)
            _repo_maps[key] = instance
        return instance


def get_repo_map(workspace: str | Path, max_tokens: int = 1500) -> str:
    """Get the repo map for a workspace (cached per workspace)."""
    workspace_path = Path(workspace).resolve()
    return _map_for(workspace_path).get_map(max_tokens)


def refresh_repo_map(workspace: str | Path) -> str:
    """Force rebuild the repo map."""
    workspace_path = Path(workspace).resolve()
    with _repo_maps_lock:
        instance = RepoMap(workspace_path)
        _repo_maps[str(workspace_path)] = instance
    return instance.refresh()

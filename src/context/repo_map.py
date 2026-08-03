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

        # Add import graph at the end
        graph = self._build_import_graph(files)
        if graph:
            lines.append("")
            lines.append("=== IMPORT GRAPH ===")
            for file_path, imports in sorted(graph.items())[:20]:
                lines.append(f"{file_path} -> {', '.join(imports[:5])}")
            if len(graph) > 20:
                lines.append(f"... ({len(graph) - 20} more files) ...")

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
        """
        size = full_path.stat().st_size
        size_str = self._format_size(size)
        name = rel_path.name

        # Python files get symbol extraction.
        if full_path.suffix == ".py" and size < MAX_FILE_SIZE:
            symbols = self._extract_python_symbols(full_path)
            if symbols:
                return f"{name} ({size_str}) -> {symbols}"

        return f"{name} ({size_str})"

    def _extract_python_symbols(self, path: Path) -> str:
        """Extract top-level symbols using AST (accurate, handles decorators/async)."""
        import ast
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except Exception:
            return ""

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

        return " | ".join(parts)

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
        If the map is too big, compress it by removing function details and
        keeping only the tree structure.
        """
        if self._cache is None:
            return ""

        lines = self._cache.splitlines()
        compressed = []

        for line in lines:
            # Remove symbol details.
            if " -> " in line:
                line = line.split(" -> ")[0]
            compressed.append(line)

        result = "\n".join(compressed)

        # If still too big, truncate.
        if len(result) * 0.75 > max_tokens:
            max_chars = int(max_tokens / 0.75)
            result = result[:max_chars]
            result += "\n... (truncated) ..."

        return result

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

_repo_map_instance: RepoMap | None = None


def get_repo_map(workspace: str | Path, max_tokens: int = 1500) -> str:
    """
    Get the repo map for a workspace.

    Uses a singleton so the map is cached across calls.
    """
    global _repo_map_instance

    workspace_path = Path(workspace).resolve()

    if _repo_map_instance is None or _repo_map_instance.root != workspace_path:
        _repo_map_instance = RepoMap(workspace_path)

    return _repo_map_instance.get_map(max_tokens)


def refresh_repo_map(workspace: str | Path) -> str:
    """Force rebuild the repo map."""
    global _repo_map_instance

    workspace_path = Path(workspace).resolve()
    _repo_map_instance = RepoMap(workspace_path)
    return _repo_map_instance.refresh()

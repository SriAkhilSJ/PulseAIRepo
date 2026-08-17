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
import time
from pathlib import Path

from src.context.bounded_scan import ContextBudget, scan_files


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
        # D25 (§44): the staleness CHECK walked the whole tree on EVERY
        # get_map — measured 106ms @10k files, 306ms @30k, and it runs once
        # per engine turn. Now the walk answer is trusted for a short TTL
        # (mutations OUR tools make call invalidate() instantly anyway; the
        # TTL only bounds edits made outside the agent's view).
        self._last_stale_check: float = 0.0
        # D14 (§37): per-file stats collected during the build — the ONLY
        # inputs the compress path's importance ranking needs (no re-walk).
        self._file_stats: dict[str, dict[str, float]] = {}
        self._in_degree: dict[str, int] = {}
        self._last_scan_report = None
        self._last_budget: ContextBudget | None = None
        self.thread_id_hint: str | None = None

    # =========================================================
    # PUBLIC API
    # =========================================================

    def get_map(self, max_tokens: int = 1500, budget: ContextBudget | None = None) -> str:
        """
        Return the repo map, using cache if fresh.

        max_tokens: Rough token budget for the map. If the map exceeds this,
                    we compress it.
        budget:     P1 shared initial-context deadline; the walk and reads
                    stop when it expires and a degraded receipt is emitted.
        """
        if self._cache is None or self._is_stale(budget):
            self.refresh(budget)

        if self._cache is None:
            return ""

        # Rough token estimate: ~0.75 tokens per char.
        estimated_tokens = len(self._cache) * 0.75

        if estimated_tokens > max_tokens:
            return self._compress_map(max_tokens)

        return self._cache

    def refresh(self, budget: ContextBudget | None = None) -> str:
        """Force rebuild the map from disk."""
        budget = budget or ContextBudget()
        self._last_budget = budget
        self._cache = self._build_map(budget)
        self._cache_mtime = self._get_latest_mtime(budget)
        self._last_stale_check = time.time()  # the build was itself a walk
        self._emit_degraded_scan(budget)
        return self._cache

    def _emit_degraded_scan(self, budget: ContextBudget | None = None) -> None:
        """Surface a truncated repo-map walk as a structured runtime.degraded
        receipt (real counts, emitted ONCE per shared budget). A walker that
        consumed NOTHING (the shared deadline expired before its scan ran) is
        not "degraded work" — the walkers that DID scan already carry the
        receipt, so zero-count emissions are suppressed."""
        report = getattr(self, "_last_scan_report", None)
        if report is None or not report.truncated:
            return
        budget = budget or self._last_budget or ContextBudget()
        # A walker that consumed NOTHING (the shared deadline expired before
        # its scan ran) is not "degraded work" — the walkers that DID scan
        # already carry the receipt. A user CANCEL is a real signal even with
        # zero consumption, so cancelled receipts always fire.
        if report.files == 0 and not budget.cancelled:
            return
        budget.emit_degraded({
            "thread_id": self.thread_id_hint or "unknown",
            "component": "repo_map",
            "reason": "context scan bounded",
            "error": f"repo map scan {report.summarize()}",
            "files_considered": report.considered,
            "files_read": budget.read_files,
            "bytes_read": budget.read_bytes,
            "elapsed_ms": int(budget.elapsed * 1000),
            "skipped_generated": (
                report.skipped_dirs + report.skipped_generated + report.skipped_gitignore
            ),
            "skipped_oversized": report.skipped_oversize,
            "skipped_binary": report.skipped_binary,
            "cancelled": budget.cancelled,
        })

    def invalidate(self):
        """Clear cache. Next get_map() will rebuild."""
        self._cache = None

    # =========================================================
    # MAP BUILDER
    # =========================================================

    def _build_map(self, budget: ContextBudget | None = None) -> str:
        """Walk the tree and build the map string.

        ``budget`` (P1): the shared initial-context deadline; file reads stop
        once it expires so a huge tree yields a partial (degraded) map.
        """
        budget = budget or ContextBudget()
        lines = [f"=== REPO MAP: {self.root.name} ===", ""]

        # Collect all interesting files.
        files = self._collect_files(budget)

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
                if budget.expired:
                    break
                full_path = self.root / rel_path
                file_info = self._describe_file(full_path, rel_path, budget)
                lines.append(f"  {file_info}")

            lines.append("")

        # Add import graph at the end. D14: prefer RESOLVED file->file edges
        # (the verified chunk_index resolver) — centrality counts only make
        # sense on real edges; the module-first-segment graph can't produce
        # them. Legacy module graph stays as the degraded fallback.
        edges = self._resolved_edges(files, budget)
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
            graph = self._build_import_graph(files, budget)
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


    def _collect_files(self, budget: ContextBudget | None = None) -> list[Path]:
        """Walk directory tree, collecting interesting files.

        BOUNDED (P1): the walk honors the shared ContextBudget (file-count /
        byte / elapsed caps, symlink skip, the IGNORED_DIRS + dot-exclusion
        set, and the root .gitignore) via BoundedScan, so a giant workspace
        fork can never hang the context build. On truncation the report is
        stored on ``self._last_scan_report`` and surfaced as a
        ``runtime.degraded`` receipt by refresh().
        """
        budget = budget or ContextBudget()
        self._last_budget = budget
        files: list[Path] = []
        iterator, report = scan_files(
            self.root,
            limits=budget.to_limits(),
            skip_dirs=IGNORED_DIRS,
            should_stop=budget.should_stop,
            priority=True,
        )
        self._last_scan_report = report

        for full_path in iterator:
            if budget.expired:
                break
            # Skip common junk.
            if full_path.name.endswith((".pyc", ".pyo", ".egg", ".whl")):
                continue
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

        # P1-fix: fold this walker's scan consumption into the shared pool.
        if budget is not None:
            budget.absorb(report)
        return files

    def _describe_file(self, full_path: Path, rel_path: Path, budget: ContextBudget | None = None) -> str:
        """
        Create a one-line description of a file.

        For Python files: extract top-level functions/classes.
        For others: just show size and extension.
        ``budget`` (P1): records the read for the degraded receipt.

        Also stashes D14 compress-ranking stats (mtime, size, symbol mass) —
        one stat() call, no re-walk later.
        """
        st = full_path.stat()
        size = st.st_size
        size_str = self._format_size(size)
        name = rel_path.name
        stats = {"mtime": st.st_mtime, "size": float(size), "mass": 0.0}
        if budget is not None:
            budget.record_read(size)

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

    # Max share of the compress budget the import-graph section may eat
    # (D24): the tree carries the map's primary content.
    _GRAPH_BUDGET_SHARE = 0.35

    def _budget_graph(self, graph_text: str, max_tokens: int) -> str:
        """D24: cap the graph section to a share of the compress budget.

        Keeps the marker, the 'Most depended-upon:' hub line (densest info),
        then as many data rows as fit; explicit note when rows are dropped.
        Never raises; short sections pass through untouched.
        """
        cap_tokens = max_tokens * self._GRAPH_BUDGET_SHARE
        if len(graph_text) * 0.75 <= cap_tokens:
            return graph_text
        lines = graph_text.splitlines()
        head: list[str] = []
        rows: list[str] = []
        tail_markers: list[str] = []
        for ln in lines:
            if ln.strip() == "=== END REPO MAP ===":
                tail_markers.append(ln)          # closing marker stays LAST
            elif " -> " in ln and not ln.startswith("..."):
                rows.append(ln)
            elif ln.startswith("..."):
                continue  # replaced by our own omission note if needed
            else:
                head.append(ln)
        kept: list[str] = list(head)
        for ln in rows:
            if len("\n".join(kept + [ln])) * 0.75 > cap_tokens and kept:
                break
            kept.append(ln)
        dropped = len(rows) - (len(kept) - len(head))
        if dropped > 0:
            kept.append(f"... ({dropped} graph rows omitted for budget) ...")
        return "\n".join(kept + tail_markers)

    def _resolved_edges(self, files: list[Path], budget: ContextBudget | None = None) -> dict[str, set[str]]:
        """D14: file->file import edges via chunk_index's verified resolver
        (full dotted-path resolution). Module-level graph is the documented
        fallback when that import is unavailable. Never raises — edges are
        a ranking bonus, not a failure mode. ``budget`` (P1): stops reading
        files once the shared deadline expires."""
        try:
            from src.context.chunk_index import _extract_py_import_edges
        except Exception:
            return {}
        edges: dict[str, set[str]] = {}
        for f in files:
            if budget is not None and budget.expired:
                break
            if f.suffix != ".py":
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
                rel = f.relative_to(self.root)
                if budget is not None:
                    budget.record_read(len(src.encode("utf-8", errors="ignore")))
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

    def _build_import_graph(self, files: list[Path], budget: ContextBudget | None = None) -> dict[str, list[str]]:
        """Build a map of file -> modules it imports.

        ``budget`` (P1): stops reading files once the shared deadline expires.
        """
        import ast
        graph: dict[str, list[str]] = {}
        for f in files:
            if budget is not None and budget.expired:
                break
            if f.suffix != ".py":
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if budget is not None:
                    budget.record_read(len(content.encode("utf-8", errors="ignore")))
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
        #
        # D24 (§38): the graph section is NOT appended whole at any cost —
        # on graph-heavy repos it alone could exceed max_tokens (legacy
        # protection overreached). The hub line always survives; data rows
        # are budgeted to GRAPH_SHARE of the token budget, dropped from the
        # tail (alphabetical rows -> tail rows carry no special rank), with
        # an explicit omission note. The FULL map never trims the graph.
        marker = "=== IMPORT GRAPH ==="
        if marker in self._cache:
            tree_part, graph_part = self._cache.split(marker, 1)
            graph_part = self._budget_graph(marker + graph_part, max_tokens)
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
        #
        # D-optimization: the legacy loop removed ONE victim per iteration
        # and rebuilt the full entry list each time — O(n^2). On repos with
        # ~15k files (e.g. a vendored editor fork like desktop/) that is
        # hundreds of millions of Python operations and hangs the turn for
        # minutes. The drop predicate is monotone (dropping MORE least-
        # important files can only shrink the map), so the smallest victim
        # count that fits is found by binary search in O(n log n) with
        # byte-identical output.
        victims = sorted(file_rels, key=lambda r: (imp[r], r))

        def _drop(k: int) -> list[tuple[str, str, str | None]]:
            dropped = set(victims[:k])
            kept = [
                e for e in entries
                if not (e[0] == "file" and e[2] in dropped)
            ]
            pruned: list[tuple[str, str, str | None]] = []
            for i, e in enumerate(kept):
                if e[0] == "dir":
                    j = i + 1
                    found = False
                    while j < len(kept) and kept[j][0] != "dir":
                        if kept[j][0] == "file":
                            found = True
                            break
                        j += 1
                    if not found:
                        continue
                pruned.append(e)
            return pruned

        lo, hi = 0, len(victims)
        while lo < hi:
            mid = (lo + hi) // 2
            entries = _drop(mid)
            if _fits(_emit()):
                hi = mid
            else:
                lo = mid + 1
        entries = _drop(lo)
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

    def _get_latest_mtime(self, budget: ContextBudget | None = None) -> float:
        """Find the most recent modification time in the project.

        P1-fix: the stale check is itself a walk, so it must honor the same
        budget — otherwise a huge workspace gets an unbounded full-tree walk
        just to answer "is the map stale?". The scan is bounded (files /
        bytes / elapsed / symlink / skip rules), so a giant repo degrades to
        "maybe stale" (force a rebuild) instead of a synchronous scan of
        everything.
        """
        latest = 0.0
        budget = budget or ContextBudget()
        iterator, report = scan_files(
            self.root,
            limits=budget.to_limits(),
            skip_dirs=IGNORED_DIRS,
            should_stop=budget.should_stop,
        )
        for path in iterator:
            if budget.expired:
                break
            try:
                mtime = path.stat().st_mtime
                if mtime > latest:
                    latest = mtime
            except OSError:
                continue
        if budget is not None:
            budget.absorb(report)
        # A bounded walk may not have seen the newest file; treating the tree
        # as stale forces one rebuild — correct, never stale-serving forever.
        if report.truncated:
            latest = float("inf")
        return latest

    def _is_stale(self, budget: ContextBudget | None = None) -> bool:
        """Check if any file has been modified since cache was built.

        D25: the full-tree walk runs at most once per TTL window
        (PULSEAI_REPO_MAP_STALE_TTL seconds, default 2.0; "0" restores the
        legacy walk-every-call behavior). Worst case within the window: the
        map is up to TTL seconds behind an EXTERNAL edit — far below one
        agent turn, while the walk itself used to cost ~30% of a big-repo
        turn (measured, §44)."""
        ttl = stale_check_ttl()
        now = time.time()
        if ttl > 0 and (now - self._last_stale_check) < ttl:
            return False
        self._last_stale_check = now
        current_mtime = self._get_latest_mtime(budget)
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


def get_repo_map(
    workspace: str | Path,
    max_tokens: int = 1500,
    budget: ContextBudget | None = None,
    thread_id: str | None = None,
) -> str:
    """Get the repo map for a workspace (cached per workspace).

    ``budget`` (P1): the shared initial-context deadline.
    ``thread_id``: routes the degraded receipt to the right session.
    """
    workspace_path = Path(workspace).resolve()
    instance = _map_for(workspace_path)
    if thread_id:
        instance.thread_id_hint = str(thread_id)
    return instance.get_map(max_tokens, budget)


def stale_check_ttl() -> float:
    """D25: seconds between full-tree staleness walks (env override)."""
    raw = os.environ.get("PULSEAI_REPO_MAP_STALE_TTL", "").strip()
    if not raw:
        return 2.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 2.0


def invalidate_repo_map(workspace: str | Path) -> None:
    """D25: called by the file tools after a mutation WE made — the known
    change must never hide behind the staleness TTL. No-op if no map has
    been built for the workspace yet."""
    try:
        workspace_path = Path(workspace).resolve()
        with _repo_maps_lock:
            instance = _repo_maps.get(str(workspace_path))
        if instance is not None:
            instance.invalidate()
    except Exception:
        pass  # bookkeeping must never break an edit


def refresh_repo_map(workspace: str | Path) -> str:
    """Force rebuild the repo map."""
    workspace_path = Path(workspace).resolve()
    with _repo_maps_lock:
        instance = RepoMap(workspace_path)
        _repo_maps[str(workspace_path)] = instance
    return instance.refresh()

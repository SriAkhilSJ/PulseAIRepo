"""
Chunk Index — P0 (verified build)
=================================

Chunk-level code retrieval for PulseAI: per-symbol chunks (module/function/class),
hybrid retrieval (sqlite-vec KNN + FTS5 BM25) fused with Reciprocal Rank Fusion.

Design notes (each one is a verified lesson, not a guess):

- sqlite-vec: vec0 FLOAT[EMBED_DIM] does exact KNN (v0.1.9); vec_f32(JSON) and
  vec_distance_l2() verified working. Falls back to a JSON-blob table + linear
  scan when the extension can't load.
- FTS5 is a STANDALONE table with an UNINDEXED chunk_id column, managed
  explicitly (insert/delete in the same transaction as the source rows).
  An external-content FTS table + manual inserts drifts on re-index.
- The connection is check_same_thread=False with a write lock, because
  first-run indexing happens on a background thread (default sqlite
  connections raise ProgrammingError cross-thread — verified).
- index_workspace COMMITS in batches; uncommitted inserts are invisible to
  other connections and lost on close (verified).
- Vector scores are exact cosine similarities (1 - L2²/2 for unit vectors);
  no max-distance normalization (divides by zero on exact matches).
- RRF fuses on rank POSITIONS — BM25's raw `rank` values are not comparable
  to vector distances.
- Embedded text is hard-capped (~200 tokens) for all-MiniLM-L6-v2; the full
  (display-truncated) body is stored separately for the LLM.
- import_edges (schema user_version=3): file->file import graph powering the
  "related files" section of the context layer ("detective mode"). Python
  via a stdlib-ast full dotted-path resolver (the repo_map graph's
  first-segment module names can't produce file->file edges — verified);
  JS/TS, Go, Rust, Java via bounded-candidate resolvers in lang_extractors
  (D15-remainder, §41). Rows live/die in the SAME transactions as chunk
  rows, so edges cannot drift from code.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.context.bounded_scan import ContextBudget, scan_files
from src.context.lang_extractors import (
    _EXT_JS_FAMILY as _EXT_JS_FAMILY_LANG,
    _sha256_id,
    _truncate_for_embedding,
    extract_chunks_treesitter,
    extract_js_import_edges,
    extract_go_import_edges,
    extract_rust_import_edges,
    extract_java_import_edges,
    source_extensions,
)

EMBED_DIM = 384  # all-MiniLM-L6-v2 output size
RRF_K = 60
BODY_HARD_CAP_CHARS = 800       # per-chunk cap for LLM context
FTS_MAX_TOKENS_PER_QUERY = 12

# ---------------------------------------------------------------------
# D13 (§37): feature re-rank over the fused candidate set
# ---------------------------------------------------------------------
# RRF fuses on rank POSITIONS — it never considers WHAT matched, so a
# chunk whose exact symbol name is in the query could lose to vocabulary
# twins ranking well in both retrievers (measured: scripts/
# d13_d14_rank_measure.py S1 — gold at rank 4, P@3 MISS). After fusing we
# re-score candidates with cheap, zero-LLM, zero-extra-embedding features:
# the query encode stays the ONLY encode of the turn (pinned).
_RERANK_W = {
    "name_exact": 4.0,   # literal `parse_auth_token` appears in the query
    "name_part": 0.6,    # per matched symbol-name part (snake/camel), cap 3
    "path_token": 1.0,   # file-stem part appears in the query ("auth ...")
    "hot": 0.5,          # freshest file among the candidates
    "test_demote": -2.5, # test file, when the query is not test-ish
    "docstring": 0.2,    # documented API preference
}
_RERANK_NAME_PART_CAP = 3
_RERANK_MIN_WORD = 3     # query words shorter than this never count as hints
_RERANK_TESTISH = {"test", "tests", "testing", "pytest", "unittest", "spec", "specs"}


def _word_parts(text: str) -> set[str]:
    """snake_case AND camelCase aware word splitting; lowered parts.

    'parse_auth_token' -> {parse, auth, token, parse_auth_token? no — parts}.
    Used symmetrically on queries and symbol/file names so a snake-cased
    symbol name can match both the full token and its parts.
    """
    parts: set[str] = set()
    for tok in re.findall(r"[A-Za-z0-9]+", text):
        for piece in re.split(r"_+", tok):
            if not piece:
                continue
            for sub in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+", piece):
                parts.add(sub.lower())
    return parts


def _is_test_path(file_path: str) -> bool:
    p = Path(file_path)
    name = p.name.lower()
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in p.parts

# C1 (fixed §36): vec0 KNN pushdown. The MATCH + k constraint is handled
# inside the extension (exact KNN over its own index) instead of computing
# vec_distance_l2 for every row and sorting in SQL — 12-14x faster at
# 2K-20K rows, identical orderings (scripts/c1_knn_benchmark.py).
# Module-level so tests can pin the shape AND break it to drive the
# fallback branch.
_VEC0_KNN_SQL = """
    SELECT v.chunk_id AS id, v.distance AS distance
    FROM chunk_vec v
    WHERE v.embedding MATCH vec_f32(?) AND k = ?
    ORDER BY v.distance
"""
# Pre-C1 shape, kept ONLY as the degraded fallback for sqlite-vec builds
# old enough to lack the k constraint (< v0.1.2). Never the first choice.
_VEC0_FULLSCAN_SQL = """
    SELECT c.id, vec_distance_l2(v.embedding, vec_f32(?)) AS distance
    FROM chunk_vec v
    JOIN code_chunks c ON v.chunk_id = c.id
    ORDER BY distance
    LIMIT ?
"""

_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".tox", ".idea", ".vscode", "generated",
}


# ---------------------------------------------------------------------
# IMPORT EDGES (v2 — "detective mode")
# ---------------------------------------------------------------------

def _extract_py_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """Resolve a Python file's imports to in-workspace file targets.

    Full dotted-path resolution (repo_map's first-segment module names
    cannot produce file->file edges — verified). `import a.b.c` resolves
    the exact module path; `from a.b import c` resolves both the module
    file (`a/b.py`, `a/b/__init__.py`) and submodule targets (`a/b/c.py`);
    relative `from .x import y` climbs from the importer's package dir.
    stdlib/third-party imports resolve to nothing and are dropped: edges
    exist only between workspace files. Never raises — missing edges are
    a retrieval bonus, not a failure mode.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()

    targets: set[str] = set()
    importer_str = importer_rel.as_posix()  # forward slashes everywhere (Windows durability)
    importer_dir = importer_rel.parent

    def _resolve(module: str, names: list[str], level: int) -> None:
        if level >= 1:
            base = importer_dir
            for _ in range(level - 1):
                base = base.parent  # Path('.').parent == '.': cannot escape root
        else:
            base = Path("")
        mod_path = Path(*module.split(".")) if module else Path("")
        full = base / mod_path
        candidates = [full.with_suffix(".py"), full / "__init__.py"]
        for name in names:  # from X import n -> X/n.py may be the real target
            candidates.append(full / f"{name}.py")
            candidates.append(full / name / "__init__.py")
        for cand in candidates:
            rel_str = cand.as_posix()
            if rel_str == importer_str:
                continue
            try:
                if (workspace / cand).is_file():
                    targets.add(rel_str)
            except OSError:
                continue

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _resolve(alias.name, [], 0)
        elif isinstance(node, ast.ImportFrom):
            _resolve(node.module or "", [a.name for a in node.names], node.level or 0)
    return targets


# One ChunkIndex per workspace, shared process-wide (constructing a fresh
# index — and re-syncing — per layer call would dominate every turn).
_INDEX_CACHE: dict[str, "ChunkIndex"] = {}
_INDEX_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------
# DATA MODEL
# ---------------------------------------------------------------------


@dataclass
class ChunkResult:
    id: str
    file_path: str
    symbol_name: str
    symbol_type: str  # module | function | class
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str]
    body: str          # display body for LLM context
    score: float       # fused score
    modified_time: float = 0.0  # file mtime at last sync (D13 hot feature)


# ---------------------------------------------------------------------
# CHUNK EXTRACTION (Python AST — stdlib; JS/TS via tree-sitter in
# lang_extractors — D5 multi-language milestone 1)
# ---------------------------------------------------------------------


def extract_chunks(
    file_path: Path, root: Path, source: str | None = None
) -> list[dict[str, Any]]:
    """Parse a Python file into semantic chunks (plain dicts for storage).

    ``source`` (P1): the file's decoded text when the caller already read it
    once for the physical-read ledger — avoids a second physical read.
    """
    try:
        if source is None:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return []

    lines = source.splitlines()
    rel_path = str(file_path.relative_to(root))
    chunks: list[dict[str, Any]] = []

    # --- module header chunk ---
    header_lines = lines[: min(20, len(lines))]
    header_body = "\n".join(header_lines)
    chunks.append({
        "id": _sha256_id(rel_path, "module"),
        "file_path": rel_path,
        "symbol_name": "(module)",
        "symbol_type": "module",
        "start_line": 1,
        "end_line": len(header_lines),
        "signature": "",
        "docstring": ast.get_docstring(tree),
        "body": header_body,
        "content": _truncate_for_embedding(
            rel_path, "module", "(module)", "", ast.get_docstring(tree), header_lines
        ),
        "content_hash": hashlib.sha256(header_body.encode()).hexdigest()[:16],
    })

    # --- top-level functions / classes ---
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno - 1
        end = node.end_lineno or start + 1
        chunk_lines = lines[start:end]

        if len(chunk_lines) > 50:
            display_body = "\n".join(
                chunk_lines[:40] + ["    ...", "    # (truncated) ..."] + chunk_lines[-5:]
            )
        else:
            display_body = "\n".join(chunk_lines)

        sig = chunk_lines[0].strip() if chunk_lines else ""
        doc = ast.get_docstring(node)
        symbol_type = "class" if isinstance(node, ast.ClassDef) else "function"

        if isinstance(node, ast.ClassDef):
            methods = [
                f"  def {c.name}(...)"
                for c in ast.iter_child_nodes(node)
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            body_for_emb = [sig] + methods[:5]
        else:
            body_for_emb = chunk_lines

        chunks.append({
            "id": _sha256_id(rel_path, node.name, str(start)),
            "file_path": rel_path,
            "symbol_name": node.name,
            "symbol_type": symbol_type,
            "start_line": start + 1,
            "end_line": end,
            "signature": sig,
            "docstring": doc,
            "body": display_body,
            "content": _truncate_for_embedding(
                rel_path, symbol_type, node.name, sig, doc, body_for_emb
            ),
            "content_hash": hashlib.sha256(display_body.encode()).hexdigest()[:16],
        })

    return chunks


def extract_source_chunks(
    file_path: Path, root: Path, source: str | None = None
) -> list[dict[str, Any]]:
    """Extension dispatch (D5): stdlib AST for Python — the richest path,
    already verified for async/decorators — tree-sitter for the JS/TS
    family. Unsupported suffixes extract to nothing (and are never yielded
    by _iter_source_files anyway). ``source`` (P1): decoded text when the
    caller already read the file once — never re-reads when provided."""
    if file_path.suffix.lower() == ".py":
        return extract_chunks(file_path, root, source)
    return extract_chunks_treesitter(file_path, root, source)


# ---------------------------------------------------------------------
# INDEX
# ---------------------------------------------------------------------


class ChunkIndex:
    """Persistent hybrid (vector + BM25) index for code chunks."""

    def __init__(
        self,
        workspace: str | Path,
        db_path: Optional[str] = None,
        embedder: Any = None,
        watch: bool = False,
    ):
        self.workspace = Path(workspace).resolve()
        if db_path is None:
            # Per-workspace DB: one shared DB would cross-contaminate
            # retrieval between unrelated projects.
            ws_hash = hashlib.sha256(str(self.workspace).encode()).hexdigest()[:12]
            db_path = os.path.join(
                os.path.expanduser("~"), ".pulseai", f"code_index_{ws_hash}.db"
            )
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # check_same_thread=False: first-run indexing happens on a background
        # thread; a default connection raises ProgrammingError when shared.
        # check_same_thread=False: first-run indexing happens on a background
        # thread; a default connection raises ProgrammingError when shared.
        # NOTE on locking: this is ONE shared connection object. "WAL allows
        # concurrent reads" applies across SEPARATE connections — not to
        # concurrent cursor use on the same connection. Therefore ALL access
        # (reads included) serializes through _write_lock. Correct by design;
        # the optimization (a dedicated read connection) is not worth it at
        # P0 scale.
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        # The dashboard AND a CLI session can hold the same per-workspace DB.
        # WAL serializes one writer + many readers but writer-writer still
        # raises SQLITE_BUSY immediately without a timeout — 5s is generous
        # for single-file sync transactions.
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._write_lock = threading.RLock()
        self._last_scan_report = None
        self._last_budget: ContextBudget | None = None
        self.thread_id_hint: str | None = None

        # File-watcher state (started only when watch=True, i.e. via
        # get_index() in production — tests construct with watch=False and
        # drive the queue helpers directly).
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()
        self._pending_syncs: set[str] = set()
        self._pending_removes: set[str] = set()
        self._sync_queue_lock = threading.Lock()

        if embedder is not None:
            self._embedder = embedder
        else:
            try:
                from src.llm.factory import get_embedder
                self._embedder = get_embedder()
            except Exception:
                self._embedder = None  # BM25-only degraded mode

        self.uses_vec = False
        try:
            import sqlite_vec
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self.uses_vec = True
        except Exception:
            self.uses_vec = False

        # Set before _init_schema(): the migration check inside flips this
        # True when it finds an old DB with chunks but no edge data.
        self._needs_edge_resync = False

        self._init_schema()

        if watch:
            self.start_watcher()

    # ------------------------------------------------------------------
    # SCHEMA
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._write_lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS code_chunks (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    symbol_name TEXT NOT NULL,
                    symbol_type TEXT NOT NULL,
                    start_line INTEGER,
                    end_line INTEGER,
                    signature TEXT,
                    docstring TEXT,
                    body TEXT,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    modified_time REAL NOT NULL
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON code_chunks(file_path)")

            # Standalone FTS5 (NOT external-content). Managed explicitly in
            # the same transactions as code_chunks — external-content + manual
            # inserts drift on re-index (verified lesson).
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                    content, file_path, symbol_name,
                    chunk_id UNINDEXED
                )
            """)

            if self.uses_vec:
                self.conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(
                        chunk_id TEXT PRIMARY KEY,
                        embedding FLOAT[{EMBED_DIM}]
                    )
                """)
            else:
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS chunk_vec_fallback (
                        chunk_id TEXT PRIMARY KEY,
                        embedding BLOB NOT NULL
                    )
                """)

            # v2: file->file import edges for the related-files section.
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS import_edges (
                    importer TEXT NOT NULL,
                    imported TEXT NOT NULL,
                    PRIMARY KEY (importer, imported)
                )
            """)
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_imported ON import_edges(imported)"
            )
            self.conn.commit()

        # Migration edge: an existing DB has chunks but no edges. One forced
        # re-sync rebuilds them; PRAGMA user_version marks it done so this
        # never loops. (Files with zero imports produce zero edge rows, so
        # "table empty" alone can NOT be the migration signal.)
        # v2 = Python edges (D15), v3 = multi-language edges (D15-remainder
        # §41): existing v2 DBs get ONE more full re-sync pick-up pass.
        if self.conn.execute("PRAGMA user_version").fetchone()[0] < 3:
            has_chunks = self.conn.execute(
                "SELECT 1 FROM code_chunks LIMIT 1"
            ).fetchone()
            self._needs_edge_resync = bool(has_chunks)
            self.conn.execute("PRAGMA user_version = 3")
            self.conn.commit()

    # ------------------------------------------------------------------
    # INDEXING
    # ------------------------------------------------------------------

    def index_workspace(self, budget: ContextBudget | None = None) -> None:
        """FULL REBUILD — explicit offline/maintenance only. Deletes every
        row first, so it is NOT resumable and NO product runtime path may
        invoke it automatically (empty-index search, the engine, the watcher
        and session startup all use the bounded incremental ``sync_workspace``
        instead). ``None`` means ``ContextBudget.unbounded()`` BY DESIGN:
        this is the one place a full delete+rebuild is legitimate, so it
        embeds everything synchronously — never an abandoned inference
        thread. Pass an explicit budget if you need a maintenance run bounded.
        """
        budget = budget if budget is not None else ContextBudget.unbounded()
        with self._write_lock:
            vec_table = "chunk_vec" if self.uses_vec else "chunk_vec_fallback"
            self.conn.execute(f"DELETE FROM {vec_table}")
            self.conn.execute("DELETE FROM code_chunks")
            self.conn.execute("DELETE FROM chunk_fts")
            self.conn.execute("DELETE FROM import_edges")
            self.conn.commit()

        files = self._iter_source_files(budget)
        # Batch commits: uncommitted inserts are invisible to other
        # connections and lost on close (verified). 25 files per batch.
        for i, fpath in enumerate(files):
            if budget.expired:
                break
            try:
                source = self._read_source(fpath, budget)
                if source is None:
                    continue
                chunks = extract_source_chunks(fpath, self.workspace, source)
                rel = str(fpath.relative_to(self.workspace))
                edges = self._edges_for(fpath, rel, budget, source)
                if chunks or edges:
                    with self._write_lock:
                        if chunks:
                            self._insert_chunks_no_commit(chunks, fpath.stat().st_mtime, budget)
                        # Full rebuild now inserts edges too — pre-D15-remainder
                        # it only DELETEed them, so freshly-indexed workspaces
                        # had detective mode empty until per-file syncs caught up
                        # (found by the §41 integration pin).
                        for target in edges:
                            self.conn.execute(
                                "INSERT OR IGNORE INTO import_edges (importer, imported) VALUES (?, ?)",
                                (rel, target),
                            )
            except Exception:
                continue
            if (i + 1) % 25 == 0:
                with self._write_lock:
                    self.conn.commit()
        with self._write_lock:
            self.conn.commit()
        self._emit_degraded_scan(budget)



    # ------------------------------------------------------------------
    # FILE WATCHER (optional, watchdog-backed with polling fallback)
    # ------------------------------------------------------------------
    #
    # Why both event-driven AND a cheap per-turn sync_workspace(): the
    # watcher batch-drains every ~2s, so a save→ask round-trip faster than
    # that would otherwise read stale chunks. The per-turn mtime sweep is
    # milliseconds; the watcher exists to catch edits made BETWEEN turns.

    _WATCH_BATCH_S = 2.0      # debounce window for queued events
    _WATCH_POLL_S = 15.0      # fallback sweep when watchdog isn't installed

    def start_watcher(self) -> None:
        """Start the background watcher thread (idempotent)."""
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            return
        self._watcher_stop.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="chunk-index-watcher"
        )
        self._watcher_thread.start()

    def stop_watcher(self) -> None:
        """Signal the watcher to stop and wait briefly. Daemon thread, so
        process exit also cleans up; this is for tests and clean shutdowns."""
        self._watcher_stop.set()
        if self._watcher_thread is not None:
            self._watcher_thread.join(timeout=5.0)
            self._watcher_thread = None

    def _enqueue_sync(self, path: str) -> None:
        with self._sync_queue_lock:
            self._pending_syncs.add(path)

    def _enqueue_remove(self, path: str) -> None:
        with self._sync_queue_lock:
            # A delete after a modify in the same debounce window: remove wins.
            self._pending_syncs.discard(path)
            self._pending_removes.add(path)

    def _drain_pending_syncs(self) -> tuple[list[str], list[str]]:
        """Atomically take the queued paths; returns (to_sync, to_remove)."""
        with self._sync_queue_lock:
            to_sync = list(self._pending_syncs)
            to_remove = list(self._pending_removes)
            self._pending_syncs.clear()
            self._pending_removes.clear()
        return to_sync, to_remove

    def _apply_queued_changes(self) -> None:
        to_sync, to_remove = self._drain_pending_syncs()
        # ONE bounded budget per debounce batch: watcher event handling must
        # enforce the per-file size cap and NEVER launch unbounded embedding
        # inference (bounded budget => text/FTS + cached vectors only).
        budget = ContextBudget()
        for path in to_remove:
            try:
                p = Path(path)
                if self.workspace in p.resolve().parents:
                    self.remove_file(p)
            except Exception as exc:
                print(f"[ChunkIndex] watcher remove failed for {path}: {exc}")
        for path in to_sync:
            try:
                p = Path(path)
                if p.exists() and self.workspace in p.resolve().parents:
                    self.sync_file(p, budget)
            except Exception as exc:
                print(f"[ChunkIndex] watcher sync failed for {path}: {exc}")

    def _watch_loop(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            # watchdog not installed: degrade to a periodic mtime sweep.
            # Same cost as the per-turn sync — a stat walk, no re-embedding
            # unless something actually changed.
            while not self._watcher_stop.wait(self._WATCH_POLL_S):
                try:
                    self.sync_workspace()
                except Exception as exc:
                    print(f"[ChunkIndex] watcher poll sync failed: {exc}")
            return

        index = self
        source_exts = tuple(source_extensions())  # snapshot once per loop

        def _is_source(path: str) -> bool:
            return path.lower().endswith(source_exts)

        class _SourceHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if not event.is_directory and _is_source(event.src_path):
                    index._enqueue_sync(event.src_path)

            def on_created(self, event):
                if not event.is_directory and _is_source(event.src_path):
                    index._enqueue_sync(event.src_path)

            def on_deleted(self, event):
                if not event.is_directory and _is_source(event.src_path):
                    index._enqueue_remove(event.src_path)

            def on_moved(self, event):
                if event.is_directory:
                    return
                if _is_source(event.src_path):
                    index._enqueue_remove(event.src_path)
                dest = getattr(event, "dest_path", "")
                if _is_source(dest):
                    index._enqueue_sync(dest)

        observer = Observer()
        observer.schedule(_SourceHandler(), str(self.workspace), recursive=True)
        try:
            observer.start()
        except Exception as exc:
            # Unsupported FS / perms: fall back to polling rather than dying.
            print(f"[ChunkIndex] watcher unavailable ({exc}); polling instead")
            while not self._watcher_stop.wait(self._WATCH_POLL_S):
                try:
                    self.sync_workspace()
                except Exception as poll_exc:
                    print(f"[ChunkIndex] watcher poll sync failed: {poll_exc}")
            return

        try:
            while not self._watcher_stop.wait(self._WATCH_BATCH_S):
                self._apply_queued_changes()
        finally:
            observer.stop()
            observer.join(timeout=5.0)

    # ------------------------------------------------------------------
    # INCREMENTAL SYNC
    # ------------------------------------------------------------------

    def remove_file(self, file_path: Path) -> int:
        """Drop all chunks AND import edges for a file. No-op if absent.

        Closes the deleted-file drift gap: before this, deleting a .py file
        left its chunks in the index (and FTS/BM25 kept retrieving ghosts).
        """
        rel = str(file_path.relative_to(self.workspace))
        vec_table = "chunk_vec" if self.uses_vec else "chunk_vec_fallback"
        with self._write_lock:
            with self.conn:  # single transaction for all stores
                old_ids = [r[0] for r in self.conn.execute(
                    "SELECT id FROM code_chunks WHERE file_path = ?", (rel,)
                )]
                for cid in old_ids:
                    self.conn.execute(f"DELETE FROM {vec_table} WHERE chunk_id = ?", (cid,))
                    self.conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (cid,))
                cur = self.conn.execute(
                    "DELETE FROM code_chunks WHERE file_path = ?", (rel,)
                )
                # Edges the deleted file OWNED vanish with it. Edges pointing
                # AT it are harmless (relations start from matched live files).
                self.conn.execute("DELETE FROM import_edges WHERE importer = ?", (rel,))
                return len(old_ids) if old_ids else cur.rowcount

    def _read_source(self, file_path: Path, budget: ContextBudget | None = None) -> str | None:
        """Read ONE source file through the shared physical-read ledger.

        Reserves the file's stat size atomically BEFORE reading, reads NO
        MORE than the reservation (a file that grew after stat() cannot bill
        past it), then settles the ACTUAL bytes read or refunds on failure.
        Returns None when the file vanished / is unreadable OR the global
        physical-read allowance is exhausted (the caller must decline, never
        read past the cap). ``budget.read_bytes`` is therefore the honest
        total of bytes ACTUALLY read.
        """
        from src.context.bounded_scan import bounded_read_text
        return bounded_read_text(file_path, budget)

    def sync_file(self, file_path: Path, budget: ContextBudget | None = None) -> None:
        """Atomic incremental re-index of one file (chunks, FTS, AND import
        edges — one transaction, so an interrupted sync never splits them).

        ``budget`` (P1): the shared initial-context deadline. ``None`` means
        the BOUNDED production default (a watcher event or a caller that
        forgot a budget must never read or embed without limits). When the
        budget expired the file is left for a later turn (no deletes, no
        embed), and the per-file size cap is enforced here so a watcher event
        for a giant file cannot read it whole. The file is read ONCE and the
        decoded text is reused for both chunk extraction and import-edge
        resolution — no avoidable second physical read.
        """
        budget = budget if budget is not None else ContextBudget()
        try:
            st = file_path.stat()
        except OSError:
            return  # disappeared / unreadable between scan and read
        mtime = st.st_mtime
        if budget.max_file_bytes > 0 and st.st_size > budget.max_file_bytes:
            return  # watcher/per-file size cap: skip, never read past it
        if budget.expired:
            return
        source = self._read_source(file_path, budget)
        if source is None:
            return  # unreadable OR the global read ledger is exhausted
        rel = str(file_path.relative_to(self.workspace))
        chunks = extract_source_chunks(file_path, self.workspace, source)
        edges = self._edges_for(file_path, rel, budget, source)
        vec_table = "chunk_vec" if self.uses_vec else "chunk_vec_fallback"
        with self._write_lock:
            with self.conn:  # single transaction for all five stores
                old_ids = [r[0] for r in self.conn.execute(
                    "SELECT id FROM code_chunks WHERE file_path = ?", (rel,)
                )]
                for cid in old_ids:
                    self.conn.execute(f"DELETE FROM {vec_table} WHERE chunk_id = ?", (cid,))
                    self.conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (cid,))
                self.conn.execute("DELETE FROM code_chunks WHERE file_path = ?", (rel,))
                self._insert_chunks_no_commit(chunks, mtime, budget)
                self.conn.execute("DELETE FROM import_edges WHERE importer = ?", (rel,))
                for target in edges:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO import_edges (importer, imported) VALUES (?, ?)",
                        (rel, target),
                    )

    def _edges_for(
        self,
        file_path: Path,
        rel: str,
        budget: ContextBudget | None = None,
        source: str | None = None,
    ) -> set[str]:
        """Resolved in-repo import targets of one source file (D15):
        Python via stdlib-ast resolver; JS/TS, Go, Rust, Java via the
        lang_extractors resolvers (§41). Empty set for unsupported or
        unparseable sources — edges are a bonus, never fatal.

        ``source`` (P1): the file's decoded text, passed by the caller that
        already read it once through the ledger — NO second physical read.
        """
        suffix = file_path.suffix.lower()
        if suffix == ".py":
            resolver = _extract_py_import_edges
        elif suffix in _EXT_JS_FAMILY_LANG:
            resolver = extract_js_import_edges
        elif suffix == ".go":
            resolver = extract_go_import_edges
        elif suffix == ".rs":
            resolver = extract_rust_import_edges
        elif suffix == ".java":
            resolver = extract_java_import_edges
        else:
            return set()
        if source is None:
            source = self._read_source(file_path, budget)
        if source is None:
            return set()
        try:
            return resolver(source, Path(rel), self.workspace)
        except Exception:
            return set()

    def sync_workspace(self, budget: ContextBudget | None = None) -> int:
        """Re-index files whose mtime is newer than what we stored. Returns count.

        ``budget`` (P1): the walk is bounded by the scan limits AND the same
        shared deadline is checked before each file's read/chunk/embed, so a
        huge or rapidly-changing workspace returns partial context instead of
        blocking the first model call. ``None`` means the BOUNDED production
        default (watcher poll, per-turn sync, tests): a background or
        automatic sync must never read or embed without limits.

        GHOST-PRUNING SAFETY: ``indexed - on_disk`` deletion only runs after a
        COMPLETE scan. When the scan was truncated, cancelled, or the deadline
        expired, ``on_disk`` is only a bounded prefix — anything outside it
        would be mistaken for a deleted file and wrongly pruned.
        """
        budget = budget if budget is not None else ContextBudget()
        # One lock for the whole sweep: concurrent sync_workspace() calls used
        # to race on the same files (wasteful duplicated delete+insert cycles;
        # RLock is reentrant so sync_file's internal acquire is free).
        with self._write_lock:
            # v2 migration: an upgraded DB with chunks but no edges gets ONE
            # full re-sync (every file) so detective mode works immediately —
            # then the flag clears and normal mtime behavior resumes.
            force_all = self._needs_edge_resync
            self._needs_edge_resync = False
            if force_all:
                print("[ChunkIndex] v2 upgrade: one-time import-edge rebuild start")
            changed = 0
            on_disk: set[str] = set()
            for fpath in self._iter_source_files(budget):
                if budget.expired:
                    break
                rel = str(fpath.relative_to(self.workspace))
                on_disk.add(rel)
                row = self.conn.execute(
                    "SELECT MAX(modified_time) FROM code_chunks WHERE file_path = ?", (rel,)
                ).fetchone()
                current = fpath.stat().st_mtime
                if force_all or not row or row[0] is None or row[0] < current:
                    self.sync_file(fpath, budget)
                    changed += 1
            if force_all:
                print("[ChunkIndex] v2 upgrade: import-edge rebuild done")
            report = getattr(self, "_last_scan_report", None)
            incomplete = (
                budget.expired
                or budget.cancelled
                or (report is not None and report.truncated)
            )
            if not incomplete:
                # Prune ghosts ONLY after a complete scan: the indexed-on_disk
                # diff is only sound when on_disk covers the whole tree.
                indexed = {
                    r[0] for r in self.conn.execute(
                        "SELECT DISTINCT file_path FROM code_chunks"
                    )
                }
                for ghost in indexed - on_disk:
                    changed += self.remove_file(self.workspace / ghost)
            # P1-fix: fold this walker's consumption back into the shared
            # pool so its other scans (and other walkers) see only remaining.
            if report is not None:
                budget.absorb(report)
            self._emit_degraded_scan(budget)
            return changed

    def _iter_source_files(self, budget: ContextBudget | None = None):
        """Generator — a 10K-file workspace shouldn't materialize a list.
        Extension allowlist is DYNAMIC: grammar packages that failed to
        load simply drop out (Python-only degraded mode), so a slim
        environment never walks files it cannot parse.

        The walk is BOUNDED (P1): elapsed / file-count / byte budgets, a
        per-file size cap, symlink skip, the exclusion set, and the root
        ``.gitignore``. ``budget`` supplies the limits AND the shared stop
        predicate, so traversal and the downstream read/chunk/embed pipeline
        expire together. Changes the scan order to deterministic priority so
        a truncated cold build indexes shallow non-test files before
        deep/bloat ones. The last report is kept on ``self._last_scan_report``;
        callers surface it as a ``runtime.degraded`` receipt when truncated.
        """
        budget = budget or ContextBudget()
        self._last_budget = budget
        exts = source_extensions()
        iterator, report = scan_files(
            self.workspace,
            limits=budget.to_limits(),
            skip_dirs=_SKIP_DIRS,
            extensions=exts,
            should_stop=budget.should_stop,
            priority=True,
        )
        self._last_scan_report = report
        return iterator

    def _emit_degraded_scan(self, budget: ContextBudget | None = None) -> None:
        """Surface a truncated index walk as a structured runtime.degraded
        receipt (real counts, emitted ONCE per shared budget).

        Inside an engine build (``collect_receipts``) the walker only RECORDS
        its component summary — the engine emits ONE aggregate build receipt
        afterwards. Standalone (watcher / background / tests) the walker
        emits its own receipt. Zero-value receipts are honest evidence of
        deadline exhaustion and are NEVER suppressed.
        """
        report = getattr(self, "_last_scan_report", None)
        if report is None or not report.truncated:
            return
        budget = budget or self._last_budget or ContextBudget()
        if getattr(budget, "collect_receipts", False):
            budget.record_component("chunk_index", report)
            return
        budget.emit_degraded({
            "thread_id": getattr(self, "thread_id_hint", None) or "unknown",
            "component": "chunk_index",
            "reason": "context scan bounded",
            "error": f"context index scan {report.summarize()}",
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

    def _insert_chunks(self, chunks: list[dict], mtime: float, commit: bool) -> None:
        with self._write_lock:
            self._insert_chunks_no_commit(chunks, mtime)
            if commit:
                self.conn.commit()

    def _insert_chunks_no_commit(
        self, chunks: list[dict], mtime: float, budget: ContextBudget | None = None
    ) -> None:
        """Insert chunks into all stores. Caller holds the lock / transaction.

        ``budget`` (P1): the synchronous initial-turn path NEVER launches
        uncancellable model inference. Text and FTS land synchronously for
        every chunk; VECTORS come only from the content-addressed cache
        (cache hits are bounded lookups) and uncached embeddings are DEFERRED
        — a later sync backfills them. ``None`` means the BOUNDED production
        default (cache-only), so a caller that forgets a budget can never
        launch inference. ONLY an explicit ``ContextBudget.unbounded()``
        (offline full rebuild) encodes synchronously, exactly like the
        pre-P1 behavior.
        """
        budget = budget if budget is not None else ContextBudget()
        if budget.expired:
            embeddings: list[list[float] | None] = [None] * len(chunks)
        elif self._embedder is not None and budget.max_elapsed <= 0:
            # Explicit unbounded path (offline full rebuild): synchronous
            # encode — never an abandoned thread.
            from src.context.embedding_cache import get_embedding_cache
            try:
                vecs = get_embedding_cache().encode(
                    self._embedder, [c["content"] for c in chunks]
                )
                embeddings = [list(v) for v in vecs]
            except Exception:
                embeddings = [None] * len(chunks)
        elif self._embedder is not None:
            # Deadline path: cache hits ONLY — no inference inside the turn.
            from src.context.embedding_cache import get_embedding_cache
            cache = get_embedding_cache()
            embeddings = [
                cache.lookup(self._embedder, c["content"]) for c in chunks
            ]
        else:
            embeddings = [None] * len(chunks)  # BM25-only degraded mode
        vec_table_insert = (
            "INSERT INTO chunk_vec (chunk_id, embedding) VALUES (?, vec_f32(?))"
            if self.uses_vec else
            "INSERT INTO chunk_vec_fallback (chunk_id, embedding) VALUES (?, ?)"
        )
        for chunk, emb in zip(chunks, embeddings):
            self.conn.execute("""
                INSERT INTO code_chunks
                (id, file_path, symbol_name, symbol_type, start_line, end_line,
                 signature, docstring, body, content, content_hash, modified_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chunk["id"], chunk["file_path"], chunk["symbol_name"],
                chunk["symbol_type"], chunk["start_line"], chunk["end_line"],
                chunk["signature"], chunk["docstring"], chunk["body"],
                chunk["content"], chunk["content_hash"], mtime,
            ))
            if emb is not None:
                if self.uses_vec:
                    self.conn.execute(vec_table_insert, (chunk["id"], json.dumps(emb)))
                else:
                    self.conn.execute(vec_table_insert, (chunk["id"], json.dumps(emb).encode("utf-8")))
            self.conn.execute(
                "INSERT INTO chunk_fts (content, file_path, symbol_name, chunk_id) VALUES (?, ?, ?, ?)",
                (chunk["content"], chunk["file_path"], chunk["symbol_name"], chunk["id"]),
            )

    # ------------------------------------------------------------------
    # RETRIEVAL
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 3) -> list[ChunkResult]:
        """Hybrid search: KNN vector + BM25, fused via RRF (rank positions),
        then D13 feature re-rank (name/path/hot/test signals) before top_k.
        top_k defaults to 3 so the layer can't eat the context budget."""
        if self._is_index_empty():
            # Automatic unlimited full-index is DISABLED (it recreated the
            # runaway daemon build): an empty index returns [] and the caller
            # falls back to repo_map. The bounded per-turn sync_workspace()
            # populates a text/FTS + cached-vector prefix instead.
            return []

        vec = self._search_vector(query, top_k * 3)
        bm25 = self._search_bm25(query, top_k * 3)
        fused = self._rrf_fuse(vec, bm25, k=RRF_K)
        return self._rerank(fused, query)[:top_k]

    # ------------------------------------------------------------------
    # RE-RANK (D13 — see the feature table at module level)
    # ------------------------------------------------------------------

    def _rerank(self, results: list[ChunkResult], query: str) -> list[ChunkResult]:
        """Feature re-rank over the fused set. Invariants, all pinned:

        - zero LLM calls, zero embedder calls (arithmetic on fetched fields);
        - normalized RRF score stays the base — features nudge, they do not
          replace retrieval;
        - Python's sort is STABLE, so a zero-feature query yields
          byte-identical order to pre-D13;
        - deterministic given (query, index contents, mtimes).
        """
        if len(results) <= 1 or not query:
            return results

        qtext = query.lower()
        qwords = {w for w in _word_parts(query) if len(w) >= _RERANK_MIN_WORD}
        test_query = bool(qwords & _RERANK_TESTISH)

        mtimes = [r.modified_time for r in results]
        max_mtime = max(mtimes)
        has_hot = len(set(mtimes)) > 1

        max_score = max((r.score for r in results), default=0.0)

        def _bonus(r: ChunkResult) -> float:
            b = 0.0
            name = r.symbol_name
            if name and name != "(module)":
                if name.lower() in qtext:
                    b += _RERANK_W["name_exact"]
                else:
                    overlap = (qwords & _word_parts(name)) if qwords else set()
                    b += _RERANK_W["name_part"] * min(len(overlap), _RERANK_NAME_PART_CAP)
            stem = Path(r.file_path).stem
            if qwords and stem:
                if qwords & _word_parts(stem):
                    b += _RERANK_W["path_token"]
            if has_hot and r.modified_time == max_mtime:
                b += _RERANK_W["hot"]
            if _is_test_path(r.file_path) and not test_query:
                b += _RERANK_W["test_demote"]
            if r.docstring:
                b += _RERANK_W["docstring"]
            return b

        scored = [
            ((r.score / max_score if max_score > 0 else 0.0) + _bonus(r), r)
            for r in results
        ]
        scored.sort(key=lambda t: t[0], reverse=True)  # stable: ties keep RRF order
        return [r for _s, r in scored]

    def _is_index_empty(self) -> bool:
        with self._write_lock:
            row = self.conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()
        return not row or row[0] == 0

    def _search_vector(self, query: str, limit: int) -> list[tuple[str, float]]:
        if not self._embedder:
            return []
        try:
            q_emb = self._embedder.encode([query], normalize_embeddings=True).tolist()[0]
        except Exception:
            return []
        if self.uses_vec:
            return self._search_vec_fast(q_emb, limit)
        return self._search_vec_linear(q_emb, limit)

    def _search_vec_fast(self, q_emb: list[float], limit: int) -> list[tuple[str, float]]:
        """C1 (fixed §36): native vec0 KNN — the embedding MATCH + k constraint
        pushes the nearest-neighbor search INTO the extension, so only the
        k winners are computed. The pre-C1 shape (vec_distance_l2 over every
        row + a JOIN that only selected back the same id) ran a full O(N)
        distance pass per search: measured 21->1.5ms at 2K rows, 206->17ms
        at 20K rows (12-14x; scripts/c1_knn_benchmark.py), with byte-identical
        orderings on real embeddings.

        - The returned hidden `distance` column IS vec_distance_l2 for FLOAT
          vectors (sqlite-vec v0.1.9), so the cosine conversion below is the
          same math — vectors are unit-normalized, cosine = 1 - L2²/2 EXACTLY
          (no max-distance math — that divides by zero on exact matches).
        - No JOIN to code_chunks here: v.chunk_id IS the id, and _rrf_fuse
          re-fetches chunk rows afterwards (tolerating any missing id).
        - The lock is intentional even for reads — see the shared-connection
          note in __init__.
        """
        with self._write_lock:
            try:
                rows = self.conn.execute(_VEC0_KNN_SQL, (json.dumps(q_emb), limit)).fetchall()
            except Exception as e:
                # Ancient sqlite-vec without the k constraint (pre-v0.1.2):
                # degrade to the pre-C1 full-scan shape rather than to nothing.
                print(f"[ChunkIndex] vec0 KNN query failed ({e}); full-scan fallback")
                try:
                    rows = self.conn.execute(_VEC0_FULLSCAN_SQL, (json.dumps(q_emb), limit)).fetchall()
                except Exception as e2:
                    print(f"[ChunkIndex] sqlite-vec query failed: {e2}")
                    return []
        return [(cid, max(0.0, 1.0 - (d * d) / 2.0)) for cid, d in rows]

    def _search_vec_linear(self, q_emb: list[float], limit: int) -> list[tuple[str, float]]:
        with self._write_lock:
            rows = self.conn.execute(
                "SELECT chunk_id, embedding FROM chunk_vec_fallback"
            ).fetchall()
        scored: list[tuple[float, str]] = []
        for cid, blob in rows:
            try:
                emb = json.loads(blob.decode("utf-8"))
                sim = sum(a * b for a, b in zip(q_emb, emb))
                scored.append((sim, cid))
            except Exception:
                continue
        scored.sort(reverse=True)
        # (sim + 1) / 2 maps cosine [-1, 1] -> [0, 1]; ordering unchanged.
        return [(cid, (sim + 1.0) / 2.0) for sim, cid in scored[:limit]]

    def _search_bm25(self, query: str, limit: int) -> list[tuple[str, float]]:
        # Raw task text is not valid FTS5 syntax (parens, colons, AND/OR...).
        # Tokenize to words and OR-join them as quoted phrases — this can
        # never produce a syntax error, so the except is truly exceptional.
        tokens = re.findall(r"\w+", query.lower())[:FTS_MAX_TOKENS_PER_QUERY]
        if not tokens:
            return []
        safe_query = " OR ".join(f'"{t}"' for t in tokens)
        with self._write_lock:
            try:
                rows = self.conn.execute("""
                    SELECT chunk_id FROM chunk_fts
                    WHERE chunk_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (safe_query, limit)).fetchall()
            except Exception:
                return []
        # Return rank POSITIONS (0, 1, 2...); raw `rank` values are not
        # comparable to vector distances, so RRF consumes positions only.
        return [(r[0], float(i)) for i, r in enumerate(rows)]

    def _rrf_fuse(
        self,
        vec_results: list[tuple[str, float]],
        bm25_results: list[tuple[str, float]],
        k: int = RRF_K,
    ) -> list[ChunkResult]:
        """Reciprocal Rank Fusion on list POSITIONS, not raw scores."""
        scores: dict[str, float] = {}
        for rank, (cid, _score) in enumerate(vec_results):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        for rank, (cid, _score) in enumerate(bm25_results):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        if not scores:
            return []

        ordered_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        placeholders = ",".join("?" * len(ordered_ids))
        with self._write_lock:  # shared connection: all access serialized
            rows = self.conn.execute(
                f"SELECT id, file_path, symbol_name, symbol_type, start_line, end_line,"
                f" signature, docstring, body, modified_time FROM code_chunks"
                f" WHERE id IN ({placeholders})",
                ordered_ids,
            ).fetchall()
        by_id = {r[0]: r for r in rows}

        results: list[ChunkResult] = []
        for cid in ordered_ids:
            row = by_id.get(cid)
            if not row:
                continue
            results.append(ChunkResult(
                id=row[0], file_path=row[1], symbol_name=row[2],
                symbol_type=row[3], start_line=row[4], end_line=row[5],
                signature=row[6] or "", docstring=row[7],
                body=row[8] or "", score=scores[cid],
                modified_time=row[9] or 0.0,
            ))
        return results

    # ------------------------------------------------------------------
    # NEIGHBORS (surrounding-chunk context window)
    # ------------------------------------------------------------------

    def get_neighbors(self, chunk_id: str, radius: int = 3) -> list[ChunkResult]:
        with self._write_lock:
            row = self.conn.execute(
                "SELECT file_path, start_line FROM code_chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
            if not row:
                return []
            file_path, center = row[0], row[1]
            rows = self.conn.execute("""
                SELECT id, file_path, symbol_name, symbol_type, start_line, end_line,
                       signature, docstring, body
                FROM code_chunks
                WHERE file_path = ? AND start_line BETWEEN ? AND ?
                ORDER BY start_line
            """, (file_path, center - radius * 5, center + radius * 5)).fetchall()
        return [
            ChunkResult(
                id=r[0], file_path=r[1], symbol_name=r[2], symbol_type=r[3],
                start_line=r[4], end_line=r[5], signature=r[6] or "",
                docstring=r[7], body=r[8] or "", score=0.0,
            )
            for r in rows
        ]


# ---------------------------------------------------------------------
# PROCESS-WIDE INDEX ACCESS
# ---------------------------------------------------------------------


def get_index(
    workspace: str | Path,
    db_path: Optional[str] = None,
    watch: bool = True,
) -> ChunkIndex:
    """One ChunkIndex per workspace, process-wide. New DB only on first use.

    watch=True (production default) starts the background file watcher so
    edits made between turns are re-indexed within ~2s (or on the next poll
    sweep if watchdog isn't installed). Tests pass watch=False.
    """
    key = str(Path(workspace).resolve())
    with _INDEX_CACHE_LOCK:
        idx = _INDEX_CACHE.get(key)
        if idx is None:
            idx = ChunkIndex(key, db_path=db_path, watch=watch)
            _INDEX_CACHE[key] = idx
        elif watch:
            idx.start_watcher()  # idempotent — a daemon thread
        return idx


# ---------------------------------------------------------------------
# CONTEXT ENGINE LAYER BUILDER
# ---------------------------------------------------------------------


def build_relevant_chunks_layer(state: dict[str, Any], budget: ContextBudget | None = None) -> Any:
    """ContextEngine layer: top-k code chunks relevant to the current task.

    ``budget`` (P1): one shared deadline for the whole initial context build.
    The index sync (scan → read → chunk → embed) stops when it expires and
    emits a structured ``runtime.degraded`` receipt; the turn continues on
    partial context.
    """
    task = state.get("current_task", "")
    if not task:
        return None

    from langchain_core.messages import SystemMessage

    try:
        index = get_index(state.get("workspace", "."))
        index.thread_id_hint = str(state.get("thread_id") or state.get("session_id") or "")
        # Cheap: bounded walk + stat only; re-indexes only changed files.
        index.sync_workspace(budget)
        chunks = index.search(task, top_k=3)
        if not chunks:
            return None
    except Exception as exc:
        # Never silent (same rule as the engine's builder loop): an import
        # error or sqlite-vec crash here must not invisibly downgrade the
        # agent to repo_map-only retrieval for the whole session.
        print(f"[ChunkIndex] relevant_chunks layer failed: {exc}")
        return None

    # Markdown fence language by extension (D5: no more ```python on JS).
    _FENCE_TAGS = {
        ".py": "python",
        ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript", ".cts": "typescript", ".mts": "typescript",
        ".tsx": "tsx",
        ".go": "go", ".rs": "rust", ".java": "java",
    }

    lines = ["=== RELEVANT CODE CHUNKS ==="]
    lines.append("Use these before reading entire files.\n")
    used_files: set[str] = set()
    for chunk in chunks:
        # Cap at 2 distinct files so the layer can't flood the budget.
        if chunk.file_path not in used_files and len(used_files) >= 2:
            continue
        used_files.add(chunk.file_path)
        doc = (chunk.docstring or "").split("\n")[0][:120]
        body = chunk.body[:BODY_HARD_CAP_CHARS]
        fence = _FENCE_TAGS.get(Path(chunk.file_path).suffix.lower(), "")
        lines.append(
            f"--- {chunk.file_path}:{chunk.start_line}-{chunk.end_line} | {chunk.symbol_name} ---"
        )
        if doc:
            lines.append(f"# {doc}")
        lines.append(f"```{fence}\n{body}\n```")
        lines.append("")

    related = _related_files_lines(index, used_files)
    if related:
        lines.extend(related)
    return SystemMessage(content="\n".join(lines))


_MAX_RELATED_FILES = 4        # total neighbor lines, both directions combined
_MAX_RELATED_SYMBOLS = 3      # symbol names listed per neighbor file


def _related_files_lines(index: "ChunkIndex", used_files: set[str]) -> list[str]:
    """Detective mode: import-linked neighbors of the matched files.

    - dependents ("X imports the matched file") are the break-warning:
      edits to the chunks above may BREAK them — listed first;
    - dependencies ("the matched file imports Y") show what the code
      relies on.

    Edges live in the same transactions as chunk rows, so this can never
    describe code that has since changed. Hard-capped; never fatal.
    """
    if not used_files:
        return []
    try:
        with index._write_lock:
            used = sorted(used_files)
            dep_pairs: list[tuple[str, str]] = []     # (neighbor, matched_file)
            depnd_pairs: list[tuple[str, str]] = []   # (neighbor, matched_file)
            for f in used:
                depnd_pairs.extend(
                    (r[0], f) for r in index.conn.execute(
                        "SELECT importer FROM import_edges WHERE imported = ? ORDER BY importer",
                        (f,),
                    )
                )
                dep_pairs.extend(
                    (r[0], f) for r in index.conn.execute(
                        "SELECT imported FROM import_edges WHERE importer = ? ORDER BY imported",
                        (f,),
                    )
                )

            seen: set[str] = set()
            ordered: list[tuple[str, str, bool]] = []  # (neighbor, matched, is_dependent)
            candidates = (
                [(n, m, True) for n, m in depnd_pairs]
                + [(n, m, False) for n, m in dep_pairs]
            )  # dependents first: the break-warning outranks the relies-on note
            for neighbor, matched, is_dependent in candidates:
                if neighbor in used_files or neighbor in seen:
                    continue
                seen.add(neighbor)
                ordered.append((neighbor, matched, is_dependent))
                if len(ordered) >= _MAX_RELATED_FILES:
                    break
            if not ordered:
                return []

            lines = ["=== RELATED FILES (import links) ==="]
            for neighbor, matched, is_dependent in ordered:
                symbols = [
                    r[0] for r in index.conn.execute(
                        """SELECT symbol_name FROM code_chunks
                           WHERE file_path = ? AND symbol_type IN ('function','class')
                                 AND symbol_name != '(module)'
                           ORDER BY start_line LIMIT ?""",
                        (neighbor, _MAX_RELATED_SYMBOLS),
                    )
                ]
                tail = f" | symbols: {', '.join(symbols)}" if symbols else ""
                if is_dependent:
                    lines.append(f"- {neighbor} imports {matched} — edits above may BREAK this file{tail}")
                else:
                    lines.append(f"- {neighbor} imported by {matched} — the matched code relies on it{tail}")
            return lines
    except Exception as exc:
        # Same loud rule as the layer itself: never an invisible downgrade.
        print(f"[ChunkIndex] related-files lookup failed: {exc}")
        return []

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
- import_edges (schema user_version=2): file->file import graph powering the
  "related files" section of the context layer ("detective mode"). Python-
  only, stdlib-ast, full dotted-path resolution to workspace files (the
  repo_map graph's first-segment module names can't produce file->file
  edges — verified). Rows live/die in the SAME transactions as chunk
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

from src.context.lang_extractors import (
    _sha256_id,
    _truncate_for_embedding,
    extract_chunks_treesitter,
    source_extensions,
)

EMBED_DIM = 384  # all-MiniLM-L6-v2 output size
RRF_K = 60
BODY_HARD_CAP_CHARS = 800       # per-chunk cap for LLM context
FTS_MAX_TOKENS_PER_QUERY = 12

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
    importer_str = str(importer_rel)
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
            rel_str = str(cand)
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


# ---------------------------------------------------------------------
# CHUNK EXTRACTION (Python AST — stdlib; JS/TS via tree-sitter in
# lang_extractors — D5 multi-language milestone 1)
# ---------------------------------------------------------------------


def extract_chunks(file_path: Path, root: Path) -> list[dict[str, Any]]:
    """Parse a Python file into semantic chunks (plain dicts for storage)."""
    try:
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


def extract_source_chunks(file_path: Path, root: Path) -> list[dict[str, Any]]:
    """Extension dispatch (D5): stdlib AST for Python — the richest path,
    already verified for async/decorators — tree-sitter for the JS/TS
    family. Unsupported suffixes extract to nothing (and are never yielded
    by _iter_source_files anyway)."""
    if file_path.suffix.lower() == ".py":
        return extract_chunks(file_path, root)
    return extract_chunks_treesitter(file_path, root)


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
        self._indexing_thread: Optional[threading.Thread] = None

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
        if self.conn.execute("PRAGMA user_version").fetchone()[0] < 2:
            has_chunks = self.conn.execute(
                "SELECT 1 FROM code_chunks LIMIT 1"
            ).fetchone()
            self._needs_edge_resync = bool(has_chunks)
            self.conn.execute("PRAGMA user_version = 2")
            self.conn.commit()

    # ------------------------------------------------------------------
    # INDEXING
    # ------------------------------------------------------------------

    def index_workspace(self) -> None:
        """Full rebuild. Blocking; used by the background thread on first run."""
        with self._write_lock:
            vec_table = "chunk_vec" if self.uses_vec else "chunk_vec_fallback"
            self.conn.execute(f"DELETE FROM {vec_table}")
            self.conn.execute("DELETE FROM code_chunks")
            self.conn.execute("DELETE FROM chunk_fts")
            self.conn.execute("DELETE FROM import_edges")
            self.conn.commit()

        files = self._iter_source_files()
        # Batch commits: uncommitted inserts are invisible to other
        # connections and lost on close (verified). 25 files per batch.
        for i, fpath in enumerate(files):
            try:
                chunks = extract_source_chunks(fpath, self.workspace)
                if chunks:
                    self._insert_chunks(chunks, fpath.stat().st_mtime, commit=False)
            except Exception:
                continue
            if (i + 1) % 25 == 0:
                with self._write_lock:
                    self.conn.commit()
        with self._write_lock:
            self.conn.commit()

    def _trigger_background_index(self) -> None:
        """Non-blocking first-run index; search() returns [] while it builds."""
        if self._indexing_thread and self._indexing_thread.is_alive():
            return
        t = threading.Thread(target=self.index_workspace, daemon=True)
        self._indexing_thread = t
        t.start()

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
                    self.sync_file(p)
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

    def sync_file(self, file_path: Path) -> None:
        """Atomic incremental re-index of one file (chunks, FTS, AND import
        edges — one transaction, so an interrupted sync never splits them)."""
        rel = str(file_path.relative_to(self.workspace))
        mtime = file_path.stat().st_mtime
        chunks = extract_source_chunks(file_path, self.workspace)
        edges = self._edges_for(file_path, rel)
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
                self._insert_chunks_no_commit(chunks, mtime)
                self.conn.execute("DELETE FROM import_edges WHERE importer = ?", (rel,))
                for target in edges:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO import_edges (importer, imported) VALUES (?, ?)",
                        (rel, target),
                    )

    def _edges_for(self, file_path: Path, rel: str) -> set[str]:
        """Resolved in-repo import targets of one Python file (empty set for
        non-Python or unparseable sources — edges are a bonus, never fatal)."""
        if file_path.suffix.lower() != ".py":
            return set()
        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return set()
        return _extract_py_import_edges(source, Path(rel), self.workspace)

    def sync_workspace(self) -> int:
        """Re-index files whose mtime is newer than what we stored. Returns count."""
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
            for fpath in self._iter_source_files():
                rel = str(fpath.relative_to(self.workspace))
                on_disk.add(rel)
                row = self.conn.execute(
                    "SELECT MAX(modified_time) FROM code_chunks WHERE file_path = ?", (rel,)
                ).fetchone()
                current = fpath.stat().st_mtime
                if force_all or not row or row[0] is None or row[0] < current:
                    self.sync_file(fpath)
                    changed += 1
            if force_all:
                print("[ChunkIndex] v2 upgrade: import-edge rebuild done")
            # Prune ghosts: chunks whose source file no longer exists.
            # One DISTINCT scan + set diff — cheap, and it makes deletions
            # visible even when the watcher missed them (or isn't installed).
            indexed = {
                r[0] for r in self.conn.execute(
                    "SELECT DISTINCT file_path FROM code_chunks"
                )
            }
            for ghost in indexed - on_disk:
                changed += self.remove_file(self.workspace / ghost)
            return changed

    def _iter_source_files(self):
        """Generator — a 10K-file workspace shouldn't materialize a list.
        Extension allowlist is DYNAMIC: grammar packages that failed to
        load simply drop out (Python-only degraded mode), so a slim
        environment never walks files it cannot parse."""
        exts = source_extensions()
        for f in self.workspace.rglob("*"):
            if f.suffix.lower() not in exts:
                continue
            if not any(part in _SKIP_DIRS for part in f.parts):
                yield f

    def _insert_chunks(self, chunks: list[dict], mtime: float, commit: bool) -> None:
        with self._write_lock:
            self._insert_chunks_no_commit(chunks, mtime)
            if commit:
                self.conn.commit()

    def _insert_chunks_no_commit(self, chunks: list[dict], mtime: float) -> None:
        """Insert chunks into all stores. Caller holds the lock / transaction."""
        embeddings = self._embed_batch([c["content"] for c in chunks])
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
            if self.uses_vec:
                self.conn.execute(vec_table_insert, (chunk["id"], json.dumps(emb)))
            else:
                self.conn.execute(vec_table_insert, (chunk["id"], json.dumps(emb).encode("utf-8")))
            self.conn.execute(
                "INSERT INTO chunk_fts (content, file_path, symbol_name, chunk_id) VALUES (?, ?, ?, ?)",
                (chunk["content"], chunk["file_path"], chunk["symbol_name"], chunk["id"]),
            )

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """One encode call per file (not per chunk) — batching is ~10x faster."""
        if not self._embedder:
            return [[0.0] * EMBED_DIM for _ in texts]
        try:
            # D2+D5 synergy: re-syncing an edited file re-embeds ALL its
            # chunks, but only the edited ones have new content — the
            # content-addressed cache returns the rest for free.
            from src.context.embedding_cache import get_embedding_cache
            return get_embedding_cache().encode(self._embedder, texts)
        except Exception:
            return [[0.0] * EMBED_DIM for _ in texts]

    # ------------------------------------------------------------------
    # RETRIEVAL
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 3) -> list[ChunkResult]:
        """Hybrid search: KNN vector + BM25, fused via RRF (rank positions).
        top_k defaults to 3 so the layer can't eat the context budget."""
        if self._is_index_empty():
            self._trigger_background_index()
            return []  # caller falls back to repo_map while we build

        vec = self._search_vector(query, top_k * 3)
        bm25 = self._search_bm25(query, top_k * 3)
        return self._rrf_fuse(vec, bm25, k=RRF_K)[:top_k]

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
        """vec_distance_l2 verified on sqlite-vec v0.1.9. Vectors are unit-
        normalized, so cosine = 1 - L2²/2 EXACTLY (no max-distance math —
        that divides by zero on exact matches). The lock is intentional even
        for reads — see the shared-connection note in __init__."""
        with self._write_lock:
            try:
                rows = self.conn.execute("""
                    SELECT c.id, vec_distance_l2(v.embedding, vec_f32(?)) AS distance
                    FROM chunk_vec v
                    JOIN code_chunks c ON v.chunk_id = c.id
                    ORDER BY distance
                    LIMIT ?
                """, (json.dumps(q_emb), limit)).fetchall()
            except Exception as e:
                print(f"[ChunkIndex] sqlite-vec query failed: {e}")
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
                f" signature, docstring, body FROM code_chunks WHERE id IN ({placeholders})",
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


def build_relevant_chunks_layer(state: dict[str, Any]) -> Any:
    """ContextEngine layer: top-k code chunks relevant to the current task."""
    task = state.get("current_task", "")
    if not task:
        return None

    from langchain_core.messages import SystemMessage

    try:
        index = get_index(state.get("workspace", "."))
        # Cheap: rglob + stat only; re-indexes only files whose mtime changed.
        index.sync_workspace()
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

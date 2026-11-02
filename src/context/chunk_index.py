"""
Chunk Index — P0 (verified build)
=================================

Chunk-level code retrieval for CrusorAI: per-symbol chunks (module/function/class),
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
BODY_HARD_CAP_CHARS = 800       # per-chunk cap for LLM context

# ---------------------------------------------------------------------
# RRF Fusion — extracted to src.context.retrieval.fusion
# ---------------------------------------------------------------------
from src.context.retrieval.fusion import (
    DEFAULT_RRF_K,
    RRF_K,
    compute_rrf_scores,
    fuse_rankings,
    hydrate_chunk_results,
    reciprocal_rank_fusion,
    rrf_score,
)
# ---------------------------------------------------------------------
# Storage & schema — extracted to src.context.indexing.index_storage
# ---------------------------------------------------------------------
from src.context.indexing.index_storage import (
    IndexStorage,
    get_neighbors as _storage_get_neighbors,
    init_schema as _storage_init_schema,
    insert_chunks as _storage_insert_chunks,
    insert_chunks_no_commit as _storage_insert_chunks_no_commit,
    is_index_empty as _storage_is_index_empty,
    open_database as _storage_open_database,
    remove_file as _storage_remove_file,
)
# ---------------------------------------------------------------------
# Keyword search — extracted to src.context.retrieval.keyword_search
# ---------------------------------------------------------------------
from src.context.retrieval.keyword_search import (
    DEFAULT_FTS_MAX_TOKENS,
    FTS_MAX_TOKENS_PER_QUERY,
    FTS_SEARCH_SQL,
    sanitize_fts_query,
    search_bm25,
)

# ---------------------------------------------------------------------
# D13 (§37): feature re-rank over the fused candidate set
# ---------------------------------------------------------------------
# Extracted to src.context.retrieval.reranker; re-exported for backward compatibility.
from src.context.retrieval.reranker import (
    _RERANK_MIN_WORD,
    _RERANK_NAME_PART_CAP,
    _RERANK_TESTISH,
    _RERANK_W,
    _is_test_path,
    _word_parts,
    rerank_chunks,
)

# ---------------------------------------------------------------------
# Vector search SQL & functions — extracted to src.context.retrieval.vector_search
# ---------------------------------------------------------------------
from src.context.retrieval.vector_search import (
    _VEC0_FULLSCAN_SQL,
    _VEC0_KNN_SQL,
    VEC0_FULLSCAN_SQL,
    VEC0_KNN_SQL,
    search_vec_fast,
    search_vec_linear,
    search_vector,
)

_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".tox", ".idea", ".vscode", "generated",
}


# ---------------------------------------------------------------------
# IMPORT EDGES (v2 — "detective mode")
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Python AST Import Extraction — extracted to src.context.extraction.python_extractor
# ---------------------------------------------------------------------
from src.context.extraction.python_extractor import (
    _extract_py_import_edges,
    extract_py_import_edges,
)


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


# ---------------------------------------------------------------------
# Python AST Chunk Extraction — extracted to src.context.extraction.python_extractor
# ---------------------------------------------------------------------
from src.context.extraction.python_extractor import (
    extract_chunks,
    extract_chunks_python,
)


# ---------------------------------------------------------------------
# Multi-Language Source Dispatch — extracted to src.context.extraction.language_registry
# ---------------------------------------------------------------------
from src.context.extraction.language_registry import extract_source_chunks


# ---------------------------------------------------------------------
# INDEX
# ---------------------------------------------------------------------


_LAZY_DEFAULT_EMBEDDER = object()


class ChunkIndex:
    """Persistent hybrid (vector + BM25) index for code chunks."""

    def __init__(
        self,
        workspace: str | Path,
        db_path: Optional[str] = None,
        embedder: Any = _LAZY_DEFAULT_EMBEDDER,
        watch: bool = False,
    ):
        self.workspace = Path(workspace).resolve()
        if db_path is None:
            # Per-workspace DB: one shared DB would cross-contaminate
            # retrieval between unrelated projects.
            ws_hash = hashlib.sha256(str(self.workspace).encode()).hexdigest()[:12]
            db_path = os.path.join(
                os.path.expanduser("~"), ".crusorai", f"code_index_{ws_hash}.db"
            )
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self.storage = IndexStorage(self.db_path, embed_dim=EMBED_DIM)
        self.conn = self.storage.conn
        self._write_lock = self.storage._write_lock
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

        # NO eager model load: opening an index during a prompt must not load
        # the embedding model. Omitted means the production lazy default;
        # explicit None means BM25-only. The old API collapsed both to None,
        # so offline tests that deliberately disabled embeddings unexpectedly
        # attempted a Hugging Face download and looked deadlocked while TLS
        # retries backed off. Preserve that caller intent explicitly.
        self._lazy_default_embedder = embedder is _LAZY_DEFAULT_EMBEDDER
        self._embedder = None if self._lazy_default_embedder else embedder

        if watch:
            self.start_watcher()

    def _ensure_embedder(self) -> None:
        """Lazily resolve the default embedder — called ONLY from explicit
        offline inference-enabled paths (``allow_embedding_compute``), never
        from the timed turn path. ``self._embedder`` stays None for turns,
        which is exactly the point: no model is loaded or invoked."""
        if self._embedder is not None or not self._lazy_default_embedder:
            return
        try:
            from src.llm.factory import get_embedder
            self._embedder = get_embedder()
        except Exception:
            self._embedder = None  # BM25-only degraded mode

    # ------------------------------------------------------------------
    # SCHEMA
    # ------------------------------------------------------------------

    @property
    def uses_vec(self) -> bool:
        return self.storage.uses_vec

    @uses_vec.setter
    def uses_vec(self, val: bool) -> None:
        self.storage.uses_vec = val

    @property
    def _needs_edge_resync(self) -> bool:
        return self.storage._needs_edge_resync

    @_needs_edge_resync.setter
    def _needs_edge_resync(self, val: bool) -> None:
        self.storage._needs_edge_resync = val
    def _init_schema(self) -> None:
        self.storage.init_schema()

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
        """Drop all chunks AND import edges for a file. No-op if absent. Delegated to storage."""
        return self.storage.remove_file(self.workspace, file_path)

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
            budget=budget,
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
        self.storage.insert_chunks(
            chunks=chunks,
            mtime=mtime,
            commit=commit,
            embedder=self._embedder,
            ensure_embedder_fn=self._ensure_embedder,
        )

    def _insert_chunks_no_commit(
        self, chunks: list[dict], mtime: float, budget: ContextBudget | None = None
    ) -> None:
        """Insert chunks into all stores. Caller holds the lock / transaction. Delegated to storage."""
        self.storage.insert_chunks_no_commit(
            chunks=chunks,
            mtime=mtime,
            embedder=self._embedder,
            budget=budget,
            ensure_embedder_fn=self._ensure_embedder,
        )

    # ------------------------------------------------------------------
    # RETRIEVAL
    # ------------------------------------------------------------------

    def search(
        self, query: str, top_k: int = 3, budget: ContextBudget | None = None
    ) -> list[ChunkResult]:
        """Hybrid search: KNN vector + BM25, fused via RRF (rank positions),
        then D13 feature re-rank (name/path/hot/test signals) before top_k.
        top_k defaults to 3 so the layer can't eat the context budget.

        ``budget`` (P1): the turn's shared budget. A BOUNDED budget is
        cache-only for the query vector — on a cache miss vector retrieval is
        skipped and FTS/BM25 still returns context; ``embedder.encode`` is
        NEVER called on the timed path. ``budget=None`` (legacy direct calls)
        and an explicit ``allow_embedding_compute`` budget may compute the
        query vector.
        """
        if self._is_index_empty():
            # Automatic unlimited full-index is DISABLED (it recreated the
            # runaway daemon build): an empty index returns [] and the caller
            # falls back to repo_map. The bounded per-turn sync_workspace()
            # populates a text/FTS + cached-vector prefix instead.
            return []

        vec = self._search_vector(query, top_k * 3, budget)
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
        return rerank_chunks(results, query)

    def _is_index_empty(self) -> bool:
        return self.storage.is_index_empty()

    def _search_vector(
        self, query: str, limit: int, budget: ContextBudget | None = None
    ) -> list[tuple[str, float]]:
        """Query-vector preparation gated by the inference policy. Delegated to vector_search."""
        if budget is None or budget.allow_embedding_compute:
            self._ensure_embedder()
        return search_vector(
            conn=self.conn,
            write_lock=self._write_lock,
            embedder=self._embedder,
            query=query,
            limit=limit,
            uses_vec=self.uses_vec,
            budget=budget,
            knn_sql=_VEC0_KNN_SQL,
            fullscan_sql=_VEC0_FULLSCAN_SQL,
        )

    def _search_vec_fast(self, q_emb: list[float], limit: int) -> list[tuple[str, float]]:
        """C1 (fixed §36): native vec0 KNN. Delegated to vector_search."""
        return search_vec_fast(
            conn=self.conn,
            write_lock=self._write_lock,
            q_emb=q_emb,
            limit=limit,
            knn_sql=_VEC0_KNN_SQL,
            fullscan_sql=_VEC0_FULLSCAN_SQL,
        )

    def _search_vec_linear(self, q_emb: list[float], limit: int) -> list[tuple[str, float]]:
        """Linear fallback search. Delegated to vector_search."""
        return search_vec_linear(
            conn=self.conn,
            write_lock=self._write_lock,
            q_emb=q_emb,
            limit=limit,
        )

    def _search_bm25(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Execute FTS5 BM25 search. Delegated to keyword_search."""
        return search_bm25(
            conn=self.conn,
            write_lock=self._write_lock,
            query=query,
            limit=limit,
            max_tokens=FTS_MAX_TOKENS_PER_QUERY,
        )

    def _rrf_fuse(
        self,
        vec_results: list[tuple[str, float]],
        bm25_results: list[tuple[str, float]],
        k: int = RRF_K,
    ) -> list[ChunkResult]:
        """Reciprocal Rank Fusion on list POSITIONS, not raw scores.
        Delegated to src.context.retrieval.fusion.
        """
        def _fetch_rows(ids: list[str]):
            placeholders = ",".join("?" * len(ids))
            with self._write_lock:  # shared connection: all access serialized
                return self.conn.execute(
                    f"SELECT id, file_path, symbol_name, symbol_type, start_line, end_line,"
                    f" signature, docstring, body, modified_time FROM code_chunks"
                    f" WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()

        return fuse_rankings(
            vec_results=vec_results,
            bm25_results=bm25_results,
            fetch_rows_fn=_fetch_rows,
            k=k,
            chunk_cls=ChunkResult,
        )

    # ------------------------------------------------------------------
    # NEIGHBORS (surrounding-chunk context window)
    # ------------------------------------------------------------------

    def get_neighbors(self, chunk_id: str, radius: int = 3) -> list[ChunkResult]:
        return self.storage.get_neighbors(chunk_id, radius=radius, chunk_cls=ChunkResult)


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
        # The SAME shared budget gates retrieval: bounded => cache-only query
        # vector (BM25/FTS fallback on miss), never embedder.encode on the
        # timed path.
        chunks = index.search(task, top_k=3, budget=budget)
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

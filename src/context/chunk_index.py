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
# Index sync — extracted to src.context.indexing.index_sync
# ---------------------------------------------------------------------
from src.context.indexing.index_sync import (
    _SKIP_DIRS,
    IndexSynchronizer,
    edges_for as _sync_edges_for,
    emit_degraded_scan as _sync_emit_degraded_scan,
    index_workspace as _sync_index_workspace,
    iter_source_files as _sync_iter_source_files,
    read_source as _sync_read_source,
    sync_file as _sync_sync_file,
    sync_workspace as _sync_sync_workspace,
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

        self._lazy_default_embedder = embedder is _LAZY_DEFAULT_EMBEDDER
        self._embedder_val = None if self._lazy_default_embedder else embedder

        self.synchronizer = IndexSynchronizer(
            workspace=self.workspace,
            storage=self.storage,
            embedder=self._embedder_val,
            ensure_embedder_fn=self._ensure_embedder,
        )

        # File-watcher state (started only when watch=True, i.e. via
        # get_index() in production — tests construct with watch=False and
        # drive the queue helpers directly).
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()
        self._pending_syncs: set[str] = set()
        self._pending_removes: set[str] = set()
        self._sync_queue_lock = threading.Lock()

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

    @property
    def _embedder(self) -> Any:
        return self._embedder_val

    @_embedder.setter
    def _embedder(self, val: Any) -> None:
        self._embedder_val = val
        if hasattr(self, "synchronizer"):
            self.synchronizer.embedder = val

    @property
    def _last_scan_report(self) -> Any:
        return self.synchronizer._last_scan_report

    @_last_scan_report.setter
    def _last_scan_report(self, val: Any) -> None:
        self.synchronizer._last_scan_report = val

    @property
    def _last_budget(self) -> ContextBudget | None:
        return self.synchronizer._last_budget

    @_last_budget.setter
    def _last_budget(self, val: ContextBudget | None) -> None:
        self.synchronizer._last_budget = val

    @property
    def thread_id_hint(self) -> str | None:
        return self.synchronizer.thread_id_hint

    @thread_id_hint.setter
    def thread_id_hint(self, val: str | None) -> None:
        self.synchronizer.thread_id_hint = val
    # ------------------------------------------------------------------
    # INDEXING
    # ------------------------------------------------------------------

    def index_workspace(self, budget: ContextBudget | None = None) -> None:
        """FULL REBUILD — explicit offline/maintenance only. Delegated to synchronizer."""
        self.synchronizer.index_workspace(budget)



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
        return self.synchronizer.read_source(file_path, budget)

    def sync_file(self, file_path: Path, budget: ContextBudget | None = None) -> None:
        self.synchronizer.sync_file(file_path, budget)

    def _edges_for(
        self,
        file_path: Path,
        rel: str,
        budget: ContextBudget | None = None,
        source: str | None = None,
    ) -> set[str]:
        return self.synchronizer.edges_for(file_path, rel, budget, source)

    def sync_workspace(self, budget: ContextBudget | None = None) -> int:
        return self.synchronizer.sync_workspace(budget)

    def _iter_source_files(self, budget: ContextBudget | None = None):
        return self.synchronizer.iter_source_files(budget)

    def _emit_degraded_scan(self, budget: ContextBudget | None = None) -> None:
        self.synchronizer.emit_degraded_scan(budget)

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

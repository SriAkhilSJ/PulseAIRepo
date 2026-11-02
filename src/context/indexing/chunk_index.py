"""
Chunk Index — Indexing Facade and Context Layer Construction
=============================================================

Coordinates storage, synchronization, file watcher, hybrid retrieval
(vector + BM25), reciprocal rank fusion, and feature re-ranking.
Exposes process-wide workspace index caching and the relevant_chunks
Context Engine layer builder.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.context.budgeting.context_budget import ContextBudget
from src.context.types import ChunkResult
from src.context.extraction.language_registry import (
    extract_source_chunks,
    source_extensions,
)
from src.context.extraction.python_extractor import (
    _extract_py_import_edges,
    extract_chunks,
    extract_chunks_python,
    extract_py_import_edges,
)
from src.context.indexing.file_watcher import (
    WATCH_BATCH_S,
    WATCH_POLL_S,
    FileWatcher,
)
from src.context.indexing.index_storage import (
    EMBED_DIM,
    IndexStorage,
    get_neighbors as _storage_get_neighbors,
    init_schema as _storage_init_schema,
    insert_chunks as _storage_insert_chunks,
    insert_chunks_no_commit as _storage_insert_chunks_no_commit,
    is_index_empty as _storage_is_index_empty,
    open_database as _storage_open_database,
    remove_file as _storage_remove_file,
)
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
from src.context.retrieval.fusion import (
    DEFAULT_RRF_K,
    RRF_K,
    compute_rrf_scores,
    fuse_rankings,
    hydrate_chunk_results,
    reciprocal_rank_fusion,
    rrf_score,
)
from src.context.retrieval.keyword_search import (
    DEFAULT_FTS_MAX_TOKENS,
    FTS_MAX_TOKENS_PER_QUERY,
    FTS_SEARCH_SQL,
    sanitize_fts_query,
    search_bm25,
)
from src.context.retrieval.reranker import (
    _RERANK_MIN_WORD,
    _RERANK_NAME_PART_CAP,
    _RERANK_TESTISH,
    _RERANK_W,
    _is_test_path,
    _word_parts,
    rerank_chunks,
)
from src.context.retrieval.vector_search import (
    _VEC0_FULLSCAN_SQL,
    _VEC0_KNN_SQL,
    VEC0_FULLSCAN_SQL,
    VEC0_KNN_SQL,
    search_vec_fast,
    search_vec_linear,
    search_vector,
)

BODY_HARD_CAP_CHARS = 800       # per-chunk cap for LLM context


# ---------------------------------------------------------------------
# DATA MODEL (canonical definition in src.context.types)
# ---------------------------------------------------------------------
# ChunkResult is imported above from src.context.types and re-exported


# One ChunkIndex per workspace, shared process-wide (constructing a fresh
# index — and re-syncing — per layer call would dominate every turn).
_INDEX_CACHE: dict[str, "ChunkIndex"] = {}
_INDEX_CACHE_LOCK = threading.Lock()


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

        self.watcher = FileWatcher(
            workspace=self.workspace,
            sync_file_fn=self.sync_file,
            remove_file_fn=self.remove_file,
            sync_workspace_fn=self.sync_workspace,
        )

        if watch:
            self.start_watcher()

    def _ensure_embedder(self) -> None:
        """Lazily resolve the default embedder."""
        if self._embedder is not None or not self._lazy_default_embedder:
            return
        try:
            from src.llm.factory import get_embedder
            self._embedder = get_embedder()
        except Exception:
            self._embedder = None

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
    # INDEXING & SYNC
    # ------------------------------------------------------------------

    def index_workspace(self, budget: ContextBudget | None = None) -> None:
        """FULL REBUILD — explicit offline/maintenance only."""
        self.synchronizer.index_workspace(budget)

    # ------------------------------------------------------------------
    # FILE WATCHER
    # ------------------------------------------------------------------

    _WATCH_BATCH_S = WATCH_BATCH_S
    _WATCH_POLL_S = WATCH_POLL_S

    @property
    def _pending_syncs(self) -> set[str]:
        return self.watcher._pending_syncs

    @property
    def _pending_removes(self) -> set[str]:
        return self.watcher._pending_removes

    @property
    def _sync_queue_lock(self) -> threading.Lock:
        return self.watcher._sync_queue_lock

    @property
    def _watcher_thread(self) -> Optional[threading.Thread]:
        return self.watcher._watcher_thread

    @_watcher_thread.setter
    def _watcher_thread(self, val: Optional[threading.Thread]) -> None:
        self.watcher._watcher_thread = val

    @property
    def _watcher_stop(self) -> threading.Event:
        return self.watcher._watcher_stop

    def start_watcher(self) -> None:
        self.watcher.start()

    def stop_watcher(self) -> None:
        self.watcher.stop()

    def _enqueue_sync(self, path: str) -> None:
        self.watcher.enqueue_sync(path)

    def _enqueue_remove(self, path: str) -> None:
        self.watcher.enqueue_remove(path)

    def _drain_pending_syncs(self) -> tuple[list[str], list[str]]:
        return self.watcher.drain_pending_syncs()

    def _apply_queued_changes(self) -> None:
        self.watcher.apply_queued_changes()

    def _watch_loop(self) -> None:
        self.watcher.watch_loop()

    # ------------------------------------------------------------------
    # INCREMENTAL SYNC
    # ------------------------------------------------------------------

    def remove_file(self, file_path: Path) -> int:
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
        if self._is_index_empty():
            return []

        vec = self._search_vector(query, top_k * 3, budget)
        bm25 = self._search_bm25(query, top_k * 3)
        fused = self._rrf_fuse(vec, bm25, k=RRF_K)
        return self._rerank(fused, query)[:top_k]

    def _rerank(self, results: list[ChunkResult], query: str) -> list[ChunkResult]:
        return rerank_chunks(results, query)

    def _is_index_empty(self) -> bool:
        return self.storage.is_index_empty()

    def _search_vector(
        self, query: str, limit: int, budget: ContextBudget | None = None
    ) -> list[tuple[str, float]]:
        if budget is None or budget.allow_embedding_compute:
            self._ensure_embedder()
        ci_mod = sys.modules.get("src.context.chunk_index")
        knn_sql = getattr(ci_mod, "_VEC0_KNN_SQL", _VEC0_KNN_SQL) if ci_mod is not None else _VEC0_KNN_SQL
        fullscan_sql = getattr(ci_mod, "_VEC0_FULLSCAN_SQL", _VEC0_FULLSCAN_SQL) if ci_mod is not None else _VEC0_FULLSCAN_SQL
        return search_vector(
            conn=self.conn,
            write_lock=self._write_lock,
            embedder=self._embedder,
            query=query,
            limit=limit,
            uses_vec=self.uses_vec,
            budget=budget,
            knn_sql=knn_sql,
            fullscan_sql=fullscan_sql,
        )

    def _search_vec_fast(self, q_emb: list[float], limit: int) -> list[tuple[str, float]]:
        ci_mod = sys.modules.get("src.context.chunk_index")
        knn_sql = getattr(ci_mod, "_VEC0_KNN_SQL", _VEC0_KNN_SQL) if ci_mod is not None else _VEC0_KNN_SQL
        fullscan_sql = getattr(ci_mod, "_VEC0_FULLSCAN_SQL", _VEC0_FULLSCAN_SQL) if ci_mod is not None else _VEC0_FULLSCAN_SQL
        return search_vec_fast(
            conn=self.conn,
            write_lock=self._write_lock,
            q_emb=q_emb,
            limit=limit,
            knn_sql=knn_sql,
            fullscan_sql=fullscan_sql,
        )

    def _search_vec_linear(self, q_emb: list[float], limit: int) -> list[tuple[str, float]]:
        return search_vec_linear(
            conn=self.conn,
            write_lock=self._write_lock,
            q_emb=q_emb,
            limit=limit,
        )

    def _search_bm25(self, query: str, limit: int) -> list[tuple[str, float]]:
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
        def _fetch_rows(ids: list[str]):
            placeholders = ",".join("?" * len(ids))
            with self._write_lock:
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
    # NEIGHBORS
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
    """One ChunkIndex per workspace, process-wide. New DB only on first use."""
    key = str(Path(workspace).resolve())
    with _INDEX_CACHE_LOCK:
        idx = _INDEX_CACHE.get(key)
        if idx is None:
            idx = ChunkIndex(key, db_path=db_path, watch=watch)
            _INDEX_CACHE[key] = idx
        elif watch:
            idx.start_watcher()
        return idx


# ---------------------------------------------------------------------
# CONTEXT ENGINE LAYER BUILDER
# ---------------------------------------------------------------------


def build_relevant_chunks_layer(state: dict[str, Any], budget: ContextBudget | None = None) -> Any:
    """ContextEngine layer: top-k code chunks relevant to the current task."""
    task = state.get("current_task", "")
    if not task:
        return None

    from langchain_core.messages import SystemMessage

    try:
        # Dynamically support patching on legacy module or indexing facade
        ci_mod = sys.modules.get("src.context.chunk_index")
        get_idx_fn = getattr(ci_mod, "get_index", get_index) if ci_mod is not None else get_index
        index = get_idx_fn(state.get("workspace", "."))
        index.thread_id_hint = str(state.get("thread_id") or state.get("session_id") or "")
        index.sync_workspace(budget)
        chunks = index.search(task, top_k=3, budget=budget)
        if not chunks:
            return None
    except Exception as exc:
        print(f"[ChunkIndex] relevant_chunks layer failed: {exc}")
        return None

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


_MAX_RELATED_FILES = 4
_MAX_RELATED_SYMBOLS = 3


def _related_files_lines(index: "ChunkIndex", used_files: set[str]) -> list[str]:
    """Detective mode: import-linked neighbors of the matched files."""
    if not used_files:
        return []
    try:
        with index._write_lock:
            used = sorted(used_files)
            dep_pairs: list[tuple[str, str]] = []
            depnd_pairs: list[tuple[str, str]] = []
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
            ordered: list[tuple[str, str, bool]] = []
            candidates = (
                [(n, m, True) for n, m in depnd_pairs]
                + [(n, m, False) for n, m in dep_pairs]
            )
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
        print(f"[ChunkIndex] related-files lookup failed: {exc}")
        return []


__all__ = [
    "BODY_HARD_CAP_CHARS",
    "ChunkResult",
    "ChunkIndex",
    "get_index",
    "build_relevant_chunks_layer",
    "_related_files_lines",
    "_INDEX_CACHE",
    "_INDEX_CACHE_LOCK",
]

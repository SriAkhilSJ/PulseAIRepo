"""
Chunk Index — Backward Compatibility Facade
===========================================

This module re-exports all indexing, storage, synchronization, retrieval, and
extraction functions and classes for backward compatibility. New code should import
from `src.context.indexing`, `src.context.retrieval`, or `src.context.extraction`.
"""

from __future__ import annotations

# Extraction re-exports
from src.context.extraction.language_registry import (
    _EXT_JS_FAMILY as _EXT_JS_FAMILY_LANG,
    extract_source_chunks,
    source_extensions,
)
from src.context.extraction.python_extractor import (
    _extract_py_import_edges,
    _sha256_id,
    _truncate_for_embedding,
    extract_chunks,
    extract_chunks_python,
    extract_py_import_edges,
)
from src.context.extraction.treesitter_extractor import (
    extract_chunks_treesitter,
    extract_go_import_edges,
    extract_java_import_edges,
    extract_js_import_edges,
    extract_rust_import_edges,
)

# Retrieval re-exports
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

# Indexing subsystem re-exports
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
from src.context.indexing.chunk_index import (
    BODY_HARD_CAP_CHARS,
    ChunkIndex,
    ChunkResult,
    _INDEX_CACHE,
    _INDEX_CACHE_LOCK,
    _related_files_lines,
    build_relevant_chunks_layer,
    get_index,
)

_WATCH_BATCH_S = WATCH_BATCH_S
_WATCH_POLL_S = WATCH_POLL_S

__all__ = [
    # Chunk Index & Result
    "BODY_HARD_CAP_CHARS",
    "ChunkResult",
    "ChunkIndex",
    "get_index",
    "build_relevant_chunks_layer",
    "_related_files_lines",
    "_INDEX_CACHE",
    "_INDEX_CACHE_LOCK",
    # Storage
    "EMBED_DIM",
    "IndexStorage",
    "_storage_open_database",
    "_storage_init_schema",
    "_storage_insert_chunks",
    "_storage_insert_chunks_no_commit",
    "_storage_remove_file",
    "_storage_is_index_empty",
    "_storage_get_neighbors",
    # Sync
    "_SKIP_DIRS",
    "IndexSynchronizer",
    "_sync_edges_for",
    "_sync_emit_degraded_scan",
    "_sync_index_workspace",
    "_sync_iter_source_files",
    "_sync_read_source",
    "_sync_sync_file",
    "_sync_sync_workspace",
    # Watcher
    "WATCH_BATCH_S",
    "WATCH_POLL_S",
    "_WATCH_BATCH_S",
    "_WATCH_POLL_S",
    "FileWatcher",
    # Fusion
    "DEFAULT_RRF_K",
    "RRF_K",
    "compute_rrf_scores",
    "fuse_rankings",
    "hydrate_chunk_results",
    "reciprocal_rank_fusion",
    "rrf_score",
    # Keyword search
    "DEFAULT_FTS_MAX_TOKENS",
    "FTS_MAX_TOKENS_PER_QUERY",
    "FTS_SEARCH_SQL",
    "sanitize_fts_query",
    "search_bm25",
    # Reranker
    "_RERANK_MIN_WORD",
    "_RERANK_NAME_PART_CAP",
    "_RERANK_TESTISH",
    "_RERANK_W",
    "_is_test_path",
    "_word_parts",
    "rerank_chunks",
    # Vector search
    "_VEC0_FULLSCAN_SQL",
    "_VEC0_KNN_SQL",
    "VEC0_FULLSCAN_SQL",
    "VEC0_KNN_SQL",
    "search_vec_fast",
    "search_vec_linear",
    "search_vector",
    # Extraction
    "extract_chunks",
    "extract_chunks_python",
    "extract_py_import_edges",
    "_extract_py_import_edges",
    "extract_source_chunks",
    "source_extensions",
    "_EXT_JS_FAMILY_LANG",
    "extract_chunks_treesitter",
    "extract_go_import_edges",
    "extract_java_import_edges",
    "extract_js_import_edges",
    "extract_rust_import_edges",
    "_sha256_id",
    "_truncate_for_embedding",
]

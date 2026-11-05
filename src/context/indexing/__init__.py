"""Indexing subsystem for CrusorAI Context Engine."""

from src.context.indexing.chunk_index import (
    BODY_HARD_CAP_CHARS,
    ChunkIndex,
    ChunkResult,
    _INDEX_CACHE,
    _INDEX_CACHE_LOCK,
    _related_files_lines,
    build_relevant_chunks_layer,
    get_index,
    get_index_generation,
    bump_index_generation,
)
from src.context.indexing.file_watcher import (
    WATCH_BATCH_S,
    WATCH_POLL_S,
    FileWatcher,
)
from src.context.indexing.index_storage import (
    EMBED_DIM,
    SCHEMA_USER_VERSION,
    IndexStorage,
    get_neighbors,
    init_schema,
    insert_chunks,
    insert_chunks_no_commit,
    is_index_empty,
    open_database,
    remove_file,
)
from src.context.indexing.index_sync import (
    _SKIP_DIRS,
    IndexSynchronizer,
    edges_for,
    emit_degraded_scan,
    index_workspace,
    iter_source_files,
    read_source,
    sync_file,
    sync_workspace,
)

__all__ = [
    # Chunk Index Facade & Layer
    "BODY_HARD_CAP_CHARS",
    "ChunkResult",
    "ChunkIndex",
    "get_index",
    "build_relevant_chunks_layer",
    "_related_files_lines",
    "_INDEX_CACHE",
    "_INDEX_CACHE_LOCK",
    "get_index_generation",
    "bump_index_generation",
    # Storage
    "EMBED_DIM",
    "SCHEMA_USER_VERSION",
    "IndexStorage",
    "open_database",
    "init_schema",
    "insert_chunks",
    "insert_chunks_no_commit",
    "remove_file",
    "is_index_empty",
    "get_neighbors",
    # Sync
    "_SKIP_DIRS",
    "read_source",
    "edges_for",
    "iter_source_files",
    "emit_degraded_scan",
    "sync_file",
    "sync_workspace",
    "index_workspace",
    "IndexSynchronizer",
    # Watcher
    "WATCH_BATCH_S",
    "WATCH_POLL_S",
    "FileWatcher",
]

"""Indexing subsystem for CrusorAI Context Engine."""

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
]

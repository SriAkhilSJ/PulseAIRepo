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

__all__ = [
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
]

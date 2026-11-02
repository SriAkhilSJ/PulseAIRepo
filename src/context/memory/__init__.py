"""
Context Memory Package
======================

Provides content-addressed embedding caching and SQLite-backed persistent vector memory.
"""

from src.context.memory.embedding_cache import (
    EmbeddingCache,
    get_embedding_cache,
    _embedder_identity,
)
from src.context.memory.vector_memory import (
    VectorMemory,
    EMBED_DIM,
    _LEGACY_SCAN_LIMIT,
)

__all__ = [
    "EmbeddingCache",
    "get_embedding_cache",
    "_embedder_identity",
    "VectorMemory",
    "EMBED_DIM",
    "_LEGACY_SCAN_LIMIT",
]

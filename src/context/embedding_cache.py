"""
Embedding Cache — Backward Compatibility Facade
================================================

This module re-exports the embedding cache from `src.context.memory.embedding_cache`.
"""

from __future__ import annotations

import sys
from src.context.memory.embedding_cache import (
    EmbeddingCache,
    get_embedding_cache,
    _embedder_identity,
    _SHARED_EMBEDDING_CACHE,
    _SHARED_EMBEDDING_CACHE_LOCK,
)

__all__ = [
    "EmbeddingCache",
    "get_embedding_cache",
    "_embedder_identity",
]

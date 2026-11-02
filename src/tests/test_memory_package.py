"""Tests for src.context.memory package."""

import pytest
from src.context.memory import (
    EmbeddingCache,
    VectorMemory,
    get_embedding_cache,
    EMBED_DIM,
)
from src.context.embedding_cache import EmbeddingCache as FacadeEmbeddingCache
from src.context.vector_memory import VectorMemory as FacadeVectorMemory


def test_memory_package_exports():
    assert EmbeddingCache is FacadeEmbeddingCache
    assert VectorMemory is FacadeVectorMemory
    assert EMBED_DIM == 384


def test_embedding_cache_instance():
    cache = EmbeddingCache(max_entries=10)
    assert len(cache) == 0
    cache._store["k1"] = [1.0]
    assert len(cache) == 1

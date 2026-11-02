"""Tests for modular vector search implementation (src.context.retrieval.vector_search)."""

import json
import sqlite3
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.context.retrieval.vector_search import (
    VEC0_FULLSCAN_SQL,
    VEC0_KNN_SQL,
    _VEC0_FULLSCAN_SQL,
    _VEC0_KNN_SQL,
    dot_product_to_unit_score,
    l2_distance_to_cosine_similarity,
    search_vec_fast,
    search_vec_linear,
    search_vector,
)


def test_distance_and_score_math():
    # Exact match: L2 distance 0.0 => cosine similarity 1.0
    assert l2_distance_to_cosine_similarity(0.0) == 1.0
    # Orthogonal unit vectors: L2 = sqrt(2) => cosine similarity 0.0
    assert l2_distance_to_cosine_similarity(2.0**0.5) == pytest.approx(0.0, abs=1e-6)
    # Cosine to unit score
    assert dot_product_to_unit_score(1.0) == 1.0
    assert dot_product_to_unit_score(-1.0) == 0.0
    assert dot_product_to_unit_score(0.0) == 0.5


def test_search_vec_linear_scores_and_sorts():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE chunk_vec_fallback (chunk_id TEXT PRIMARY KEY, embedding BLOB)")
    
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [0.0, 1.0, 0.0]
    vec3 = [0.7071, 0.7071, 0.0]

    conn.execute("INSERT INTO chunk_vec_fallback VALUES (?, ?)", ("c1", json.dumps(vec1).encode("utf-8")))
    conn.execute("INSERT INTO chunk_vec_fallback VALUES (?, ?)", ("c2", json.dumps(vec2).encode("utf-8")))
    conn.execute("INSERT INTO chunk_vec_fallback VALUES (?, ?)", ("c3", json.dumps(vec3).encode("utf-8")))

    lock = threading.Lock()
    q_emb = [1.0, 0.0, 0.0]
    results = search_vec_linear(conn, lock, q_emb, limit=2)

    assert len(results) == 2
    # c1 is exact match (dot product 1.0 => unit score 1.0)
    assert results[0][0] == "c1"
    assert results[0][1] == pytest.approx(1.0)
    # c3 is second closest
    assert results[1][0] == "c3"


def test_search_vec_fast_fallback_on_knn_failure(capsys):
    conn = MagicMock()
    lock = threading.Lock()
    
    # KNN fails, fallback succeeds
    call_count = 0
    def execute_mock(sql, params):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise sqlite3.OperationalError("no such match constraint")
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("chunk_fb", 0.0)]
        return mock_cursor

    conn.execute.side_effect = execute_mock
    res = search_vec_fast(conn, lock, [0.1, 0.2], limit=5)

    assert len(res) == 1
    assert res[0][0] == "chunk_fb"
    assert res[0][1] == 1.0
    out = capsys.readouterr().out
    assert "full-scan fallback" in out


def test_search_vector_budget_offline_skips_when_not_cached():
    conn = MagicMock()
    lock = threading.Lock()
    mock_embedder = MagicMock()

    class BudgetOffline:
        allow_embedding_compute = False

    with patch("src.context.embedding_cache.get_embedding_cache") as mock_cache_get:
        mock_cache = MagicMock()
        mock_cache.lookup.return_value = None
        mock_cache_get.return_value = mock_cache

        res = search_vector(
            conn=conn,
            write_lock=lock,
            embedder=mock_embedder,
            query="test query",
            limit=5,
            budget=BudgetOffline(),
        )

        assert res == []
        mock_embedder.encode.assert_not_called()


def test_chunk_index_reexports_sql_constants():
    from src.context.chunk_index import _VEC0_FULLSCAN_SQL as CI_FULLSCAN, _VEC0_KNN_SQL as CI_KNN
    assert CI_KNN == _VEC0_KNN_SQL
    assert CI_FULLSCAN == _VEC0_FULLSCAN_SQL

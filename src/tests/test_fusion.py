"""Tests for modular fusion implementation (src.context.retrieval.fusion)."""

from dataclasses import dataclass
from typing import Optional

import pytest

from src.context.retrieval.fusion import (
    DEFAULT_RRF_K,
    RRF_K,
    compute_rrf_scores,
    fuse_rankings,
    hydrate_chunk_results,
    reciprocal_rank_fusion,
    rrf_score,
)


@dataclass
class DummyChunk:
    id: str
    file_path: str
    symbol_name: str
    symbol_type: str
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str]
    body: str
    score: float
    modified_time: float = 0.0


def test_rrf_score_formula():
    assert rrf_score(0, k=60) == pytest.approx(1.0 / 61.0)
    assert rrf_score(1, k=60) == pytest.approx(1.0 / 62.0)
    assert rrf_score(0, k=10) == pytest.approx(1.0 / 11.0)


def test_compute_rrf_scores_combines_ranks():
    vec = [("doc1", 0.9), ("doc2", 0.8)]
    bm25 = [("doc2", 5.0), ("doc3", 4.0)]

    scores = compute_rrf_scores(vec, bm25, k=60)
    # doc1 is rank 0 in vec only: 1/61
    assert scores["doc1"] == pytest.approx(1.0 / 61.0)
    # doc2 is rank 1 in vec (1/62) and rank 0 in bm25 (1/61)
    assert scores["doc2"] == pytest.approx(1.0 / 62.0 + 1.0 / 61.0)
    # doc3 is rank 1 in bm25 only: 1/62
    assert scores["doc3"] == pytest.approx(1.0 / 62.0)


def test_compute_rrf_scores_accepts_strings_or_tuples():
    list1 = ["docA", "docB"]
    list2 = [("docB", 10.0), ("docC", 5.0)]

    scores = compute_rrf_scores(list1, list2, k=60)
    assert "docA" in scores
    assert "docB" in scores
    assert "docC" in scores
    assert scores["docB"] == pytest.approx(1.0 / 62.0 + 1.0 / 61.0)


def test_reciprocal_rank_fusion_ordering():
    # Item present in both lists should rank first
    vec = [("a", 0.99), ("b", 0.5)]
    bm25 = [("b", 10.0), ("c", 1.0)]

    fused = reciprocal_rank_fusion(vec, bm25, k=60)
    # Order should be "b" (both), then "a" (rank 0 in vec), then "c" (rank 1 in bm25)
    ids = [cid for cid, score in fused]
    assert ids == ["b", "a", "c"]
    assert fused[0][1] > fused[1][1]
    assert fused[1][1] > fused[2][1]


def test_reciprocal_rank_fusion_empty():
    assert reciprocal_rank_fusion([], []) == []


def test_reciprocal_rank_fusion_stable_ties():
    # Both a and b have rank 0 in their respective single list
    list1 = ["a"]
    list2 = ["b"]

    fused = reciprocal_rank_fusion(list1, list2, k=60)
    # Insertion order preserved on tie
    assert [cid for cid, _ in fused] == ["a", "b"]


def test_hydrate_chunk_results():
    ordered_ids = ["chunk1", "chunk2", "missing_chunk"]
    scores = {"chunk1": 0.05, "chunk2": 0.03, "missing_chunk": 0.01}
    rows_by_id = {
        "chunk1": (
            "chunk1", "src/a.py", "func_a", "function", 1, 10,
            "def func_a():", "Doc A", "return 1", 100.0
        ),
        "chunk2": (
            "chunk2", "src/b.py", "func_b", "function", 5, 15,
            "def func_b():", None, "return 2", 200.0
        ),
    }

    chunks = hydrate_chunk_results(
        ordered_ids,
        scores,
        rows_by_id,
        chunk_cls=DummyChunk,
    )

    assert len(chunks) == 2
    assert chunks[0].id == "chunk1"
    assert chunks[0].score == pytest.approx(0.05)
    assert chunks[0].docstring == "Doc A"
    assert chunks[1].id == "chunk2"
    assert chunks[1].score == pytest.approx(0.03)
    assert chunks[1].docstring is None


def test_fuse_rankings_e2e():
    vec = [("c1", 0.8), ("c2", 0.7)]
    bm25 = [("c2", 2.0), ("c3", 1.0)]

    def mock_fetch(ids):
        return [
            ("c1", "a.py", "f1", "function", 1, 5, "def f1():", None, "pass", 0.0),
            ("c2", "b.py", "f2", "function", 1, 5, "def f2():", None, "pass", 0.0),
            ("c3", "c.py", "f3", "function", 1, 5, "def f3():", None, "pass", 0.0),
        ]

    results = fuse_rankings(vec, bm25, fetch_rows_fn=mock_fetch, k=60, chunk_cls=DummyChunk)
    # c2 is in both, so top
    assert [r.id for r in results] == ["c2", "c1", "c3"]


def test_chunk_index_reexports_rrf_k():
    from src.context.chunk_index import RRF_K as CI_RRF_K
    assert CI_RRF_K == RRF_K == DEFAULT_RRF_K == 60

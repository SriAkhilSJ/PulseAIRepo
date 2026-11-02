"""Retrieval subsystem for Context Engine."""

from src.context.retrieval.fusion import (
    DEFAULT_RRF_K,
    RRF_K,
    compute_rrf_scores,
    fuse_rankings,
    hydrate_chunk_results,
    reciprocal_rank_fusion,
    rrf_score,
)
from src.context.retrieval.reranker import (
    RERANK_MIN_WORD,
    RERANK_NAME_PART_CAP,
    RERANK_TESTISH,
    RERANK_WEIGHTS,
    _RERANK_MIN_WORD,
    _RERANK_NAME_PART_CAP,
    _RERANK_TESTISH,
    _RERANK_W,
    _is_test_path,
    _word_parts,
    compute_rerank_bonus,
    extract_word_parts,
    is_test_path,
    rerank,
    rerank_chunks,
)

__all__ = [
    # Reranker
    "_RERANK_W",
    "_RERANK_NAME_PART_CAP",
    "_RERANK_MIN_WORD",
    "_RERANK_TESTISH",
    "RERANK_WEIGHTS",
    "RERANK_NAME_PART_CAP",
    "RERANK_MIN_WORD",
    "RERANK_TESTISH",
    "_word_parts",
    "_is_test_path",
    "extract_word_parts",
    "is_test_path",
    "compute_rerank_bonus",
    "rerank_chunks",
    "rerank",
    # Fusion
    "DEFAULT_RRF_K",
    "RRF_K",
    "rrf_score",
    "compute_rrf_scores",
    "reciprocal_rank_fusion",
    "hydrate_chunk_results",
    "fuse_rankings",
]

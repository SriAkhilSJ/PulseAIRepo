"""
Context Retrieval Fusion
========================

Reciprocal Rank Fusion (RRF) for combining multi-source retrieval rankings
(e.g., vector KNN search and keyword/BM25 full-text search).

Invariants:
- Fuses strictly on rank POSITIONS (0, 1, 2...) rather than raw retrieval scores
  (because vector distances and BM25 BM25-rank values are not directly comparable).
- Standard RRF formula: score = sum(1.0 / (k + rank + 1)).
- Stable ordering: ties preserve insertion order across rankings.
- Zero extra embedding or LLM inference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Sequence, TypeVar

if TYPE_CHECKING:
    from src.context.types import ChunkResult

T = TypeVar("T")

DEFAULT_RRF_K: int = 60
RRF_K: int = DEFAULT_RRF_K


def rrf_score(rank: int, k: int = RRF_K) -> float:
    """Compute individual RRF contribution for a 0-indexed rank position.

    rank 0 -> 1.0 / (k + 1)
    rank 1 -> 1.0 / (k + 2)
    """
    return 1.0 / (k + rank + 1)


def compute_rrf_scores(
    *ranked_lists: Sequence[tuple[str, Any] | str],
    k: int = RRF_K,
) -> dict[str, float]:
    """Compute Reciprocal Rank Fusion (RRF) scores across multiple ranked lists.

    Each ranked list contains either item IDs (str) or (item_id, raw_score) tuples.
    Rank is determined by 0-indexed position within each list.

    Returns:
        A dict mapping item_id -> accumulated RRF score.
    """
    scores: dict[str, float] = {}
    for rlist in ranked_lists:
        for rank, item in enumerate(rlist):
            cid = item[0] if isinstance(item, (tuple, list)) else item
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def reciprocal_rank_fusion(
    *ranked_lists: Sequence[tuple[str, Any] | str],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Compute RRF and return sorted (item_id, score) pairs in descending score order.

    Python's stable sort preserves insertion order for tied scores.
    """
    scores = compute_rrf_scores(*ranked_lists, k=k)
    if not scores:
        return []
    ordered_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [(cid, scores[cid]) for cid in ordered_ids]


def hydrate_chunk_results(
    ordered_ids: Sequence[str],
    scores: dict[str, float],
    rows_by_id: dict[str, tuple[Any, ...]],
    chunk_cls: type[T] | None = None,
) -> list[T]:
    """Hydrate raw database row tuples into chunk result instances ordered by RRF score.

    Row tuple schema expected:
    (id, file_path, symbol_name, symbol_type, start_line, end_line,
     signature, docstring, body, modified_time)
    """
    if chunk_cls is None:
        from src.context.types import ChunkResult
        target_cls: Any = ChunkResult
    else:
        target_cls = chunk_cls

    results: list[T] = []
    for cid in ordered_ids:
        row = rows_by_id.get(cid)
        if not row:
            continue
        results.append(target_cls(
            id=row[0],
            file_path=row[1],
            symbol_name=row[2],
            symbol_type=row[3],
            start_line=row[4],
            end_line=row[5],
            signature=row[6] or "",
            docstring=row[7],
            body=row[8] or "",
            score=scores[cid],
            modified_time=row[9] or 0.0,
        ))
    return results


def fuse_rankings(
    vec_results: Sequence[tuple[str, float] | str],
    bm25_results: Sequence[tuple[str, float] | str],
    fetch_rows_fn: Callable[[list[str]], list[tuple[Any, ...]]],
    k: int = RRF_K,
    chunk_cls: type[T] | None = None,
) -> list[T]:
    """Execute Reciprocal Rank Fusion on vector and BM25 results, then hydrate results."""
    scores = compute_rrf_scores(vec_results, bm25_results, k=k)
    if not scores:
        return []
    ordered_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    rows = fetch_rows_fn(ordered_ids)
    by_id = {r[0]: r for r in rows}
    return hydrate_chunk_results(ordered_ids, scores, by_id, chunk_cls=chunk_cls)


__all__ = [
    "DEFAULT_RRF_K",
    "RRF_K",
    "rrf_score",
    "compute_rrf_scores",
    "reciprocal_rank_fusion",
    "hydrate_chunk_results",
    "fuse_rankings",
]

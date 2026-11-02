"""
Context Retrieval Vector Search
===============================

Vector similarity search for code chunks:
- Native sqlite-vec exact KNN search (vec0 MATCH + k constraint).
- Pre-C1 full-scan fallback if k constraint is unavailable in older sqlite-vec builds.
- Linear dot-product fallback over JSON embeddings (chunk_vec_fallback table)
  when sqlite-vec extension is not available.
- Query-vector preparation gated by inference budget policy.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import TYPE_CHECKING, Any, Callable, Sequence

if TYPE_CHECKING:
    from src.context.bounded_scan import ContextBudget

# ---------------------------------------------------------------------
# SQL queries for sqlite-vec
# ---------------------------------------------------------------------

# C1 (fixed §36): vec0 KNN pushdown. The MATCH + k constraint is handled
# inside the extension (exact KNN over its own index) instead of computing
# vec_distance_l2 for every row and sorting in SQL — 12-14x faster at
# 2K-20K rows, identical orderings (scripts/c1_knn_benchmark.py).
_VEC0_KNN_SQL = """
    SELECT v.chunk_id AS id, v.distance AS distance
    FROM chunk_vec v
    WHERE v.embedding MATCH vec_f32(?) AND k = ?
    ORDER BY v.distance
"""

# Pre-C1 shape, kept ONLY as the degraded fallback for sqlite-vec builds
# old enough to lack the k constraint (< v0.1.2). Never the first choice.
_VEC0_FULLSCAN_SQL = """
    SELECT c.id, vec_distance_l2(v.embedding, vec_f32(?)) AS distance
    FROM chunk_vec v
    JOIN code_chunks c ON v.chunk_id = c.id
    ORDER BY distance
    LIMIT ?
"""

VEC0_KNN_SQL = _VEC0_KNN_SQL
VEC0_FULLSCAN_SQL = _VEC0_FULLSCAN_SQL


def l2_distance_to_cosine_similarity(distance: float) -> float:
    """Convert L2 distance between unit-normalized vectors to cosine similarity.

    Vectors are unit-normalized, cosine = 1 - L2²/2 EXACTLY
    (no max-distance normalization — that divides by zero on exact matches).
    """
    return max(0.0, 1.0 - (distance * distance) / 2.0)


def dot_product_to_unit_score(sim: float) -> float:
    """Map cosine [-1, 1] to [0, 1]; ordering unchanged."""
    return (sim + 1.0) / 2.0


def search_vec_fast(
    conn: sqlite3.Connection,
    write_lock: threading.Lock | Any,
    q_emb: list[float],
    limit: int,
    knn_sql: str = _VEC0_KNN_SQL,
    fullscan_sql: str = _VEC0_FULLSCAN_SQL,
) -> list[tuple[str, float]]:
    """Native vec0 KNN search — embedding MATCH + k constraint pushes search into extension.

    Falls back to pre-C1 full scan if KNN query raises.
    """
    with write_lock:
        try:
            rows = conn.execute(knn_sql, (json.dumps(q_emb), limit)).fetchall()
        except Exception as e:
            # Ancient sqlite-vec without the k constraint (pre-v0.1.2):
            # degrade to the pre-C1 full-scan shape rather than to nothing.
            print(f"[ChunkIndex] vec0 KNN query failed ({e}); full-scan fallback")
            try:
                rows = conn.execute(fullscan_sql, (json.dumps(q_emb), limit)).fetchall()
            except Exception as e2:
                print(f"[ChunkIndex] sqlite-vec query failed: {e2}")
                return []
    return [(cid, l2_distance_to_cosine_similarity(d)) for cid, d in rows]


def search_vec_linear(
    conn: sqlite3.Connection,
    write_lock: threading.Lock | Any,
    q_emb: list[float],
    limit: int,
) -> list[tuple[str, float]]:
    """Linear fallback search over JSON blobs in chunk_vec_fallback."""
    with write_lock:
        rows = conn.execute(
            "SELECT chunk_id, embedding FROM chunk_vec_fallback"
        ).fetchall()
    scored: list[tuple[float, str]] = []
    for cid, blob in rows:
        try:
            emb = json.loads(blob.decode("utf-8"))
            sim = sum(a * b for a, b in zip(q_emb, emb))
            scored.append((sim, cid))
        except Exception:
            continue
    scored.sort(reverse=True)
    return [(cid, dot_product_to_unit_score(sim)) for sim, cid in scored[:limit]]


def search_vector(
    conn: sqlite3.Connection,
    write_lock: threading.Lock | Any,
    embedder: Any,
    query: str,
    limit: int,
    uses_vec: bool = True,
    budget: ContextBudget | None = None,
    ensure_embedder_fn: Callable[[], None] | None = None,
    knn_sql: str = _VEC0_KNN_SQL,
    fullscan_sql: str = _VEC0_FULLSCAN_SQL,
) -> list[tuple[str, float]]:
    """Query-vector preparation gated by the inference policy, followed by vector retrieval.

    - budget None (legacy direct call): compute the query vector.
    - budget.allow_embedding_compute (explicit offline): compute it.
    - otherwise (bounded turn): a cached query vector ONLY; on a cache
      miss vector retrieval is skipped (BM25 still serves context).
      ``embedder.encode`` is never called on the timed path.
    """
    if budget is None or getattr(budget, "allow_embedding_compute", True):
        if ensure_embedder_fn is not None:
            ensure_embedder_fn()
        if embedder is None:
            return []
        try:
            q_emb = embedder.encode(
                [query], normalize_embeddings=True
            ).tolist()[0]
        except Exception:
            return []
    else:
        if embedder is None:
            return []
        from src.context.embedding_cache import get_embedding_cache
        q_emb = get_embedding_cache().lookup(embedder, query)
        if q_emb is None:
            return []  # no cached query vector -> BM25 only, no inference
    if uses_vec:
        return search_vec_fast(
            conn=conn,
            write_lock=write_lock,
            q_emb=q_emb,
            limit=limit,
            knn_sql=knn_sql,
            fullscan_sql=fullscan_sql,
        )
    return search_vec_linear(conn=conn, write_lock=write_lock, q_emb=q_emb, limit=limit)


__all__ = [
    "_VEC0_KNN_SQL",
    "_VEC0_FULLSCAN_SQL",
    "VEC0_KNN_SQL",
    "VEC0_FULLSCAN_SQL",
    "l2_distance_to_cosine_similarity",
    "dot_product_to_unit_score",
    "search_vec_fast",
    "search_vec_linear",
    "search_vector",
]

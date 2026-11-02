"""
Context Retrieval Keyword Search
================================

Keyword / BM25 full-text search over code chunks via SQLite FTS5.

Invariants:
- Query text is sanitized into quoted OR-joined words (`"term1" OR "term2"`)
  so raw queries with brackets, parens, or operators never cause syntax errors.
- Token count capped at FTS_MAX_TOKENS_PER_QUERY (default 12).
- Returns 0-indexed rank positions as floats: [(chunk_id, 0.0), (chunk_id, 1.0), ...]
  because raw FTS5 `rank` values are not directly comparable to vector distances.
- RRF combines these positions with vector positions.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any, Sequence

FTS_MAX_TOKENS_PER_QUERY: int = 12
DEFAULT_FTS_MAX_TOKENS: int = FTS_MAX_TOKENS_PER_QUERY

FTS_SEARCH_SQL: str = """
    SELECT chunk_id FROM chunk_fts
    WHERE chunk_fts MATCH ?
    ORDER BY rank
    LIMIT ?
"""


def sanitize_fts_query(
    query: str,
    max_tokens: int = FTS_MAX_TOKENS_PER_QUERY,
) -> str:
    """Sanitize raw query text into safe FTS5 query string.

    Extracts word tokens (lowercased), caps at max_tokens, and formats each
    as a quoted token separated by OR. Returns an empty string if no alphanumeric
    tokens are found.
    """
    tokens = re.findall(r"\w+", query.lower())[:max_tokens]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def search_bm25(
    conn: sqlite3.Connection,
    write_lock: threading.Lock | Any,
    query: str,
    limit: int,
    max_tokens: int = FTS_MAX_TOKENS_PER_QUERY,
    query_sql: str = FTS_SEARCH_SQL,
) -> list[tuple[str, float]]:
    """Execute FTS5 BM25 search and return rank positions [(chunk_id, rank_pos), ...].

    Raw task text is not valid FTS5 syntax (parens, colons, AND/OR...).
    Tokenize to words and OR-join them as quoted phrases — this can
    never produce a syntax error, so the except is truly exceptional.
    """
    safe_query = sanitize_fts_query(query, max_tokens=max_tokens)
    if not safe_query:
        return []

    with write_lock:
        try:
            rows = conn.execute(query_sql, (safe_query, limit)).fetchall()
        except Exception:
            return []

    # Return rank POSITIONS (0, 1, 2...); raw `rank` values are not
    # comparable to vector distances, so RRF consumes positions only.
    return [(r[0], float(i)) for i, r in enumerate(rows)]


keyword_search = search_bm25

__all__ = [
    "FTS_MAX_TOKENS_PER_QUERY",
    "DEFAULT_FTS_MAX_TOKENS",
    "FTS_SEARCH_SQL",
    "sanitize_fts_query",
    "search_bm25",
    "keyword_search",
]

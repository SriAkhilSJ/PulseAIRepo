"""Tests for modular keyword search implementation (src.context.retrieval.keyword_search)."""

import sqlite3
import threading
from unittest.mock import MagicMock

import pytest

from src.context.retrieval.keyword_search import (
    DEFAULT_FTS_MAX_TOKENS,
    FTS_MAX_TOKENS_PER_QUERY,
    FTS_SEARCH_SQL,
    keyword_search,
    sanitize_fts_query,
    search_bm25,
)


def test_sanitize_fts_query():
    # Empty query
    assert sanitize_fts_query("") == ""
    assert sanitize_fts_query("   !@#$%^&*()   ") == ""

    # Complex punctuation / code syntax
    sanitized = sanitize_fts_query("fix(parser): auth{token}[broken] AND/OR")
    assert sanitized == '"fix" OR "parser" OR "auth" OR "token" OR "broken" OR "and" OR "or"'

    # Max tokens limit
    long_query = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    capped = sanitize_fts_query(long_query, max_tokens=5)
    assert capped == '"one" OR "two" OR "three" OR "four" OR "five"'


def test_search_bm25_empty_query():
    conn = MagicMock()
    lock = threading.Lock()
    assert search_bm25(conn, lock, "", limit=5) == []
    assert search_bm25(conn, lock, "   !@#   ", limit=5) == []
    conn.execute.assert_not_called()


def test_search_bm25_fts_in_memory():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, body)")
    conn.execute("INSERT INTO chunk_fts VALUES ('c1', 'authentication token parser')")
    conn.execute("INSERT INTO chunk_fts VALUES ('c2', 'database connection manager')")
    conn.execute("INSERT INTO chunk_fts VALUES ('c3', 'token refresh service')")

    lock = threading.Lock()
    results = search_bm25(conn, lock, "token parser", limit=5)

    assert len(results) >= 1
    # First item should be c1 (matches both tokens)
    assert results[0][0] == "c1"
    # Result scores are 0-indexed rank positions (float)
    assert results[0][1] == 0.0
    if len(results) > 1:
        assert results[1][1] == 1.0


def test_search_bm25_sql_error_handled_cleanly():
    conn = MagicMock()
    lock = threading.Lock()
    conn.execute.side_effect = sqlite3.OperationalError("fts table corrupted")

    # Should not raise, returns empty list
    results = search_bm25(conn, lock, "some query", limit=5)
    assert results == []


def test_chunk_index_reexports_fts_constants():
    from src.context.chunk_index import FTS_MAX_TOKENS_PER_QUERY as CI_MAX_TOKENS
    assert CI_MAX_TOKENS == FTS_MAX_TOKENS_PER_QUERY == DEFAULT_FTS_MAX_TOKENS == 12

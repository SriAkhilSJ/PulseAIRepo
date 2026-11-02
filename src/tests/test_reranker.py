"""Tests for modular reranker implementation (src.context.retrieval.reranker)."""

from dataclasses import dataclass
from typing import Optional

import pytest

from src.context.retrieval.reranker import (
    RERANK_WEIGHTS,
    _RERANK_W,
    _is_test_path,
    _word_parts,
    compute_rerank_bonus,
    extract_word_parts,
    is_test_path,
    rerank,
    rerank_chunks,
)


@dataclass
class DummyChunk:
    id: str
    file_path: str
    symbol_name: str
    symbol_type: str = "function"
    docstring: Optional[str] = None
    score: float = 0.5
    modified_time: float = 0.0


def test_word_parts_snake_and_camel_case():
    assert _word_parts("parse_auth_token") == {"parse", "auth", "token"}
    assert extract_word_parts("HTTPServerError") == {"http", "server", "error"}
    assert _word_parts("getUserById") == {"get", "user", "by", "id"}
    assert _word_parts("") == set()


def test_is_test_path_detection():
    assert _is_test_path("tests/test_cache.py")
    assert _is_test_path("src/tests/test_utils.py")
    assert _is_test_path("pkg/cache_test.py")
    assert is_test_path("deep/nested/tests/foo.py")
    assert not _is_test_path("src/cache.py")
    assert not is_test_path("src/context/retrieval/reranker.py")


def test_rerank_empty_and_trivial():
    assert rerank_chunks([], "query") == []
    c1 = DummyChunk(id="1", file_path="a.py", symbol_name="func1", score=1.0)
    assert rerank_chunks([c1], "query") == [c1]
    c2 = DummyChunk(id="2", file_path="b.py", symbol_name="func2", score=0.5)
    # Empty query preserves order
    assert rerank_chunks([c1, c2], "") == [c1, c2]


def test_rerank_exact_name_boost():
    c1 = DummyChunk(id="1", file_path="pkg/other.py", symbol_name="validate_user", score=0.9)
    c2 = DummyChunk(id="2", file_path="pkg/auth.py", symbol_name="parse_token", score=0.8)
    
    # Query mentions parse_token exactly
    res = rerank_chunks([c1, c2], "how does parse_token work?")
    assert res[0].id == "2"
    assert res[1].id == "1"


def test_rerank_test_demotion():
    c_impl = DummyChunk(id="impl", file_path="src/service.py", symbol_name="serve", score=0.8)
    c_test = DummyChunk(id="test", file_path="tests/test_service.py", symbol_name="serve", score=0.85)

    # For non-test query, implementation beats test file
    res = rerank_chunks([c_test, c_impl], "service serve requests")
    assert res[0].id == "impl"

    # For test-specific query, test file is not demoted
    res_test_q = rerank_chunks([c_test, c_impl], "test service serve")
    assert res_test_q[0].id == "test"


def test_rerank_freshest_file_wins_tie():
    c1 = DummyChunk(id="old", file_path="src/a.py", symbol_name="util", score=0.5, modified_time=100.0)
    c2 = DummyChunk(id="new", file_path="src/b.py", symbol_name="util", score=0.5, modified_time=200.0)

    res = rerank([c1, c2], "util function")
    assert res[0].id == "new"


def test_rerank_stable_tie_breaking():
    c1 = DummyChunk(id="first", file_path="src/a.py", symbol_name="foo", score=0.5)
    c2 = DummyChunk(id="second", file_path="src/b.py", symbol_name="bar", score=0.5)

    # When query gives zero feature bonuses to both, original order is preserved
    res = rerank_chunks([c1, c2], "unrelated query with no matches")
    assert [c.id for c in res] == ["first", "second"]


def test_custom_weights_support():
    c1 = DummyChunk(id="doc", file_path="src/a.py", symbol_name="func", docstring="Documentation", score=0.5)
    c2 = DummyChunk(id="nodoc", file_path="src/b.py", symbol_name="func", docstring=None, score=0.5)

    custom_w = dict(_RERANK_W)
    custom_w["docstring"] = 10.0

    res = rerank_chunks([c2, c1], "func", weights=custom_w)
    assert res[0].id == "doc"

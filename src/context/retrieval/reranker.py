"""
Context Retrieval Reranker
==========================

Feature-based reranker over candidate code chunks.

Invariants:
- Zero LLM calls, zero embedder calls (arithmetic on fetched metadata fields).
- Normalized base score stays the foundation — features nudge, they do not
  replace retrieval.
- Stable sort: zero-feature queries yield byte-identical order to base retrieval.
- Deterministic given (query, candidates, mtimes).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Sequence, TypeVar

if TYPE_CHECKING:
    from src.context.chunk_index import ChunkResult

T = TypeVar("T")

# ---------------------------------------------------------------------
# Feature weights and thresholds for candidate reranking
# ---------------------------------------------------------------------

_RERANK_W: dict[str, float] = {
    "name_exact": 4.0,   # literal `parse_auth_token` appears in the query
    "name_part": 0.6,    # per matched symbol-name part (snake/camel), cap 3
    "path_token": 1.0,   # file-stem part appears in the query ("auth ...")
    "hot": 0.5,          # freshest file among the candidates
    "test_demote": -2.5, # test file, when the query is not test-ish
    "docstring": 0.2,    # documented API preference
}
_RERANK_NAME_PART_CAP: int = 3
_RERANK_MIN_WORD: int = 3     # query words shorter than this never count as hints
_RERANK_TESTISH: set[str] = {"test", "tests", "testing", "pytest", "unittest", "spec", "specs"}

# Public aliases
RERANK_WEIGHTS = _RERANK_W
RERANK_NAME_PART_CAP = _RERANK_NAME_PART_CAP
RERANK_MIN_WORD = _RERANK_MIN_WORD
RERANK_TESTISH = _RERANK_TESTISH


def _word_parts(text: str) -> set[str]:
    """snake_case AND camelCase aware word splitting; lowered parts.

    'parse_auth_token' -> {parse, auth, token, parse_auth_token? no — parts}.
    Used symmetrically on queries and symbol/file names so a snake-cased
    symbol name can match both the full token and its parts.
    """
    parts: set[str] = set()
    for tok in re.findall(r"[A-Za-z0-9]+", text):
        for piece in re.split(r"_+", tok):
            if not piece:
                continue
            for sub in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+", piece):
                parts.add(sub.lower())
    return parts


def _is_test_path(file_path: str) -> bool:
    """Return True if the file path indicates a test file."""
    p = Path(file_path)
    name = p.name.lower()
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in p.parts


extract_word_parts = _word_parts
is_test_path = _is_test_path


def compute_rerank_bonus(
    item: Any,
    query_lower: str,
    query_words: set[str],
    is_test_query: bool,
    has_hot_candidates: bool,
    max_modified_time: float,
    weights: dict[str, float] = _RERANK_W,
    name_part_cap: int = _RERANK_NAME_PART_CAP,
) -> float:
    """Compute additive bonus score for a candidate chunk result."""
    b = 0.0
    name = getattr(item, "symbol_name", None)
    if name and name != "(module)":
        if name.lower() in query_lower:
            b += weights["name_exact"]
        else:
            overlap = (query_words & _word_parts(name)) if query_words else set()
            b += weights["name_part"] * min(len(overlap), name_part_cap)

    file_path = getattr(item, "file_path", "")
    stem = Path(file_path).stem if file_path else ""
    if query_words and stem:
        if query_words & _word_parts(stem):
            b += weights["path_token"]

    modified_time = getattr(item, "modified_time", 0.0)
    if has_hot_candidates and modified_time == max_modified_time:
        b += weights["hot"]

    if file_path and _is_test_path(file_path) and not is_test_query:
        b += weights["test_demote"]

    if getattr(item, "docstring", None):
        b += weights["docstring"]

    return b


def rerank_chunks(
    results: Sequence[T],
    query: str,
    weights: dict[str, float] | None = None,
) -> list[T]:
    """Feature re-rank over the fused set.

    Invariants:
    - zero LLM calls, zero embedder calls (arithmetic on fetched fields);
    - normalized base score stays the base — features nudge, they do not
      replace retrieval;
    - Python's sort is STABLE, so a zero-feature query yields
      byte-identical order to pre-rerank order;
    - deterministic given (query, candidate contents, mtimes).
    """
    if len(results) <= 1 or not query:
        return list(results)

    w = weights if weights is not None else _RERANK_W
    qtext = query.lower()
    qwords = {wrd for wrd in _word_parts(query) if len(wrd) >= _RERANK_MIN_WORD}
    test_query = bool(qwords & _RERANK_TESTISH)

    mtimes = [getattr(r, "modified_time", 0.0) for r in results]
    max_mtime = max(mtimes) if mtimes else 0.0
    has_hot = len(set(mtimes)) > 1

    max_score = max((getattr(r, "score", 0.0) for r in results), default=0.0)

    scored = [
        (
            ((getattr(r, "score", 0.0) / max_score if max_score > 0 else 0.0) +
             compute_rerank_bonus(
                 r,
                 query_lower=qtext,
                 query_words=qwords,
                 is_test_query=test_query,
                 has_hot_candidates=has_hot,
                 max_modified_time=max_mtime,
                 weights=w,
                 name_part_cap=_RERANK_NAME_PART_CAP,
             )),
            r,
        )
        for r in results
    ]
    scored.sort(key=lambda t: t[0], reverse=True)  # stable: ties keep RRF order
    return [r for _s, r in scored]


rerank = rerank_chunks

__all__ = [
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
]

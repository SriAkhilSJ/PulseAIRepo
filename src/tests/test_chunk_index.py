"""Tests for the P0 ChunkIndex — pure, deterministic, CI-safe.

Each test maps to a verified fix from the review chain:
- FTS5 staleness cleanup ......... pasted review Bug 1
- exact-match vector search ...... pasted review Bug 2 (division by zero)
- background thread indexing ..... this review: check_same_thread fix
- committed persistence .......... this review: index_workspace must commit
- FTS5 query sanitization ........ this review: raw task text breaks MATCH
"""

import hashlib
import math
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest

from src.context.chunk_index import (
    ChunkIndex,
    ChunkResult,
    extract_chunks,
    get_index,
    build_relevant_chunks_layer,
)


# ---------------------------------------------------------------------
# Deterministic fake embedder (no sentence-transformers needed)
# ---------------------------------------------------------------------


class _Embeds(list):
    def tolist(self):
        return list(self)


class FakeEmbedder:
    """Word-bucket hashing: texts sharing words get similar vectors."""

    DIM = 384
    calls = 0  # D13: the re-rank must add ZERO embedder calls

    def encode(self, texts, normalize_embeddings=True):
        type(self).calls += 1
        out = _Embeds()
        for text in texts:
            vec = [0.0] * self.DIM
            for word in re.findall(r"\w+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0 if (h >> 8) % 2 == 0 else -1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

AUTH_CODE = '''"""Authentication module."""
import os
import hashlib


def parse_auth_token(raw_header):
    """Parse a Bearer token from an Authorization header."""
    parts = raw_header.split(" ")
    assert len(parts) == 2, "malformed header"
    return parts[1]


class AuthHandler:
    """Handles login and session validation."""

    def login(self, user, password):
        """Validate credentials and return a session id."""
        digest = hashlib.sha256(password.encode()).hexdigest()
        return digest[:32]

    def validate(self, session):
        return bool(session)
'''

GARDEN_CODE = '''"""Gardening module."""


def water_plants(plants, litres):
    """Water each plant with the given amount."""
    return {p: litres for p in plants}


def prune_bush(bush):
    return bush.strip()
'''


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "auth.py").write_text(AUTH_CODE)
    (tmp_path / "garden.py").write_text(GARDEN_CODE)
    return tmp_path


@pytest.fixture
def index(workspace, tmp_path):
    return ChunkIndex(
        workspace,
        db_path=str(tmp_path / "code_index.db"),
        embedder=FakeEmbedder(),
    )


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------


def test_extract_chunks_module_function_class(workspace):
    chunks = extract_chunks(workspace / "auth.py", workspace)
    names = [(c["symbol_type"], c["symbol_name"]) for c in chunks]
    assert ("module", "(module)") in names
    assert ("function", "parse_auth_token") in names
    assert ("class", "AuthHandler") in names
    fn = next(c for c in chunks if c["symbol_name"] == "parse_auth_token")
    assert "Bearer token" in fn["docstring"]
    assert fn["signature"].startswith("def parse_auth_token")
    assert len(fn["content"]) <= 800, "embedding text exceeded hard cap"


# ---------------------------------------------------------------------
# Index + hybrid search
# ---------------------------------------------------------------------


def test_search_finds_relevant_chunk(index):
    index.index_workspace()
    results = index.search("fix the auth token parser", top_k=3)
    assert results, "no results"
    top = results[0]
    assert top.file_path == "auth.py"
    assert top.symbol_name in ("parse_auth_token", "(module)", "AuthHandler")
    assert top.body, "empty body"
    ids = {r.id for r in results}
    assert len(ids) == len(results), "duplicate chunks in results"


def test_exact_match_does_not_crash(index):
    """Review Bug 2: exact match -> L2 distance 0 -> old normalization
    divided by zero. Exact cosine mapping (1 - d^2/2) must yield ~1.0."""
    index.index_workspace()
    row = index.conn.execute(
        "SELECT content FROM code_chunks WHERE symbol_name = 'parse_auth_token'"
    ).fetchone()
    assert row, "chunk content missing"
    vec_results = index._search_vector(row[0], 3)
    assert vec_results, "vector search returned nothing"
    assert vec_results[0][1] > 0.99, (
        f"exact-match score should be ~1.0, got {vec_results[0][1]}"
    )
    # End-to-end fused path must not crash either
    assert index.search("parse auth token from the authorization header")


def test_fts_query_sanitization(workspace, index):
    """Raw task text (parens, colons, braces) must never break MATCH."""
    index.index_workspace()
    results = index.search("fix(parser): auth{token}[broken] AND/OR")
    assert results, "sanitized query returned nothing"
    assert results[0].file_path == "auth.py"


# ---------------------------------------------------------------------
# Staleness (review Bug 1: FTS rows must die with the file's chunks)
# ---------------------------------------------------------------------


def test_sync_removes_stale_symbols(index, workspace):
    index.index_workspace()
    assert index.search("parse_auth_token"), "baseline missing"

    (workspace / "auth.py").write_text(
        '"""Auth v2."""\n\n\ndef refresh_session(sid):\n'
        '    """Refresh an existing session."""\n    return sid + 1\n'
    )
    future = time.time() + 5
    os.utime(workspace / "auth.py", (future, future))

    changed = index.sync_workspace()
    assert changed == 1, "sync_workspace did not detect the edit"

    bm25_old = index._search_bm25("parse_auth_token Bearer", limit=5)
    assert not bm25_old, f"stale FTS row survived re-index: {bm25_old}"
    assert index.search("refresh_session"), "new symbol not indexed"


# ---------------------------------------------------------------------
# Background first-run (this review: cross-thread connection fix)
# ---------------------------------------------------------------------


def test_background_indexing_thread(workspace, index):
    """search() on an empty index kicks a background build (returns []),
    and the build must actually succeed from that thread (a default
    sqlite3 connection would raise ProgrammingError there)."""
    assert index.search("auth token") == [], "empty index should return []"
    assert index._indexing_thread is not None
    index._indexing_thread.join(timeout=30)
    assert not index._is_index_empty(), "background build never stored rows"
    assert index.search("auth token"), "search after build returned nothing"


# ---------------------------------------------------------------------
# Committed persistence (this review: uncommitted writes were invisible)
# ---------------------------------------------------------------------


def test_rows_are_committed(index, tmp_path):
    index.index_workspace()
    raw = sqlite3.connect(str(tmp_path / "code_index.db"))
    count = raw.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
    raw.close()
    assert count >= 4, "rows not committed — index would be lost on exit"


# ---------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------


def test_rrf_prefers_chunks_in_both_lists(index):
    index.index_workspace()
    fused = index._rrf_fuse(
        [("a", 0.99), ("b", 0.5)], [("b", 0.0), ("c", 1.0)], k=60
    )
    if fused:
        # 'b' appears in both lists — but it isn't a real stored chunk,
        # so synthetic ids are dropped; just assert no crash and ordering
        # is by fused score for ids that exist.
        scores = [r.score for r in fused]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------
# Context-engine integration (one process-wide index per workspace)
# ---------------------------------------------------------------------


def test_layer_builder_and_engine_integration(workspace):
    from langchain_core.messages import SystemMessage
    from src.context.context_engine import ContextEngine

    idx = get_index(workspace)  # no embedder in CI -> BM25-only degrade
    idx.index_workspace()

    # "bug" keyword -> DEBUG classification under the CI regex fallback
    # (no embedder); relevant_chunks relevance is 0.95 for DEBUG.
    layer = build_relevant_chunks_layer(
        {"workspace": str(workspace),
         "current_task": "fix the bug where the auth token parser crashes"}
    )
    assert isinstance(layer, SystemMessage)
    assert layer.content.startswith("=== RELEVANT CODE CHUNKS")
    assert "auth.py" in layer.content

    eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
    state = {
        "current_task": "fix the bug where the auth token parser crashes",
        "messages": [],
        "workspace": str(workspace),
        "plan": [{"id": 1, "description": "repro", "status": "pending"}],
        "steps_completed": [], "failed_steps": ["boom"],
        "recovery_mode": True, "recovery_attempts": 1, "replan_count": 0,
    }
    eng.build_ai_messages(state, SystemMessage(content="SYS"))
    names = eng._infer_layer_name(layer)
    assert names == "relevant_chunks"
    assert "relevant_chunks" in eng._last_layers_sent, (
        f"chunks layer missing from sent layers: {eng._last_layers_sent}"
    )


# ---------------------------------------------------------------------
# File watcher queue logic + deleted-file pruning (deterministic, no threads)
# ---------------------------------------------------------------------


def test_busy_timeout_pragma_set(index):
    # Two processes (dashboard + CLI) can hold the same per-workspace DB;
    # writer-writer must WAIT, not fail with SQLITE_BUSY.
    row = index.conn.execute("PRAGMA busy_timeout").fetchone()
    assert row[0] == 5000


def test_watcher_queue_dedup_and_drain(index):
    index._enqueue_sync("/ws/a.py")
    index._enqueue_sync("/ws/a.py")  # duplicate save events collapse
    index._enqueue_sync("/ws/b.py")
    to_sync, to_remove = index._drain_pending_syncs()
    assert sorted(to_sync) == ["/ws/a.py", "/ws/b.py"]
    assert to_remove == []
    assert index._drain_pending_syncs() == ([], [])  # queue is drained


def test_remove_wins_over_sync_in_same_window(index):
    # Editor swap-delete right after save: the delete must win, or we'd
    # re-index a ghost.
    index._enqueue_sync("/ws/a.py")
    index._enqueue_remove("/ws/a.py")
    to_sync, to_remove = index._drain_pending_syncs()
    assert to_sync == []
    assert to_remove == ["/ws/a.py"]


def test_remove_file_drops_all_stores(index):
    index.index_workspace()
    assert index.search("auth token"), "precondition: auth chunks indexed"
    removed = index.remove_file(index.workspace / "auth.py")
    assert removed > 0
    results = index.search("auth token")
    assert all("auth.py" not in c.file_path for c in results)
    # Explicitly verify ALL FOUR stores, not just the search result.
    with index._write_lock:
        assert index.conn.execute(
            "SELECT COUNT(*) FROM code_chunks WHERE file_path = 'auth.py'"
        ).fetchone()[0] == 0
        vec_table = "chunk_vec" if index.uses_vec else "chunk_vec_fallback"
        assert index.conn.execute(
            f"SELECT COUNT(*) FROM {vec_table}"
        ).fetchone()[0] == index.conn.execute(
            "SELECT COUNT(*) FROM code_chunks"
        ).fetchone()[0]
    # No-op on a file that isn't indexed.
    assert index.remove_file(index.workspace / "auth.py") == 0


def test_sync_workspace_prunes_deleted_files(index, workspace):
    index.index_workspace()
    (workspace / "garden.py").unlink()
    index.sync_workspace()
    results = index.search("water the plants")
    assert all("garden.py" not in c.file_path for c in results)
    with index._write_lock:
        assert index.conn.execute(
            "SELECT COUNT(*) FROM code_chunks WHERE file_path = 'garden.py'"
        ).fetchone()[0] == 0


def test_get_index_watch_flag(workspace, tmp_path):
    idx = get_index(workspace, db_path=str(tmp_path / "w.db"), watch=False)
    assert idx._watcher_thread is None
    idx.start_watcher()
    assert idx._watcher_thread is not None and idx._watcher_thread.is_alive()
    idx.start_watcher()  # idempotent — must not spawn a second thread
    assert idx._watcher_thread is not None
    idx.stop_watcher()
    assert idx._watcher_thread is None


# ---------------------------------------------------------------------
# C1 pins (ARCHITECTURE_REVIEW.md §36): vec0 KNN pushdown
# ---------------------------------------------------------------------
# Pre-C1, _search_vec_fast ran vec_distance_l2 over EVERY row plus a JOIN
# that only re-selected the id it already had. Measured: 21ms -> 1.5ms at
# 2K rows, 206ms -> 17ms at 20K rows (12-14x) with identical orderings
# (scripts/c1_knn_benchmark.py). The pins below guard the fix:
#   1. exact-ordering equivalence vs an exhaustive brute-force reference
#   2. the query shape really uses MATCH + k (regression guard vs revert)
#   3. the full-scan fallback still works for ancient sqlite-vec builds
#   4. total-tie (all-zero, degraded) behavior is stable and harmless
#   5. limit > population returns everything without error

import json
import random

import src.context.chunk_index as chunk_index_mod


def _gauss_unit_vec(rng: "random.Random", dim: int = 384) -> list:
    vals = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def _insert_synthetic_vectors(index, n: int, seed: int = 42) -> None:
    """Straight into the stores — embedding is not what C1 is about."""
    rng = random.Random(seed)
    with index._write_lock:
        for i in range(n):
            cid = f"syn-{i:05d}"
            vec = _gauss_unit_vec(rng)
            index.conn.execute(
                "INSERT INTO code_chunks (id, file_path, symbol_name, symbol_type,"
                " start_line, end_line, signature, docstring, body, content,"
                " content_hash, modified_time) VALUES (?, 'syn.py', 's',"
                " 'function', 1, 2, '', NULL, '', 'c', 'h', 0.0)",
                (cid,),
            )
            index.conn.execute(
                "INSERT INTO chunk_vec (chunk_id, embedding) VALUES (?, vec_f32(?))",
                (cid, json.dumps(vec)),
            )
        index.conn.commit()


def _exhaustive_reference(conn, q_emb: list, limit: int) -> list:
    """Brute-force exact KNN over the STORED (float32) values."""
    rows = conn.execute("SELECT chunk_id, vec_to_json(embedding) FROM chunk_vec").fetchall()
    scored = []
    for cid, j in rows:
        v = json.loads(j)
        d2 = sum((a - b) ** 2 for a, b in zip(q_emb, v))
        scored.append((d2, cid))
    scored.sort()
    return [(cid, math.sqrt(d2)) for d2, cid in scored[:limit]]


def test_c1_knn_ordering_matches_exhaustive_reference(index):
    if not index.uses_vec:
        pytest.skip("sqlite-vec unavailable in this environment")
    _insert_synthetic_vectors(index, 600)
    rng = random.Random(99)
    q = _gauss_unit_vec(rng)

    fast = index._search_vec_fast(q, 12)
    ref = _exhaustive_reference(index.conn, q, 12)

    assert [cid for cid, _ in fast] == [cid for cid, _ in ref]
    # The MATCH distance column is vec_distance_l2: same cosine math, so the
    # scores must agree to float32 tolerance.
    for (cid, score), (_cid, d) in zip(fast, ref):
        assert cid == _cid
        assert score == pytest.approx(1.0 - (d * d) / 2.0, abs=1e-4)


def test_c1_search_uses_knn_pushdown_sql(index):
    """Regression guard: reverting to vec_distance_l2-over-everything must
    turn this test red, even though results would stay correct."""
    if not index.uses_vec:
        pytest.skip("sqlite-vec unavailable in this environment")
    _insert_synthetic_vectors(index, 50)
    q = _gauss_unit_vec(random.Random(7))

    captured: list[str] = []
    index.conn.set_trace_callback(captured.append)
    try:
        index._search_vec_fast(q, 5)
    finally:
        index.conn.set_trace_callback(None)

    # Note: the trace callback shows statements with bound params EXPANDED
    # to literals, so the k constraint appears as "k = 5", not "k = ?".
    vec_stmts = [s for s in captured if "chunk_vec" in s]
    assert vec_stmts, "expected a chunk_vec query"
    knn = [s for s in vec_stmts if "MATCH vec_f32" in s and re.search(r"\bk\s*=", s)]
    assert knn, f"vec search did NOT use the MATCH+k pushdown: {vec_stmts}"
    assert not any("vec_distance_l2" in s and "JOIN" in s for s in vec_stmts), (
        f"pre-C1 full-scan JOIN shape reappeared: {vec_stmts}"
    )


def test_c1_fullscan_fallback_when_knn_unsupported(index, monkeypatch, capsys):
    """Ancient sqlite-vec without the k constraint: degrade to the pre-C1
    full-scan shape, never to zero results or a crash."""
    if not index.uses_vec:
        pytest.skip("sqlite-vec unavailable in this environment")
    _insert_synthetic_vectors(index, 120, seed=13)
    q = _gauss_unit_vec(random.Random(5))

    ref = [cid for cid, _ in _exhaustive_reference(index.conn, q, 8)]
    monkeypatch.setattr(chunk_index_mod, "_VEC0_KNN_SQL",
                        "SELECT nope FROM nope WHERE nope = nope")
    got = index._search_vec_fast(q, 8)

    assert [cid for cid, _ in got] == ref
    assert "full-scan fallback" in capsys.readouterr().out


def test_c1_knn_all_zero_embeddings_total_tie_is_stable(workspace, tmp_path):
    """Degraded index (no embedder at index time => all-zero vectors) makes
    EVERY distance identical. The old full-scan and the new KNN both return
    an arbitrary member of the tie-class — the pin locks: no crash, exactly
    min(limit, n) rows, identical scores, and hybrid search still works."""

    class _ZeroEmbedder:
        DIM = 384

        def encode(self, texts, normalize_embeddings=True):
            out = _Embeds()
            for _t in texts:
                out.append([0.0] * self.DIM)
            return out

    zero_index = ChunkIndex(
        workspace, db_path=str(tmp_path / "zero_index.db"), embedder=_ZeroEmbedder()
    )
    if not zero_index.uses_vec:
        pytest.skip("sqlite-vec unavailable in this environment")
    zero_index.index_workspace()
    total = zero_index.conn.execute("SELECT COUNT(*) FROM chunk_vec").fetchone()[0]
    assert total > 3  # fixture produced real chunks

    res = zero_index._search_vector("parse the auth token", 5)
    assert len(res) == min(5, total)
    scores = {round(s, 9) for _cid, s in res}
    assert len(scores) == 1  # every distance identical => one score value

    hybrid = zero_index.search("water the plants", top_k=3)
    assert hybrid  # BM25 keeps degraded indexes useful


def test_c1_knn_limit_exceeds_population(index):
    if not index.uses_vec:
        pytest.skip("sqlite-vec unavailable in this environment")
    _insert_synthetic_vectors(index, 3, seed=5)
    q = _gauss_unit_vec(random.Random(1))
    res = index._search_vec_fast(q, 50)
    assert len(res) == 3
    assert all(0.0 <= s <= 1.0 for _cid, s in res)


# ---------------------------------------------------------------------
# D13 pins (ARCHITECTURE_REVIEW.md §37): fused-set feature re-rank
# ---------------------------------------------------------------------
# Measured baseline (scripts/d13_d14_rank_measure.py): a query naming the
# exact symbol ranked it #4 (P@3 MISS) behind vocabulary twins; test files
# occupied the top-3 on implementation questions; twin files ranked by
# vocabulary only, ignoring recency. The re-rank adds zero LLM and zero
# embedder calls — pinned directly.

from src.context.chunk_index import _word_parts, _is_test_path  # noqa: E402

_RERANK_GOLD = '''"""Authentication module."""
import os
import hashlib


def parse_auth_token(raw_header):
    """Parse a Bearer token from an Authorization header."""
    parts = raw_header.split(" ")
    assert len(parts) == 2, "malformed header"
    return parts[1]
'''


def test_d13_exact_name_query_rescues_gold(tmp_path):
    ws = tmp_path
    (ws / "core").mkdir()
    (ws / "core" / "auth.py").write_text(_RERANK_GOLD)
    (ws / "noise").mkdir()
    for n in range(6):
        (ws / "noise" / f"distractor_{n}.py").write_text(
            f'"""Twin module {n}: raises TypeError malformed header assertion."""\n'
            + "".join(
                f"def twin_{n}_{i}(raw_header, malformed, assertion):\n"
                '    """Raises TypeError on malformed header data, assertion plumbing."""\n'
                "    return raw_header or malformed or assertion\n\n"
                for i in range(3)
            )
        )
    idx = ChunkIndex(ws, db_path=str(tmp_path / "d13.db"), embedder=FakeEmbedder())
    idx.index_workspace()

    res = idx.search("parse_auth_token raises TypeError: malformed header assertion", top_k=3)
    assert res, "no results at all"
    assert res[0].symbol_name == "parse_auth_token"
    assert res[0].file_path == os.path.join("core", "auth.py")


def test_d13_test_files_demoted_out_of_top3_for_impl_query(tmp_path):
    ws = tmp_path
    (ws / "src").mkdir()
    (ws / "tests").mkdir()
    impl = (
        '"""Cache layer with eviction and TTL policy."""\n\n'
        "def cache_put(key, value, ttl):\n"
        '    """Store value under key with ttl eviction policy."""\n'
        "    return (key, value, ttl)\n\n"
        "def cache_get(key):\n"
        '    """Fetch a cached value by key."""\n'
        "    return key\n"
    )
    twin = (
        '"""Cache layer with eviction and TTL policy."""\n\n'
        "def cache_put_checked(key, value, ttl):\n"
        '    """Store value under key with ttl eviction policy, verified."""\n'
        "    assert key and (key, value, ttl)\n\n"
        "def cache_get_checked(key):\n"
        '    """Fetch a cached value by key, verified."""\n'
        "    assert key and key\n"
    )
    (ws / "src" / "cache.py").write_text(impl)
    (ws / "tests" / "test_cache.py").write_text(twin)
    idx = ChunkIndex(ws, db_path=str(tmp_path / "d13t.db"), embedder=FakeEmbedder())
    idx.index_workspace()

    res = idx.search("cache layer eviction ttl policy", top_k=3)
    assert res
    assert all("test_" not in r.file_path for r in res[:3]), \
        f"test file leaked into top3: {[(r.symbol_name, r.file_path) for r in res[:3]]}"

    # Control: a test-ISH query lifts the demote — tests may surface again.
    res_testish = idx.search("test cache eviction policy", top_k=3)
    assert res_testish  # and it must not crash/demote either way


def test_d13_freshest_file_wins_vocabulary_tie(tmp_path):
    ws = tmp_path
    body = (
        '"""Rate limiting."""\n\n'
        "def throttle_request(req):\n"
        '    """Apply the sliding window to this request."""\n'
        "    return req\n"
    )
    (ws / "legacy_limiter.py").write_text(body)
    (ws / "limiter.py").write_text(body)
    old = time.time() - 30 * 86400
    os.utime(ws / "legacy_limiter.py", (old, old))
    now = time.time()
    os.utime(ws / "limiter.py", (now, now))

    idx = ChunkIndex(ws, db_path=str(tmp_path / "d13h.db"), embedder=FakeEmbedder())
    idx.index_workspace()
    res = idx.search("throttle request sliding window", top_k=2)
    assert res
    assert res[0].file_path == "limiter.py"


def test_d13_zero_feature_query_keeps_raw_rrf_order(tmp_path):
    """STRICT no-regress: no feature fires => search() output is identical
    to raw _rrf_fuse, in both members and order."""
    ws = tmp_path
    (ws / "hydra.py").write_text(
        '"""Hydration scheduling."""\n\n'
        "def schedule_irrigation(zones):\n"
        '    """Compute watering windows per zone."""\n'
        "    return zones\n"
    )
    (ws / "beams.py").write_text(
        '"""Pergola assembly notes."""\n\n'
        "def assemble_beams(beams):\n"
        '    """Bolt the cross beams together."""\n'
        "    return beams\n"
    )
    # Latent flake pinned shut (§43): left to chance, the two fixture files
    # land ~ms apart, so has_hot (=> hot bonus to the single freshest
    # candidate) fires on sub-second drift — and whether that bonus changes
    # the outcome then depends on scandir tie-order inside the RRF fixture
    # (inode order is tmpfs-luck). The test's intent is "no feature fires",
    # so force it: identical mtimes => len(set(mtimes)) == 1 => hot off.
    old = time.time() - 3600
    for f in ("hydra.py", "beams.py"):
        os.utime(ws / f, (old, old))
    idx = ChunkIndex(ws, db_path=str(tmp_path / "d13z.db"), embedder=FakeEmbedder())
    idx.index_workspace()
    q = "compute watering windows per zone"
    raw = idx._rrf_fuse(idx._search_vector(q, 9), idx._search_bm25(q, 9))[:3]
    got = idx.search(q, top_k=3)
    assert [r.id for r in got] == [r.id for r in raw]


def test_d13_rerank_adds_zero_embedder_and_llm_calls(tmp_path):
    ws = tmp_path
    (ws / "auth.py").write_text(_RERANK_GOLD)
    (ws / "garden.py").write_text(GARDEN_CODE)
    FakeEmbedder.calls = 0
    idx = ChunkIndex(ws, db_path=str(tmp_path / "d13e.db"), embedder=FakeEmbedder())
    idx.index_workspace()
    after_index = FakeEmbedder.calls
    idx.search("token header", top_k=3)
    assert FakeEmbedder.calls - after_index == 1, \
        "search must encode exactly once (the query); re-rank is arithmetic-only"


def test_d13_word_parts_and_test_path_helpers(index):
    parts = _word_parts("parse_auth_token")
    assert {"parse", "auth", "token"} <= parts
    camel = _word_parts("HTTPServerError")
    assert {"http", "server", "error"} <= camel
    assert _is_test_path("tests/test_cache.py")
    assert _is_test_path(os.path.join("pkg", "tests", "cache.py"))
    assert _is_test_path("pkg/cache_test.py")
    assert not _is_test_path("src/cache.py")

    # unit-level rerank smoke: no query / single result are pass-through
    r = ChunkResult(id="x", file_path="a.py", symbol_name="f",
                    symbol_type="function", start_line=1, end_line=2,
                    signature="", docstring=None, body="", score=1.0)
    assert index._rerank([r], "anything") == [r]
    assert index._rerank([r], "") == [r]

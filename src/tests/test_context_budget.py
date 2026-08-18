"""P1: the shared initial-context deadline through the REAL consumers.

``ContextBudget`` is one deadline for the complete pipeline — scan -> read ->
chunk -> repo map -> index -> embed. These tests drive the actual consumers
(ChunkIndex sync/index, build_relevant_chunks_layer, RepoMap, conventions)
against synthetic trees, no model calls:

1. a 20,000-file workspace returns bounded initial context;
2. file / byte / per-file-size / elapsed limits each stop work;
3. excluded directories and .gitignore rules are respected;
4. oversized and binary files are skipped;
5. a symlink / junction cannot escape the workspace;
6. cancellation stops traversal and downstream work promptly;
7. downstream chunking/indexing shares the same deadline;
8. budget exhaustion returns partial context plus a degraded receipt;
9. unreadable / disappearing files do not fail the turn;
10. repeated preparation uses fingerprints/cache instead of rebuilding.

Plus one real wall-clock smoke test (default limits) to catch an accidental
unlimited walk.
"""

import hashlib
import math
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

from src.context.bounded_scan import ContextBudget, ScanLimits, scan_files
from src.context.chunk_index import ChunkIndex, build_relevant_chunks_layer
from src.dashboard.event_bus import event_bus


def _write_tree(root, spec, size_of=None):
    for rel, content in spec.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        elif content == "!!":
            p.write_bytes(b"\0" * (size_of or 1000))
        else:
            p.write_text(content)


def _py_sized(size_of):
    base = "def f():\n    pass\n"
    return base + "#" * max(0, size_of - len(base)) + "\n"


class _Embeds(list):
    def tolist(self):
        return list(self)


class FakeEmbedder:
    """Deterministic hash embedder; counts encode batches (test 10)."""

    DIM = 384  # must match ChunkIndex.EMBED_DIM (schema pins the column)
    calls = 0

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


@pytest.fixture
def index(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    idx = ChunkIndex(
        ws, db_path=str(tmp_path / "index.db"), embedder=FakeEmbedder(),
        watch=False,
    )
    idx.thread_id_hint = "t-budget"
    yield idx
    idx.stop_watcher()


def _drain(q):
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except Exception:
            return events


@pytest.fixture
def receipts():
    event_bus.clear()  # fresh history: only THIS test's receipts are seen
    q = event_bus.subscribe(thread_id=None)
    yield q
    event_bus.unsubscribe(q)


def _degraded(events):
    return [e["payload"] for e in events if e["type"] == "runtime.degraded"]


# ---------------------------------------------------------------------------
# 1 — a 20,000-file workspace returns BOUNDED initial context
# ---------------------------------------------------------------------------


def test_20k_workspace_initial_context_is_bounded(tmp_path, index, receipts):
    for d in range(200):
        (tmp_path / "ws" / f"dir{d:03d}").mkdir(parents=True, exist_ok=True)
        for i in range(100):
            (tmp_path / "ws" / f"dir{d:03d}" / f"f{i:03d}.py").write_text("x = 1\n")

    budget = ContextBudget(max_files=50, max_elapsed=0)
    changed = index.sync_workspace(budget)
    report = index._last_scan_report

    assert changed == 50, "sync must stop at the file budget, not scan everything"
    assert report.truncated is True
    assert report.files == 50
    # Read-once accounting: the file's decoded text is reused for BOTH chunk
    # extraction and import-edge resolution — one physical read per file.
    assert budget.read_files == report.files
    assert budget.elapsed < 30, "20k-file prep must not block for minutes"

    rows = index.conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
    assert rows > 0 and rows < 20_000, "partial context only"

    degraded = _degraded(_drain(receipts))
    assert degraded, "a truncated scan must emit a degraded receipt"
    assert degraded[0]["reason"] == "context scan bounded"
    assert degraded[0]["files_considered"] >= report.files
    assert degraded[0]["cancelled"] is False


# ---------------------------------------------------------------------------
# 2 — file / byte / per-file-size / elapsed limits each stop work
# ---------------------------------------------------------------------------


def test_byte_limit_stops_pipeline_before_read(tmp_path, index):
    for i in range(12):
        (tmp_path / "ws" / f"f{i:02d}.py").write_text("##" * 512)  # 1KiB each
    budget = ContextBudget(max_bytes=3 * 1024, max_elapsed=0, max_files=100)
    index.sync_workspace(budget)
    # The byte BUDGET is a consumption cap enforced at scan time (stat
    # size, before any read). Each consumed .py is then read EXACTLY ONCE
    # (decoded text reused for chunk + import extraction); read_bytes counts
    # those physical reads and can never exceed the 16 MiB-style cap.
    assert budget.read_files == 3
    assert budget.read_bytes <= 3 * 1024 + 64
    assert budget.read_bytes <= budget.max_bytes
    assert index._last_scan_report.reason == "bytes"


def test_per_file_size_cap_skips_oversize(tmp_path, index):
    (tmp_path / "ws" / "big.py").write_text(_py_sized(2048))
    (tmp_path / "ws" / "small.py").write_text("x = 1\n")
    budget = ContextBudget(max_file_bytes=1024, max_bytes=0, max_elapsed=0)
    index.sync_workspace(budget)
    report = index._last_scan_report
    assert report.skipped_oversize == 1
    assert report.files == 1
    rows = index.conn.execute(
        "SELECT COUNT(*) FROM code_chunks WHERE file_path = 'big.py'"
    ).fetchone()[0]
    assert rows == 0, "oversized file must not be chunked/embedded"


def test_elapsed_limit_stops_pipeline(tmp_path, index, receipts):
    for i in range(100):
        (tmp_path / "ws" / f"f{i:03d}.py").write_text("x = 1\n")
    budget = ContextBudget(max_elapsed=1e-9, max_files=1000)
    index.sync_workspace(budget)
    assert index._last_scan_report.truncated is True
    assert index._last_scan_report.reason in ("elapsed", "stopped")
    # Deadline exhaustion is honest evidence even at ZERO consumption — the
    # receipt must fire with zero counts, never be suppressed.
    degraded = _degraded(_drain(receipts))
    assert degraded, "deadline exhaustion must emit the receipt"
    r = degraded[0]
    assert r["reason"] == "context scan bounded"
    assert r["cancelled"] is False
    assert r["files_considered"] == 0
    assert r["files_read"] == 0
    assert r["bytes_read"] == 0
    assert r["elapsed_ms"] >= 0


# ---------------------------------------------------------------------------
# 3 — excluded directories and .gitignore rules are respected
# ---------------------------------------------------------------------------


def test_exclusions_and_gitignore_respected(tmp_path, index):
    ws = tmp_path / "ws"
    (ws / "keep.py").write_text("x = 1\n")
    p = ws / "node_modules" / "dep" / "deep.js"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("let a = 1;\n")
    (ws / ".git" / "objects").mkdir(parents=True, exist_ok=True)
    (ws / ".git" / "objects" / "abc").write_bytes(b"\0")
    p = ws / "out-vscode-min" / "bundle.js"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x=1;")
    (ws / "vendor").mkdir()
    (ws / "vendor" / "skip.py").write_text("x = 2\n")
    (ws / ".gitignore").write_text("vendor/\n")

    budget = ContextBudget(max_files=100, max_elapsed=0)
    index.sync_workspace(budget)
    report = index._last_scan_report
    assert report.skipped_dirs >= 2  # node_modules + .git + out-vscode-min pruned
    assert report.skipped_gitignore >= 1  # vendor/ pruned via .gitignore
    paths = [r[0] for r in index.conn.execute(
        "SELECT DISTINCT file_path FROM code_chunks"
    )]
    assert paths == ["keep.py"], f"only keep.py may be indexed, got {paths}"


# ---------------------------------------------------------------------------
# 4 — oversized and binary files are skipped
# ---------------------------------------------------------------------------


def test_binary_files_skipped(tmp_path, index):
    ws = tmp_path / "ws"
    (ws / "keep.py").write_text("x = 1\n")
    (ws / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (ws / "data.sqlite").write_bytes(b"SQLite format 3\0")
    budget = ContextBudget(max_files=100, max_elapsed=0)
    index.sync_workspace(budget)
    assert index._last_scan_report.skipped_binary >= 2
    paths = [r[0] for r in index.conn.execute(
        "SELECT DISTINCT file_path FROM code_chunks"
    )]
    assert paths == ["keep.py"]


# ---------------------------------------------------------------------------
# 5 — a symlink / junction cannot escape the workspace
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="no symlinks")
def test_symlink_cannot_escape_workspace(tmp_path, index):
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("x = 999\n")
    ws = tmp_path / "ws"
    (ws / "keep.py").write_text("x = 1\n")
    try:
        os.symlink(outside, ws / "escaped", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks on this filesystem")

    budget = ContextBudget(max_files=100, max_elapsed=0)
    index.sync_workspace(budget)
    assert index._last_scan_report.skipped_symlinks >= 1
    paths = [r[0] for r in index.conn.execute(
        "SELECT DISTINCT file_path FROM code_chunks"
    )]
    assert "escaped/secret.py" not in paths
    assert "keep.py" in paths


# ---------------------------------------------------------------------------
# 6 — cancellation stops traversal and downstream work promptly
# ---------------------------------------------------------------------------


def test_cancellation_stops_pipeline_promptly(tmp_path, index, receipts):
    for i in range(100):
        (tmp_path / "ws" / f"f{i:03d}.py").write_text("x = 1\n")
    budget = ContextBudget(max_files=1000, max_elapsed=0)
    budget.cancelled = True
    started = time.perf_counter()
    changed = index.sync_workspace(budget)
    assert changed == 0
    assert index._last_scan_report.reason == "stopped"
    assert time.perf_counter() - started < 5, "cancellation must be prompt"
    degraded = _degraded(_drain(receipts))
    assert degraded and degraded[0]["cancelled"] is True


# ---------------------------------------------------------------------------
# 7 — downstream chunking/indexing shares the same deadline
# ---------------------------------------------------------------------------


def test_downstream_shares_deadline(tmp_path, index):
    for i in range(100):
        (tmp_path / "ws" / f"f{i:03d}.py").write_text("x = 1\n")
    budget = ContextBudget(max_files=7, max_elapsed=0)
    index.sync_workspace(budget)
    report = index._last_scan_report
    # Reads never exceed the files the bounded scan consumed; each .py is
    # read EXACTLY ONCE (decoded text reused for chunk + import edges).
    assert budget.read_files == report.files == 7
    # The index really only holds those files' chunks.
    rows = index.conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
    assert rows > 0


# ---------------------------------------------------------------------------
# 8 — budget exhaustion returns partial context + degraded receipt, turn continues
# ---------------------------------------------------------------------------


def test_budget_exhaustion_partial_context_and_receipt(tmp_path, receipts):
    from src.context.chunk_index import get_index as _real_get_index
    from unittest.mock import patch

    ws = tmp_path / "ws"
    ws.mkdir()
    for i in range(120):
        (ws / f"m{i:03d}.py").write_text(
            f"def target_{i}():\n    return {i}\n"
        )
    idx = ChunkIndex(
        ws, db_path=str(tmp_path / "layer.db"), watch=False, embedder=FakeEmbedder(),
    )
    idx.thread_id_hint = "t-layer"

    with patch("src.context.chunk_index.get_index", return_value=idx):
        budget = ContextBudget(max_files=10, max_elapsed=0)
        layer = build_relevant_chunks_layer(
            {"workspace": str(ws), "current_task": "fix target_000",
             "thread_id": "t-layer"},
            budget,
        )
    # Partial context still produced -> the turn can continue.
    assert layer is not None and "RELEVANT CODE CHUNKS" in layer.content

    degraded = _degraded(_drain(receipts))
    assert degraded, "exhaustion must emit the structured receipt"
    receipt = degraded[0]
    assert receipt["reason"] == "context scan bounded"
    assert receipt["files_considered"] >= 10
    assert receipt["elapsed_ms"] >= 0
    assert receipt["skipped_oversized"] >= 0
    assert receipt["cancelled"] is False


# ---------------------------------------------------------------------------
# 9 — unreadable / disappearing files do not fail the turn
# ---------------------------------------------------------------------------


def test_disappearing_files_do_not_fail(tmp_path, index):
    ws = tmp_path / "ws"
    (ws / "a.py").write_text("x = 1\n")
    (ws / "b.py").write_text("y = 2\n")
    (ws / "c.py").write_text("z = 3\n")

    # A file vanishes between the scan and the read (simulated directly).
    index.sync_file(ws / "gone.py")  # never existed
    # Delete after a successful first sync; second sync must not crash.
    index.sync_workspace(ContextBudget(max_files=10, max_elapsed=0))
    (ws / "b.py").unlink()
    changed = index.sync_workspace(ContextBudget(max_files=10, max_elapsed=0))
    assert changed >= 0
    assert index._last_scan_report.truncated is False


# ---------------------------------------------------------------------------
# 10 — repeated preparation uses fingerprints/cache, not a rebuild
# ---------------------------------------------------------------------------


def test_repeated_preparation_uses_cache(tmp_path, index):
    FakeEmbedder.calls = 0
    for i in range(20):
        (tmp_path / "ws" / f"f{i:02d}.py").write_text(f"x = {i}\n")

    first = ContextBudget(max_files=100, max_elapsed=0)
    index.sync_workspace(first)
    calls_after_first = FakeEmbedder.calls
    assert calls_after_first > 0

    second = ContextBudget(max_files=100, max_elapsed=0)
    changed = index.sync_workspace(second)
    assert changed == 0, "unchanged workspace must not re-index"
    assert FakeEmbedder.calls == calls_after_first, (
        "unchanged content must hit the embedding cache, not re-encode"
    )


# ---------------------------------------------------------------------------
# 11 — a live stop hook (user cancel via turn_controls) halts the pipeline and
#      marks the receipt cancelled=True
# ---------------------------------------------------------------------------


def test_live_stop_hook_cancels_pipeline(tmp_path, index, receipts):
    for i in range(100):
        (tmp_path / "ws" / f"f{i:03d}.py").write_text("x = 1\n")
    budget = ContextBudget(max_files=1000, max_elapsed=0)
    budget.extra_stop = lambda: True  # simulate turn_controls.cancelled()
    changed = index.sync_workspace(budget)
    assert changed == 0, "live stop must halt the walk"
    assert index._last_scan_report.reason == "stopped"
    assert budget.cancelled is True, "stop hook must mark the budget cancelled"
    degraded = _degraded(_drain(receipts))
    assert degraded and degraded[0]["cancelled"] is True


# ---------------------------------------------------------------------------
# 12 — the engine routes degraded receipts to its OWN session id (graph state
#      has no thread_id, so the engine's id is the authoritative source)
# ---------------------------------------------------------------------------


def test_engine_receipt_carries_session_thread_id(tmp_path, receipts):
    from src.context.context_engine import ContextEngine
    from src.context.chunk_index import get_index as _get_index
    from unittest.mock import patch

    ws = tmp_path / "ws"
    ws.mkdir()
    for i in range(120):
        (ws / f"m{i:03d}.py").write_text(f"def target_{i}():\n    return {i}\n")
    idx = ChunkIndex(
        ws, db_path=str(tmp_path / "routing.db"), watch=False, embedder=FakeEmbedder(),
    )
    idx.thread_id_hint = "t-route"
    with patch("src.context.chunk_index.get_index", return_value=idx):
        eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None, thread_id="s-session-42")
        budget = ContextBudget(max_files=10, max_elapsed=0)
        eng._active_budget = budget
        eng._active_thread_id = "s-session-42"
        layer = eng._relevant_chunks_layer(
            {"current_task": "fix target_000", "workspace": str(ws)}
        )
        assert layer is not None
        idx.sync_workspace(budget)
    degraded = _degraded(_drain(receipts))
    assert degraded, "no receipt emitted"
    assert degraded[0]["thread_id"] == "s-session-42", (
        "receipt must be routed to the engine's session, not 'unknown'"
    )


# ---------------------------------------------------------------------------
# Wall-clock smoke: an accidental unlimited walk is caught with CI margin
# ---------------------------------------------------------------------------


def test_wall_clock_smoke_large_workspace_stays_bounded(tmp_path):
    # Fixture creation is measured SEPARATELY from the pipeline so the
    # wall-clock budget applies only to synchronous context preparation.
    t0 = time.perf_counter()
    for d in range(60):
        (tmp_path / f"dir{d:02d}").mkdir(exist_ok=True)
        for i in range(100):  # 6,000 files total
            (tmp_path / f"dir{d:02d}" / f"f{i:03d}.py").write_text("x = 1\n")
    creation_s = time.perf_counter() - t0

    idx = ChunkIndex(
        tmp_path, db_path=str(tmp_path / "smoke.db"), watch=False,
        embedder=FakeEmbedder(),
    )
    budget = ContextBudget()  # production defaults: 5s / 1000 files / 16 MiB
    started = time.perf_counter()
    idx.sync_workspace(budget)
    pipeline_s = time.perf_counter() - started
    idx.stop_watcher()

    report = idx._last_scan_report
    assert report.files <= 1000, "default file budget must hold"
    # The file cap (1,000) bites first on this tree; the pipeline must stop
    # near the 5s deadline at most — a small scheduling margin, nothing more.
    assert pipeline_s < 8, f"pipeline took {pipeline_s:.1f}s — unlimited walk?"
    assert report.truncated is True
    # The receipt's elapsed_ms must track the pipeline, not include fixture
    # creation (which the test measures and reports separately).
    assert budget.elapsed < 8
    assert creation_s > 0


# ---------------------------------------------------------------------------
# 13 — a slow/hung embedder can NEVER block a timed preparation: the
#      synchronous initial-turn path performs NO model inference at all —
#      cache hits only, uncached embeddings deferred. Repeated timed preps
#      must leave ZERO live embed threads and ZERO concurrent abandoned
#      calls, complete inside the deadline, and keep text/FTS available.
# ---------------------------------------------------------------------------


class _HungEmbedder(FakeEmbedder):
    def encode(self, texts, normalize_embeddings=True):
        time.sleep(60)  # stuck far past any test deadline
        return super().encode(texts, normalize_embeddings)


def test_hung_embedder_repeated_timed_preps_leave_zero_threads(tmp_path, receipts):
    ws = tmp_path / "ws"
    ws.mkdir()
    for i in range(4):
        (ws / f"f{i}.py").write_text("def f():\n    pass\n")
    idx = ChunkIndex(
        ws, db_path=str(tmp_path / "hung2.db"), watch=False,
        embedder=_HungEmbedder(),
    )
    idx.thread_id_hint = "t-hung2"
    for i in range(3):
        # Touch the files so each preparation re-indexes them.
        for f in (ws / "f0.py", ws / "f1.py", ws / "f2.py", ws / "f3.py"):
            f.write_text(f"def f_{i}():\n    pass\n")
        budget = ContextBudget(max_elapsed=1.0, max_files=10)
        started = time.perf_counter()
        idx.sync_workspace(budget)
        assert time.perf_counter() - started < 8, (
            "prep must complete inside the deadline — a hung embedder must "
            "never be awaited or abandoned mid-flight"
        )
    idx.stop_watcher()

    # ZERO live embed threads after repeated timed preparations.
    live = [t for t in threading.enumerate() if "chunk-embed" in t.name]
    assert live == [], f"zero live embed threads expected, got {[t.name for t in live]}"

    # Text and FTS are still available (deferral is not data loss)...
    rows = idx.conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
    assert rows > 0
    nfts = idx.conn.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0]
    assert nfts > 0
    # ...but NO vectors: uncached embeddings were deferred, never launched.
    vec_table = "chunk_vec" if idx.uses_vec else "chunk_vec_fallback"
    nvec = idx.conn.execute(f"SELECT COUNT(*) FROM {vec_table}").fetchone()[0]
    assert nvec == 0, "the deadline path must never run model inference"


# ---------------------------------------------------------------------------
# 14 — receipt semantics: files_read counts PHYSICAL read operations and
#      bytes_read every physical byte; the pool hands out only REMAINING
#      allowance to the next consumer (no fresh full caps per walker).
# ---------------------------------------------------------------------------


def test_receipt_reads_are_physical_and_pool_draws_down(tmp_path, receipts):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("import b\nx = 1\n")
    (ws / "b.py").write_text("y = 2\n")
    # NOTE: .json is not a chunkable source extension, so only the two .py
    # files enter the pipeline — a deliberate part of this pin.
    idx = ChunkIndex(
        ws, db_path=str(tmp_path / "pool.db"), watch=False,
        embedder=FakeEmbedder(),
    )
    idx.thread_id_hint = "t-pool"
    budget = ContextBudget(max_files=100, max_elapsed=0)
    idx.sync_workspace(budget)
    idx.stop_watcher()

    # files_read counts PHYSICAL read operations: each consumed .py file is
    # read ONCE (decoded text reused for chunk + import-edge resolution),
    # and every physical byte lands in read_bytes.
    assert budget.read_files == 2
    assert budget.read_bytes >= budget.consumed_bytes
    # The pool hands the next consumer only the REMAINING allowance — a
    # second walker can never get a fresh full 1,000-file / 16 MiB cap.
    assert budget.consumed_files >= 2
    limits = budget.to_limits()
    assert limits.max_files == budget.max_files - budget.consumed_files
    assert limits.max_bytes == budget.max_bytes - budget.consumed_bytes


# ---------------------------------------------------------------------------
# 15 — the engine's fair slices keep the PIPELINE total under the caps:
#      n walkers each get ~cap//n, never cap each; all share the deadline.
# ---------------------------------------------------------------------------


def test_engine_slices_keep_pipeline_total_under_caps():
    pool = ContextBudget(max_files=300, max_bytes=3000, max_elapsed=0)
    slices = [pool.share(3) for _ in range(3)]
    assert [s.max_files for s in slices] == [100, 100, 100]
    assert sum(s.max_files for s in slices) <= pool.max_files
    assert sum(s.max_bytes for s in slices) <= pool.max_bytes
    # Slices share ONE deadline (same _start), the cancellation hook, and
    # the degraded-receipt emission flag (one aggregate receipt per build).
    assert all(s._start == pool._start for s in slices)
    assert all(s.collect_receipts is pool.collect_receipts for s in slices)
    pool.extra_stop = lambda: True
    share = pool.share(2)
    assert share.should_stop() is True
    assert share.cancelled is True


def test_small_cap_slices_never_exceed_parent():
    # Splitting a small cap among n walkers must NEVER inflate the combined
    # allowance: floor division only, and 0 means zero allowance.
    for cap, n, expected in [
        (1, 3, [0, 0, 0]),
        (2, 3, [0, 0, 0]),
        (5, 3, [1, 1, 1]),
        (7, 3, [2, 2, 2]),
        (1000, 3, [333, 333, 333]),
    ]:
        pool = ContextBudget(
            max_files=cap, max_bytes=cap * 1024,
            max_considered=cap, max_visited=cap, max_elapsed=0,
        )
        slices = [pool.share(n) for _ in range(n)]
        assert [s.max_files for s in slices] == expected, f"files cap {cap}/{n}"
        assert sum(s.max_files for s in slices) <= cap
        assert sum(s.max_bytes for s in slices) <= cap * 1024
        assert sum(s.max_considered for s in slices) <= cap
        assert sum(s.max_visited for s in slices) <= cap


def test_zero_quota_slice_yields_nothing(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")
    (tmp_path / "c.py").write_text("z = 3\n")
    pool = ContextBudget(max_files=1, max_bytes=1024, max_elapsed=0)
    it, report = scan_files(tmp_path, limits=pool.share(3).to_limits())
    got = list(it)
    assert got == [], "a zero-quota slice must yield NOTHING (not unlimited)"
    assert report.truncated is True


# ---------------------------------------------------------------------------
# 16 — the GLOBAL physical-read ledger: total bytes read across every
#      consumer (repo map + chunk sync, files parsed by both) never exceeds
#      ContextBudget.max_bytes.
# ---------------------------------------------------------------------------


def test_physical_read_cap_enforced_across_consumers(tmp_path, receipts):
    ws = tmp_path / "ws"
    ws.mkdir()
    body = "def f():\n    pass\n" + "#" * 1000  # ~1KiB per file
    for i in range(24):
        (ws / f"f{i:02d}.py").write_text(body)

    from src.context.repo_map import get_repo_map

    idx = ChunkIndex(
        ws, db_path=str(tmp_path / "cap.db"), watch=False,
        embedder=FakeEmbedder(),
    )
    idx.thread_id_hint = "t-cap"
    budget = ContextBudget(max_bytes=6 * 1024, max_elapsed=0, max_files=1000)

    # TWO consumers parse the same files against ONE shared ledger: repo map
    # (describe + edges) then chunk sync. Without the ledger this would read
    # ~2x the cap; with it, reads decline once the global allowance is gone.
    get_repo_map(ws, budget=budget, thread_id="t-cap")
    idx.sync_workspace(budget)
    idx.stop_watcher()

    assert budget.read_bytes <= 6 * 1024, (
        f"global physical-read cap violated: {budget.read_bytes} > 6144"
    )
    assert budget.read_bytes <= budget.max_bytes
    # Multiple consumers really did work: reads happened, they were just capped.
    assert budget.read_files > 0


# ---------------------------------------------------------------------------
# 17 — the considered-entry cap bounds unsupported/ignored trees: thousands
#      of non-source files cannot make the scan inspect the whole tree while
#      report.files stays zero.
# ---------------------------------------------------------------------------


def test_considered_cap_bounds_unsupported_files(tmp_path):
    for i in range(20000):
        (tmp_path / f"f{i:05d}.xyz").write_text("junk\n")
    it, report = scan_files(
        tmp_path,
        limits=ScanLimits(
            max_considered=1000, max_visited=2000,
            max_files=1000, max_bytes=0, max_elapsed=0,
        ),
        extensions={".py"},
    )
    got = list(it)
    assert got == [], "no source files in this tree"
    assert report.truncated is True
    assert report.reason == "considered"
    assert report.considered <= 1000
    assert report.visited < 20000, "must stop at the considered cap, not walk everything"


def test_visited_cap_bounds_directory_heavy_tree(tmp_path):
    for i in range(5000):
        (tmp_path / f"d{i:04d}").mkdir()
    it, report = scan_files(
        tmp_path,
        limits=ScanLimits(
            max_considered=10**9, max_visited=1000,
            max_files=10**9, max_bytes=0, max_elapsed=0,
        ),
    )
    got = list(it)
    assert got == []
    assert report.truncated is True
    assert report.reason == "visited"
    assert report.visited <= 1000


# ---------------------------------------------------------------------------
# 18 — a truncated / cancelled sync must NEVER prune indexed files outside
#      its bounded prefix: indexed - on_disk is only sound after a complete
#      scan.
# ---------------------------------------------------------------------------


def test_truncated_sync_never_prunes_ghosts(tmp_path, index):
    ws = tmp_path / "ws"
    for name in "abcdefgh":
        (ws / f"{name}.py").write_text("x = 1\n")
    expected = {f"{n}.py" for n in "abcdefgh"}

    def _paths():
        return {r[0] for r in index.conn.execute(
            "SELECT DISTINCT file_path FROM code_chunks"
        )}

    # Complete scan first: every file indexed.
    index.sync_workspace(ContextBudget(max_files=1000, max_elapsed=0))
    assert _paths() == expected

    # Truncated bounded sync (max_files=2): on_disk is only a prefix, so the
    # other six indexed files must NOT be mistaken for deletions.
    index.sync_workspace(ContextBudget(max_files=2, max_elapsed=0))
    assert _paths() == expected, "truncated sync must not prune ghosts"

    # Complete scan after deleting one REAL file: only that file is pruned.
    (ws / "a.py").unlink()
    index.sync_workspace(ContextBudget(max_files=1000, max_elapsed=0))
    assert _paths() == expected - {"a.py"}


def test_cancelled_sync_never_prunes_ghosts(tmp_path, index):
    ws = tmp_path / "ws"
    for name in "abcdefgh":
        (ws / f"{name}.py").write_text("x = 1\n")
    index.sync_workspace(ContextBudget(max_files=1000, max_elapsed=0))

    budget = ContextBudget(max_files=1000, max_elapsed=0)
    budget.cancelled = True
    index.sync_workspace(budget)
    paths = {r[0] for r in index.conn.execute(
        "SELECT DISTINCT file_path FROM code_chunks"
    )}
    assert paths == {f"{n}.py" for n in "abcdefgh"}, "cancelled sync must not prune"


# ---------------------------------------------------------------------------
# 19 — a real Windows directory junction cannot escape the workspace
#      (skipped only when the host genuinely cannot create one).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction test")
def test_windows_junction_cannot_escape_workspace(tmp_path):
    import os
    import shutil
    import tempfile
    from src.context.chunk_index import ChunkIndex

    def _attempt(base):
        outside = base / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "secret.py").write_text("x = 999\n")
        ws = base / "ws"
        ws.mkdir(exist_ok=True)
        (ws / "keep.py").write_text("x = 1\n")
        link = ws / "escaped"
        rc = os.system(f'cmd /c mklink /J "{link}" "{outside}"')
        if rc != 0 or not os.path.exists(link):
            return None, None, None
        return ws, link, outside

    base = tmp_path
    ws, link, _outside = _attempt(base)
    alt_cleanup = None
    if ws is None:
        # The TEMP drive can deny reparse-point creation by policy even when
        # the host supports it; retry on the workspace drive before skipping.
        alt = Path(tempfile.mkdtemp(prefix="pulse_jtest_", dir=Path.cwd().anchor))
        alt_cleanup = alt
        ws, link, _outside = _attempt(alt)
        if ws is None:
            pytest.skip("host genuinely cannot create directory junctions")
    try:
        idx = ChunkIndex(
            ws, db_path=str(ws / "j.db"), watch=False, embedder=None,
        )
        idx.thread_id_hint = "t-junction"
        budget = ContextBudget(max_files=100, max_elapsed=0)
        idx.sync_workspace(budget)
        assert idx._last_scan_report.skipped_symlinks >= 1, (
            "junction must be counted as a skipped link"
        )
        paths = {r[0] for r in idx.conn.execute(
            "SELECT DISTINCT file_path FROM code_chunks"
        )}
        assert "escaped/secret.py" not in paths
        assert "keep.py" in paths
    finally:
        try:
            os.rmdir(link)  # removes the junction, not the target
        except OSError:
            pass
        if alt_cleanup is not None:
            shutil.rmtree(alt_cleanup, ignore_errors=True)
        else:
            shutil.rmtree(base / "ws", ignore_errors=True)
            shutil.rmtree(base / "outside", ignore_errors=True)


# ---------------------------------------------------------------------------
# 20 — the engine build emits EXACTLY ONE aggregate degraded receipt with
#      pipeline-wide counts and nested component summaries.
# ---------------------------------------------------------------------------


def test_engine_emits_one_aggregate_receipt(tmp_path, receipts, monkeypatch):
    from src.context.context_engine import ContextEngine, TaskType
    from src.context.chunk_index import get_index as _get_index
    from src.context.convention_learner import ConventionLearner
    from unittest.mock import patch

    # Hermeticity: ConventionLearner persists to the GLOBAL ~/.pulseai file
    # keyed by workspace path, so a leftover entry for THIS ws path would
    # make the fresh learner skip its scan (no component in the receipt).
    # Route this test's learners to a per-test storage file instead.
    _iso_storage = str(tmp_path / "conventions.json")
    _orig_init = ConventionLearner.__init__

    def _isolated_init(self, storage_path: str | None = None):
        _orig_init(self, _iso_storage)

    monkeypatch.setattr(ConventionLearner, "__init__", _isolated_init)

    ws = tmp_path / "ws"
    ws.mkdir()
    for i in range(400):
        (ws / f"m{i:03d}.py").write_text(f"def target_{i}():\n    return {i}\n")
    idx = ChunkIndex(
        ws, db_path=str(tmp_path / "agg.db"), watch=False,
        embedder=FakeEmbedder(),
    )
    with patch("src.context.chunk_index.get_index", return_value=idx):
        eng = ContextEngine(
            max_tokens=4000, llm=None, memory_manager=None, thread_id="s-agg"
        )
        eng._build_context_layers(
            {"current_task": "fix target_000", "workspace": str(ws)},
            TaskType.DEBUG,
        )

    degraded = _degraded(_drain(receipts))
    assert len(degraded) == 1, (
        f"exactly ONE aggregate receipt per build, got {len(degraded)}"
    )
    r = degraded[0]
    assert r["thread_id"] == "s-agg"
    assert r["reason"] == "context scan bounded"
    assert r["files_considered"] > 0
    assert r["cancelled"] is False
    comps = r.get("components", {})
    assert set(comps) == {"repo_map", "chunk_index", "convention_learner"}, (
        "all three walkers must nest inside the single receipt"
    )

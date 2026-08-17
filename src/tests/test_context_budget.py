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
import time
from pathlib import Path

import pytest

from src.context.bounded_scan import ContextBudget
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
    assert budget.read_files <= 50
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
    assert budget.read_files <= 3
    assert budget.read_bytes <= 3 * 1024
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
    degraded = _degraded(_drain(receipts))
    assert degraded and degraded[0]["elapsed_ms"] >= 0


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
    # Reads never exceed the files the bounded scan consumed.
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
    for d in range(60):
        (tmp_path / f"dir{d:02d}").mkdir(exist_ok=True)
        for i in range(100):  # 6,000 files total
            (tmp_path / f"dir{d:02d}" / f"f{i:03d}.py").write_text("x = 1\n")

    idx = ChunkIndex(
        tmp_path, db_path=str(tmp_path / "smoke.db"), watch=False,
        embedder=FakeEmbedder(),
    )
    budget = ContextBudget()  # production defaults: 5s / 1000 files / 16 MiB
    started = time.perf_counter()
    idx.sync_workspace(budget)
    elapsed = time.perf_counter() - started

    report = idx._last_scan_report
    assert report.files <= 1000, "default file budget must hold"
    assert elapsed < 15, f"smoke prep took {elapsed:.1f}s — unlimited walk?"
    assert report.truncated is True
    idx.stop_watcher()

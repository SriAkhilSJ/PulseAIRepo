"""
Tests for Non-Blocking Workspace Synchronization (Phase 8.1).
=============================================================

Validates:
1. Context preparation does not trigger a full workspace scan on every turn.
2. Initial indexing makes files searchable on turn 1.
3. Modified files queued in FileWatcher are flushed and become searchable before retrieval.
4. Deleted files queued in FileWatcher are pruned before retrieval.
5. Concurrent retrieval and synchronization remain thread-safe without locks or corruption.
6. Failed background synchronization records error and recovers cleanly.
7. Legacy facade imports and monkeypatch compatibility are preserved.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import SystemMessage

from src.context.budgeting.context_budget import ContextBudget
from src.context.indexing.chunk_index import (
    ChunkIndex,
    _INDEX_CACHE,
    build_relevant_chunks_layer,
    get_index,
)


class DummyEmbedder:
    """Fast deterministic dummy embedder for tests."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.calls = 0

    def encode(self, text: str | list[str]) -> list[float] | list[list[float]]:
        self.calls += 1
        if isinstance(text, str):
            return [0.01] * self.dim
        return [[0.01] * self.dim for _ in text]


@pytest.fixture
def test_workspace(tmp_path: Path):
    ws = (tmp_path / "project").resolve()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "main.py").write_text(
        "def run_main():\n    \"\"\"Main entrypoint.\"\"\"\n    return 'main_val'\n",
        encoding="utf-8",
    )
    (ws / "auth.py").write_text(
        "def parse_auth_token(token):\n    \"\"\"Parse and validate auth token.\"\"\"\n    return token.strip()\n",
        encoding="utf-8",
    )
    (ws / "utils.py").write_text(
        "def format_response(data):\n    \"\"\"Format JSON response.\"\"\"\n    return str(data)\n",
        encoding="utf-8",
    )
    return ws


def test_turn2_skips_full_workspace_scan(test_workspace: Path, tmp_path: Path):
    """Context preparation must not trigger full workspace scan on subsequent turns."""
    db_path = str(tmp_path / "idx.db")
    idx = ChunkIndex(test_workspace, db_path=db_path, watch=False, embedder=DummyEmbedder())

    state = {
        "workspace": str(test_workspace),
        "current_task": "fix parse_auth_token logic",
        "thread_id": "test-t1",
    }

    with patch("src.context.chunk_index.get_index", return_value=idx):
        # Turn 1: Cold start -> ensure_initialized triggers initial sync
        layer1 = build_relevant_chunks_layer(state)
        assert layer1 is not None
        assert "=== RELEVANT CODE CHUNKS ===" in layer1.content
        assert "auth.py" in layer1.content
        assert idx.full_sync_count == 1
        assert idx.is_initialized is True

        # Turn 2: Steady state -> skips full workspace sync entirely
        sync_called = []
        original_sync = idx.synchronizer.sync_workspace

        def tracked_sync(*args, **kwargs):
            sync_called.append(True)
            return original_sync(*args, **kwargs)

        idx.synchronizer.sync_workspace = tracked_sync

        layer2 = build_relevant_chunks_layer(state)
        assert layer2 is not None
        assert "=== RELEVANT CODE CHUNKS ===" in layer2.content
        assert len(sync_called) == 0, "Turn 2 must NOT call sync_workspace"
        assert idx.full_sync_count == 1, "Full sync count must remain 1"


def test_initial_indexing_makes_files_searchable(test_workspace: Path, tmp_path: Path):
    """Initial indexing on a cold index populates code chunks and allows immediate retrieval."""
    db_path = str(tmp_path / "cold_idx.db")
    idx = ChunkIndex(test_workspace, db_path=db_path, watch=False, embedder=DummyEmbedder())
    assert idx._is_index_empty() is True
    assert idx.is_initialized is False

    state = {
        "workspace": str(test_workspace),
        "current_task": "look up format_response",
        "thread_id": "test-init",
    }
    with patch("src.context.chunk_index.get_index", return_value=idx):
        layer = build_relevant_chunks_layer(state)
        assert layer is not None
        assert "utils.py" in layer.content
        assert "format_response" in layer.content
        assert idx._is_index_empty() is False
        assert idx.is_initialized is True


def test_queued_modifications_are_flushed_and_searchable(test_workspace: Path, tmp_path: Path):
    """Modified files queued in the file watcher become searchable before retrieval."""
    db_path = str(tmp_path / "mod_idx.db")
    idx = ChunkIndex(test_workspace, db_path=db_path, watch=False, embedder=DummyEmbedder())

    state = {
        "workspace": str(test_workspace),
        "current_task": "call parse_auth_token",
        "thread_id": "test-mod",
    }
    with patch("src.context.chunk_index.get_index", return_value=idx):
        # Initial turn
        build_relevant_chunks_layer(state)

        # Modify main.py with a brand new function
        main_file = test_workspace / "main.py"
        main_file.write_text(
            "def newly_added_symbol():\n    \"\"\"Newly added test symbol.\"\"\"\n    return 'secret_value'\n",
            encoding="utf-8",
        )
        # FileWatcher queues modification event
        idx.watcher.enqueue_sync(str(main_file))

        # Turn 2 searches for newly added symbol
        state["current_task"] = "use newly_added_symbol"
        layer = build_relevant_chunks_layer(state)
        assert layer is not None
        assert "newly_added_symbol" in layer.content
        assert "secret_value" in layer.content


def test_queued_deletions_are_flushed_and_removed(test_workspace: Path, tmp_path: Path):
    """Deleted files queued in the file watcher are pruned before retrieval."""
    db_path = str(tmp_path / "del_idx.db")
    idx = ChunkIndex(test_workspace, db_path=db_path, watch=False, embedder=DummyEmbedder())

    state = {
        "workspace": str(test_workspace),
        "current_task": "use format_response",
        "thread_id": "test-del",
    }
    with patch("src.context.chunk_index.get_index", return_value=idx):
        # Initial turn indexes all files
        layer1 = build_relevant_chunks_layer(state)
        assert layer1 is not None
        assert "utils.py" in layer1.content

        # Delete utils.py and enqueue remove event
        utils_file = test_workspace / "utils.py"
        utils_file.unlink()
        idx.watcher.enqueue_remove(str(utils_file))

        # Turn 2: flush prunes utils.py chunks
        state["current_task"] = "use format_response"
        layer2 = build_relevant_chunks_layer(state)
        # Either utils.py is gone or layer is None
        if layer2 is not None:
            assert "utils.py" not in layer2.content

        # Direct search verifies utils.py chunks are pruned
        results = idx.search("format_response")
        matching_files = [r.file_path for r in results]
        assert "utils.py" not in matching_files


def test_concurrent_retrieval_and_synchronization(test_workspace: Path, tmp_path: Path):
    """Retrieval while background sync is running must not raise SQLite lock errors or crash."""
    db_path = str(tmp_path / "concur_idx.db")
    idx = ChunkIndex(test_workspace, db_path=db_path, watch=False, embedder=DummyEmbedder())
    idx.sync_workspace()

    errors: list[Exception] = []
    stop_event = threading.Event()

    def reader_worker():
        while not stop_event.is_set():
            try:
                res = idx.search("parse_auth_token", top_k=2)
                assert isinstance(res, list)
            except Exception as e:
                errors.append(e)

    def writer_worker():
        for _ in range(5):
            try:
                idx.sync_workspace()
            except Exception as e:
                errors.append(e)
            time.sleep(0.01)

    threads = [threading.Thread(target=reader_worker) for _ in range(3)]
    writer = threading.Thread(target=writer_worker)

    for t in threads:
        t.start()
    writer.start()

    writer.join(timeout=10.0)
    stop_event.set()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == [], f"Concurrent read/sync raised errors: {errors}"


def test_sync_workspace_async_lifecycle_and_error_recovery(test_workspace: Path, tmp_path: Path):
    """Background async synchronization executes, updates state, and handles errors cleanly."""
    db_path = str(tmp_path / "async_idx.db")
    idx = ChunkIndex(test_workspace, db_path=db_path, watch=False, embedder=DummyEmbedder())

    # 1. Successful async sync
    completed_event = threading.Event()
    changed_count = []

    def on_complete(changed: int):
        changed_count.append(changed)
        completed_event.set()

    thread = idx.sync_workspace_async(on_complete=on_complete)
    assert thread is not None
    assert thread.name == "chunk-index-bg-sync"
    completed_event.wait(timeout=5.0)

    assert len(changed_count) == 1
    assert idx.is_syncing is False
    assert idx.last_sync_time > 0
    assert idx.last_sync_error is None

    # 2. Simulated failure recovery
    def failing_sync(*args, **kwargs):
        raise RuntimeError("Simulated disk I/O failure")

    with patch.object(idx.synchronizer, "sync_workspace", side_effect=failing_sync):
        err_event = threading.Event()
        caught_errors = []

        def on_error(exc: Exception):
            caught_errors.append(exc)
            err_event.set()

        err_thread = idx.sync_workspace_async(on_error=on_error)
        err_event.wait(timeout=5.0)
        err_thread.join(timeout=2.0)

        assert len(caught_errors) == 1
        assert "Simulated disk I/O failure" in idx.last_sync_error
        assert idx.is_syncing is False

    # 3. Subsequent recovery succeeds
    rec_event = threading.Event()
    rec_thread = idx.sync_workspace_async(on_complete=lambda c: rec_event.set())
    rec_event.wait(timeout=5.0)
    rec_thread.join(timeout=2.0)
    assert idx.last_sync_error is None


def test_legacy_facade_and_monkeypatch_compatibility(test_workspace: Path, tmp_path: Path):
    """Existing monkeypatches on src.context.chunk_index work identically."""
    import src.context.chunk_index as legacy_ci

    db_path = str(tmp_path / "facade.db")
    idx = legacy_ci.ChunkIndex(test_workspace, db_path=db_path, watch=False, embedder=DummyEmbedder())

    # Test re-exports
    assert hasattr(legacy_ci, "ChunkIndex")
    assert hasattr(legacy_ci, "get_index")
    assert hasattr(legacy_ci, "build_relevant_chunks_layer")
    assert hasattr(idx, "ensure_initialized")
    assert hasattr(idx, "flush_pending_changes")
    assert hasattr(idx, "sync_workspace_async")

    # Monkeypatching get_index
    with patch("src.context.chunk_index.get_index", return_value=idx):
        layer = legacy_ci.build_relevant_chunks_layer(
            {"workspace": str(test_workspace), "current_task": "test parse_auth_token"}
        )
        assert layer is not None
        assert "auth.py" in layer.content

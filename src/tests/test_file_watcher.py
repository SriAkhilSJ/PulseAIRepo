"""Tests for file watcher and event debouncing (Phase 5.3)."""

from pathlib import Path

from src.context.indexing.file_watcher import (
    WATCH_BATCH_S,
    WATCH_POLL_S,
    FileWatcher,
)


def test_watcher_constants():
    assert WATCH_BATCH_S == 2.0
    assert WATCH_POLL_S == 15.0


def test_queue_sync_and_drain(tmp_path: Path):
    watcher = FileWatcher(
        workspace=tmp_path,
        sync_file_fn=lambda p, b: None,
        remove_file_fn=lambda p: 1,
        sync_workspace_fn=lambda: 0,
    )
    watcher.enqueue_sync(str(tmp_path / "a.py"))
    watcher.enqueue_sync(str(tmp_path / "b.py"))
    watcher.enqueue_sync(str(tmp_path / "a.py"))  # duplicate

    to_sync, to_remove = watcher.drain_pending_syncs()
    assert len(to_sync) == 2
    assert len(to_remove) == 0

    # Drain again is empty
    empty_sync, empty_remove = watcher.drain_pending_syncs()
    assert len(empty_sync) == 0
    assert len(empty_remove) == 0


def test_remove_wins_over_sync_in_same_window(tmp_path: Path):
    watcher = FileWatcher(
        workspace=tmp_path,
        sync_file_fn=lambda p, b: None,
        remove_file_fn=lambda p: 1,
        sync_workspace_fn=lambda: 0,
    )
    file_p = str(tmp_path / "mod.py")
    watcher.enqueue_sync(file_p)
    watcher.enqueue_remove(file_p)

    to_sync, to_remove = watcher.drain_pending_syncs()
    assert file_p not in to_sync
    assert file_p in to_remove


def test_apply_queued_changes(tmp_path: Path):
    synced = []
    removed = []

    f_existing = tmp_path / "live.py"
    f_existing.write_text("def live(): pass")
    f_deleted = tmp_path / "dead.py"

    watcher = FileWatcher(
        workspace=tmp_path,
        sync_file_fn=lambda p, b: synced.append(p),
        remove_file_fn=lambda p: removed.append(p) or 1,
        sync_workspace_fn=lambda: 0,
    )

    watcher.enqueue_sync(str(f_existing))
    watcher.enqueue_remove(str(f_deleted))
    watcher.apply_queued_changes()

    assert f_existing in synced
    assert f_deleted in removed


def test_start_and_stop_lifecycle(tmp_path: Path):
    watcher = FileWatcher(
        workspace=tmp_path,
        sync_file_fn=lambda p, b: None,
        remove_file_fn=lambda p: 1,
        sync_workspace_fn=lambda: 0,
    )
    watcher.start()
    assert watcher._watcher_thread is not None
    assert watcher._watcher_thread.is_alive()

    # Idempotent start
    watcher.start()
    assert watcher._watcher_thread.is_alive()

    watcher.stop()
    assert watcher._watcher_thread is None

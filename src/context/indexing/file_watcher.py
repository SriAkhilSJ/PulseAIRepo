"""
File Watcher — Background File System Event Handling and Polling
================================================================

Monitors the workspace for file additions, modifications, and deletions.
Uses watchdog if installed, falling back to a periodic polling sweep.
Queues file changes and debounces them to prevent redundant sync runs.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Optional

from src.context.bounded_scan import ContextBudget
from src.context.extraction.language_registry import source_extensions

WATCH_BATCH_S = 2.0      # debounce window for queued events
WATCH_POLL_S = 15.0      # fallback sweep when watchdog isn't installed


class FileWatcher:
    """Manages workspace file watching and event debouncing."""

    def __init__(
        self,
        workspace: Path,
        sync_file_fn: Callable[[Path, ContextBudget | None], None],
        remove_file_fn: Callable[[Path], int],
        sync_workspace_fn: Callable[[], int],
        batch_debounce_s: float = WATCH_BATCH_S,
        poll_interval_s: float = WATCH_POLL_S,
    ):
        self.workspace = Path(workspace).resolve()
        self.sync_file_fn = sync_file_fn
        self.remove_file_fn = remove_file_fn
        self.sync_workspace_fn = sync_workspace_fn
        self.batch_debounce_s = batch_debounce_s
        self.poll_interval_s = poll_interval_s

        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()
        self._pending_syncs: set[str] = set()
        self._pending_removes: set[str] = set()
        self._sync_queue_lock = threading.Lock()

    def start(self) -> None:
        """Start the background watcher thread (idempotent)."""
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            return
        self._watcher_stop.clear()
        self._watcher_thread = threading.Thread(
            target=self.watch_loop, daemon=True, name="chunk-index-watcher"
        )
        self._watcher_thread.start()

    def stop(self) -> None:
        """Signal the watcher to stop and wait briefly."""
        self._watcher_stop.set()
        if self._watcher_thread is not None:
            self._watcher_thread.join(timeout=5.0)
            self._watcher_thread = None

    def enqueue_sync(self, path: str) -> None:
        with self._sync_queue_lock:
            self._pending_syncs.add(path)

    def enqueue_remove(self, path: str) -> None:
        with self._sync_queue_lock:
            self._pending_syncs.discard(path)
            self._pending_removes.add(path)

    def drain_pending_syncs(self) -> tuple[list[str], list[str]]:
        """Atomically take the queued paths; returns (to_sync, to_remove)."""
        with self._sync_queue_lock:
            to_sync = list(self._pending_syncs)
            to_remove = list(self._pending_removes)
            self._pending_syncs.clear()
            self._pending_removes.clear()
        return to_sync, to_remove

    def apply_queued_changes(self) -> None:
        to_sync, to_remove = self.drain_pending_syncs()
        budget = ContextBudget()
        for path in to_remove:
            try:
                p = Path(path)
                if self.workspace in p.resolve().parents:
                    self.remove_file_fn(p)
            except Exception as exc:
                print(f"[FileWatcher] watcher remove failed for {path}: {exc}")
        for path in to_sync:
            try:
                p = Path(path)
                if p.exists() and self.workspace in p.resolve().parents:
                    self.sync_file_fn(p, budget)
            except Exception as exc:
                print(f"[FileWatcher] watcher sync failed for {path}: {exc}")

    def watch_loop(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            while not self._watcher_stop.wait(self.poll_interval_s):
                try:
                    self.sync_workspace_fn()
                except Exception as exc:
                    print(f"[FileWatcher] watcher poll sync failed: {exc}")
            return

        watcher = self
        source_exts = tuple(source_extensions())

        def _is_source(path: str) -> bool:
            return path.lower().endswith(source_exts)

        class _SourceHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if not event.is_directory and _is_source(event.src_path):
                    watcher.enqueue_sync(event.src_path)

            def on_created(self, event):
                if not event.is_directory and _is_source(event.src_path):
                    watcher.enqueue_sync(event.src_path)

            def on_deleted(self, event):
                if not event.is_directory and _is_source(event.src_path):
                    watcher.enqueue_remove(event.src_path)

            def on_moved(self, event):
                if event.is_directory:
                    return
                if _is_source(event.src_path):
                    watcher.enqueue_remove(event.src_path)
                dest = getattr(event, "dest_path", "")
                if _is_source(dest):
                    watcher.enqueue_sync(dest)

        observer = Observer()
        observer.schedule(_SourceHandler(), str(self.workspace), recursive=True)
        try:
            observer.start()
        except Exception as exc:
            print(f"[FileWatcher] watcher unavailable ({exc}); polling instead")
            while not self._watcher_stop.wait(self.poll_interval_s):
                try:
                    self.sync_workspace_fn()
                except Exception as poll_exc:
                    print(f"[FileWatcher] watcher poll sync failed: {poll_exc}")
            return

        try:
            while not self._watcher_stop.wait(self.batch_debounce_s):
                self.apply_queued_changes()
        finally:
            observer.stop()
            observer.join(timeout=5.0)


__all__ = [
    "WATCH_BATCH_S",
    "WATCH_POLL_S",
    "FileWatcher",
]

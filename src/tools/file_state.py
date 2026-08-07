# src/tools/file_state.py
"""
File-State Guard (D32, hermes steal #8)
========================================

Plain English: when two agents work in the same process (main agent +
sub-agents, or D33's parallel sub-agent batches), one agent can silently
overwrite another's fresh work: A reads a file, B edits it, A writes its
(now stale) version back over B's changes. This module makes that clobber
IMPOSSIBLE: before any write, we check whether someone else wrote the file
since the writer last read it — and refuse with an agent-readable message
telling them to re-read first.

Design stolen from hermes `tools/file_state.py:1-40` (receipts §45),
adapted: our agents are identified by the graph's thread_id (main
conversation = its session thread, sub-agents = "sub-..." ids from
invoke_agent's config — see chat_graph.py:1737-1744).

    record_read(task_id, path)      — read_file hook
    check_stale(task_id, path)      — write_file, BEFORE a full overwrite
    note_write(task_id, path)       — write_file / edit_file, after success
    lock_path(path)                 — per-path RMW critical section

Policy note (pinned in tests): the stale REFUSAL lives on write_file,
whose full-overwrite shape is the true clobber vector. edit_file needs
no refusal — it reads fresh content itself and replaces only the matched
span, so a stale-anchored old_text either fails to match (self-healing
error: "read the file first") or lands surgically while PRESERVING the
other agent's changes outside the span.

Boring-by-choice details:
- Stamps are (mtime, monotonic read/write time); a write also stamps the
  writer's own knowledge (you know what YOU wrote — pinned).
- Blind-overwrite is refused too: if OUR registry saw another agent write
  the file and I never read it since, I don't get to clobber it blindly.
- External edits (vim, IDE) are honestly OUT of scope: we only track
  in-process tool traffic (same upstream scope). The mtime is recorded so
  a smarter future check can compare — today's refusal is registry-based.
- Kill-switch: PULSEAI_FILE_STATE_GUARD=off => instant no-op behavior.
- Never raises. All hooks fail-open (log nothing, allow the action) — a
  guard bug must never break an edit; the D31 shadow checkpoint is the
  seatbelt underneath either way.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

_MAX_PATH_ENTRIES = 4096  # bounded registry (locks/stamps are ~100B each)

_reads: dict[str, dict[str, tuple[float, float]]] = {}
#        path -> task_id -> (mtime_at_read, monotonic read ts)
_writers: dict[str, tuple[str, float]] = {}
#          path -> (last writer task_id, monotonic write ts)
_path_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _enabled() -> bool:
    import os
    return os.environ.get("PULSEAI_FILE_STATE_GUARD", "").strip().lower() != "off"


def _key(path) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path)


def _evict_if_needed() -> None:
    if len(_reads) > _MAX_PATH_ENTRIES:
        _reads.pop(next(iter(_reads)))
    if len(_writers) > _MAX_PATH_ENTRIES:
        _writers.pop(next(iter(_writers)))
    if len(_path_locks) > _MAX_PATH_ENTRIES:
        for key, lock in list(_path_locks.items()):
            if not lock.locked():
                del _path_locks[key]
                break


def record_read(task_id: str, path) -> None:
    """Stamp: this agent has seen this file's current content."""
    if not _enabled():
        return
    try:
        key = _key(path)
        try:
            mtime = Path(key).stat().st_mtime
        except OSError:
            mtime = 0.0
        with _guard:
            _evict_if_needed()
            _reads.setdefault(key, {})[task_id] = (mtime, time.monotonic())
    except Exception:
        pass


def note_write(task_id: str, path) -> None:
    """Stamp: this agent is the last writer (and knows what it wrote)."""
    if not _enabled():
        return
    try:
        key = _key(path)
        now = time.monotonic()
        with _guard:
            _evict_if_needed()
            _writers[key] = (task_id, now)
            _reads.setdefault(key, {})[task_id] = (
                Path(key).stat().st_mtime if Path(key).exists() else 0.0,
                now,
            )
    except Exception:
        pass


def check_stale(task_id: str, path) -> Optional[str]:
    """None if the write is safe; an agent-readable refusal string if
    ANOTHER tool-using agent wrote this file and my knowledge is older
    (or absent). Registry-only by design (see module docstring)."""
    if not _enabled():
        return None
    try:
        key = _key(path)
        with _guard:
            writer = _writers.get(key)
            if writer is None:
                return None
            writer_id, write_ts = writer
            if writer_id == task_id:
                return None
            my_stamp = _reads.get(key, {}).get(task_id)
        if my_stamp is not None and my_stamp[1] >= write_ts:
            return None  # I read it AFTER their write — I'm current.
        rel = Path(path).name
        return (
            f"⚠️ Refusing to clobber: {rel} was modified by another agent "
            f"(thread {writer_id!r}) since you last read it.\n"
            f"Re-read the file with read_file first, then retry your edit — "
            f"their changes are protected from being silently overwritten."
        )
    except Exception:
        return None  # fail-open: guard bugs must never break an edit


@contextmanager
def lock_path(path):
    """Per-path read-modify-write critical section (in-process)."""
    key = _key(path)
    with _guard:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _path_locks[key] = lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def reset_for_tests() -> None:
    with _guard:
        _reads.clear()
        _writers.clear()
        _path_locks.clear()


# ------------------------------------------------------------------ helpers

def task_id_from_config(config) -> str:
    """Agent identity from the tool config (main session thread_id, or the
    sub-* id invoke_agent gives children). 'main' when absent (direct tool
    invocations in scripts/tests without graph context)."""
    try:
        tid = (config or {}).get("configurable", {}).get("thread_id", "")
        return str(tid) or "main"
    except Exception:
        return "main"

# src/dashboard/turn_locks.py
"""
Per-thread turn serialization (D29, §44).

The problem (external review Aug 7, CONFIRMED by reading): the dashboard
spawns a raw `threading.Thread` per chat POST. Two rapid messages on the
SAME thread_id = two agent graphs racing one LangGraph checkpoint — SQLite
makes the writes transactional, but the turns still interleave logically
(messages cross-wire, engine state double-serves, approvals cross-fire).

The fix is deliberately boring: one lock per thread_id — the second turn
for a conversation simply waits for the first to finish. Turns are usually
seconds; queues are somebody else's job today.

Module kept Flask-free so the pin suite imports it without the dashboard
stack. Bounded dict (locks are ~100 bytes; evict an idle one past the cap).
"""

from __future__ import annotations

import threading

_TURN_LOCKS: dict[str, threading.Lock] = {}
_TURN_LOCKS_GUARD = threading.Lock()
_TURN_LOCKS_MAX = 256


def turn_lock(thread_id: str) -> threading.Lock:
    """Return THE lock for a conversation thread (created on demand)."""
    with _TURN_LOCKS_GUARD:
        lock = _TURN_LOCKS.get(thread_id)
        if lock is None:
            if len(_TURN_LOCKS) >= _TURN_LOCKS_MAX:
                for key, candidate in list(_TURN_LOCKS.items()):
                    if key != thread_id and not candidate.locked():
                        del _TURN_LOCKS[key]
                        break
                else:
                    _TURN_LOCKS.pop(next(iter(_TURN_LOCKS)))
            lock = threading.Lock()
            _TURN_LOCKS[thread_id] = lock
        return lock


def reset_for_tests() -> None:
    with _TURN_LOCKS_GUARD:
        _TURN_LOCKS.clear()

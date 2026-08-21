"""Session-scoped cancel, steer, and queue controls."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Control:
    cancel_event: threading.Event = field(default_factory=threading.Event)
    steer: deque[str] = field(default_factory=deque)
    queued: deque[str] = field(default_factory=deque)
    active: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)
    aborts: set = field(default_factory=set)


# The "active session" for the current thread. RetryLLMProxy consults this so
# a Stop pressed on one session aborts exactly that session's in-flight HTTP
# request even when several sessions' LLM proxies run on distinct worker
# threads (threading.local is per-thread, so no cross-session bleed).
_thread_local = threading.local()


def set_active_session(session_id: str | None) -> None:
    """Bind this thread to a session id; pass None to unbind."""
    _thread_local.session_id = None if session_id is None else str(session_id)


def active_session() -> str | None:
    """The session id this thread is currently serving, if any."""
    return getattr(_thread_local, "session_id", None)


class TurnControlRegistry:
    def __init__(self):
        self._items: dict[str, _Control] = {}
        self._lock = threading.RLock()

    def _get(self, session_id: str) -> _Control:
        with self._lock:
            return self._items.setdefault(str(session_id), _Control())

    def begin(self, session_id: str) -> None:
        item = self._get(session_id)
        with item.lock:
            # Do NOT clear a pre-existing cancel event: if Stop arrived
            # between turn_started and begin(), the cancellation must
            # survive so the turn terminates as cancelled rather than
            # starting a fresh LLM request.
            item.active = True

    def end(self, session_id: str) -> None:
        item = self._get(session_id)
        with item.lock:
            item.active = False

    def cancel(self, session_id: str) -> bool:
        item = self._get(session_id)
        item.cancel_event.set()
        # A Stop must also fire every registered abort so a blocking HTTP
        # request in flight is interrupted immediately, not after the provider
        # returns.
        self.abort(session_id)
        return item.active

    def register_abort(self, session_id: str, fn) -> None:
        """Register a session-scoped abort callable (e.g. an LLM proxy's
        transport-closing handler). Thread-safe."""
        item = self._get(session_id)
        with item.lock:
            item.aborts.add(fn)

    def unregister_abort(self, session_id: str, fn) -> None:
        item = self._get(session_id)
        with item.lock:
            item.aborts.discard(fn)

    def abort(self, session_id: str) -> None:
        """Fire every registered abort callable for the session, best-effort.

        Each callable is wrapped in try/except so one broken handler can never
        block the others or the caller. Must return quickly."""
        item = self._get(session_id)
        with item.lock:
            callbacks = list(item.aborts)
        for fn in callbacks:
            try:
                fn()
            except Exception:
                pass

    def cancelled(self, session_id: str) -> bool:
        return self._get(session_id).cancel_event.is_set()

    def steer(self, session_id: str, text: str) -> bool:
        if not str(text).strip():
            return False
        item = self._get(session_id)
        with item.lock:
            if not item.active:
                return False
            item.steer.append(str(text).strip())
            return True

    def drain_steer(self, session_id: str) -> list[str]:
        item = self._get(session_id)
        with item.lock:
            out = list(item.steer)
            item.steer.clear()
            return out

    def queue(self, session_id: str, text: str) -> int:
        item = self._get(session_id)
        with item.lock:
            item.queued.append(str(text).strip())
            return len(item.queued)

    def pop_queued(self, session_id: str) -> str | None:
        item = self._get(session_id)
        with item.lock:
            return item.queued.popleft() if item.queued else None

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._items.pop(str(session_id), None)


turn_controls = TurnControlRegistry()

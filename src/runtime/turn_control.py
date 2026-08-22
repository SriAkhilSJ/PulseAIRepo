"""Session-scoped cancel, steer, queue, and in-flight abort controls."""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

AbortHandle = Callable[[], None]


@dataclass
class _Control:
    cancel_event: threading.Event = field(default_factory=threading.Event)
    steer: deque[str] = field(default_factory=deque)
    queued: deque[str] = field(default_factory=deque)
    active: bool = False
    active_depth: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)
    aborts: set[AbortHandle] = field(default_factory=set)


# The active session for the current worker thread. RetryLLMProxy uses this to
# register each blocking provider request with the matching session control.
_thread_local = threading.local()


def set_active_session(session_id: str | None) -> None:
    """Bind this thread to a session id; pass None to unbind."""
    _thread_local.session_id = None if session_id is None else str(session_id)


def active_session() -> str | None:
    """Return the session id this thread is currently serving, if any."""
    return getattr(_thread_local, "session_id", None)


class TurnControlRegistry:
    def __init__(self):
        self._items: dict[str, _Control] = {}
        self._lock = threading.RLock()

    def _get(self, session_id: str) -> _Control:
        with self._lock:
            return self._items.setdefault(str(session_id), _Control())

    def begin(self, session_id: str) -> None:
        """Acquire turn ownership for a session.

        The outer bridge begins before publishing ``turn_started``. The graph
        may begin the same turn again, so ownership is depth-counted. Only the
        first owner of a new turn clears the previous turn's cancellation;
        nested begin calls can never erase a Stop from the active turn.
        """
        item = self._get(session_id)
        with item.lock:
            if item.active_depth == 0:
                item.cancel_event.clear()
            item.active_depth += 1
            item.active = True

    def end(self, session_id: str) -> None:
        """Release one turn owner; repeated cleanup is harmless."""
        item = self._get(session_id)
        with item.lock:
            if item.active_depth > 0:
                item.active_depth -= 1
            item.active = item.active_depth > 0

    def cancel(self, session_id: str) -> bool:
        """Cancel an active turn and interrupt its registered requests.

        Cancelling an inactive session is rejected instead of poisoning the
        next turn. The event and callback snapshot are serialized with begin()
        and request registration, while callbacks run outside the lock.
        """
        item = self._get(session_id)
        with item.lock:
            if item.active_depth == 0:
                return False
            item.cancel_event.set()
            callbacks = tuple(item.aborts)
        self._fire(callbacks)
        return True

    def register_abort(self, session_id: str, fn: AbortHandle) -> None:
        """Register a request-owned abort handle for an active session.

        If Stop won the race just before registration, fire the new handle
        immediately instead of allowing the request to start uninterruptibly.
        """
        item = self._get(session_id)
        with item.lock:
            abort_now = item.cancel_event.is_set()
            if not abort_now:
                item.aborts.add(fn)
        if abort_now:
            self._fire((fn,))

    def unregister_abort(self, session_id: str, fn: AbortHandle) -> None:
        item = self._get(session_id)
        with item.lock:
            item.aborts.discard(fn)

    def abort(self, session_id: str) -> None:
        """Fire all currently registered handles without changing state."""
        item = self._get(session_id)
        with item.lock:
            callbacks = tuple(item.aborts)
        self._fire(callbacks)

    @staticmethod
    def _fire(callbacks: tuple[AbortHandle, ...]) -> None:
        for fn in callbacks:
            try:
                fn()
            except Exception:
                # Cancellation is best-effort and must never block the bridge.
                pass

    def cancelled(self, session_id: str) -> bool:
        return self._get(session_id).cancel_event.is_set()

    def admit_action(self, session_id: str) -> bool:
        """Atomically admit a tool batch before execution begins.

        cancel() uses the same lock, establishing a deterministic ordering:
        either the action is admitted first, or Stop wins and execution must
        not start.
        """
        item = self._get(session_id)
        with item.lock:
            # Unmanaged/direct graph callers have no begin()/end() lifecycle;
            # they remain compatible as long as no cancellation is pending.
            return not item.cancel_event.is_set()

    def steer(self, session_id: str, text: str) -> bool:
        if not str(text).strip():
            return False
        item = self._get(session_id)
        with item.lock:
            if item.active_depth == 0:
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

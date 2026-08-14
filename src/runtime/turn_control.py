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
            item.cancel_event.clear()
            item.active = True

    def end(self, session_id: str) -> None:
        item = self._get(session_id)
        with item.lock:
            item.active = False

    def cancel(self, session_id: str) -> bool:
        item = self._get(session_id)
        item.cancel_event.set()
        return item.active

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

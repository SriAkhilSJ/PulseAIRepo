"""Session-scoped runtime events and pre-execution approval broker."""
from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import Any


class EventBus:
    """Thread-safe event projection with session-filtered replay.

    `thread_id=None` is the compatibility/admin subscription and receives all
    sessions. User-facing clients must subscribe with their session id.
    """

    def __init__(self):
        self._queues: list[tuple[queue.Queue, str | None]] = []
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._max_history = 500

    @staticmethod
    def _session_of(event: dict) -> str | None:
        payload = event.get("payload") or {}
        return str(payload.get("thread_id") or payload.get("session_id") or "") or None

    def subscribe(self, thread_id: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        wanted = str(thread_id) if thread_id else None
        with self._lock:
            if wanted is None:
                replay = list(self._history)
            else:
                replay = [e for e in self._history if self._session_of(e) == wanted]
            # P6: replay the NEWEST events that fit the queue. The previous
            # head-first loop broke on queue-full, so a late subscriber to a
            # busy session replayed the OLDEST retained events and missed
            # the most recent ones — a reconnected dashboard lost the latest
            # state. The tail slice is always <= maxsize items into an empty
            # queue, so put_nowait cannot raise here.
            for evt in replay[-q.maxsize:]:
                q.put_nowait(evt)
            self._queues.append((q, wanted))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._queues = [(candidate, sid) for candidate, sid in self._queues if candidate is not q]

    def emit(self, event_type: str, payload: dict[str, Any]) -> dict:
        event = {
            "event_id": f"evt-{uuid.uuid4().hex}",
            "type": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }
        event_session = self._session_of(event)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            dead: list[queue.Queue] = []
            for q, wanted in self._queues:
                if wanted is not None and event_session != wanted:
                    continue
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            if dead:
                self._queues = [(q, sid) for q, sid in self._queues if q not in dead]
        return event

    @staticmethod
    def _release(q: queue.Queue) -> None:
        """Pair one removal with one task_done, tolerating an over-release.

        Queue.join() counts PUTS, not deliveries: anything that takes an item out
        of a subscriber queue has to release its join slot, or the counter stays
        above zero forever. A live round hung exactly this way — an engine turn
        completed, `turn_done` was never emitted, and the bridge sat in `join()`
        waiting on a slot that had already been consumed. task_done() raises
        ValueError on an over-release; swallowing that is far cheaper than the
        hang, and no consumer here pairs its own gets with task_done twice.
        """
        try:
            q.task_done()
        except ValueError:
            pass

    def clear(self, thread_id: str | None = None) -> None:
        wanted = str(thread_id) if thread_id else None
        with self._lock:
            if wanted is None:
                self._history.clear()
            else:
                self._history = [e for e in self._history if self._session_of(e) != wanted]
            for q, sid in self._queues:
                if wanted is not None and sid not in (None, wanted):
                    continue
                kept: list[dict] = []
                while True:
                    try:
                        evt = q.get_nowait()
                    except queue.Empty:
                        break
                    # Every removal releases a join slot; the re-queue below starts
                    # a fresh cycle, so the counter stays honest either way.
                    self._release(q)
                    if wanted is not None and self._session_of(evt) != wanted:
                        kept.append(evt)
                for evt in kept:
                    try:
                        q.put_nowait(evt)
                    except queue.Full:
                        break


class ApprovalQueue:
    """Session-scoped approval requests; timeout and errors deny by default."""

    def __init__(self):
        self._pending: dict[str, dict] = {}
        self._conditions: dict[str, threading.Condition] = {}
        self._lock = threading.RLock()

    def request(
        self, tool_id: str, tool_name: str, tool_args: dict,
        *, session_id: str = "default", diff: dict | None = None,
    ) -> dict:
        with self._lock:
            condition = self._conditions.setdefault(tool_id, threading.Condition(self._lock))
            item = {
                "id": tool_id, "session_id": session_id,
                "tool_name": tool_name, "tool_args": tool_args,
                "diff": diff, "status": "pending", "decision": None,
                "always_allow": False, "created_at": time.time(),
            }
            self._pending[tool_id] = item
            return dict(item)

    def resolve(
        self, tool_id: str, approved: bool, always_allow: bool = False,
        *, session_id: str | None = None,
    ) -> bool:
        with self._lock:
            item = self._pending.get(tool_id)
            if item is None or (session_id and item["session_id"] != session_id):
                return False
            item.update(status="resolved", decision=bool(approved), always_allow=bool(always_allow))
            self._conditions.setdefault(tool_id, threading.Condition(self._lock)).notify_all()
            return True

    def wait_for_decision(self, tool_id: str, timeout: float = 300.0) -> dict | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            condition = self._conditions.setdefault(tool_id, threading.Condition(self._lock))
            while True:
                item = self._pending.get(tool_id)
                if item and item.get("status") == "resolved":
                    result = dict(item)
                    self._pending.pop(tool_id, None)
                    self._conditions.pop(tool_id, None)
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if item:
                        item.update(status="resolved", decision=False, timeout=True)
                        result = dict(item)
                        self._pending.pop(tool_id, None)
                        self._conditions.pop(tool_id, None)
                        return result
                    return None
                condition.wait(timeout=remaining)

    def get_pending(self, session_id: str | None = None) -> list[dict]:
        with self._lock:
            return [
                dict(item) for item in self._pending.values()
                if item["status"] == "pending"
                and (session_id is None or item["session_id"] == session_id)
            ]


event_bus = EventBus()
approval_queue = ApprovalQueue()


class ClarifyQueue:
    """Session-scoped clarify (hermes ask-tool) requests: the model's batch of
    questions blocks the turn until the UI replies, the user skips, or the
    timeout fires. Shape mirrors ApprovalQueue so the bridge/renderer plumbing
    is identical; the payload is answers-by-qid instead of a decision."""

    def __init__(self):
        self._pending: dict[str, dict] = {}
        self._conditions: dict[str, threading.Condition] = {}
        self._lock = threading.RLock()

    def request(self, request_id: str, questions: list[dict], *, session_id: str = "default") -> dict:
        with self._lock:
            condition = self._conditions.setdefault(request_id, threading.Condition(self._lock))
            item = {
                "id": request_id, "session_id": session_id,
                "questions": questions, "status": "pending",
                "answers": None, "timed_out": False,
                "created_at": time.time(),
            }
            self._pending[request_id] = item
            return dict(item)

    def resolve(
        self, request_id: str, answers: dict | None,
        *, timed_out: bool = False, session_id: str | None = None,
    ) -> bool:
        with self._lock:
            item = self._pending.get(request_id)
            if item is None or (session_id and item["session_id"] != session_id):
                return False
            item.update(status="resolved", answers=dict(answers or {}), timed_out=bool(timed_out))
            self._conditions.setdefault(request_id, threading.Condition(self._lock)).notify_all()
            return True

    def wait_for_answers(self, request_id: str, timeout: float = 300.0) -> dict | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            condition = self._conditions.setdefault(request_id, threading.Condition(self._lock))
            while True:
                item = self._pending.get(request_id)
                if item and item.get("status") == "resolved":
                    result = dict(item)
                    self._pending.pop(request_id, None)
                    self._conditions.pop(request_id, None)
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Hermes timeout semantics: the user walked away — every
                    # question resolves to the canonical sentinel, which the
                    # tool reports as timed_out so the model decides and moves.
                    if item:
                        item.update(status="resolved", answers={}, timed_out=True)
                        result = dict(item)
                        self._pending.pop(request_id, None)
                        self._conditions.pop(request_id, None)
                        return result
                    return None
                condition.wait(timeout=remaining)

    def get_pending(self, session_id: str | None = None) -> list[dict]:
        with self._lock:
            return [
                dict(item) for item in self._pending.values()
                if item["status"] == "pending"
                and (session_id is None or item["session_id"] == session_id)
            ]


clarify_queue = ClarifyQueue()

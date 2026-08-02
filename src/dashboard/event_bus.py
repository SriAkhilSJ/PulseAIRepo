"""
Event Bus for PulseAI Dashboard
================================
Thread-safe event streaming between the agent and the web UI.
The agent emits events. The Flask server reads them and pushes
to the browser via Server-Sent Events (SSE).

Event Types:
- message.user          : User sent a message
- message.agent.start   : Agent began responding
- message.agent.chunk   : Streaming text token
- message.agent.end     : Agent finished
- message.agent.error   : Agent hit an error
- tool.call             : Agent wants to call a tool
- tool.result           : Tool returned output
- tool.approval.request : Needs user approval
- tool.approval.done    : Approval resolved
- plan.created          : Plan generated
- plan.step.complete    : Step finished
- plan.step.fail        : Step failed
- diff.show             : File diff to render
- analytics.update      : Cost / tokens / timing
- session.status        : Agent online/offline/busy
"""

import json
import queue
import threading
import time
from typing import Any, Callable

class EventBus:
    """
    Thread-safe event bus for agent ↔ dashboard communication.
    """
    def __init__(self):
        self._queues: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._max_history = 500

    def subscribe(self) -> queue.Queue:
        """Create a new subscriber queue. Used by Flask SSE endpoint."""
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            # Replay history so new subscriber catches up
            for evt in self._history:
                try:
                    q.put_nowait(evt)
                except queue.Full:
                    break
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        Emit an event to all subscribers.
        Call this from anywhere in the agent code.
        """
        event = {
            "type": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            dead = []
            for q in self._queues:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._queues.remove(q)

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            for q in self._queues:
                try:
                    while not q.empty():
                        q.get_nowait()
                except queue.Empty:
                    pass

class ApprovalQueue:
    """
    Holds pending tool approvals from the UI.
    The agent checks this before executing destructive tools.
    """
    def __init__(self):
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._event = threading.Event()

    def request(self, tool_id: str, tool_name: str, tool_args: dict) -> None:
        with self._lock:
            self._pending[tool_id] = {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "status": "pending",
                "decision": None,
            }
        self._event.clear()

    def resolve(self, tool_id: str, approved: bool, always_allow: bool = False) -> None:
        with self._lock:
            if tool_id in self._pending:
                self._pending[tool_id]["status"] = "resolved"
                self._pending[tool_id]["decision"] = approved
                self._pending[tool_id]["always_allow"] = always_allow
        self._event.set()

    def wait_for_decision(self, tool_id: str, timeout: float = 300.0) -> dict | None:
        """
        Block until the user approves/denies, or timeout.
        Returns the decision dict or None on timeout.
        """
        # wait_for_decision logic refinement: 
        # Since we use self._event.wait(), we must ensure we check the specific tool_id
        # because many tools could be waiting.
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                if self._pending.get(tool_id, {}).get("status") == "resolved":
                    return self._pending.get(tool_id)
            if self._event.wait(timeout=1.0):
                self._event.clear() # Reset event for next notification
        return None

    def get_pending(self) -> list[dict]:
        with self._lock:
            return [
                {"id": k, **v}
                for k, v in self._pending.items()
                if v["status"] == "pending"
            ]

# Global singletons — shared across the whole app
event_bus = EventBus()
approval_queue = ApprovalQueue()

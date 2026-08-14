"""Managed, cancellable lifecycle contracts for delegated agents."""
from __future__ import annotations

import enum
import hashlib
import hmac
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from typing import Any

from src.agents.runtime_profile import KNOWN_CAPABILITIES


class SubagentState(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SubagentHandle:
    subagent_id: str
    parent_session_id: str
    created_at: float
    capability_token: str


@dataclass
class _Record:
    handle: SubagentHandle
    state: SubagentState
    goal: str
    mode: str
    allowed_capabilities: tuple[str, ...]
    result: str | None = None
    error: str | None = None
    future: Any = None
    updated_at: float = field(default_factory=time.time)


class SubagentLifecycleService:
    def __init__(self, max_workers: int = 4):
        self._secret = secrets.token_bytes(32)
        self._records: dict[str, _Record] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pulse-subagent")

    def _token(self, sid: str, parent: str, created: float) -> str:
        return hmac.new(self._secret, f"{sid}|{parent}|{created:.6f}".encode(), hashlib.sha256).hexdigest()

    def _record(self, handle: SubagentHandle) -> _Record | None:
        if not isinstance(handle, SubagentHandle):
            return None
        expected = self._token(handle.subagent_id, handle.parent_session_id, handle.created_at)
        if not hmac.compare_digest(expected, handle.capability_token):
            return None
        with self._lock:
            return self._records.get(handle.subagent_id)

    def launch(
        self, *, parent_session_id: str, goal: str, mode: str = "research",
        parent_capabilities: tuple[str, ...] = (),
        allowed_capabilities: tuple[str, ...] = (),
    ) -> SubagentHandle:
        if mode not in {"research", "code", "test", "review"}:
            raise ValueError("invalid subagent mode")
        if not goal.strip() or len(goal) > 16000:
            raise ValueError("goal must be 1..16000 characters")
        unknown = set(allowed_capabilities) - KNOWN_CAPABILITIES
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        if parent_capabilities and not set(allowed_capabilities).issubset(parent_capabilities):
            raise ValueError("child capabilities may not broaden parent permissions")
        sid = f"sub-{mode}-{uuid.uuid4().hex[:12]}"
        created = time.time()
        handle = SubagentHandle(sid, parent_session_id, created, self._token(sid, parent_session_id, created))
        record = _Record(handle, SubagentState.PENDING, goal, mode, tuple(allowed_capabilities))
        with self._lock:
            self._records[sid] = record
        record.future = self._pool.submit(self._run, record)
        return handle

    def _emit(self, record: _Record) -> None:
        try:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("subagent.updated", {
                "thread_id": record.handle.parent_session_id,
                "subagent_id": record.handle.subagent_id,
                "state": record.state.value, "goal": record.goal[:200],
            })
        except Exception:
            pass

    def _run(self, record: _Record) -> None:
        with self._lock:
            if record.state == SubagentState.CANCEL_REQUESTED:
                record.state = SubagentState.CANCELLED
                self._emit(record)
                return
            record.state = SubagentState.RUNNING
            record.updated_at = time.time()
        self._emit(record)
        try:
            from src.agents.sub_agent import subagent_coordinator
            agent_id = subagent_coordinator.spawn(
                mode=record.mode, task=record.goal,
                parent_thread_id=record.handle.parent_session_id,
                allowed_capabilities=record.allowed_capabilities,
            )
            result = subagent_coordinator.get_result(agent_id)
            with self._lock:
                if record.state == SubagentState.CANCEL_REQUESTED:
                    record.state = SubagentState.CANCELLED
                else:
                    record.state = SubagentState.SUCCEEDED
                    record.result = result[:32000]
                record.updated_at = time.time()
        except Exception as exc:
            with self._lock:
                record.state = SubagentState.FAILED
                record.error = str(exc)[:32000]
                record.updated_at = time.time()
        self._emit(record)

    def status(self, handle: SubagentHandle) -> dict:
        record = self._record(handle)
        if record is None:
            return {"state": "unknown"}
        with self._lock:
            return {"state": record.state.value, "updated_at": record.updated_at,
                    "subagent_id": record.handle.subagent_id}

    def wait(self, handle: SubagentHandle, timeout: float | None = None) -> dict:
        record = self._record(handle)
        if record is None:
            return {"state": "unknown", "ready": False}
        try:
            record.future.result(timeout=timeout)
        except TimeoutError:
            return {"state": record.state.value, "ready": False, "timed_out": True}
        except Exception:
            pass
        return self.result(handle)

    def cancel(self, handle: SubagentHandle) -> bool:
        record = self._record(handle)
        if record is None:
            return False
        with self._lock:
            if record.state in {SubagentState.SUCCEEDED, SubagentState.FAILED, SubagentState.CANCELLED}:
                return False
            record.state = SubagentState.CANCEL_REQUESTED
            record.updated_at = time.time()
        from src.runtime.turn_control import turn_controls
        turn_controls.cancel(record.handle.subagent_id)
        record.future.cancel()
        self._emit(record)
        return True

    def result(self, handle: SubagentHandle) -> dict:
        record = self._record(handle)
        if record is None:
            return {"state": "unknown", "ready": False}
        terminal = record.state in {SubagentState.SUCCEEDED, SubagentState.FAILED, SubagentState.CANCELLED}
        return {"state": record.state.value, "ready": terminal,
                "result": record.result, "error": record.error,
                "subagent_id": record.handle.subagent_id}


subagent_lifecycle = SubagentLifecycleService()

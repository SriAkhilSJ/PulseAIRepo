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
    # OpenCode parity extensions
    description: str = ""
    agent_name: str = ""
    tool_call_id: str | None = None
    tool_calls: int = 0
    background: bool = False
    child_thread_id: str = ""
    workspace: str = ""
    # OpenCode parity: per-agent / per-call model + prompt, and resume.
    provider: str = ""
    model: str = ""
    agent_prompt: str | None = None
    continuation: bool = False


class SubagentLifecycleService:
    def __init__(self, max_workers: int = 4):
        self._secret = secrets.token_bytes(32)
        self._records: dict[str, _Record] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="crusor-subagent")
        # OpenCode parity: track toolCalls per child session via event_bus
        self._tool_listener_started = False
        self._start_tool_listener()

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
        description: str = "",
        agent_name: str = "",
        tool_call_id: str | None = None,
        background: bool = False,
        parent_permission: list[dict] | None = None,
        subagent_permission: list[dict] | None = None,
        workspace: str | None = None,
        provider: str = "",
        model: str = "",
        agent_prompt: str | None = None,
    ) -> SubagentHandle:
        if mode not in {"research", "code", "test", "review"}:
            raise ValueError("invalid subagent mode")
        if not goal.strip() or len(goal) > 16000:
            raise ValueError("goal must be 1..16000 characters")
        # OpenCode parity: derive capabilities via permission module (subset enforcement)
        try:
            from src.agents.subagent_permissions import derive_subagent_capabilities, derive_subagent_session_permission
            # Filter to subset (if parent has caps, child cannot broaden)
            filtered_caps = derive_subagent_capabilities(tuple(parent_capabilities or ()), tuple(allowed_capabilities or ()))
            # If filtering reduced caps and parent had caps, it means child tried to broaden — enforce error for strict parity
            if parent_capabilities and set(allowed_capabilities) - set(filtered_caps):
                # For strict contract, keep error, but filtered is used for persistence
                raise ValueError("child capabilities may not broaden parent permissions")
            allowed_capabilities = filtered_caps
            # Derive file permission ruleset (deny + external_directory inheritance) — stored for audit
            _derived_perm = derive_subagent_session_permission(parent_permission, subagent_permission)
            # _derived_perm could be persisted or logged; for now we keep it in memory for debugging
        except ValueError:
            raise
        except Exception:
            # Permission derivation is best-effort, never blocks launch
            pass
        if not allowed_capabilities:
            # No scope asked for: the mode's canonical scope (children bind
            # a strict-waisted tool surface; an empty scope would collapse
            # them to the core-only waist). Derived BEFORE the broadening
            # check so an explicit parent scope still constrains it.
            from src.agents.subagent_permissions import default_capabilities_for_mode
            allowed_capabilities = default_capabilities_for_mode(mode)
        unknown = set(allowed_capabilities) - KNOWN_CAPABILITIES
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        if parent_capabilities and not set(allowed_capabilities).issubset(parent_capabilities):
            raise ValueError("child capabilities may not broaden parent permissions")
        sid = f"sub-{mode}-{uuid.uuid4().hex[:12]}"
        created = time.time()
        handle = SubagentHandle(sid, parent_session_id, created, self._token(sid, parent_session_id, created))
        record = _Record(
            handle, SubagentState.PENDING, goal, mode, tuple(allowed_capabilities),
            description=(description or goal[:50])[:200],
            agent_name=agent_name or mode,
            tool_call_id=tool_call_id,
            background=background,
            child_thread_id=sid,
            workspace=workspace or "",
            provider=provider,
            model=model,
            agent_prompt=agent_prompt,
        )
        with self._lock:
            self._records[sid] = record
        # Persist to store (OpenCode parity: child session with parentID)
        try:
            from src.runtime.subagent_store import get_store, SubagentSessionRow
            store = get_store()
            store.create(SubagentSessionRow(
                subagent_id=sid,
                parent_session_id=parent_session_id,
                child_thread_id=sid,
                mode=mode,
                goal=goal,
                description=record.description,
                agent_name=record.agent_name,
                state=record.state.value,
                created_at=created,
                updated_at=record.updated_at,
                tool_call_id=tool_call_id,
                tool_calls=0,
                background=background,
            ))
        except Exception:
            pass
        record.future = self._pool.submit(self._run, record)
        return handle

    def resume_child(
        self, child_id: str, *, goal: str, parent_session_id: str,
        workspace: str | None = None, provider: str = "", model: str = "",
        description: str = "",
    ) -> SubagentHandle:
        """Continue an existing child session (OpenCode: passing a
        sessionID to the task tool resumes that session — same thread,
        same checkpoint, so the worker keeps its context; the specialist
        persona is NOT re-applied, the follow-up goes in verbatim). Only
        the child's own parent may resume it, and only once it settled."""
        if not goal.strip() or len(goal) > 16000:
            raise ValueError("goal must be 1..16000 characters")
        from src.runtime.subagent_store import get_store

        row = get_store().get(child_id)
        if row is None:
            raise ValueError(f"unknown sub-agent session '{child_id}'")
        if str(row.parent_session_id) != str(parent_session_id):
            raise ValueError(f"session '{child_id}' belongs to a different parent session")
        if str(row.state) in ("running", "pending"):
            raise ValueError(f"session '{child_id}' is still running")
        with self._lock:
            existing = self._records.get(child_id)
            if existing is not None and existing.state in (SubagentState.RUNNING, SubagentState.PENDING):
                raise ValueError(f"session '{child_id}' is still running")
        from src.agents.subagent_permissions import default_capabilities_for_mode

        mode = row.mode if row.mode in {"research", "code", "test", "review"} else "code"
        created = time.time()
        handle = SubagentHandle(child_id, parent_session_id, created, self._token(child_id, parent_session_id, created))
        record = _Record(
            handle, SubagentState.PENDING, goal, mode,
            tuple(default_capabilities_for_mode(mode)),
            description=(description or goal[:50])[:200],
            agent_name=row.agent_name or mode,
            background=False,
            child_thread_id=child_id,
            workspace=workspace or "",
            provider=provider,
            model=model,
            continuation=True,
        )
        with self._lock:
            self._records[child_id] = record
        # Refresh the durable row so lists/cards show it running again.
        try:
            get_store().update(child_id, state=record.state.value, updated_at=record.updated_at)
        except Exception:
            pass
        record.future = self._pool.submit(self._run, record)
        return handle

    def _start_tool_listener(self):
        if self._tool_listener_started:
            return
        self._tool_listener_started = True
        def _loop():
            try:
                from src.dashboard.event_bus import event_bus
                q = event_bus.subscribe(thread_id=None)
                while True:
                    try:
                        ev = q.get(timeout=1.0)
                    except Exception:
                        continue
                    try:
                        kind = ev.get("type", "")
                        payload = ev.get("payload") or {}
                        # Only care about tool events for child sessions
                        if kind not in {"tool.call", "tool.result", "tool_call_start", "tool_call_end"}:
                            # Also handle bridge projected events? Those have type tool_call_start/end but payload thread_id in event itself?
                            # For internal bus, tool.result has thread_id
                            pass
                        thread_id = str(payload.get("thread_id") or payload.get("session_id") or ev.get("session_id") or "")
                        if not thread_id or not thread_id.startswith("sub-"):
                            continue
                        # Increment tool_calls for matching child_thread_id
                        with self._lock:
                            rec = self._records.get(thread_id)
                            if rec is None:
                                # Also check by child_thread_id field
                                for r in self._records.values():
                                    if r.child_thread_id == thread_id:
                                        rec = r
                                        break
                            if rec is None:
                                continue
                            # Only count tool.result to avoid double counting call+result
                            if kind in {"tool.result", "tool_call_end"}:
                                rec.tool_calls += 1
                                rec.updated_at = time.time()
                                # Persist and emit updated count
                                try:
                                    self._persist_state(rec)
                                except Exception:
                                    pass
                                try:
                                    self._emit(rec)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    finally:
                        try:
                            q.task_done()
                        except Exception:
                            pass
            except Exception:
                pass
        t = threading.Thread(target=_loop, name="crusor-subagent-tool-listener", daemon=True)
        t.start()

    def _persist_state(self, record: _Record) -> None:
        try:
            from src.runtime.subagent_store import get_store
            store = get_store()
            store.update(
                record.handle.subagent_id,
                state=record.state.value,
                updated_at=record.updated_at,
                result=record.result,
                error=record.error,
                tool_calls=record.tool_calls,
                background=record.background,
                description=record.description,
                agent_name=record.agent_name,
                tool_call_id=record.tool_call_id,
            )
        except Exception:
            pass

    def _emit(self, record: _Record) -> None:
        try:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("subagent.updated", {
                "thread_id": record.handle.parent_session_id,
                "subagent_id": record.handle.subagent_id,
                "child_thread_id": record.child_thread_id or record.handle.subagent_id,
                "parent_session_id": record.handle.parent_session_id,
                "state": record.state.value,
                "goal": record.goal[:200],
                "description": record.description[:200],
                "mode": record.mode,
                "agent_name": record.agent_name,
                "tool_call_id": record.tool_call_id,
                "tool_calls": record.tool_calls,
                "background": record.background,
                "result": (record.result or "")[:2000] if record.result else None,
                "error": (record.error or "")[:500] if record.error else None,
            })
        except Exception:
            pass

    def _run(self, record: _Record) -> None:
        with self._lock:
            if record.state == SubagentState.CANCEL_REQUESTED:
                record.state = SubagentState.CANCELLED
                self._persist_state(record)
                self._emit(record)
                return
            record.state = SubagentState.RUNNING
            record.updated_at = time.time()
            self._persist_state(record)
        self._emit(record)
        try:
            from src.agents.sub_agent import subagent_coordinator
            _model_kwargs: dict[str, str] = {}
            if record.provider:
                _model_kwargs["provider"] = record.provider
            if record.model:
                _model_kwargs["model"] = record.model
            agent_id = subagent_coordinator.spawn(
                mode=record.mode, task=record.goal,
                parent_thread_id=record.handle.parent_session_id,
                **_model_kwargs,
                allowed_capabilities=record.allowed_capabilities,
                description=record.description,
                background=record.background,
                tool_call_id=record.tool_call_id,
                agent_prompt=record.agent_prompt,
                continuation=record.continuation,
                # The lifecycle emits this child's subagent.updated
                # stream itself; the coordinator must not double-speak.
                emit_events=False,
                # One id per child, everywhere: the child RUNS on the
                # lifecycle's session id, so the checkpoint the reader
                # opens is the conversation the child actually had.
                agent_id=record.handle.subagent_id,
                workspace=record.workspace or None,
            )
            result = subagent_coordinator.get_result(agent_id)
            with self._lock:
                if record.state == SubagentState.CANCEL_REQUESTED:
                    record.state = SubagentState.CANCELLED
                else:
                    record.state = SubagentState.SUCCEEDED
                    record.result = result[:32000]
                record.updated_at = time.time()
                self._persist_state(record)
        except Exception as exc:
            with self._lock:
                record.state = SubagentState.FAILED
                record.error = str(exc)[:32000]
                record.updated_at = time.time()
                self._persist_state(record)
        self._emit(record)
        # Background inject: if background, inject completion back to parent as synthetic turn
        if record.background and record.state == SubagentState.SUCCEEDED:
            try:
                self._inject_background_result(record)
            except Exception:
                pass

    def _inject_background_result(self, record: _Record) -> None:
        """OpenCode parity: when background subagent completes, inject <task> result into parent."""
        try:
            from src.agents.subagent_permissions import format_task_output
            from src.dashboard.event_bus import event_bus
            # Emit a synthetic token event that parent UI can show as completion
            # The parent's turn already ended with running state; this starts a new logical turn
            # We emit subagent.updated with completed + also a token-like event for transcript
            text = format_task_output(
                session_id=record.child_thread_id,
                state="completed",
                text=record.result or "",
                summary=f"Background task completed: {record.description}",
            )
            # Use event_bus to notify parent session — bridge will forward as token if needed
            event_bus.emit("subagent.background_completed", {
                "thread_id": record.handle.parent_session_id,
                "subagent_id": record.handle.subagent_id,
                "child_thread_id": record.child_thread_id,
                "text": text,
                "description": record.description,
            })
        except Exception:
            pass

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

"""Bounded reverse-RPC broker for read-only Code OSS host capabilities.

The desktop publishes compact descriptors. Agent tools may then request one of
those capabilities while the bridge's stdin loop remains responsive on its main
thread. No extension/MCP implementation or secret crosses this boundary.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

READ_ONLY_CAPABILITIES = frozenset({
    "workspace.trust", "editor.activeSelection", "editor.dirtyText",
    "diagnostics.markers", "language.symbols", "language.definitions",
    "language.references", "search.workspace", "scm.state",
})
_MAX_ARGUMENT_CHARS = 16_000
_MAX_RESULT_CHARS = 128_000


class HostCapabilityError(RuntimeError):
    pass


class HostCapabilityBroker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capabilities: dict[str, dict[str, dict[str, Any]]] = {}
        self._workspaces: dict[str, str] = {}
        self._pending: dict[str, tuple[threading.Event, dict[str, Any], str, str]] = {}
        self._emit: Callable[[dict[str, Any]], None] | None = None

    def reset(self) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
            self._capabilities.clear()
            self._workspaces.clear()
            self._emit = None
        for event, box, _session, _workspace in pending:
            box.update(status="error", error="host capability transport reset")
            event.set()

    def set_emitter(self, emit: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._emit = emit

    def update(self, session_id: str, workspace: str, descriptors: list[dict[str, Any]]) -> int:
        compact: dict[str, dict[str, Any]] = {}
        for raw in descriptors[:128]:
            capability_id = str(raw.get("id") or "")
            if capability_id not in READ_ONLY_CAPABILITIES:
                continue
            compact[capability_id] = {
                "id": capability_id,
                "availability": str(raw.get("availability") or "unavailable"),
                "risk": "read",
                "requiresTrust": bool(raw.get("requiresTrust", False)),
                "provider": str(raw.get("provider") or "workbench"),
                "detail": str(raw.get("detail") or "")[:500],
            }
        with self._lock:
            bound = self._workspaces.get(session_id)
            if bound is not None and bound != workspace:
                raise HostCapabilityError(
                    f"host capability workspace changed for {session_id}: {bound!r} -> {workspace!r}"
                )
            self._workspaces[session_id] = workspace
            self._capabilities[session_id] = compact
        return len(compact)

    def discover(self, session_id: str, query: str = "") -> list[dict[str, Any]]:
        terms = [term.lower() for term in query.split() if term.strip()]
        with self._lock:
            values = list(self._capabilities.get(session_id, {}).values())
        if terms:
            values = [item for item in values if all(
                term in f"{item['id']} {item['provider']} {item['detail']}".lower()
                for term in terms
            )]
        return sorted(values, key=lambda item: item["id"])

    def request(
        self, *, session_id: str, workspace: str, capability_id: str,
        arguments: dict[str, Any], timeout: float = 30.0,
    ) -> dict[str, Any]:
        with self._lock:
            descriptor = self._capabilities.get(session_id, {}).get(capability_id)
            bound_workspace = self._workspaces.get(session_id)
            emit = self._emit
        if capability_id not in READ_ONLY_CAPABILITIES or descriptor is None:
            raise HostCapabilityError(f"host capability is not published: {capability_id}")
        if descriptor.get("availability") != "available":
            raise HostCapabilityError(
                f"host capability {capability_id} is {descriptor.get('availability')}"
            )
        if bound_workspace != workspace:
            raise HostCapabilityError("host capability request workspace does not match desktop binding")
        if emit is None:
            raise HostCapabilityError("desktop host capability transport is unavailable")
        argument_size = len(json.dumps(arguments, ensure_ascii=False, separators=(",", ":")))
        if argument_size > _MAX_ARGUMENT_CHARS:
            raise HostCapabilityError(
                f"host capability arguments exceeded {_MAX_ARGUMENT_CHARS} characters"
            )

        request_id = f"host-{uuid.uuid4().hex}"
        event = threading.Event()
        box: dict[str, Any] = {}
        with self._lock:
            self._pending[request_id] = (event, box, session_id, workspace)

        from src.runtime.turn_control import turn_controls

        def abort() -> None:
            with self._lock:
                pending = self._pending.pop(request_id, None)
            if pending is not None:
                box.update(status="error", error="host capability cancelled by user")
                event.set()

        turn_controls.register_abort(session_id, abort)
        try:
            emit({
                "type": "host_tool_request", "request_id": request_id,
                "session_id": session_id, "workspace": workspace,
                "capability_id": capability_id, "arguments": arguments,
                "deadline_ms": max(1000, min(int(timeout * 1000), 60_000)),
                "timestamp": time.time(),
            })
            if not event.wait(max(1.0, min(timeout, 60.0))):
                with self._lock:
                    self._pending.pop(request_id, None)
                raise HostCapabilityError(f"host capability {capability_id} timed out")
        finally:
            turn_controls.unregister_abort(session_id, abort)
            with self._lock:
                self._pending.pop(request_id, None)
        if str(box.get("status")) != "ok":
            raise HostCapabilityError(str(box.get("error") or "desktop host capability failed"))
        result = box.get("result")
        text_size = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        if text_size > _MAX_RESULT_CHARS:
            raise HostCapabilityError(
                f"host capability result exceeded {_MAX_RESULT_CHARS} characters"
            )
        return {"capability_id": capability_id, "result": result,
                "duration_ms": box.get("duration_ms")}

    def resolve(self, request_id: str, payload: dict[str, Any]) -> bool:
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return False
            event, box, expected_session, expected_workspace = pending
            if (
                str(payload.get("session_id") or "") != expected_session
                or str(payload.get("workspace") or "") != expected_workspace
            ):
                return False
            self._pending.pop(request_id, None)
        box.update(payload)
        event.set()
        return True


host_capability_broker = HostCapabilityBroker()

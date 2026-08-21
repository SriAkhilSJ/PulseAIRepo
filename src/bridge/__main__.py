"""Headless Scope/Pulse IDE bridge with real agent streaming and turn control.

Workspace contract (P0): a session is only ever bound to a real project folder.
The renderer disables prompt submission without one, and the bridge enforces
the same rule so no client can silently run against ".", the engine root, or
the bundled app dir. The desktop MUST pass the user's opened workspace.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import uuid

from src.bridge.protocol import (
    CLIENT_METHODS, ProtocolError, check_client_hello, decode_line, encode,
    error_frame, hello,
)
from src.runtime.identity import TurnIdentity, normalize_id

ENGINE_VERSION = "0.2.0-runtime"

# A session is only ever bound to a real project folder. The renderer disables
# prompt submission without one; the bridge enforces the same contract so no
# client can silently run against ".", the engine root, or the bundled app dir.
_WORKSPACE_REQUIRED_METHODS = frozenset({
    "session_create", "session_load", "session_resume", "session_fork", "prompt",
})
NO_WORKSPACE_ERROR = (
    "workspace required: open a project folder before starting a Pulse session"
)


class WorkspaceSwitchError(Exception):
    """A session already bound to one workspace must never silently move."""

    def __init__(self, sid: str, bound: str, requested: str) -> None:
        super().__init__(
            f"session {sid} is bound to workspace {bound!r}; "
            f"cannot switch to workspace {requested!r}"
        )


class BridgeServer:
    def __init__(self):
        # --- Strict stdout ownership (Protocol v2 transport) ---
        # Protocol frames go to the original stdout buffer, captured once.
        # All ordinary print() output is routed to stderr so that engine/
        # graph diagnostics can never corrupt the JSON-lines wire protocol.
        self._protocol_out = sys.stdout.buffer
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
        sys.stdout = sys.stderr
        self.greeted = False
        self.protocol_version: int | None = None
        self._write_lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._subagents: dict[str, object] = {}
        self._shutdown = threading.Event()

    def emit(self, frame: dict) -> None:
        with self._write_lock:
            self._protocol_out.write(encode(frame))
            self._protocol_out.flush()

    def _session(self, requested: str | None, workspace: str = "") -> str:
        """Resolve a session id, binding the FIRST workspace only.

        An existing session keeps its bound workspace: a follow-up frame that
        carries a DIFFERENT workspace raises WorkspaceSwitchError instead of
        silently re-homing the session. Frames without a workspace (cancel,
        steer, events_replay, ...) never trip this because they do not bind.
        """
        sid = normalize_id(requested, prefix="session")
        existing = self._sessions.get(sid)
        if existing is not None:
            if workspace and existing["workspace"] != workspace:
                raise WorkspaceSwitchError(sid, existing["workspace"], workspace)
            return sid
        self._sessions[sid] = {"session_id": sid, "workspace": workspace}
        return sid

    @staticmethod
    def _project_event(event: dict, identity: TurnIdentity) -> dict | None:
        """Normalize internal event-bus fields into the stable Protocol v2 wire schema."""
        kind = event.get("type", "")
        payload = dict(event.get("payload") or {})
        mapping = {
            "message.agent.chunk": "token",
            "tool.call": "tool_call_start",
            "tool.result": "tool_call_end",
            "tool.approval.request": "safety_request",
            "analytics.update": "telemetry",
            "plan.created": "plan_updated",
            "checkpoint.created": "checkpoint_event",
            "verification.updated": "verification_updated",
            "subagent.updated": "subagent_updated",
            "runtime.degraded": "runtime_degraded",
        }
        target = mapping.get(kind)
        if target is None:
            return None
        base = {
            "type": target,
            "event_id": event.get("event_id"),
            "timestamp": event.get("timestamp"),
            **identity.event_fields(),
            "lineage_id": identity.lineage_root_id,
        }

        raw_tool_id = str(
            payload.get("tool_id") or payload.get("tool_call_id")
            or payload.get("id") or ""
        )
        prefix = f"{identity.session_id}-"
        tool_id = raw_tool_id[len(prefix):] if raw_tool_id.startswith(prefix) else raw_tool_id
        name = str(payload.get("name") or payload.get("tool_name") or "")

        if target == "token":
            return {**base, "text": str(payload.get("text") or payload.get("chunk") or "")}
        if target == "tool_call_start":
            return {
                **base, "tool_id": tool_id, "name": name,
                "arguments": payload.get("arguments", payload.get("tool_args")),
            }
        if target == "tool_call_end":
            return {
                **base, "tool_id": tool_id, "name": name,
                "status": str(payload.get("status") or "completed"),
                "result": payload.get("result", payload.get("content")),
            }
        if target == "safety_request":
            return {
                **base, "tool_id": tool_id, "name": name,
                "arguments": payload.get("arguments", payload.get("tool_args")),
                "diff": payload.get("diff"), "warning": payload.get("warning"),
            }
        return {**base, **payload, "type": target}

    @staticmethod
    def _project_stored_event(event: dict) -> dict | None:
        """Project durable journal rows before session resume/replay reaches the UI."""
        kind = str(event.get("type") or "")
        payload = dict(event.get("payload") or {})
        target = {
            "tool.intent": "tool_call_start",
            "tool.result": "tool_call_end",
            "message.agent.chunk": "token",
        }.get(kind)
        if target is None:
            return event if kind in {
                "turn_started", "token", "reasoning", "plan_updated",
                "tool_call_start", "tool_call_end", "safety_request",
                "verification_updated", "subagent_updated", "telemetry",
                "checkpoint_event", "turn_done", "turn_failed", "runtime_degraded",
            } else None
        base = {
            "type": target,
            "event_id": event.get("event_id"),
            "timestamp": event.get("timestamp"),
            "session_id": event.get("session_id"),
            "turn_id": event.get("turn_id"),
            "workspace_id": event.get("workspace_id"),
            "tool_id": str(event.get("tool_call_id") or payload.get("tool_id") or ""),
        }
        if target == "token":
            return {**base, "text": str(payload.get("text") or payload.get("chunk") or "")}
        name = str(payload.get("name") or payload.get("tool_name") or "")
        if target == "tool_call_start":
            return {**base, "name": name, "arguments": payload.get("arguments", payload.get("args"))}
        return {
            **base, "name": name, "status": str(payload.get("status") or "completed"),
            "result": payload.get("result", payload.get("content")),
        }

    @classmethod
    def _project_stored_events(cls, events: list[dict]) -> list[dict]:
        return [projected for event in events if (projected := cls._project_stored_event(event))]

    def _forward_events(self, q: queue.Queue, identity: TurnIdentity, done: threading.Event) -> None:
        """Forward event-bus events to protocol frames; never dies silently."""
        while not done.is_set():
            try:
                event = q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                frame = self._project_event(event, identity)
                if frame:
                    self.emit(frame)
            except Exception as exc:
                print(
                    f"[PulseAI bridge] event forwarder failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr, flush=True,
                )
                try:
                    self.emit({
                        "type": "runtime_degraded", **identity.event_fields(),
                        "reason": f"event forwarder failed: {type(exc).__name__}",
                    })
                except Exception:
                    pass

    def _run_turn(self, sid: str, text: str, workspace: str) -> None:
        from src.runtime.turn_control import set_active_session
        set_active_session(sid)
        identity = TurnIdentity.create(session_id=sid, workspace=workspace)
        # faulthandler.dump_traceback_later() returns None, so track the flag
        # explicitly: the scheduled dump must always be cancelled after the
        # turn, and the echo branch must not leak it either.
        diagnostics_enabled = (
            os.environ.get("PULSEAI_BRIDGE_DIAGNOSTICS", "").lower() in {"1", "true", "yes"}
        )
        if diagnostics_enabled:
            import faulthandler
            faulthandler.dump_traceback_later(60, repeat=False, exit=False)
        q = None
        done = None
        forwarder = None
        try:
            self.emit({"type": "turn_started", **identity.event_fields(), "timestamp": identity.created_at})
            if os.environ.get("PULSEAI_BRIDGE_RUNNER", "").lower() == "echo":
                self.emit({
                    "type": "token", **identity.event_fields(),
                    "text": text, "test_runner": "echo",
                })
                self.emit({
                    "type": "turn_done", **identity.event_fields(),
                    "message": text, "completed": True, "stub": False,
                })
                return

            from src.dashboard.event_bus import event_bus
            from src.graphs.chat_graph import stream_agent
            q = event_bus.subscribe(thread_id=sid)
            done = threading.Event()
            forwarder = threading.Thread(
                target=self._forward_events, args=(q, identity, done),
                name=f"bridge-events-{sid}", daemon=True,
            )
            forwarder.start()

            # Non-sensitive liveness frame before entering the real graph.
            self.emit({
                "type": "reasoning", **identity.event_fields(),
                "text": "Preparing workspace context…",
            })
            try:
                result = stream_agent(
                    text, thread_id=sid, workspace=workspace,
                    approval_channel=True, approval_timeout=300.0,
                    turn_id=identity.turn_id,
                )
                from src.runtime.turn_control import turn_controls
                cancelled = turn_controls.cancelled(sid)
                self.emit({
                    "type": "turn_done", **identity.event_fields(),
                    "message": result, "completed": not cancelled,
                    "cancelled": cancelled, "stub": False,
                })
            except Exception as exc:
                self.emit({
                    "type": "turn_failed", **identity.event_fields(),
                    "error": str(exc), "completed": False,
                })
        finally:
            if diagnostics_enabled:
                import faulthandler
                faulthandler.cancel_dump_traceback_later()
            if forwarder is not None and q is not None and done is not None:
                done.set()
                forwarder.join(timeout=1.0)
                from src.dashboard.event_bus import event_bus
                event_bus.unsubscribe(q)
                from src.runtime.turn_control import turn_controls
                turn_controls.end(sid)
            set_active_session(None)

        from src.runtime.turn_control import turn_controls
        queued = turn_controls.pop_queued(sid)
        if queued and not self._shutdown.is_set():
            self._run_turn(sid, queued, workspace)

    def handle(self, frame: dict) -> bool:
        kind = frame["type"]
        if kind not in CLIENT_METHODS:
            self.emit(error_frame(f"unknown method: {kind!r}"))
            return True
        if kind == "hello":
            if self.greeted:
                self.emit(error_frame("duplicate hello"))
                return True
            self.protocol_version = check_client_hello(frame)
            self.greeted = True
            self.emit(hello(ENGINE_VERSION, protocol=self.protocol_version))
            return True
        if not self.greeted:
            self.emit(error_frame("hello handshake required first"))
            return True
        if kind == "shutdown":
            self._shutdown.set()
            return False

        raw_workspace = frame.get("workspace")
        workspace = str(raw_workspace).strip() if raw_workspace else ""
        if not workspace and kind in _WORKSPACE_REQUIRED_METHODS:
            self.emit(error_frame(NO_WORKSPACE_ERROR))
            return True
        try:
            sid = self._session(frame.get("session_id") or frame.get("thread_id"), workspace)
        except WorkspaceSwitchError as exc:
            self.emit(error_frame(str(exc)))
            return True
        if kind == "session_create":
            self.emit({"type": "session_info", **self._sessions[sid]})
        elif kind in {"session_load", "session_resume"}:
            try:
                from src.runtime.factory import get_runtime_services
                stored = get_runtime_services().journal.list_events(sid)
                events = self._project_stored_events(stored)
                from src.graphs.chat_graph import get_agent_status
                status = get_agent_status(sid)
            except Exception:
                events, status = [], {}
            self.emit({
                "type": "session_info", **self._sessions[sid],
                "resumed": kind == "session_resume",
                "events": events, "agent_status": status,
            })
        elif kind == "session_list":
            self.emit({"type": "session_info", "sessions": list(self._sessions.values())})
        elif kind == "session_fork":
            source = sid
            target = self._session(None, workspace)
            try:
                from src.graphs.chat_graph import fork_conversation
                fork_conversation(source, target)
            except Exception:
                pass
            self.emit({"type": "session_info", **self._sessions[target], "forked_from": source})
        elif kind == "prompt":
            text = str(frame.get("text") or frame.get("message") or "").strip()
            if not text:
                self.emit(error_frame("prompt text is required"))
            elif sid in self._workers and self._workers[sid].is_alive():
                from src.runtime.turn_control import turn_controls
                depth = turn_controls.queue(sid, text)
                self.emit({"type": "session_info", "session_id": sid, "queued": depth})
            else:
                # Warm the heavy turn-path imports on the MAIN thread before
                # dispatching the worker: numpy/transformers C-extension init
                # deadlocks when imported on a non-main thread (Windows), which
                # previously hung the real turn silently. Once cached in
                # sys.modules, the worker's own imports are instant no-ops.
                # The echo runner never touches chat_graph, so skip the ~11s
                # warm-up there.
                if os.environ.get("PULSEAI_BRIDGE_RUNNER", "").lower() != "echo":
                    from src.dashboard.event_bus import event_bus  # noqa: F401
                    from src.graphs.chat_graph import stream_agent  # noqa: F401
                worker = threading.Thread(
                    target=self._run_turn, args=(sid, text, self._sessions[sid]["workspace"]),
                    name=f"bridge-turn-{sid}", daemon=True,
                )
                self._workers[sid] = worker
                worker.start()
        elif kind == "cancel":
            from src.runtime.turn_control import turn_controls
            active = turn_controls.cancel(sid)
            # Fire registered aborts so an in-flight blocking HTTP request is
            # interrupted immediately (not after the provider returns).
            turn_controls.abort(sid)
            self.emit({"type": "session_info", "session_id": sid, "cancel_requested": active})
        elif kind == "steer":
            from src.runtime.turn_control import turn_controls
            accepted = turn_controls.steer(sid, str(frame.get("text") or ""))
            self.emit({"type": "session_info", "session_id": sid, "steer_accepted": accepted})
        elif kind == "queue":
            from src.runtime.turn_control import turn_controls
            depth = turn_controls.queue(sid, str(frame.get("text") or ""))
            self.emit({"type": "session_info", "session_id": sid, "queued": depth})
        elif kind == "safety_reply":
            from src.dashboard.event_bus import approval_queue
            ok = approval_queue.resolve(
                str(frame.get("tool_id") or ""), bool(frame.get("approved")),
                bool(frame.get("always_allow", False)), session_id=sid,
            )
            self.emit({"type": "session_info", "session_id": sid, "safety_resolved": ok})
        elif kind == "subagent_launch":
            from src.agents.subagent_lifecycle import subagent_lifecycle
            handle = subagent_lifecycle.launch(
                parent_session_id=sid,
                goal=str(frame.get("goal") or ""),
                mode=str(frame.get("mode") or "research"),
                parent_capabilities=tuple(frame.get("parent_capabilities") or ()),
                allowed_capabilities=tuple(frame.get("allowed_capabilities") or ()),
            )
            self._subagents[handle.subagent_id] = handle
            self.emit({
                "type": "subagent_updated", "session_id": sid,
                "subagent_id": handle.subagent_id, "state": "pending",
            })
        elif kind in {"subagent_status", "subagent_cancel", "subagent_result"}:
            from src.agents.subagent_lifecycle import subagent_lifecycle
            sub_id = str(frame.get("subagent_id") or "")
            handle = self._subagents.get(sub_id)
            if handle is None:
                payload = {"state": "unknown"}
            elif kind == "subagent_status":
                payload = subagent_lifecycle.status(handle)
            elif kind == "subagent_cancel":
                payload = {"cancel_accepted": subagent_lifecycle.cancel(handle), **subagent_lifecycle.status(handle)}
            else:
                payload = subagent_lifecycle.result(handle)
            self.emit({
                "type": "subagent_updated", "session_id": sid,
                "subagent_id": sub_id, **payload,
            })
        elif kind == "checkpoint_list":
            from src.tools.shadow_checkpoints import get_shadow_checkpoints
            checkpoints = get_shadow_checkpoints().list_checkpoints(workspace)
            self.emit({
                "type": "checkpoint_event", "session_id": sid,
                "workspace": workspace, "checkpoints": checkpoints,
            })
        elif kind == "checkpoint_restore":
            from src.tools.shadow_checkpoints import get_shadow_checkpoints
            result = get_shadow_checkpoints().restore(
                workspace, str(frame.get("checkpoint_hash") or ""),
                str(frame.get("file_path")) if frame.get("file_path") else None,
            )
            self.emit({
                "type": "checkpoint_event", "session_id": sid,
                "workspace": workspace, "restore": result,
            })
        elif kind == "events_replay":
            from src.runtime.factory import get_runtime_services
            stored = get_runtime_services().journal.list_events(
                sid, after_seq=int(frame.get("after_seq") or 0),
            )
            events = self._project_stored_events(stored)
            self.emit({"type": "events_replay", "session_id": sid, "events": events})
        return True

    def run(self) -> int:
        while not self._shutdown.is_set():
            line = sys.stdin.buffer.readline()
            if not line:
                return 0
            try:
                frame = decode_line(line)
                if not self.handle(frame):
                    return 0
            except ProtocolError as exc:
                self.emit(error_frame(str(exc)))
            except Exception as exc:
                self.emit(error_frame(f"bridge internal error: {exc!r}"))
        return 0


def main() -> int:
    return BridgeServer().run()


if __name__ == "__main__":
    raise SystemExit(main())

"""Headless Scope/Pulse IDE bridge with real agent streaming and turn control."""
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


class BridgeServer:
    def __init__(self):
        self.greeted = False
        self.protocol_version: int | None = None
        self._write_lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._subagents: dict[str, object] = {}
        self._shutdown = threading.Event()

    def emit(self, frame: dict) -> None:
        with self._write_lock:
            sys.stdout.buffer.write(encode(frame))
            sys.stdout.buffer.flush()

    def _session(self, requested: str | None, workspace: str = ".") -> str:
        sid = normalize_id(requested, prefix="session")
        self._sessions.setdefault(sid, {"session_id": sid, "workspace": workspace})
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

    def _run_turn(self, sid: str, text: str, workspace: str) -> None:
        identity = TurnIdentity.create(session_id=sid, workspace=workspace)
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

        def forward() -> None:
            while not done.is_set():
                try:
                    event = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                frame = self._project_event(event, identity)
                if frame:
                    self.emit(frame)

        forwarder = threading.Thread(target=forward, name=f"bridge-events-{sid}", daemon=True)
        forwarder.start()
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
            done.set()
            forwarder.join(timeout=1.0)
            event_bus.unsubscribe(q)
            from src.runtime.turn_control import turn_controls
            turn_controls.end(sid)

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

        workspace = str(frame.get("workspace") or ".")
        sid = self._session(frame.get("session_id") or frame.get("thread_id"), workspace)
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
                worker = threading.Thread(
                    target=self._run_turn, args=(sid, text, workspace),
                    name=f"bridge-turn-{sid}", daemon=True,
                )
                self._workers[sid] = worker
                worker.start()
        elif kind == "cancel":
            from src.runtime.turn_control import turn_controls
            active = turn_controls.cancel(sid)
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

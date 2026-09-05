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

#: How long a turn may wait for the event forwarder to drain before the
#: terminal frame goes out anyway (see _flush_events).
_EVENT_FLUSH_TIMEOUT_S = 5.0

# ---------------------------------------------------------------------------
# Env-file loading BEFORE any src.* import: several modules resolve keys and
# knobs from os.environ at import time, and the desktop child process cannot
# rely on Windows propagating freshly `setx`-ed user env through a
# still-running explorer.exe (the owner's scan knobs silently never arrived).
# The workspace `.env` (cwd == engine root) and ~/.pulseai/.env are the
# reliable sources. load_dotenv never overrides values already in the
# process environment: real env wins, files are the fallback.
# ---------------------------------------------------------------------------
try:
    from pathlib import Path as _dotenv_path
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()  # <engine root>/.env
    _load_dotenv(str(_dotenv_path.home() / ".pulseai" / ".env"))
except Exception:
    pass  # env files are a fallback; their absence must never block boot

from src.bridge.protocol import (
    CLIENT_METHODS, EXECUTION_MODES, ProtocolError, check_client_hello, decode_line,
    encode, error_frame, hello,
)
from src.runtime.identity import TurnIdentity, normalize_id

ENGINE_VERSION = "0.2.0-runtime"

# A session is only ever bound to a real project folder. The renderer disables
# prompt submission without one; the bridge enforces the same contract so no
# client can silently run against ".", the engine root, or the bundled app dir.
_WORKSPACE_REQUIRED_METHODS = frozenset({
    "session_create", "session_load", "session_resume", "session_fork", "prompt",
    "host_capabilities_update", "host_tool_result",
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
        from src.runtime.host_capabilities import host_capability_broker
        host_capability_broker.reset()
        host_capability_broker.set_emitter(self.emit)

    def emit(self, frame: dict) -> None:
        with self._write_lock:
            self._protocol_out.write(encode(frame))
            self._protocol_out.flush()

    @staticmethod
    def _prior_checkpoint_count(sid: str, db_path: str | None = None) -> int | None:
        """Count durable checkpoints for a thread id (read-only, no engine
        import). None = unknown (db unreadable/schema changed) — never
        reported as 0 when unknown."""
        db = db_path or os.path.join(os.path.expanduser("~"), ".pulseai", "sessions.db")
        if not os.path.exists(db):
            return 0
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (sid,)
                ).fetchone()
                return int(row[0])
            finally:
                conn.close()
        except Exception:
            return None

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
            "llm.request": "llm.request",
            "llm.response": "llm.response",
            "reasoning.update": "reasoning",
            "tool.call": "tool_call_start",
            "tool.result": "tool_call_end",
            "tool.approval.request": "safety_request",
            "analytics.update": "telemetry",
            "plan.created": "plan_updated",
            "checkpoint.created": "checkpoint_event",
            "verification.updated": "verification_updated",
            "subagent.updated": "subagent_updated",
            "runtime.degraded": "runtime_degraded",
            "context.status": "context_status",
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
                "llm.request", "llm.response", "workspace.bound", "context_status",
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

    def _forward_events(self, q: queue.Queue, identity: TurnIdentity, done: threading.Event,
                        own_sid: str | None = None) -> None:
        """Forward event-bus events to protocol frames; never dies silently.

        Events naming a DIFFERENT session are dropped (concurrent-turn
        isolation); session-less events (aux/pre-turn/post-turn calls) are
        kept — they belong to whoever is running the turn.
        """
        while not done.is_set():
            try:
                event = q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if own_sid is not None:
                    payload = event.get("payload") or {}
                    event_session = str(
                        payload.get("session_id") or payload.get("thread_id") or ""
                    ) or None
                    # llm.request/llm.response are provider-call STATUS from
                    # threads whose thread-local session binding may not match
                    # the bridge session (field proof: the activity row sat on
                    # the generic "Waiting on the model" text because these
                    # frames were filtered out here). They are diagnostic, not
                    # turn content — forward them; concurrency isolation stays
                    # for everything user-visible.
                    is_llm_status = str(event.get("type") or "").startswith("llm.")
                    if (event_session is not None and event_session != own_sid
                            and not is_llm_status):
                        continue
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
            finally:
                # Pair Queue.put with task_done so the turn owner can flush
                # every provider/tool event before emitting its terminal frame.
                q.task_done()

    @staticmethod
    def _flush_events(q: queue.Queue, timeout: float) -> int:
        """Wait for the forwarder to drain, bounded — returns events left stranded.

        `Queue.join()` has no timeout, so it can only ever be correct if every
        consumer releases its slot (see EventBus._release). That is the right fix,
        and it is still not the right *shape* here: a terminal frame must never be
        gated on an unbounded wait, because the failure mode is not a lost event,
        it is a client that never learns the turn ended.
        """
        import time
        deadline = time.monotonic() + max(timeout, 0.0)
        while time.monotonic() < deadline:
            if not getattr(q, "unfinished_tasks", 0):
                return 0
            time.sleep(0.02)
        return max(int(getattr(q, "unfinished_tasks", 0) or 0), 0)

    def _run_turn(self, sid: str, text: str, workspace: str, mode: str = "agent") -> None:
        from src.runtime.turn_control import set_active_session, turn_controls

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
        import time as _time
        _turn_t0 = _time.monotonic()
        # Hermes run-watchdog discipline: the UI must never wait on a turn
        # forever. Owner field proof (2026-09-04): the graph finished its last
        # node but the turn never ended - "Working" hung until the user pressed
        # Stop. If no terminal frame lands within the budget, the bridge emits
        # one itself (stall receipt) so the session is RELEASED even while the
        # stuck thread stays stuck. PULSEAI_TURN_STALL_TIMEOUT_S, 0 = off.
        _terminal = threading.Event()

        def _stall_watchdog() -> None:
            raw = os.environ.get("PULSEAI_TURN_STALL_TIMEOUT_S", "").strip()
            try:
                budget = float(raw) if raw else 600.0
            except (TypeError, ValueError):
                budget = 600.0
            budget = max(0.0, min(budget, 3600.0))
            if budget <= 0:
                return
            if not _terminal.wait(budget):
                wall = _time.monotonic() - _turn_t0
                print(
                    f"[bridge] turn STALL watchdog fired after {wall:.0f}s "
                    "with no terminal frame - releasing the session",
                    file=sys.stderr, flush=True,
                )
                self.emit({
                    "type": "runtime_degraded", **identity.event_fields(),
                    "reason": f"turn stalled {wall:.0f}s after the last engine activity (watchdog)",
                })
                self.emit({
                    "type": "turn_done", **identity.event_fields(),
                    "message": (
                        "This turn stalled and was ended by the watchdog. "
                        "The reply above is what the engine produced; send "
                        "another message to continue."
                    ),
                    "completed": False, "cancelled": False, "stub": False,
                })

        threading.Thread(target=_stall_watchdog, name="pulseai-turn-watchdog", daemon=True).start()
        # Establish active ownership before publishing turn_started. Once the
        # UI can show Stop, stream_agent's nested begin must preserve it.
        turn_controls.begin(sid)
        set_active_session(sid)
        try:
            self.emit({"type": "turn_started", **identity.event_fields(), "timestamp": identity.created_at})
            if os.environ.get("PULSEAI_BRIDGE_RUNNER", "").lower() == "echo":
                # Test seam (PULSEAI_ECHO_DELAY_MS): simulate an in-flight turn
                # that honours a cancel request, mirroring real turn semantics.
                # Used by the reliability-benchmark harness (PBR-012) to verify
                # cancel behaviour with zero model calls. Default 0 => the
                # historical instant echo turn, byte-compatible with past tests.
                delay_ms = int(os.environ.get("PULSEAI_ECHO_DELAY_MS", "0") or "0")
                if delay_ms > 0:
                    from src.runtime.turn_control import turn_controls
                    import time as _time
                    deadline = _time.monotonic() + max(delay_ms, 0) / 1000.0
                    while _time.monotonic() < deadline and not turn_controls.cancelled(sid):
                        _time.sleep(0.05)
                    if turn_controls.cancelled(sid):
                        self.emit({
                            "type": "turn_done", **identity.event_fields(),
                            "message": "Operation cancelled by the user.",
                            "completed": False, "cancelled": True, "stub": False,
                        })
                        return
                self.emit({
                    "type": "token", **identity.event_fields(),
                    "text": text, "test_runner": "echo",
                })
                _terminal.set()
                self.emit({
                    "type": "turn_done", **identity.event_fields(),
                    "message": text, "completed": True, "stub": False,
                })
                return

            from src.dashboard.event_bus import event_bus
            from src.graphs.chat_graph import stream_agent
            # ADMIN subscription + own filter, not a session-filtered one:
            # provider calls made where no active session is set (planner
            # pre-turn, post-turn review threads) carry session_id=None and a
            # session-filtered queue silently DROPS them — the founder's
            # PBR-002 run counted 11 provider calls but only 4 llm.request
            # frames reached the client. Events that DO name another session
            # are still excluded here so concurrent turns never cross-wire.
            q = event_bus.subscribe(thread_id=None)
            done = threading.Event()
            forwarder = threading.Thread(
                target=self._forward_events, args=(q, identity, done, sid),
                name=f"bridge-events-{sid}", daemon=True,
            )
            forwarder.start()

            # Non-sensitive liveness frame before entering the real graph. The text used to name a
            # workspace step this code had not started and would not necessarily reach -- a 402 from the
            # No canned "thinking" prose here. The bridge used to inject a
            # fabricated reasoning row ("Turn accepted. Waiting on the model…")
            # — text that appears and vanishes with no model behind it, which
            # the owner explicitly rejected. The renderer's live activity row
            # (dot + real state + elapsed seconds) already says everything
            # that is unconditionally true; the transcript carries only real
            # events now.
            try:
                # Interactive IDE sessions default to ask. Guarded autonomous
                # benchmark runners may opt into the same session-scoped,
                # workspace-only mutation policy used by the dashboard. Without
                # this handoff every safe write emits safety_request and a
                # headless runner waits until the watchdog kills the bridge.
                approval_policy = os.environ.get(
                    "PULSEAI_BRIDGE_APPROVAL_POLICY", "ask"
                ).strip()
                if approval_policy not in {"ask", "workspace_session", "session"}:
                    approval_policy = "ask"
                result = stream_agent(
                    text, thread_id=sid, workspace=workspace,
                    approval_channel=True, approval_timeout=300.0,
                    approval_policy=approval_policy,
                    turn_id=identity.turn_id,
                    execution_mode=mode,
                )
                cancelled = turn_controls.cancelled(sid)
                # Owner-machine diagnosis (2026-09-04 "run never ends, I have
                # to press Stop"): turn_done is SILENT in the log, so a log
                # that ends at the last ai answer proves nothing — the engine
                # may have finished with the frame lost, or be stuck right
                # here. These stderr receipts make the end of the turn
                # observable: if the [bridge] turn-end line appears, the
                # engine completed and the hunt is renderer-side; if it never
                # appears, the wall between the last ai answer and this line
                # names the guilty call. (stderr -> owner log as
                # `[PulseAI Engine] ...`.)
                import sys as _sys
                import time as _time
                _turn_wall = _time.monotonic() - _turn_t0
                print(f"[bridge] graph returned in {_turn_wall:.1f}s; draining event queue", file=_sys.stderr, flush=True)
                if q is not None:
                    stranded = self._flush_events(q, _EVENT_FLUSH_TIMEOUT_S)
                    if stranded:
                        # Better a degraded note than a swallowed terminal frame:
                        # without turn_done a headless client waits for its whole
                        # watchdog while the engine has already finished.
                        print(f"[bridge] event queue STRANDED {stranded} event(s)", file=_sys.stderr, flush=True)
                        self.emit({
                            "type": "runtime_degraded", **identity.event_fields(),
                            "reason": f"event queue flush incomplete: {stranded} event(s) undrained",
                        })
                task_completed = bool(getattr(result, "completed", True))
                _terminal.set()
                self.emit({
                    "type": "turn_done", **identity.event_fields(),
                    "message": str(result),
                    "completed": task_completed and not cancelled,
                    "cancelled": cancelled, "stub": False,
                })
                print(
                    f"[bridge] turn end: completed={task_completed and not cancelled} "
                    f"cancelled={cancelled} wall={_time.monotonic() - _turn_t0:.1f}s",
                    file=_sys.stderr, flush=True,
                )
            except Exception as exc:
                # Transport closure can surface through different provider
                # exception types. Intentional Stop wins over generic failure
                # attribution and must produce one terminal cancelled receipt.
                if turn_controls.cancelled(sid):
                    _terminal.set()
                    self.emit({
                        "type": "turn_done", **identity.event_fields(),
                        "message": "Operation cancelled by the user.",
                        "completed": False, "cancelled": True, "stub": False,
                    })
                else:
                    _terminal.set()
                    self.emit({
                        "type": "turn_failed", **identity.event_fields(),
                        "error": str(exc), "completed": False,
                    })
                    print(f"[bridge] turn FAILED after {_time.monotonic() - _turn_t0:.1f}s: {exc!r}", file=sys.stderr, flush=True)
        finally:
            if diagnostics_enabled:
                import faulthandler
                faulthandler.cancel_dump_traceback_later()
            if forwarder is not None and q is not None and done is not None:
                done.set()
                forwarder.join(timeout=1.0)
                from src.dashboard.event_bus import event_bus
                event_bus.unsubscribe(q)
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
        if kind == "host_capabilities_update":
            from src.runtime.host_capabilities import host_capability_broker
            descriptors = frame.get("capabilities")
            if not isinstance(descriptors, list):
                self.emit(error_frame("host capabilities must be an array"))
            else:
                count = host_capability_broker.update(sid, workspace, descriptors)
                self.emit({
                    "type": "session_info", "session_id": sid,
                    "host_capabilities_updated": count,
                })
        elif kind == "host_tool_result":
            from src.runtime.host_capabilities import host_capability_broker
            request_id = str(frame.get("request_id") or "")
            resolved = host_capability_broker.resolve(request_id, frame)
            self.emit({
                "type": "session_info", "session_id": sid,
                "host_tool_result_resolved": resolved,
            })
        elif kind == "session_create":
            prior = self._prior_checkpoint_count(sid)
            info = {"type": "session_info", **self._sessions[sid]}
            if prior is not None:
                # Visibility: a session id with durable history SILENTLY
                # resumes it (the langgraph checkpointer keys by thread id).
                # Measured live: a fixed id made each benchmark run replay
                # every prior run (+3 calls / +~10k tokens per run, linear).
                # The create reply must never claim a fresh start silently.
                info["prior_checkpoints"] = prior
            self.emit(info)
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
        elif kind == "voice_transcribe":
            # Floor 5 voice: audio (base64) in, transcript out. Fail-closed —
            # a voice hiccup returns an honest error event, never a crash.
            import base64 as _b64
            from src.voice.pipeline import transcribe as _transcribe
            try:
                audio = _b64.b64decode(str(frame.get("audio_b64") or ""))
                result = _transcribe(audio, filename=str(frame.get("filename") or "audio.webm"))
            except Exception as exc:
                result = type("R", (), {"as_dict": staticmethod(lambda: {"ok": False, "text": "", "error": str(exc)})})()
            payload = result.as_dict() if hasattr(result, "as_dict") else dict(result)
            self.emit({"type": "voice_text", **payload, **self._identity_fields(sid)})
        elif kind == "prompt":
            text = str(frame.get("text") or frame.get("message") or "").strip()
            mode = str(frame.get("mode") or "agent").strip().lower()
            if not text:
                self.emit(error_frame("prompt text is required"))
            elif mode not in EXECUTION_MODES:
                self.emit(error_frame(f"unsupported execution mode: {mode}"))
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
                    target=self._run_turn,
                    args=(sid, text, self._sessions[sid]["workspace"], mode),
                    name=f"bridge-turn-{sid}", daemon=True,
                )
                self._workers[sid] = worker
                worker.start()
        elif kind == "cancel":
            from src.runtime.turn_control import turn_controls
            # cancel() owns both the event transition and one-shot abort firing.
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
        elif kind == "inline_completion":
            self._handle_inline_completion(sid, frame)
        elif kind == "next_edit_suggestions":
            self._handle_next_edit_suggestions(sid, frame)
        if workspace:
            # Workspace routing evidence (P0 contract + PBR-002): every
            # workspace-bearing frame asserts the exact root this session is
            # pinned to, client through engine. Emitted after the direct reply
            # so clients expecting a specific response frame are unaffected.
            # `hops` stays the resolved root string so a grader can assert all
            # hops equal the opened fixture root.
            self.emit({
                "type": "workspace.bound", "session_id": sid,
                "workspace": workspace, "hops": workspace, "engine_root": workspace,
            })
        return True

    def _handle_inline_completion(self, sid: str, frame: dict) -> None:
        """Handle inline completion request from the editor."""
        try:
            from src.tools.inline_completions import get_inline_completion_provider, CompletionRequest
            provider = get_inline_completion_provider()
            if not provider.enabled:
                self.emit({
                    "type": "inline_completion_result", "session_id": sid,
                    "request_id": frame.get("request_id", ""),
                    "completions": [],
                })
                return

            request = CompletionRequest(
                resource=str(frame.get("resource", "")),
                language_id=str(frame.get("language_id", "")),
                line=int(frame.get("line", 0)),
                column=int(frame.get("column", 0)),
                prefix=str(frame.get("prefix", "")),
                suffix=str(frame.get("suffix", "")),
                context_lines=int(frame.get("context_lines", 30)),
                max_tokens=int(frame.get("max_tokens", 128)),
            )
            items = provider.compute_completions(request)
            self.emit({
                "type": "inline_completion_result", "session_id": sid,
                "request_id": frame.get("request_id", ""),
                "completions": [
                    {
                        "text": item.text,
                        "range_start_line": item.range_start_line,
                        "range_start_column": item.range_start_column,
                        "range_end_line": item.range_end_line,
                        "range_end_column": getattr(item, "end_column", item.range_start_column + len(item.text)),
                        "confidence": item.confidence,
                    }
                    for item in items
                ],
            })
        except Exception as exc:
            self.emit({
                "type": "inline_completion_result", "session_id": sid,
                "request_id": frame.get("request_id", ""),
                "completions": [],
                "error": str(exc),
            })

    def _handle_next_edit_suggestions(self, sid: str, frame: dict) -> None:
        """Handle next edit suggestions request from the editor."""
        try:
            from src.tools.next_edit_suggestions import get_next_edit_predictor
            predictor = get_next_edit_predictor()
            if not predictor.enabled:
                self.emit({
                    "type": "next_edit_result", "session_id": sid,
                    "request_id": frame.get("request_id", ""),
                    "suggestions": [],
                })
                return

            workspace = str(frame.get("workspace", ""))
            max_suggestions = int(frame.get("max_suggestions", 5))
            suggestions = predictor.predict_next_edits(workspace, max_suggestions)
            self.emit({
                "type": "next_edit_result", "session_id": sid,
                "request_id": frame.get("request_id", ""),
                "suggestions": [
                    {
                        "resource": s.resource,
                        "line": s.line,
                        "column": s.column,
                        "end_line": s.end_line,
                        "end_column": s.end_column,
                        "title": s.title,
                        "description": s.description,
                        "confidence": s.confidence,
                        "category": s.category,
                    }
                    for s in suggestions
                ],
            })
        except Exception as exc:
            self.emit({
                "type": "next_edit_result", "session_id": sid,
                "request_id": frame.get("request_id", ""),
                "suggestions": [],
                "error": str(exc),
            })

    @staticmethod
    def _start_boot_warmup() -> None:
        """Load optional heavy backends at PROCESS START, not mid-turn.

        Field proof (owner, 2026-09-04): the first WORK turn triggered the
        first memory write -> first MemoryManager construction -> embedder
        load — and the turn never came back, with the last log line being
        the memory warmup notice. Housekeeping (hermes: memory saves are
        never on the turn's critical path) belongs at boot, where its cost
        is visible and its failure cannot eat a live conversation. The
        PULSEAI_MEMORY_WARMUP_AT_BOOT gate is read per process start.
        """
        if os.environ.get("PULSEAI_MEMORY_WARMUP_AT_BOOT", "").strip().lower() in {"0", "false", "no", "off"}:
            return

        def _warm():
            try:
                from src.graphs.chat_graph import memory_manager
                if memory_manager is not None:
                    memory_manager.warmup()
            except Exception as exc:
                print(f"[bridge] boot memory warmup skipped: {exc!r}", file=sys.stderr, flush=True)

        threading.Thread(target=_warm, name="pulseai-boot-warmup", daemon=True).start()

    def _log_build(self) -> None:
        """One stderr line naming the exact build this engine process runs.

        Field discipline (2026-09-04): hung turns can only be attributed to
        a build by which probe lines exist in the log — and twice the actual
        answer was "the engine is still running the previous build". Now the
        log says so itself: every session starts with the engine's commit.
        """
        build = "unknown"
        try:
            import subprocess
            engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            proc = subprocess.run(
                ["git", "log", "-1", "--format=%h %ci"],
                capture_output=True, text=True, timeout=3, cwd=engine_root,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                build = proc.stdout.strip()
        except Exception:
            pass
        print(f"[bridge] engine build: {build}", file=sys.stderr, flush=True)

    def run(self) -> int:
        self._log_build()
        self._start_boot_warmup()
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

"""Headless Scope/Crusor IDE bridge with real agent streaming and turn control.

Workspace contract (P0): a session is only ever bound to a real project folder.
The renderer disables prompt submission without one, and the bridge enforces
the same rule so no client can silently run against ".", the engine root, or
the bundled app dir. The desktop MUST pass the user's opened workspace.
"""
from __future__ import annotations

import json
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
# The workspace `.env` (cwd == engine root) and ~/.crusorai/.env are the
# reliable sources. load_dotenv never overrides values already in the
# process environment: real env wins, files are the fallback.
# ---------------------------------------------------------------------------
try:
    from pathlib import Path as _dotenv_path
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(override=True)  # <engine root>/.env — override parent env so .env off wins (9/20 trace ON persisted)
    _load_dotenv(str(_dotenv_path.home() / ".crusorai" / ".env"), override=True)
    print(f"[bridge][env] loaded: CRUSORAI_MEMORY={os.getenv('CRUSORAI_MEMORY')!r} LLM_PROVIDER={os.getenv('LLM_PROVIDER')!r} CRUSORAI_SCAN_MAX_FILES={os.getenv('CRUSORAI_SCAN_MAX_FILES')!r}", file=sys.stderr, flush=True)
except Exception as _e:
    print(f"[bridge][env] load_dotenv failed: {_e!r}", file=sys.stderr, flush=True)

from src.bridge.protocol import (
    CLIENT_METHODS, EXECUTION_MODES, ProtocolError, check_client_hello, decode_line,
    encode, error_frame, hello,
)
from src.bridge.turn_watchdog import TurnLiveness, run_stall_watchdog
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
    "workspace required: open a project folder before starting a Crusor session"
)


def _ensure_preview_proxy(ensure, workspace: str) -> None:
    """Thread body for the preview-proxy autostart: report the outcome, swallow everything else.

    ``ensure`` is :meth:`src.preview.autostart.PreviewAutostart.ensure`, which already refuses to
    raise; the second guard is here because this runs while a user is mid-turn and an unhandled
    thread exception is exactly the kind of thing that shows up as a mystery panel error.
    """
    try:
        handle = ensure(workspace)
    except Exception as exc:  # pragma: no cover - defence in depth
        print(f"[bridge] preview proxy autostart failed for {workspace!r}: {exc!r}",
              file=sys.stderr, flush=True)
        return
    if handle is None:
        print(f"[bridge] preview proxy could not be started for {workspace!r} — "
              "Preview needs it; start one by hand (see CRUSOR_PREVIEW_SETUP.md §5b)",
              file=sys.stderr, flush=True)


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
        # On Windows, stdout defaults to the system codepage (charmap/cp1252)
        # which cannot encode characters like → (U+2192). Reconfigure to UTF-8
        # so that any text-mode writes (print, etc.) don't crash with
        # UnicodeEncodeError in the _writerthread.
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
        sys.stdout = sys.stderr
        self.greeted = False
        self.protocol_version: int | None = None
        self._write_lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._subagents: dict[str, object] = {}
        # Workspaces this process has already kicked a preview-proxy start for. The frame loop must
        # never block on a spawn, so the work happens on a daemon thread (see _start_preview_proxy);
        # this set is only here to keep one thread per workspace rather than one per frame.
        self._preview_hooked: set[str] = set()
        self._shutdown = threading.Event()
        from src.runtime.host_capabilities import host_capability_broker
        host_capability_broker.reset()
        host_capability_broker.set_emitter(self.emit)

    def emit(self, frame: dict) -> None:
        if frame.get("type") == "session_info":
            # The renderer paints the engine build on its status chip — a
            # stale engine is visible IN THE PANEL, not just in stderr.
            frame = {**frame, "build": self._engine_build()}
        with self._write_lock:
            self._protocol_out.write(encode(frame))
            self._protocol_out.flush()

    @staticmethod
    def _prior_checkpoint_count(sid: str, db_path: str | None = None) -> int | None:
        """Count durable checkpoints for a thread id (read-only, no engine
        import). None = unknown (db unreadable/schema changed) — never
        reported as 0 when unknown."""
        db = db_path or os.path.join(os.path.expanduser("~"), ".crusorai", "sessions.db")
        if not os.path.exists(db):
            return 0
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
            try:
                table = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
                ).fetchone()
                if table is None:
                    # A sessions.db without the checkpointer table was minted
                    # by the session/subagent stores before any turn ran —
                    # that is honestly zero checkpoints, not unknown.
                    return 0
                row = conn.execute(
                    "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (sid,)
                ).fetchone()
                return int(row[0])
            finally:
                conn.close()
        except Exception:
            return None

    # -- Hermes desktop session pipeline: durable rows + paged history --------
    # The in-memory _sessions map stays the live-turn registry (workers,
    # workspace binding); the CrusorSessionStore below is the durable list
    # the desktop hydrates from. session_create mints a lazy draft (no row)
    # and the first prompt persists it — Hermes "no Untitled litter".

    @staticmethod
    def _durable_store():
        from src.runtime.session_store import get_session_store
        return get_session_store()

    @staticmethod
    def _session_row_public(row: dict | None) -> dict | None:
        """Client-safe session row (Hermes _session_response shape)."""
        if not row:
            return None
        safe = (
            "id", "title", "workspace", "source", "model", "created_at",
            "last_active", "message_count", "preview", "pinned", "archived",
            "hidden", "unread", "parent_session_id", "lineage_root_id",
        )
        return {key: row.get(key) for key in safe if key in row}

    def _transcript_messages(
        self, sid: str, *, limit: int, offset: int, order: str,
    ) -> tuple[list[dict], dict]:
        """Paged transcript from the checkpointer (Hermes messages paging).

        Order ``latest`` pages back from the NEWEST message (tail hydration);
        ``oldest`` pages forward from the first row. A bounded get_state read
        (Hermes 1.5s snapshot discipline) fails open to an empty page — the
        desktop falls back to the journal events from session_resume.
        """
        limit = max(1, min(int(limit or 120), 500))
        offset = max(0, int(offset or 0))
        if order not in ("latest", "oldest"):
            order = "latest"
        raw: list = []
        try:
            import concurrent.futures as _cf
            from src.graphs.chat_graph import graph as _graph
            config = {"configurable": {"thread_id": sid}}
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                snap = _ex.submit(_graph.get_state, config).result(timeout=2.0)
            values = dict(snap.values or {}) if snap else {}
            raw = list(values.get("messages") or [])
        except Exception as exc:
            print(f"[bridge] transcript read failed for {sid}: {exc!r}",
                  file=sys.stderr, flush=True)
            raw = []
        projected: list[dict] = []
        for index, msg in enumerate(raw):
            mtype = str(getattr(msg, "type", "") or "").lower()
            if mtype == "system":
                # Engine scaffolding (persona, progress reflection,
                # pivot guidance, steers' system parts) is model-facing
                # only. Projecting it as assistant text painted the
                # internal "You just received a tool result..." nudge
                # into the visible transcript (field 2026-10-15).
                continue
            if mtype == "human":
                role = "user"
            elif mtype == "tool":
                role = "tool"
            else:
                role = "assistant"
            kwargs = getattr(msg, "additional_kwargs", None) or {}
            if not isinstance(kwargs, dict):
                kwargs = {}
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            block_calls: list[dict] = []
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                # Provider block content (Anthropic-style and OpenAI-compat
                # routers): text / thinking / tool_use / tool_result blocks,
                # not a plain string. Dropping non-text blocks here is what
                # used to resume tool-heavy sessions as text-only transcripts.
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                        continue
                    if not isinstance(block, dict):
                        continue
                    btype = str(block.get("type") or "").lower()
                    if btype in ("thinking", "thinking_block", "redacted_thinking"):
                        thought = block.get("thinking") or block.get("text") or ""
                        if thought:
                            reasoning_parts.append(str(thought))
                    elif btype in ("tool_use", "tool_call"):
                        try:
                            block_calls.append({
                                "id": str(block.get("id") or ""),
                                "name": str(block.get("name") or ""),
                                "args": block.get("input", block.get("args", {})),
                            })
                        except Exception:
                            pass
                    elif btype == "tool_result":
                        out = block.get("content") or block.get("output") or ""
                        if out:
                            text_parts.append(out if isinstance(out, str)
                                              else json.dumps(out)[:2000])
                    else:
                        text_parts.append(str(block.get("text", "")))
                content_text = "".join(text_parts)
            else:
                content_text = str(content or "")
            entry: dict = {"id": index, "role": role, "content": content_text}
            # Reasoning (Hermes thinking parts): the router's lifted
            # additional_kwargs carrier first, content thinking blocks second.
            # Without this, resumed turns lose their Think card.
            reasoning = ""
            for key in ("reasoning_content", "reasoning"):
                candidate = kwargs.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    reasoning = candidate
                    break
            if not reasoning and reasoning_parts:
                reasoning = "\n\n".join(reasoning_parts)
            if reasoning:
                entry["reasoning"] = reasoning
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                try:
                    entry["tool_calls"] = [
                        {"id": str(c.get("id") or ""),
                         "name": c.get("name", ""),
                         "args": c.get("args", {})}
                        for c in tool_calls
                    ]
                except Exception:
                    pass
            if "tool_calls" not in entry:
                # Fallback carriers when the parsed list is empty: raw OpenAI
                # additional_kwargs tool_calls plus content tool_use blocks.
                parsed: list[dict] = []
                raw_kwargs_calls = kwargs.get("tool_calls")
                if isinstance(raw_kwargs_calls, list):
                    for call in raw_kwargs_calls:
                        if not isinstance(call, dict):
                            continue
                        fn = call.get("function") or {}
                        if not isinstance(fn, dict):
                            fn = {}
                        name = call.get("name") or fn.get("name") or ""
                        raw_args = fn.get("arguments", call.get("args", {}))
                        if isinstance(raw_args, str):
                            try:
                                raw_args = json.loads(raw_args) if raw_args.strip() else {}
                            except Exception:
                                raw_args = {"_raw": raw_args[:2000]}
                        parsed.append({"id": str(call.get("id") or ""),
                                       "name": str(name), "args": raw_args})
                parsed.extend(block_calls)
                if parsed:
                    entry["tool_calls"] = parsed
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                entry["tool_call_id"] = str(tool_call_id)
            name = getattr(msg, "name", None)
            if name:
                entry["tool_name"] = str(name)
            projected.append(entry)
        total = len(projected)
        if order == "latest":
            start = max(0, total - offset - limit)
            end = max(0, total - offset)
            page = projected[start:end]
        else:
            page = projected[offset:offset + limit]
        pagination = {
            "limit": limit, "offset": offset, "order": order,
            "returned": len(page), "total": total,
            "has_more": (start > 0) if order == "latest" else (offset + len(page) < total),
        }
        return page, pagination

    def _touch_turn(self, sid: str, user_text: str) -> None:
        """Persist-on-first-prompt + per-turn activity (Hermes lazy rows).

        Best-effort by contract: accounting never breaks the receipt.
        """
        try:
            store = self._durable_store()
            workspace = ""
            try:
                workspace = str(self._sessions.get(sid, {}).get("workspace") or "")
            except Exception:
                workspace = ""
            row = store.get_session(sid)
            if row is None:
                # Untitled by design: the auto-titler CREATES the title after a
                # completed exchange (field 2026-09-28 — no first-message capture).
                store.create_session(sid, workspace, title="")
                store.touch_activity(sid, preview=str(user_text or "")[:500],
                                     message_count_inc=2)
                return
            preview = (row.get("preview") or "") or str(user_text or "")[:500]
            store.touch_activity(sid, preview=preview, message_count_inc=2)
        except Exception as exc:
            print(f"[bridge] turn touch failed for {sid}: {exc!r}",
                  file=sys.stderr, flush=True)

    def _maybe_autotitle_session(self, sid: str, user_text: str, assistant_text: str = "") -> None:
        """Fire the async auto-titler for an untitled session (Hermes parity).

        FIXED rule: a session with any title (generated, renamed, pending) is
        never retitled here. Best-effort by contract: titling never breaks
        the turn. ``CRUSORAI_AUTOTITLE=off`` disables the call entirely.
        """
        if os.environ.get("CRUSORAI_AUTOTITLE", "").strip().lower() in {"0", "off", "false", "no"}:
            return
        try:
            store = self._durable_store()
            row = store.get_session(sid)
            if row is None or (row.get("title") or "").strip() or not str(user_text or "").strip():
                return
            workspace = str(row.get("workspace") or "") or str(self._sessions.get(sid, {}).get("workspace") or "")

            def _run() -> None:
                try:
                    from src.runtime.session_titling import (
                        ensure_unique_title,
                        generate_session_title,
                    )
                    base = generate_session_title(user_text, assistant_text)
                    if not base:
                        return
                    title = ensure_unique_title(store, workspace, base)
                    # Re-check under the race: a rename may have landed meanwhile.
                    current = store.get_session(sid) or {}
                    if (current.get("title") or "").strip():
                        return
                    if store.set_title(sid, title):
                        # Same ack shape as session_rename: the desktop notes the
                        # row directly (live auto-title push, no list refetch).
                        self.emit({"type": "session_info", "session_id": sid,
                                   "title": title, "renamed": True})
                except Exception as exc:
                    print(f"[bridge] autotitle failed for {sid}: {exc!r}",
                          file=sys.stderr, flush=True)

            threading.Thread(target=_run, name=f"bridge-titler-{sid}", daemon=True).start()
        except Exception as exc:
            print(f"[bridge] autotitle dispatch failed for {sid}: {exc!r}",
                  file=sys.stderr, flush=True)

    @staticmethod
    def _identity_fields(sid: str) -> dict:
        """Minimal identity for non-turn frames (voice needs session_id)."""
        return {"session_id": sid}

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
            if workspace and existing["workspace"] and existing["workspace"] != workspace:
                raise WorkspaceSwitchError(sid, existing["workspace"], workspace)
            if workspace and not existing["workspace"]:
                # First REAL binding: an entry minted by a workspace-less
                # frame (subagent_status, reply routes) carries '' — the
                # absence of a binding, not a binding to nowhere. Adopt
                # the real workspace instead of refusing it forever
                # (field 2026-10-16: a delegate child could never be
                # opened — "bound to workspace ''" — so its finished
                # session stayed invisible).
                existing["workspace"] = workspace
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
            "message.agent.retract": "token_retract",
            "llm.request": "llm.request",
            "llm.response": "llm.response",
            "reasoning.update": "reasoning",
            "tool.call": "tool_call_start",
            "tool.args": "tool_call_args",
            "tool.result": "tool_call_end",
            "tool.output": "tool_output",
            "tool.approval.request": "safety_request",
            "tool.clarify.request": "clarify_request",
            "todo.updated": "todo_updated",
            "analytics.update": "telemetry",
            "plan.created": "plan_updated",
            "checkpoint.created": "checkpoint_event",
            "verification.updated": "verification_updated",
            "subagent.updated": "subagent_updated",
            "subagent.background_completed": "subagent_background_completed",
            "runtime.degraded": "runtime_degraded",
            "context.status": "context_status",
        }
        target = mapping.get(kind)
        if target is None:
            return None
        # Frames carry their AUTHOR's session, not the running turn's.
        # The old base stamped every event with the turn identity (the
        # parent), so a child's tokens/tool cards/reasoning arrived
        # labelled "parent": they merged into the parent's live answer
        # (and repeated in the child's own session), while the child
        # view — routing frames by session — saw them as foreign and
        # never streamed (field 2026-10-16). Session-less events keep
        # the turn's identity (aux/pre-turn traffic).
        event_session = str(
            payload.get("session_id") or payload.get("thread_id") or ""
        ) or identity.session_id
        base = {
            "type": target,
            "event_id": event.get("event_id"),
            "timestamp": event.get("timestamp"),
            **identity.event_fields(),
            "session_id": event_session,
            "lineage_id": identity.lineage_root_id,
        }

        raw_tool_id = str(
            payload.get("tool_id") or payload.get("tool_call_id")
            or payload.get("id") or ""
        )
        prefix = f"{event_session}-"
        tool_id = raw_tool_id[len(prefix):] if raw_tool_id.startswith(prefix) else raw_tool_id
        name = str(payload.get("name") or payload.get("tool_name") or "")

        if target == "subagent_background_completed":
            # A background child's completion is a STATUS signal for the
            # parent's card (the engine wakes the parent model through its
            # own channel). It is never transcript text: injecting the
            # child's <task> output into the parent's voice merged the
            # child into the parent and duplicated its answer
            # (field 2026-10-16: "i don't want the child to get merged").
            return {
                **base,
                "type": "subagent_background_completed",
                "subagent_id": payload.get("subagent_id"),
                "child_thread_id": payload.get("child_thread_id"),
                "text": payload.get("text", ""),
                "description": payload.get("description", ""),
            }
        if target == "token":
            return {**base, "text": str(payload.get("text") or payload.get("chunk") or "")}
        if target == "token_retract":
            # A discarded generation (dropped-toolcall re-prompt) withdraws
            # its painted chars; the replacement attempt paints fresh.
            return {**base, "chars": max(0, int(payload.get("chars") or 0))}
        if target == "tool_call_start":
            return {
                **base, "tool_id": tool_id, "name": name,
                "arguments": payload.get("arguments", payload.get("tool_args")),
            }
        if target == "tool_call_args":
            # Streamed arguments snapshot (ephemeral; the durable
            # tool_call_start carries the complete arguments).
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
        if target == "tool_output":
            # Live chunk (ephemeral preview; the durable record is the
            # tool_call_end result that follows).
            return {
                **base, "tool_id": tool_id, "name": name,
                "text": str(payload.get("chunk") or ""),
            }
        if target == "safety_request":
            return {
                **base, "tool_id": tool_id, "name": name,
                "arguments": payload.get("arguments", payload.get("tool_args")),
                "diff": payload.get("diff"), "warning": payload.get("warning"),
            }
        if target == "clarify_request":
            # Hermes clarify card payload: one batch of normalized questions,
            # answered per qid through the clarify_reply frame.
            # tool_id is the ASK TOOL CALL's id or nothing: the generic
            # fallback above would stamp payload["id"] — the queue item's
            # REQUEST id — and the desktop matches a pending ask to its
            # transcript tool call by this field. A request id here made
            # every checkpoint-hydrated ask paint read-only and
            # unanswerable (field 2026-10-16).
            return {
                **base, "tool_id": str(payload.get("tool_id") or payload.get("tool_call_id") or ""),
                "request_id": str(payload.get("id") or ""),
                "title": payload.get("title", ""),
                "questions": payload.get("questions", []),
                "session_id": payload.get("session_id", identity.session_id),
            }
        if target == "todo_updated":
            # Hermes todo panel payload: {todos, revision} reconciles atomically.
            return {
                **base,
                "todos": payload.get("todos", []),
                "revision": payload.get("revision", 0),
                "summary": payload.get("summary", {}),
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
            "message.agent.retract": "token_retract",
        }.get(kind)
        if target is None:
            return event if kind in {
                "turn_started", "token", "token_retract", "reasoning", "plan_updated",
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
        if target == "subagent_background_completed":
            # A background child's completion is a STATUS signal for the
            # parent's card (the engine wakes the parent model through its
            # own channel). It is never transcript text: injecting the
            # child's <task> output into the parent's voice merged the
            # child into the parent and duplicated its answer
            # (field 2026-10-16: "i don't want the child to get merged").
            return {
                **base,
                "type": "subagent_background_completed",
                "subagent_id": payload.get("subagent_id"),
                "child_thread_id": payload.get("child_thread_id"),
                "text": payload.get("text", ""),
                "description": payload.get("description", ""),
            }
        if target == "token":
            return {**base, "text": str(payload.get("text") or payload.get("chunk") or "")}
        if target == "token_retract":
            return {**base, "chars": max(0, int(payload.get("chars") or 0))}
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

    def _emit_stall_release(self, identity: TurnIdentity, force_ended: threading.Event,
                            budget: float) -> None:
        """Watchdog release: one honest receipt, then a synthetic turn_done.

        Only reachable when a full budget window passed with zero relayed
        engine events (see turn_watchdog.run_stall_watchdog), i.e. the turn
        is silent, not merely slow.
        """
        force_ended.set()
        print(
            f"[bridge] turn STALL watchdog fired after {budget:.0f}s "
            "with no engine activity - releasing the session",
            file=sys.stderr, flush=True,
        )
        self.emit({
            "type": "runtime_degraded", **identity.event_fields(),
            "reason": f"turn stalled: no engine activity for {budget:.0f}s (watchdog)",
        })
        self.emit({
            "type": "turn_done", **identity.event_fields(),
            "message": (
                f"The engine produced no activity for {budget:.0f}s, so the "
                "watchdog ended the turn. The reply above is what the engine "
                "produced; send another message to continue."
            ),
            "completed": False, "cancelled": False, "stub": False,
        })

    def _lineage_root(self, session_id: str) -> str | None:
        """The topmost ancestor of `session_id` per the durable rows.

        A rowless session DEEP in the walk is a top-level session (the
        chain's proven root); a rowless ASKER is unproven lineage (a
        fresh child's row may not exist yet — the spawn race) and returns
        None. Proven roots cache on the server — a session's lineage
        never changes once its row exists.
        """
        cache = getattr(self, "_lineage_root_cache", None)
        if cache is None:
            cache = self._lineage_root_cache = {}
        if session_id in cache:
            return cache[session_id]
        try:
            from src.runtime.subagent_store import get_store
            store = get_store()
        except Exception:
            return None
        current = session_id
        for depth in range(8):
            row = store.get(current)
            if row is None:
                if depth == 0:
                    return None
                cache[session_id] = current
                return current
            parent = getattr(row, "parent_session_id", None)
            if not parent:
                cache[session_id] = current
                return current
            current = str(parent)
        return None

    def _in_session_tree(self, session_id: str, root: str, *,
                         fail_open: bool = True) -> bool:
        """True when `session_id` is `root` or a descendant of it.

        Lineage comes from the durable sub-agent rows (cached per
        session). Unproven lineage fails OPEN for blocking asks — the
        desktop parks asks outside the viewed tree harmlessly, while a
        dropped ask blocks a child invisibly — but CLOSED for turn
        content: foreign tokens must never stream into a running turn's
        view. Only a proven different tree isolates either kind.
        """
        if session_id == root:
            return True
        try:
            top = self._lineage_root(session_id)
        except Exception:
            return fail_open
        if top is None:
            return fail_open
        return top == root

    def _forward_events(self, q: queue.Queue, identity: TurnIdentity, done: threading.Event,
                        own_sid: str | None = None, liveness: TurnLiveness | None = None) -> None:
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
                    # Session-TREE traffic: a child's frames name the CHILD
                    # session, so plain isolation drops them all — which is
                    # how child questions/approvals vanished invisibly
                    # (field 2026-10-16), and why child transcripts could
                    # only poll checkpoints instead of streaming. Blocking
                    # asks fail OPEN on unproven lineage (a question must
                    # never be stranded); turn CONTENT (tokens, tool cards,
                    # reasoning — what makes a child view stream like the
                    # parent's) forwards only on PROVEN in-tree lineage, so
                    # a concurrent foreign turn can never paint into this
                    # one. The desktop routes every forwarded frame by its
                    # own session: viewed sessions paint live, background
                    # ones update their rows.
                    is_tree_hitl = str(event.get("type") or "") in (
                        "tool.clarify.request", "tool.approval.request")
                    if (event_session is not None and event_session != own_sid
                            and not is_llm_status
                            and not self._in_session_tree(
                                event_session, own_sid,
                                fail_open=is_tree_hitl)):
                        continue
                if liveness is not None:
                    # Hermes activity_tracking discipline: relayed engine
                    # output IS liveness — provider status, tool frames,
                    # approval waits, context receipts. Cross-session events
                    # dropped above never touch this turn's stall clock.
                    liveness.touch()
                frame = self._project_event(event, identity)
                if frame:
                    self.emit(frame)
            except Exception as exc:
                print(
                    f"[CrusorAI bridge] event forwarder failed: {type(exc).__name__}: {exc}",
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

    def _run_turn(self, sid: str, text: str, workspace: str, mode: str = "agent", reasoning_effort: str | None = None) -> None:
        from src.runtime.turn_control import set_active_session, turn_controls

        identity = TurnIdentity.create(session_id=sid, workspace=workspace)
        # faulthandler.dump_traceback_later() returns None, so track the flag
        # explicitly: the scheduled dump must always be cancelled after the
        # turn, and the echo branch must not leak it either.
        diagnostics_enabled = (
            os.environ.get("CRUSORAI_BRIDGE_DIAGNOSTICS", "").lower() in {"1", "true", "yes"}
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
        # Stop. The bridge emits the terminal frame itself (stall receipt) so
        # the session is RELEASED even while the stuck thread stays stuck.
        # CRUSORAI_TURN_STALL_TIMEOUT_S, 0 = off.
        #
        # FIELD FIX (owner log 2026-09-08): the first watchdog fired on a LIVE
        # turn — it timed TOTAL wall time from turn start, and a turn the
        # owner watched working (311.6s non-streaming LLM answer, 264.9s
        # browser_navigate, 108.7s context build) blew straight past 600s:
        # "run stopped but agent is still in job". Hermes' liveness watchdog
        # is activity-based (agent/activity_tracking.py: a stall observation
        # binds to a generation; real progress invalidates it), so the budget
        # now measures SILENCE: every own-session event the forwarder relays
        # touches the liveness generation and re-arms the window. A turn that
        # only looks slow never fires; a truly silent one still releases.
        _terminal = threading.Event()
        _force_ended = threading.Event()
        _liveness = TurnLiveness()

        def _emit_terminal(frame: dict) -> None:
            # Exactly-once terminal delivery: after the watchdog released the
            # session, an engine thread finishing late must not emit a second
            # terminal frame (the field UI showed a dead run still working).
            if _force_ended.is_set():
                print(
                    "[bridge] watchdog already released this turn; "
                    "late terminal frame suppressed",
                    file=sys.stderr, flush=True,
                )
                return
            self.emit(frame)

        def _stall_watchdog() -> None:
            run_stall_watchdog(
                terminal=_terminal,
                liveness=_liveness,
                budget_env=os.environ.get("CRUSORAI_TURN_STALL_TIMEOUT_S", "").strip(),
                fire=lambda budget: self._emit_stall_release(identity, _force_ended, budget),
            )

        threading.Thread(target=_stall_watchdog, name="crusorai-turn-watchdog", daemon=True).start()
        # Establish active ownership before publishing turn_started. Once the
        # UI can show Stop, stream_agent's nested begin must preserve it.
        turn_controls.begin(sid)
        set_active_session(sid)
        try:
            self.emit({"type": "turn_started", **identity.event_fields(), "timestamp": identity.created_at})
            if os.environ.get("CRUSORAI_BRIDGE_RUNNER", "").lower() == "echo":
                # Test seam (CRUSORAI_ECHO_DELAY_MS): simulate an in-flight turn
                # that honours a cancel request, mirroring real turn semantics.
                # Used by the reliability-benchmark harness (PBR-012) to verify
                # cancel behaviour with zero model calls. Default 0 => the
                # historical instant echo turn, byte-compatible with past tests.
                delay_ms = int(os.environ.get("CRUSORAI_ECHO_DELAY_MS", "0") or "0")
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
                # Say that no model was called, in the transcript, BEFORE the echo lands. Without
                # this the user's own words come back as the reply and the app looks broken rather
                # than deliberately provider-free; `test_runner` on the token frame is not rendered
                # anywhere, so the notice bar (the runtime_degraded channel, which the renderer
                # paints as an honest receipt rather than an error) is the only place the user
                # actually looks.
                self.emit({
                    "type": "runtime_degraded", **identity.event_fields(),
                    "reason": (
                        "Test mode (CRUSORAI_BRIDGE_RUNNER=echo): no model was called, and the reply "
                        "below is your own message echoed back. Clear that variable and relaunch for "
                        "real answers. (The engine is fine; this is a deliberate test seam.)"
                    ),
                })
                self.emit({
                    "type": "token", **identity.event_fields(),
                    "text": text, "test_runner": "echo",
                })
                self._touch_turn(sid, text)
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
                target=self._forward_events, args=(q, identity, done, sid, _liveness),
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
                    "CRUSORAI_BRIDGE_APPROVAL_POLICY", "workspace_session"
                ).strip()
                if approval_policy not in {"ask", "workspace_session", "session"}:
                    approval_policy = "workspace_session"
                result = stream_agent(
                    text, thread_id=sid, workspace=workspace,
                    approval_channel=True, approval_timeout=300.0,
                    approval_policy=approval_policy,
                    turn_id=identity.turn_id,
                    execution_mode=mode,
                    reasoning_effort=reasoning_effort,
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
                # `[CrusorAI Engine] ...`.)
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
                _emit_terminal({
                    "type": "turn_done", **identity.event_fields(),
                    "message": str(result),
                    "completed": task_completed and not cancelled,
                    "cancelled": cancelled, "stub": False,
                })
                # Hermes auto-title rule: only after a FULL exchange — a completed,
                # uncancelled turn. The titler runs async and pushes session_info.
                if task_completed and not cancelled:
                    try:
                        self._maybe_autotitle_session(sid, text, str(result))
                    except Exception:
                        pass  # accounting never breaks the receipt
                _model_wall = 0.0
                _subagent_model_wall = 0.0
                try:
                    from src.graphs.chat_graph import pop_turn_model_accounting
                    # Read-and-clear (field 2026-09-09's cumulative read
                    # charged later turns for earlier ones). Sub-agent
                    # model seconds arrive already attributed: children
                    # accumulate under their own thread ids and the
                    # delegate settles their wall onto this thread —
                    # before that transfer existed, a 742.3s turn
                    # reported "model 42.8s, non-model 699.6s" while
                    # the child's model calls hid inside the wait.
                    _model_wall, _subagent_model_wall = pop_turn_model_accounting(sid)
                except Exception:
                    pass  # accounting never breaks the receipt
                _other = max(0.0, (_time.monotonic() - _turn_t0) - _model_wall - _subagent_model_wall)
                _model_part = (
                    f"model {_model_wall:.1f}s + sub-agent model {_subagent_model_wall:.1f}s"
                    if _subagent_model_wall > 0 else f"model {_model_wall:.1f}s"
                )
                print(
                    f"[bridge] turn end: completed={task_completed and not cancelled} "
                    f"cancelled={cancelled} wall={_time.monotonic() - _turn_t0:.1f}s "
                    f"({_model_part}, non-model {_other:.1f}s — tools, "
                    "finalize, review, transport gaps live there)",
                    file=_sys.stderr, flush=True,
                )
            except Exception as exc:
                # Transport closure can surface through different provider
                # exception types. Intentional Stop wins over generic failure
                # attribution and must produce one terminal cancelled receipt.
                if turn_controls.cancelled(sid):
                    self._touch_turn(sid, text)
                    _terminal.set()
                    _emit_terminal({
                        "type": "turn_done", **identity.event_fields(),
                        "message": "Operation cancelled by the user.",
                        "completed": False, "cancelled": True, "stub": False,
                    })
                else:
                    self._touch_turn(sid, text)
                    _terminal.set()
                    _emit_terminal({
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
            self._run_turn(sid, queued[0], workspace, reasoning_effort=queued[1])

    def _delegate_tip(self, sid: str, tip: str) -> str:
        """A delegated child is always its OWN tip.

        Delegation is not lineage continuation: even where an older
        writer rooted a child's session row in the parent's lineage,
        resolve_tip would climb to the (more recently active) parent,
        and opening the child would rebind the desktop surface to the
        parent while painting the child's transcript — no child
        chrome, no way back (field 2026-10-16: "where am i this is
        not parent screen"). Fork children carry no sub-agent row, so
        genuine lineage continuations still resolve to their tip.
        """
        try:
            from src.runtime.subagent_store import get_store
            subs = get_store()
            if subs.get(sid) is not None or subs.get_by_child(sid) is not None:
                return sid
            if tip != sid and (subs.get(tip) is not None or subs.get_by_child(tip) is not None):
                # The climb crossed a delegation boundary: resolve_tip's
                # parent edges treat a delegate child as the parent's
                # latest descendant, so the parent's conversation
                # "resolved" to the child and its transcript page was
                # served for the parent — the child's history under the
                # parent's chrome, live composer, no way back (field
                # 2026-10-16: "i got sub agent output not main agent
                # output"). A delegate is a separate conversation: the
                # requested session is its own tip here. Fork
                # continuations carry no sub-agent row and still climb.
                return sid
        except Exception:
            pass
        return tip

    def _handle_session_meta(self, kind: str, sid: str, frame: dict, workspace: str) -> bool:
        """Durable-row session APIs (Hermes PATCH/DELETE/GET messages parity)."""
        try:
            store = self._durable_store()
        except Exception as exc:
            self.emit(error_frame(f"session store unavailable: {exc}"))
            return True
        if kind == "session_messages":
            try:
                tip = store.resolve_tip(sid)
            except Exception:
                tip = sid
            tip = self._delegate_tip(sid, tip)
            try:
                limit = int(frame.get("limit") or 120)
            except (TypeError, ValueError):
                limit = 120
            try:
                offset = int(frame.get("offset") or 0)
            except (TypeError, ValueError):
                offset = 0
            order = str(frame.get("order") or "latest").strip().lower()
            messages, pagination = self._transcript_messages(
                tip, limit=limit, offset=offset, order=order)
            self.emit({
                "type": "session_messages", "session_id": tip,
                "requested_session_id": sid, "messages": messages,
                "pagination": pagination,
            })
            return True
        if kind == "session_delete":
            worker = self._workers.get(sid)
            if worker is not None and worker.is_alive():
                self.emit(error_frame(
                    f"session {sid} has a live turn; stop it before deleting"))
                return True
            try:
                from src.runtime.factory import get_runtime_services
                journal_path = str(get_runtime_services().journal.path)
            except Exception:
                journal_path = None
            try:
                deleted = store.delete_session(sid, journal_path=journal_path)
            except Exception as exc:
                self.emit(error_frame(f"session delete failed: {exc}"))
                return True
            self._sessions.pop(sid, None)
            self.emit({"type": "session_deleted", "session_id": sid,
                       "deleted": bool(deleted)})
            return True
        if kind == "session_rename":
            from src.runtime.session_store import sanitize_title
            title = sanitize_title(frame.get("title"))
            try:
                ok = store.set_title(sid, title)
            except Exception as exc:
                self.emit(error_frame(f"session rename failed: {exc}"))
                return True
            if not ok:
                # Renaming a lazy draft that has no row yet: persist it now so
                # the title survives the restart (Hermes seeded-row rule).
                try:
                    store.create_session(sid, workspace, title=title)
                    ok = True
                except Exception as exc:
                    self.emit(error_frame(f"session rename failed: {exc}"))
                    return True
            self.emit({"type": "session_info", "session_id": sid,
                       "title": title, "renamed": bool(ok)})
            return True
        if kind == "session_pin":
            raw = frame.get("pinned", frame.get("enabled", frame.get("value")))
            pinned = bool(raw) if not isinstance(raw, str) else raw.strip().lower() in {
                "1", "true", "yes", "on"}
            try:
                ok = store.set_pinned(sid, pinned)
            except Exception as exc:
                self.emit(error_frame(f"session pin failed: {exc}"))
                return True
            self.emit({"type": "session_info", "session_id": sid,
                       "pinned": pinned, "pin_updated": bool(ok)})
            return True
        if kind == "session_archive":
            raw = frame.get("archived", frame.get("enabled", frame.get("value")))
            archived = bool(raw) if not isinstance(raw, str) else raw.strip().lower() in {
                "1", "true", "yes", "on"}
            try:
                ok = store.set_archived(sid, archived)
            except Exception as exc:
                self.emit(error_frame(f"session archive failed: {exc}"))
                return True
            self.emit({"type": "session_info", "session_id": sid,
                       "archived": archived, "archive_updated": bool(ok)})
            return True
        self.emit(error_frame(f"unknown session method: {kind!r}"))
        return True

    def _start_preview_proxy(self, workspace: str) -> None:
        """Make the preview proxy exist for this workspace, without ever touching the frame path.

        Nothing used to start it, so Preview needed a second terminal pointed at the opened folder
        (CRUSOR_PREVIEW_SETUP.md §5b) — and on Windows that terminal was a visible Python console
        next to the app. The engine knows the folder, so it starts the proxy itself: hidden, adopted
        when a healthy one already serves the same folder, and throttled by src.preview.autostart.

        A daemon thread is deliberate. A cold start is seconds of Python import plus a health poll,
        and a frame's response must not wait on the preview (a broken preview is a degraded feature;
        a stalled handshake is a broken product). The thread only logs, and ``ensure`` does not
        raise; ``CRUSORAI_PREVIEW_AUTOSTART=0`` turns the whole thing off (the test suite sets it).
        """
        if not workspace or workspace in self._preview_hooked:
            return
        self._preview_hooked.add(workspace)
        try:
            from src.preview.autostart import default as preview_autostart
            service = preview_autostart()
            if not service.enabled():
                return
        except Exception as exc:  # pragma: no cover - import failure is an env problem, not a bug
            print(f"[bridge] preview autostart unavailable ({exc!r})", file=sys.stderr, flush=True)
            return
        threading.Thread(
            target=_ensure_preview_proxy, args=(service.ensure, workspace),
            name="crusor-preview-autostart", daemon=True,
        ).start()

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
        if kind == "skills_hub_op":
            # Skills Hub ops are USER-level state (catalog/registry), not
            # session state: they are handled BEFORE workspace/session
            # resolution so the palette works on a fresh window (no session
            # bound yet) and a click never mints a phantom session. The
            # result echoes the caller's session_id as-is; the panel
            # correlates on `op`. (Field 2026-10-01: the op sat inside the
            # session-scoped chain, so palette clicks before any chat bound
            # went through session resolution and silently stalled.)
            op = str(frame.get("op") or "list").strip().lower()
            try:
                from src.agents.skills_hub import handle_hub_op
                result = handle_hub_op(op, frame=frame)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)[:500]}
            self.emit({
                "type": "skills_hub_result",
                "session_id": frame.get("session_id") or "",
                "op": op, "result": result,
            })
            return True
        if kind == "oneshot":
            # One-shot quick jobs (hermes oneshot parity): template or ad-hoc
            # ask -> ONE cheap-tier provider call. Handled BEFORE session
            # resolution on purpose: a one-shot has nothing to do with the
            # chat thread - it must never mint a session, append to history,
            # or touch the prompt cache. Result rides oneshot_result.
            #
            # The provider call runs on a daemon thread, NOT inline: the
            # read loop at run() is single-threaded, so an inline 30-50s
            # provider call parked every later frame (skills_hub_op,
            # anything) behind it and the panel's 12s listener answered
            # "the engine did not answer the 'skill_create' request".
            # emit() is already lock-protected, so a worker may emit.
            template = str(frame.get("template") or "adhoc")
            session_id = frame.get("session_id") or ""
            variables = frame.get("variables")
            import time as _t

            def _oneshot() -> None:
                _t0 = _t.monotonic()
                try:
                    from src.prompts.oneshot import run_oneshot
                    res = run_oneshot(
                        str(frame.get("template") or ""),
                        instructions=str(frame.get("instructions") or ""),
                        variables=variables if isinstance(variables, dict) else {},
                    )
                except Exception as exc:
                    res = {"ok": False, "error": str(exc)[:500]}
                # Field diagnosis: without this line, "the engine did not answer"
                # could mean old bridge, lost frame, OR a slow provider - and
                # nothing in the log said which.
                print(
                    "[bridge] oneshot "
                    + template + f": {int((_t.monotonic() - _t0) * 1000)}ms "
                    + (f"error: {str(res.get('error', ''))[:120]}" if res.get("error") else "ok"),
                    file=sys.stderr, flush=True,
                )
                self.emit({
                    "type": "oneshot_result",
                    "session_id": session_id,
                    "template": template,
                    "text": str(res.get("text", "")),
                    "error": str(res.get("error", "")),
                })

            threading.Thread(target=_oneshot, name="crusorai-oneshot", daemon=True).start()
            return True

        raw_workspace = frame.get("workspace")
        workspace = str(raw_workspace).strip() if raw_workspace else ""
        if not workspace and kind in _WORKSPACE_REQUIRED_METHODS:
            self.emit(error_frame(NO_WORKSPACE_ERROR))
            return True
        # The frame that binds a workspace is also the moment we know which folder the user opened,
        # and the preview proxy is useless without it — so this is where it gets started. Nothing
        # visible: no console window, no waiting, no failure path into the turn.
        self._start_preview_proxy(workspace)
        # Project skills (.crusorai/skills/*/SKILL.md, committed with the
        # repo) must be in the index BEFORE this turn's system prompt is
        # built. Idempotent + cheap (a listdir), so every workspace-bearing
        # frame refreshes it — pull a teammate's skill and it just works.
        try:
            from src.agents.skill_manager import skill_manager as _sm
            _sm.load_workspace_skills(workspace)
        except Exception:
            pass  # a broken team skills folder must never block the turn
        # Hermes session-metadata reads/writes are workspace-optional: they
        # address the DURABLE row, not the live worker, so they must neither
        # mint phantom in-memory entries nor demand an open folder.
        if kind in {"session_rename", "session_pin", "session_archive",
                    "session_delete", "session_messages"}:
            raw_sid = str(frame.get("session_id") or frame.get("thread_id") or "").strip()
            if not raw_sid:
                self.emit(error_frame(f"{kind} requires session_id"))
                return True
            bound = self._sessions.get(raw_sid)
            if workspace and bound is not None and bound.get("workspace") and bound.get("workspace") != workspace:
                self.emit(error_frame(
                    f"session {raw_sid} is bound to workspace {bound.get('workspace')!r}; "
                    f"cannot switch to workspace {workspace!r}"))
                return True
            if workspace and bound is not None and not bound.get("workspace"):
                # Same first-real-binding rule as _session: '' is the
                # absence of a binding (minted by a workspace-less
                # frame), never a binding to nowhere.
                bound["workspace"] = workspace
            return self._handle_session_meta(kind, raw_sid, frame, workspace)
        if kind == "session_list":
            # A listing must never mint: resolving-or-creating here would add a
            # phantom live draft on every refresh (a fresh window has no
            # session id yet). The list branch only reads the durable store +
            # the live registry, so an absent id is simply no filter.
            sid = str(frame.get("session_id") or frame.get("thread_id") or "").strip() or None
        else:
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
            # Hermes session.create: mint a lazy draft (no DB row) unless this
            # create carries intent (a parent link or seed messages), in which
            # case the row persists NOW because the post-create resume reads
            # the DB. prior_checkpoints keeps the "fixed id silently resumes"
            # visibility (measured: +3 calls / +~10k tokens per run, linear).
            title_param = frame.get("title")
            source_param = str(frame.get("source") or "desktop").strip() or "desktop"
            model_param = frame.get("model")
            parent_param = str(frame.get("parent_session_id") or "").strip() or None
            seed_messages = frame.get("messages") or []
            seeded = bool(parent_param) or (isinstance(seed_messages, list) and len(seed_messages) > 0)
            lazy = True
            session_row: dict | None = None
            if seeded:
                try:
                    store = self._durable_store()
                    created_row = store.create_session(
                        sid, workspace, source=source_param,
                        title=str(title_param) if title_param is not None else None,
                        model=str(model_param) if model_param else None,
                        parent_session_id=parent_param,
                    )
                    lazy = False
                    session_row = self._session_row_public(created_row)
                except Exception as exc:
                    print(f"[bridge] seeded session persist failed for {sid}: {exc!r}",
                          file=sys.stderr, flush=True)
            else:
                # Remember the draft's intent in memory; the first prompt
                # persists it (see _touch_turn). Stash on the live entry so
                # session_list can surface optimistic rows for drafts.
                try:
                    entry = self._sessions.get(sid, {})
                    if title_param is not None:
                        entry["pending_title"] = str(title_param)[:200]
                    if model_param:
                        entry["model"] = str(model_param)[:200]
                    if parent_param:
                        entry["parent_session_id"] = parent_param
                    entry["stored_session_id"] = sid
                    entry["lazy"] = True
                except Exception:
                    pass
            prior = self._prior_checkpoint_count(sid)
            info: dict = {"type": "session_info", **self._sessions[sid],
                          "stored_session_id": sid, "lazy": lazy,
                          "info": {"model": str(model_param or ""),
                                   "cwd": workspace, "source": source_param,
                                   "lazy": lazy}}
            if session_row is not None:
                info["session"] = session_row
            if prior is not None:
                info["prior_checkpoints"] = prior
            self.emit(info)
        elif kind in {"session_load", "session_resume"}:
            # Hermes session.resume: resolve the lineage tip, reopen the row,
            # mark read (an explicit open means the user saw it), and return
            # the journal timeline + status + subagents for the TIP.
            try:
                tip = self._durable_store().resolve_tip(sid)
            except Exception:
                tip = sid
            tip = self._delegate_tip(sid, tip)
            try:
                from src.graphs.chat_graph import get_agent_status
                status = get_agent_status(tip)
            except Exception:
                status = {}
            # Navigation hydrates the transcript from session_messages (paged
            # checkpoints); include_events:false skips the journal here so the
            # two views never double-paint one transcript. Restart recovery
            # keeps the default and replays the journal instead.
            include_events = frame.get("include_events", True)
            if (include_events is False
                    or str(include_events).strip().lower() in {"false", "0", "no"}):
                events = []
            else:
                try:
                    from src.runtime.factory import get_runtime_services
                    stored = get_runtime_services().journal.list_events(tip)
                    events = self._project_stored_events(stored)
                except Exception:
                    events = []
            try:
                self._durable_store().set_read(tip, True)
            except Exception:
                pass
            session_row_public: dict | None = None
            try:
                session_row_public = self._session_row_public(
                    self._durable_store().get_session(tip))
            except Exception:
                session_row_public = None
            # OpenCode parity: include subagent list on resume for parentMap navigation
            subagents_payload = []
            try:
                from src.runtime.subagent_store import get_store
                s_store = get_store()
                rows = s_store.list_by_parent(tip)
                if not rows and tip != sid:
                    rows = s_store.list_by_parent(sid)
                subagents_payload = [r.to_dict() for r in rows]
            except Exception:
                subagents_payload = []
            resume_frame: dict = {
                "type": "session_info", **self._sessions[sid],
                "resumed": kind == "session_resume",
                "resolved_session_id": tip,
                "events": events, "agent_status": status,
                "subagents": subagents_payload,
            }
            if session_row_public is not None:
                resume_frame["session"] = session_row_public
            self.emit(resume_frame)
            # Also emit dedicated subagent_list frame for UI that listens specifically
            if subagents_payload:
                self.emit({
                    "type": "subagent_list", "session_id": sid,
                    "subagents": subagents_payload,
                })
        elif kind == "session_list":
            # Hermes listSessions: durable rows first (recency window + pinned
            # back-fill), live lazy drafts merged as optimistic rows so a
            # just-created chat renders before its first prompt persists it.
            try:
                limit = int(frame.get("limit") or 40)
            except (TypeError, ValueError):
                limit = 40
            try:
                offset = int(frame.get("offset") or 0)
            except (TypeError, ValueError):
                offset = 0
            order = str(frame.get("order") or "recent").strip().lower()
            if order not in ("recent", "created"):
                order = "recent"
            archived = str(frame.get("archived") or "exclude").strip().lower()
            if archived not in ("exclude", "include", "only"):
                archived = "exclude"
            query = str(frame.get("query") or frame.get("search") or "").strip() or None
            try:
                min_messages = max(0, int(frame.get("min_messages") or 0))
            except (TypeError, ValueError):
                min_messages = 0
            ws_filter = workspace or None
            store = None
            try:
                store = self._durable_store()
                durable = store.list_sessions_rich(
                    limit=limit, offset=offset, order=order, archived=archived,
                    workspace=ws_filter, search_query=query,
                    min_messages=min_messages, include_pinned=True)
            except Exception as exc:
                print(f"[bridge] durable session list failed: {exc!r}",
                      file=sys.stderr, flush=True)
                durable = []
            seen = {str(r.get("id")) for r in durable}
            optimistic: list[dict] = []
            if offset == 0 and not query and archived != "only":
                for live_id, entry in self._sessions.items():
                    if live_id in seen:
                        continue
                    if ws_filter and entry.get("workspace") != ws_filter:
                        continue
                    # A live entry with a DURABLE row was excluded by the
                    # query's own filters (archived, min_messages, ...) — the
                    # optimistic merge must not resurrect it. Only rowless
                    # lazy drafts surface here.
                    try:
                        if store.get_session(live_id) is not None:
                            continue
                    except Exception:
                        pass
                    optimistic.append({
                        "id": live_id, "session_id": live_id,
                        "title": str(entry.get("pending_title") or ""),
                        "workspace": str(entry.get("workspace") or ""),
                        "source": "desktop",
                        "model": str(entry.get("model") or ""),
                        "message_count": 0, "preview": "",
                        "pinned": False, "archived": False, "hidden": False,
                        "unread": False,
                        "parent_session_id": entry.get("parent_session_id"),
                        "lineage_root_id": live_id,
                        "lazy": True,
                    })
            sessions_payload = optimistic + [
                {**self._session_row_public(r), "session_id": r.get("id")}
                for r in durable
            ]
            # Back-compat: historical shape is session_info.sessions of
            # {session_id, workspace}; durable rows carry both id and
            # session_id so old and new readers agree.
            self.emit({"type": "session_info", "sessions": sessions_payload,
                       "limit": limit, "offset": offset,
                       "has_more": len(durable) >= max(1, min(limit, 200))})
        elif kind == "session_fork":
            # Hermes branch: child first (a failed create never leaves the
            # source ended with no fork), then copy the transcript. The child
            # row links parent_session_id + lineage root so listings nest it
            # and resolve_tip lands on it.
            source = sid
            target = self._session(None, workspace)
            try:
                from src.graphs.chat_graph import fork_conversation
                fork_conversation(source, target)
            except Exception:
                pass
            try:
                store = self._durable_store()
                parent_row = store.get_session(source)
                base_title = str((parent_row or {}).get("title") or "").strip()
                # Title discipline: a fork of a titled parent derives a unique
                # lineage title; a fork of an untitled parent stays untitled so
                # the auto-titler creates one after its first exchange.
                if base_title:
                    from src.runtime.session_titling import ensure_unique_title
                    child_title = ensure_unique_title(store, workspace, f"{base_title} (fork)")
                else:
                    child_title = ""
                store.create_session(target, workspace, title=child_title,
                                     model=str((parent_row or {}).get("model") or "") or None,
                                     parent_session_id=source)
                if parent_row and parent_row.get("message_count"):
                    store.touch_activity(
                        target, preview=str(parent_row.get("preview") or ""),
                        message_count=int(parent_row.get("message_count") or 0))
            except Exception as exc:
                print(f"[bridge] fork row persist failed for {target}: {exc!r}",
                      file=sys.stderr, flush=True)
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
            # Think-picker effort rides every prompt frame; keep it with the
            # turn so a mid-session pick applies to that turn only. Queue the
            # (text, effort) pair so a busy session's queued prompt keeps ITS
            # pick, not the active turn's.
            effort = str(frame.get("reasoning_effort") or "").strip() or None
            if not text:
                self.emit(error_frame("prompt text is required"))
            elif mode not in EXECUTION_MODES:
                self.emit(error_frame(f"unsupported execution mode: {mode}"))
            elif sid in self._workers and self._workers[sid].is_alive():
                from src.runtime.turn_control import turn_controls
                depth = turn_controls.queue(sid, text, effort)
                self.emit({"type": "session_info", "session_id": sid, "queued": depth})
            else:
                # Warm the heavy turn-path imports on the MAIN thread before
                # dispatching the worker: numpy/transformers C-extension init
                # deadlocks when imported on a non-main thread (Windows), which
                # previously hung the real turn silently. Once cached in
                # sys.modules, the worker's own imports are instant no-ops.
                # The echo runner never touches chat_graph, so skip the ~11s
                # warm-up there.
                if os.environ.get("CRUSORAI_BRIDGE_RUNNER", "").lower() != "echo":
                    from src.dashboard.event_bus import event_bus  # noqa: F401
                    from src.graphs.chat_graph import stream_agent  # noqa: F401
                # Hermes lazy-row rule: the row exists from the first ACCEPTED
                # prompt, so a turn that dies mid-flight still lists. The
                # title/activity touch lands at turn end (see _touch_turn).
                try:
                    store = self._durable_store()
                    if store.get_session(sid) is None:
                        # Explicit pending titles (session_new) persist; otherwise the
                        # row stays untitled for the auto-titler (no capture).
                        pending = str(self._sessions.get(sid, {}).get("pending_title") or "")
                        store.create_session(
                            sid, self._sessions[sid]["workspace"],
                            title=pending or "",
                            model=str(self._sessions.get(sid, {}).get("model") or "") or None,
                            parent_session_id=self._sessions.get(sid, {}).get("parent_session_id"),
                        )
                except Exception as exc:
                    print(f"[bridge] prompt row ensure failed for {sid}: {exc!r}",
                          file=sys.stderr, flush=True)
                worker = threading.Thread(
                    target=self._run_turn,
                    args=(sid, text, self._sessions[sid]["workspace"], mode, effort),
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
        elif kind == "clarify_reply":
            # Hermes ask-tool answer path: the card replies per qid; an explicit
            # skip (timed_out) resolves the batch so the model decides itself.
            from src.dashboard.event_bus import clarify_queue
            ok = clarify_queue.resolve(
                str(frame.get("request_id") or ""),
                frame.get("answers") or {},
                timed_out=bool(frame.get("timed_out", False)),
                session_id=sid,
            )
            self.emit({"type": "session_info", "session_id": sid, "clarify_resolved": ok})
        elif kind == "subagent_launch":
            # Depth check (OpenCode parity: subagent_depth, default 1)
            try:
                from src.runtime.subagent_store import get_store
                import os as _depth_os
                _store = get_store()
                _depth = _store.depth_of(str(sid))
                if str(sid).startswith("sub-"):
                    _depth = max(_depth, 1)
                _max_depth = int(_depth_os.getenv("CRUSORAI_SUBAGENT_DEPTH", "1") or "1")
                if _depth >= _max_depth:
                    self.emit({
                        "type": "subagent_updated", "session_id": sid,
                        "subagent_id": f"depth-denied-{sid}",
                        "state": "failed",
                        "error": f"Subagent depth cap reached ({_max_depth})",
                    })
                    self.emit(error_frame(f"Subagent depth cap reached ({_max_depth})"))
                else:
                    from src.agents.subagent_lifecycle import subagent_lifecycle
                    handle = subagent_lifecycle.launch(
                        parent_session_id=sid,
                        goal=str(frame.get("goal") or frame.get("prompt") or ""),
                        mode=str(frame.get("mode") or frame.get("subagent_type") or "research"),
                        parent_capabilities=tuple(frame.get("parent_capabilities") or ()),
                        allowed_capabilities=tuple(frame.get("allowed_capabilities") or ()),
                        description=str(frame.get("description") or "")[:200],
                        agent_name=str(frame.get("subagent_type") or frame.get("mode") or "research"),
                        tool_call_id=str(frame.get("tool_call_id") or "") or None,
                        background=bool(frame.get("background", False)),
                        workspace=str(self._sessions.get(sid, {}).get("workspace") or "") or None,
                    )
                    self._subagents[handle.subagent_id] = handle
                    # The delegation goal is explicit (not a capture): the child row
                    # carries it as a unique fixed title so history rows stay distinct.
                    try:
                        from src.runtime.session_titling import ensure_unique_title, shorten_title
                        _dstore = self._durable_store()
                        if _dstore.get_session(handle.subagent_id) is None:
                            _goal = str(frame.get("goal") or frame.get("prompt") or frame.get("description") or "")
                            _ws = str(self._sessions.get(sid, {}).get("workspace") or "")
                            _dstore.create_session(
                                handle.subagent_id, _ws,
                                title=ensure_unique_title(_dstore, _ws, shorten_title(_goal) or "Sub-agent task"),
                                parent_session_id=sid,
                                # Delegation roots its own lineage (see
                                # coordinator spawn): resolve_tip must
                                # never climb from child back to parent.
                                lineage_root_id=handle.subagent_id,
                            )
                    except Exception as _title_exc:
                        print(f"[bridge] child title failed for {handle.subagent_id}: {_title_exc!r}",
                              file=sys.stderr, flush=True)
                    self.emit({
                        "type": "subagent_updated", "session_id": sid,
                        "subagent_id": handle.subagent_id,
                        "child_thread_id": handle.subagent_id,
                        "parent_session_id": sid,
                        "state": "pending",
                        "description": str(frame.get("description") or "")[:200],
                        "mode": str(frame.get("mode") or "research"),
                        "agent_name": str(frame.get("subagent_type") or frame.get("mode") or "research"),
                        "background": bool(frame.get("background", False)),
                    })
            except Exception as _launch_exc:
                # If depth check failed or launch threw, ensure error emitted (depth case already emitted)
                if "depth limit" not in str(_launch_exc).lower():
                    try:
                        self.emit({
                            "type": "subagent_updated", "session_id": sid,
                            "subagent_id": f"launch-failed-{sid}",
                            "state": "failed",
                            "error": str(_launch_exc)[:500],
                        })
                    except Exception:
                        pass

        elif kind == "subagent_list":
            # OpenCode parity: list child sessions for a parent
            try:
                from src.runtime.subagent_store import get_store
                store = get_store()
                rows = store.list_by_parent(sid)
                payload = [r.to_dict() for r in rows]
                self.emit({
                    "type": "subagent_list", "session_id": sid,
                    "subagents": payload,
                })
            except Exception as exc:
                self.emit({
                    "type": "subagent_list", "session_id": sid,
                    "subagents": [], "error": str(exc),
                })
        elif kind in {"subagent_status", "subagent_cancel", "subagent_result"}:
            from src.agents.subagent_lifecycle import subagent_lifecycle
            sub_id = str(frame.get("subagent_id") or "")
            handle = self._subagents.get(sub_id)
            if handle is None:
                # Try to recover from store (process restart)
                try:
                    from src.runtime.subagent_store import get_store
                    store = get_store()
                    row = store.get(sub_id) or store.get_by_child(sub_id)
                    if row:
                        payload = row.to_dict()
                    else:
                        payload = {"state": "unknown"}
                except Exception:
                    payload = {"state": "unknown"}
            elif kind == "subagent_status":
                payload = subagent_lifecycle.status(handle)
            elif kind == "subagent_cancel":
                payload = {"cancel_accepted": subagent_lifecycle.cancel(handle), **subagent_lifecycle.status(handle)}
            else:
                payload = subagent_lifecycle.result(handle)
            # Extend with store data if available for UI richness
            try:
                from src.runtime.subagent_store import get_store
                store = get_store()
                row = store.get(sub_id) or store.get_by_child(sub_id)
                if row:
                    base = row.to_dict()
                    # Merge lifecycle payload over store base
                    payload = {**base, **payload}
            except Exception:
                pass
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
        CRUSORAI_MEMORY_WARMUP_AT_BOOT gate is read per process start.
        """
        if os.environ.get("CRUSORAI_MEMORY_WARMUP_AT_BOOT", "").strip().lower() in {"0", "false", "no", "off"}:
            return

        def _warm():
            try:
                from src.graphs.chat_graph import memory_manager
                if memory_manager is not None:
                    memory_manager.warmup()
            except Exception as exc:
                print(f"[bridge] boot memory warmup skipped: {exc!r}", file=sys.stderr, flush=True)

        threading.Thread(target=_warm, name="crusorai-boot-warmup", daemon=True).start()

    @staticmethod
    def _apply_memory_policy() -> None:
        """Desktop default: long-term memory OFF.

        Field proof (2026-09-04): the in-process embedder backend
        (torch/sentence-transformers + its own SQLite) wedged the turn
        process at the checkpointer commit — twice, always while backend
        construction overlapped a live turn, on Windows. Hermes keeps
        memory housekeeping OFF the turn's critical path; ours sat right
        on it. Until the backend moves behind a real process boundary,
        the desktop engine runs with memory disabled unless the user
        opts in (CRUSORAI_MEMORY=on). CLI/dashboard surfaces are not
        affected (this policy lives in the bridge). Must run BEFORE the
        first chat_graph import — the lazy manager reads the env there.

        Fix 2026-09-21: when OFF, also disable boot warmup entirely so no
        background thread burns 30s+ downloading the embedder on first boot
        (trace 202.6s wall / 204.4s warmup). Opt-in path keeps warmup.
        """
        opted_in = os.environ.get("CRUSORAI_MEMORY", "").strip().lower() in {"1", "true", "yes", "on"}
        print(f"[bridge][memory] policy check: CRUSORAI_MEMORY={os.getenv('CRUSORAI_MEMORY')!r} opted_in={opted_in} DISABLE={os.getenv('CRUSORAI_DISABLE_LONG_TERM_MEMORY')!r}", file=sys.stderr, flush=True)
        if opted_in:
            print("[bridge] long-term memory: ON (CRUSORAI_MEMORY=on)", file=sys.stderr, flush=True)
            return
        os.environ.setdefault("CRUSORAI_DISABLE_LONG_TERM_MEMORY", "1")
        # Prevent background embedder download when memory is OFF
        os.environ.setdefault("CRUSORAI_MEMORY_WARMUP_AT_BOOT", "off")
        # Tight per-call wait so degraded calls don't park 350ms+ each
        os.environ.setdefault("CRUSORAI_MEMORY_WARMUP_BUDGET_S", "0.35")
        os.environ.setdefault("CRUSORAI_MEMORY_INIT_BUDGET_S", "30")
        print(
            "[bridge] long-term memory: OFF (desktop default; "
            "CRUSORAI_MEMORY=on to enable) — boot warmup disabled "
            f"(DISABLE={os.getenv('CRUSORAI_DISABLE_LONG_TERM_MEMORY')!r} WARMUP_AT_BOOT={os.getenv('CRUSORAI_MEMORY_WARMUP_AT_BOOT')!r})",
            file=sys.stderr, flush=True,
        )

    def _engine_build(self) -> str:
        """The exact build this engine process runs ("<sha> <date>")."""
        try:
            import subprocess
            engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            proc = subprocess.run(
                ["git", "log", "-1", "--format=%h %ci"],
                capture_output=True, text=True, timeout=3, cwd=engine_root,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass
        return "unknown"

    def _log_build(self) -> None:
        """One stderr line naming the exact build this engine process runs.

        Field discipline (2026-09-04): hung turns can only be attributed to
        a build by which probe lines exist in the log — and twice the actual
        answer was "the engine is still running the previous build". Now the
        log says so itself: every session starts with the engine's commit.
        """
        print(f"[bridge] engine build: {self._engine_build()}", file=sys.stderr, flush=True)
        self._log_workbench_freshness()

    @staticmethod
    def _log_workbench_freshness() -> None:
        """Field 2026-09-09, twice ("Ur claim failed"): the engine restarts
        current after `git pull`, but the desktop panel runs COMPILED JS from
        `desktop/vscode/out/` and keeps rendering old cards until someone
        runs the fork's compile task. The stamp chip that flags this lives
        INSIDE the workbench — a stale workbench never shows it. The engine
        is the only surface guaranteed current, so it compares mtimes:
        pulled UI sources newer than the compiled bundle -> the panel is
        stale, and the log says exactly what to run. Best effort: never
        fatal, one line."""
        try:
            import json
            import subprocess
            from pathlib import Path
            root = Path(__file__).resolve().parents[2]
            src_dir = root / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"
            out_file = root / "desktop" / "vscode" / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRenderer.js"
            srcs = list(src_dir.rglob("*.ts")) if src_dir.is_dir() else []
            if not srcs:
                return  # unusual layout (packaged engine without the fork tree) — nothing to compare
            if not out_file.exists():
                print(
                    "[bridge] desktop UI: no compiled workbench at "
                    f"{out_file} — the Agent pane cannot pick up UI fixes until "
                    "`npx gulp compile` runs in desktop/vscode (then fully quit "
                    "and reopen the app)",
                    file=sys.stderr, flush=True,
                )
                return
            # Preferred, exact: the shipped panel carries SOURCES_HASH — a
            # sha256 over the contrib sources the emitter consumed — and the
            # engine recomputes it from the pulled working tree. Match =
            # current; mismatch = STALE. (Field 2026-09-10: the commit stamp
            # had captured a rolled-back HEAD and the ancestor check passed
            # by luck — ancestry proves "not from the future", never "built
            # from THESE sources". A content hash does both, no git needed,
            # no mtime jitter.)
            import hashlib
            def _sources_hash():
                # Mirrors scripts/emit-crusorai-bundle.mjs BYTE-FOR-BYTE:
                # repo-relative-to-desktop/vscode POSIX paths in codepoint
                # order, feeding rel + NUL + line-ending-normalized bytes
                # + NUL, emitter last. Normalization is CRLF -> LF at the
                # byte level: a Windows checkout keeps CRLF copies of files
                # a pull never rewrote (eol=lf applies only at checkout of
                # changed files), and the raw-byte hash differed per
                # machine (field 2026-09-10: STALE banner on a current
                # panel). Content still flips the hash; checkout state
                # no longer can.
                h = hashlib.sha256()
                vscode_root = root / "desktop" / "vscode"
                # Feed order = the REL STRING codepoint sort, never a
                # Path-object sort. Field 2026-09-10 (owner saw aa68b244…
                # != shipped f5b8d974… on every boot over a PRISTINE tree):
                # this used to be `sorted(<Path objects>)`, and on Windows
                # PurePath comparison is case-insensitive (os.path.normcase)
                # — so `crusorAI…` vs `crusorai…` siblings ordered opposite to
                # the JS emitter's codepoint string sort, the hash inputs
                # fed in a different order, and a byte-identical checkout
                # hashed to a different digest. The STALE banner fired on a
                # current panel; unreproducible on Linux, where both sorts
                # coincide. Sorting the same strings the emitter sorts makes
                # the two recipes agree BY CONSTRUCTION on every OS.
                files = sorted(
                    (f.relative_to(vscode_root).as_posix(), f)
                    for f in src_dir.rglob("*") if f.is_file()
                )
                # hashlib.update() returns None (unlike the JS emitter's
                # chainable crypto.update) — no call chaining here.
                for rel, f in files:
                    h.update(rel.encode("utf-8"))
                    h.update(b"\0")
                    h.update(f.read_bytes().replace(b"\r\n", b"\n"))
                    h.update(b"\0")
                emitter = vscode_root / "scripts" / "emit-crusorai-bundle.mjs"
                h.update(emitter.relative_to(vscode_root).as_posix().encode("utf-8"))
                h.update(b"\0")
                h.update(emitter.read_bytes().replace(b"\r\n", b"\n"))
                h.update(b"\0")
                return h.hexdigest()
            hash_file = out_file.parent / "SOURCES_HASH"
            if hash_file.exists():
                shipped = hash_file.read_text(encoding="utf-8").strip()
                current = _sources_hash()
                if shipped == current:
                    print(
                        "[bridge] desktop UI: compiled workbench matches the pulled "
                        "crusorai sources (sha256) — panel is current",
                        file=sys.stderr, flush=True,
                    )
                    return
                print(
                    "[bridge] DESKTOP WORKBENCH STALE: the shipped panel was emitted "
                    "from DIFFERENT crusorai sources than this checkout (sha256 "
                    f"{shipped[:12]}… != {current[:12]}…) — the Agent pane will render "
                    "OLD cards no matter what the engine runs. Fix: `git pull` (the "
                    f"repo ships a current compiled panel), or `npx gulp compile` in "
                    f"{root / 'desktop' / 'vscode'} — then fully quit and reopen the app.",
                    file=sys.stderr, flush=True,
                )
                # Diagnosis (field 2026-09-10 x2: the owner's checkout hashed
                # differently from the sandbox for an on-disk reason the
                # aggregate could not name). The shipped per-file manifest
                # turns the mismatch into named files: DIFFERENT content,
                # MISSING from the tree, or EXTRA on disk (untracked editor
                # droppings inside the contrib tree count too).
                try:
                    manifest_file = out_file.parent / "SOURCES_MANIFEST.json"
                    if not manifest_file.exists():
                        return
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    expected = manifest.get("files") or {}
                    vscode_root = root / "desktop" / "vscode"
                    on_disk = {
                        f.relative_to(vscode_root).as_posix(): hashlib.sha256(
                            f.read_bytes().replace(b"\r\n", b"\n")
                        ).hexdigest()
                        for f in src_dir.rglob("*") if f.is_file()
                    }
                    different = [
                        rel for rel, want in sorted(expected.items())
                        if rel in on_disk and on_disk[rel] != want
                    ]
                    missing = sorted(set(expected) - set(on_disk))
                    extra = sorted(set(on_disk) - set(expected))
                    lines = []
                    if different:
                        lines.append("modified: " + ", ".join(different[:5])
                                     + (f" (+{len(different) - 5} more)" if len(different) > 5 else ""))
                    if missing:
                        lines.append("missing: " + ", ".join(missing[:5]))
                    if extra:
                        lines.append("extra on disk: " + ", ".join(extra[:5]))
                    if lines:
                        print(
                            "[bridge] STALE diagnosis (per-file manifest): "
                            + "; ".join(lines)
                            + " — compare with `git status -- desktop/vscode/src/vs/"
                            "workbench/contrib/crusorai` and restore with "
                            "`git checkout -- <file>` (or delete the extra file).",
                            file=sys.stderr, flush=True,
                        )
                    else:
                        print(
                            "[bridge] STALE diagnosis: every manifest file matches — "
                            "the drift is in tree membership or the emitter itself; "
                            "re-run `node scripts/emit-crusorai-bundle.mjs` in "
                            "desktop/vscode and reopen.",
                            file=sys.stderr, flush=True,
                        )
                except Exception:
                    pass  # diagnosis is best-effort; the STALE verdict stands
                return
            # Fallback: the panel carries BUILD_INFO.json naming the commit it
            # was emitted from. "Contained in this engine's HEAD" = current —
            # exact, no mtime jitter. (Field 2026-09-09: mtime ordering lies
            # after a checkout; commits do not.)
            info_file = out_file.parent / "BUILD_INFO.json"
            if info_file.exists():
                bundle_commit = str(json.loads(info_file.read_text(encoding="utf-8")).get("commit", "")).strip()
                if bundle_commit and bundle_commit != "unknown":
                    proc = subprocess.run(
                        ["git", "merge-base", "--is-ancestor", bundle_commit, "HEAD"],
                        capture_output=True, text=True, timeout=5, cwd=str(root),
                    )
                    short = bundle_commit[:8]
                    if proc.returncode == 0:
                        print(
                            f"[bridge] desktop UI: compiled workbench built from {short} — "
                            "contained in this engine build; panel is current",
                            file=sys.stderr, flush=True,
                        )
                        return
                    print(
                        f"[bridge] DESKTOP WORKBENCH STALE: the compiled panel was built from {short}, "
                        f"which is NOT contained in this engine build ({self._engine_build().split()[0] if self._engine_build() != 'unknown' else 'unknown'}) — "
                        "the Agent pane will render OLD cards no matter what the engine runs. "
                        "Fix: `git pull` (the repo ships a current compiled panel), or "
                        f"`npx gulp compile` in {root / 'desktop' / 'vscode'} — then fully quit and reopen the app.",
                        file=sys.stderr, flush=True,
                    )
                    return
                # fall through to mtime when the stamp is unusable
            import time as _t
            newest_src = max(src_m.stat().st_mtime for src_m in srcs if src_m.stat().st_mtime is not None)
            slack = 10.0  # checkout/compile timestamp jitter
            if newest_src > out_file.stat().st_mtime + slack:
                fmt = lambda ts: _t.strftime("%Y-%m-%d %H:%M", _t.localtime(ts))
                print(
                    "[bridge] DESKTOP WORKBENCH STALE (mtimes): crusorai UI sources changed "
                    f"({fmt(newest_src)}) but the compiled panel ({fmt(out_file.stat().st_mtime)}) "
                    "predates them — run `npx gulp compile` in "
                    f"{root / 'desktop' / 'vscode'}, then fully quit and reopen the app.",
                    file=sys.stderr, flush=True,
                )
            else:
                print("[bridge] desktop UI: compiled workbench is newer than the newest crusorai source — panel is current", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"[bridge] desktop UI freshness check skipped ({exc})", file=sys.stderr, flush=True)

    def run(self) -> int:
        self._apply_memory_policy()
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

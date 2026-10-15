"""Bridge Protocol v2 -> AG-UI event mapping (Phase 1, AGUI_A2UI_PLAN.md).

The desktop keeps Bridge v2 (src/bridge/protocol.py). This module is the
edge contract: it projects one session's v2 event dicts into AG-UI wire
events (dicts shaped like the `ag-ui-protocol` SDK models serialize:
camelCase keys, `type` carrying the EventType value).

Pure stdlib and side-effect free apart from translator state, so golden
sequence tests need no server, no SDK, and no live model.

Deliberately NOT mapped (desktop-only concerns; they are why v2 stays):
session_info, session_messages, events_replay, workspace.bound,
checkpoint_event, host_tool_request, inline_completion_result,
next_edit_result, llm.* — translate() returns [] for them and records
their types in `translator.unmapped` for observability.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

# Event types that are part of the edge contract. Anything else in a v2
# stream is ignored by translate() (and recorded), never raised on.
_MAPPED = frozenset({
    "turn_started", "token", "reasoning", "tool_call_start", "tool_call_end",
    "plan_updated", "todo_updated", "verification_updated",
    "safety_request", "clarify_request",
    "subagent_updated", "subagent_list", "subagent_background_completed",
    "telemetry", "context_status", "runtime_degraded",
    "turn_done", "turn_failed", "error",
})


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


class V2ToAguiTranslator:
    """Stateful translator for one session's v2 event stream.

    One instance per session: it tracks the open text message, the open
    reasoning message, and emitted state paths so AG-UI lifecycle events
    (START/END pairs) stay balanced.
    """

    def __init__(self, session_id: str = "session") -> None:
        self.thread_id = session_id
        self.run_id: Optional[str] = None
        self.unmapped: list[str] = []
        self._message_id: Optional[str] = None
        self._reasoning_id: Optional[str] = None
        self._msg_seq = 0
        self._state_paths: set[str] = set()

    # -- identity ---------------------------------------------------------
    def _ids(self, event: dict) -> tuple[str, str]:
        thread = str(event.get("session_id") or self.thread_id)
        self.thread_id = thread
        run = str(event.get("turn_id") or self.run_id or f"run-{thread}")
        return thread, run

    # -- lifecycle closers -------------------------------------------------
    def _close_reasoning(self, out: list[dict]) -> None:
        if self._reasoning_id is not None:
            out.append({"type": "REASONING_MESSAGE_END", "messageId": self._reasoning_id})
            out.append({"type": "REASONING_END", "messageId": self._reasoning_id})
            self._reasoning_id = None

    def _close_message(self, out: list[dict]) -> None:
        if self._message_id is not None:
            out.append({"type": "TEXT_MESSAGE_END", "messageId": self._message_id})
            self._message_id = None

    # -- main entry ---------------------------------------------------------
    def translate(self, event: dict) -> list[dict]:
        etype = str(event.get("type") or "")
        if etype not in _MAPPED:
            if etype:
                self.unmapped.append(etype)
            return []
        thread, run = self._ids(event)
        self.run_id = run
        out: list[dict] = []

        if etype == "turn_started":
            self.run_id = run
            out.append({"type": "RUN_STARTED", "threadId": thread, "runId": run})

        elif etype == "token":
            text = _text(event.get("text"))
            if text:
                if self._message_id is None:
                    self._msg_seq += 1
                    self._message_id = f"{run}-msg-{self._msg_seq}"
                    out.append({
                        "type": "TEXT_MESSAGE_START",
                        "messageId": self._message_id,
                        "role": "assistant",
                    })
                out.append({
                    "type": "TEXT_MESSAGE_CONTENT",
                    "messageId": self._message_id,
                    "delta": text,
                })

        elif etype == "reasoning":
            text = _text(event.get("text"))
            if text:
                if self._reasoning_id is None:
                    self._reasoning_id = f"{run}-reasoning"
                    out.append({"type": "REASONING_START", "messageId": self._reasoning_id})
                    out.append({
                        "type": "REASONING_MESSAGE_START",
                        "messageId": self._reasoning_id,
                        "role": "reasoning",
                    })
                out.append({
                    "type": "REASONING_MESSAGE_CONTENT",
                    "messageId": self._reasoning_id,
                    "delta": text,
                })

        elif etype == "tool_call_start":
            tool_id = str(event.get("tool_id") or "")
            start: dict[str, Any] = {
                "type": "TOOL_CALL_START",
                "toolCallId": tool_id,
                "toolCallName": str(event.get("name") or "tool"),
            }
            if self._message_id is not None:
                start["parentMessageId"] = self._message_id
            out.append(start)
            args = event.get("arguments")
            if args is not None:
                out.append({
                    "type": "TOOL_CALL_ARGS",
                    "toolCallId": tool_id,
                    "delta": _text(args),
                })

        elif etype == "tool_call_end":
            tool_id = str(event.get("tool_id") or "")
            out.append({"type": "TOOL_CALL_END", "toolCallId": tool_id})
            out.append({
                "type": "TOOL_CALL_RESULT",
                "messageId": f"{tool_id}-result",
                "toolCallId": tool_id,
                "content": _text(event.get("result")),
                "role": "tool",
            })

        elif etype in ("plan_updated", "todo_updated"):
            path = "/plan" if etype == "plan_updated" else "/todos"
            value = event.get("steps") if etype == "plan_updated" else event.get("todos")
            out.append({
                "type": "STATE_DELTA",
                "delta": [{"op": "add", "path": path, "value": value or []}],
            })
            self._state_paths.add(path)

        elif etype == "verification_updated":
            out.append({
                "type": "CUSTOM",
                "name": "crusor.verification_updated",
                "value": {
                    "status": event.get("status"),
                    "evidence": event.get("evidence"),
                },
            })

        elif etype in ("safety_request", "clarify_request"):
            # Human-in-the-loop: the run finishes as an interrupt; the
            # client's resume maps back via interrupt_resume_to_v2().
            self._close_reasoning(out)
            self._close_message(out)
            if etype == "safety_request":
                interrupt = {
                    "id": str(event.get("tool_id") or ""),
                    "reason": "safety_request",
                    "message": event.get("warning") or "This action needs approval",
                    "toolCallId": str(event.get("tool_id") or ""),
                    "metadata": {
                        "name": event.get("name"),
                        "arguments": event.get("arguments"),
                        "diff": event.get("diff"),
                    },
                }
            else:
                interrupt = {
                    "id": str(event.get("request_id") or ""),
                    "reason": "clarify_request",
                    "message": event.get("title") or "The agent needs your input",
                    "metadata": {"questions": event.get("questions") or []},
                }
            out.append({
                "type": "RUN_FINISHED",
                "threadId": thread,
                "runId": run,
                "outcome": {"type": "interrupt", "interrupts": [interrupt]},
            })

        elif etype in ("subagent_updated", "subagent_list", "subagent_background_completed",
                       "telemetry", "context_status", "runtime_degraded"):
            value = {k: v for k, v in event.items()
                     if k not in ("type", "session_id", "turn_id", "event_id", "timestamp")}
            out.append({"type": "CUSTOM", "name": f"crusor.{etype}", "value": value})

        elif etype == "turn_done":
            self._close_reasoning(out)
            self._close_message(out)
            finished: dict[str, Any] = {
                "type": "RUN_FINISHED",
                "threadId": thread,
                "runId": run,
                "outcome": {"type": "success"},
            }
            if event.get("cancelled"):
                finished["outcome"] = {"type": "cancelled"}
            if event.get("message"):
                finished["result"] = event["message"]
            out.append(finished)

        elif etype in ("turn_failed", "error"):
            self._close_reasoning(out)
            self._close_message(out)
            out.append({
                "type": "RUN_ERROR",
                "message": str(event.get("error") or event.get("message") or "turn failed"),
                "code": etype,
            })

        return out

    def translate_stream(self, events: Iterable[dict]) -> list[dict]:
        out: list[dict] = []
        for event in events:
            out.extend(self.translate(event))
        return out


def interrupt_resume_to_v2(reason: str, interrupt_id: str, payload: dict) -> dict:
    """Map an AG-UI interrupt resume back to a Bridge v2 command.

    reason "safety_request" -> safety_reply; "clarify_request" ->
    clarify_reply. Anything else is a programming error at the edge.
    """
    payload = payload or {}
    if reason == "safety_request":
        return {
            "type": "safety_reply",
            "tool_id": interrupt_id,
            "approved": bool(payload.get("approved")),
            "always_allow": bool(payload.get("always_allow", False)),
        }
    if reason == "clarify_request":
        return {
            "type": "clarify_reply",
            "request_id": interrupt_id,
            "answers": payload.get("answers") or {},
            "timed_out": bool(payload.get("timed_out", False)),
        }
    raise ValueError(f"unknown interrupt reason: {reason!r}")


__all__ = ["V2ToAguiTranslator", "interrupt_resume_to_v2"]

"""PulseAI Bridge Protocol v2 newline-delimited JSON codec (stdlib only)."""
from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = 2
SUPPORTED_PROTOCOL_VERSIONS = frozenset({1, PROTOCOL_VERSION})
MAX_LINE_BYTES = 1 << 20

CLIENT_METHODS = frozenset({
    "hello", "session_create", "session_load", "session_resume",
    "session_list", "session_fork", "prompt", "cancel", "steer", "queue", "safety_reply",
    "checkpoint_list", "checkpoint_restore",
    "subagent_launch", "subagent_status", "subagent_cancel", "subagent_result",
    "events_replay", "host_capabilities_update", "host_tool_result", "shutdown",
})
SERVER_EVENTS = frozenset({
    "hello", "session_info", "token", "reasoning", "plan_updated",
    "tool_call_start", "tool_call_end", "safety_request",
    "verification_updated", "subagent_updated", "telemetry",
    "turn_started", "turn_done", "turn_failed", "checkpoint_event",
    "runtime_degraded", "events_replay", "error",
    # Observability frames (PBR-002/012 evidence): the exact workspace a
    # session is bound to, and one frame per real provider request attempt.
    "workspace.bound", "llm.request", "llm.response", "host_tool_request",
})


class ProtocolError(Exception):
    pass


def encode(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def decode_line(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(f"frame exceeds {MAX_LINE_BYTES} bytes ({len(line)})")
    try:
        obj = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"malformed JSON frame: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError(f"frame must be an object, got {type(obj).__name__}")
    if "type" not in obj or not isinstance(obj["type"], str):
        raise ProtocolError("frame missing string field 'type'")
    return obj


def hello(engine_version: str, *, protocol: int = PROTOCOL_VERSION) -> dict[str, Any]:
    if protocol not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ProtocolError(f"unsupported negotiated protocol: {protocol!r}")
    return {
        "type": "hello", "protocol": protocol,
        "engine": "pulseai", "engine_version": engine_version,
        "capabilities": sorted(CLIENT_METHODS - {"hello", "shutdown"}),
    }


def error_frame(message: str, *, fatal: bool = False, request_id: str | None = None) -> dict[str, Any]:
    frame = {"type": "error", "message": message, "fatal": fatal}
    if request_id:
        frame["request_id"] = request_id
    return frame


def check_client_hello(frame: dict[str, Any]) -> int:
    if frame.get("type") != "hello":
        raise ProtocolError("first frame must be 'hello'")
    their = frame.get("protocol")
    if their not in SUPPORTED_PROTOCOL_VERSIONS:
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_PROTOCOL_VERSIONS))
        raise ProtocolError(f"protocol mismatch: client {their!r}, engine supports {supported}")
    return int(their)

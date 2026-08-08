"""Bridge protocol v1 codec — stdlib only, no engine imports.

Keep this module dependency-free: the fork spawns the bridge before any
engine init, and a codec that can't import can't wedge the handshake.
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = 1

# Hard bound so a wedged/malicious peer cannot OOM the sidecar with an
# endless line. 1 MiB is generous for any legitimate frame (prompts,
# safety payloads) and cheap to enforce.
MAX_LINE_BYTES = 1 << 20

CLIENT_METHODS = frozenset({"hello", "prompt", "safety_reply", "shutdown"})
SERVER_EVENTS = frozenset({
    "hello", "token", "tool_call_start", "tool_call_end",
    "safety_request", "telemetry", "turn_done", "checkpoint_event",
    "echo", "error",
})


class ProtocolError(Exception):
    """Raised for malformed, oversize, or version-mismatched frames."""


def encode(obj: dict[str, Any]) -> bytes:
    """One object -> one newline-terminated line (UTF-8)."""
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def decode_line(line: bytes) -> dict[str, Any]:
    """One raw line -> validated frame dict. Raises ProtocolError."""
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(
            f"frame exceeds {MAX_LINE_BYTES} bytes ({len(line)})"
        )
    try:
        obj = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"malformed JSON frame: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError(f"frame must be an object, got {type(obj).__name__}")
    if "type" not in obj or not isinstance(obj["type"], str):
        raise ProtocolError("frame missing string field 'type'")
    return obj


def hello(engine_version: str) -> dict[str, Any]:
    """The handshake frame the server sends in reply to client hello."""
    return {
        "type": "hello",
        "protocol": PROTOCOL_VERSION,
        "engine": "pulseai",
        "engine_version": engine_version,
    }


def error_frame(message: str, *, fatal: bool = False) -> dict[str, Any]:
    return {"type": "error", "message": message, "fatal": fatal}


def check_client_hello(frame: dict[str, Any]) -> None:
    """Validate the client's hello; raise ProtocolError on mismatch."""
    if frame.get("type") != "hello":
        raise ProtocolError("first frame must be 'hello'")
    their = frame.get("protocol")
    if their != PROTOCOL_VERSION:
        raise ProtocolError(
            f"protocol mismatch: client {their!r}, engine {PROTOCOL_VERSION}"
        )

"""Bridge sidecar entry point: python -m src.bridge

Stdio loop, newline-delimited JSON-RPC. Deliberately stupid: no engine
state, no threads, no globals — those arrive with M1's prompt wiring.
What ships NOW (P2 Phase 0.4) is the handshake, the echo bus, and the
wired-shape honest stub for `prompt` so the fork can build its UI
against real frames while the engine streaming hookup lands.

NEVER crashes on malformed input: bad frames become error frames and
the loop continues (the fork's renderer must not lose its engine
because one message was shaped wrong).
"""

from __future__ import annotations

import sys

from src.bridge.protocol import (
    CLIENT_METHODS,
    ProtocolError,
    check_client_hello,
    decode_line,
    encode,
    error_frame,
    hello,
)

ENGINE_VERSION = "0.1.0-p2-bridge"


def _emit(obj: dict) -> None:
    sys.stdout.buffer.write(encode(obj))
    sys.stdout.buffer.flush()


def handle(frame: dict, *, greeted: bool) -> dict | None:
    """One validated client frame -> the reply frame (or None)."""
    t = frame["type"]
    if t not in CLIENT_METHODS:
        return error_frame(f"unknown method: {t!r}")
    if t == "hello":
        if greeted:
            return error_frame("duplicate hello")
        check_client_hello(frame)  # raises on mismatch
        return hello(ENGINE_VERSION)
    if not greeted:
        return error_frame("hello handshake required first")
    if t == "shutdown":
        return None  # caller breaks the loop
    if t == "prompt":
        # M1 shape-stub: the real stream_agent wiring lands with the
        # fork's chat view. Honesty > pretending: the fork learns from
        # this flag that the stub answered, not the engine.
        return {
            "type": "turn_done",
            "stub": True,
            "thread_id": str(frame.get("thread_id", "")),
            "message": "bridge alive; engine wiring lands with M1 chat view",
        }
    if t == "safety_reply":
        return error_frame("no safety_request pending (stub bridge)")
    return error_frame(f"unhandled method: {t!r}")


def main() -> int:
    greeted = False
    while True:
        line = sys.stdin.buffer.readline()
        if not line:  # EOF: the fork closed the pipe
            return 0
        try:
            frame = decode_line(line)
            reply = handle(frame, greeted=greeted)
            if frame.get("type") == "hello" and reply is not None and reply.get("type") == "hello":
                greeted = True
        except ProtocolError as exc:
            _emit(error_frame(str(exc)))
            continue
        except Exception as exc:  # codec bugs must not kill the sidecar
            _emit(error_frame(f"bridge internal error: {exc!r}"))
            continue
        if reply is None:
            return 0  # shutdown
        _emit(reply)


if __name__ == "__main__":
    raise SystemExit(main())

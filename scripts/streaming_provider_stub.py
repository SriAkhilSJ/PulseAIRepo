#!/usr/bin/env python3
"""Deterministic OpenAI-compatible streaming provider for Crusor tests.

This is a *transport fixture*, not a model: it speaks the real OpenAI wire
protocol (SSE ``chat.completion.chunk`` frames, usage on the final chunk) so the
real ``ChatOpenAI`` client, the real ModelGateway and the real engineering
adapter can be exercised without any paid request.

Usage:
    python scripts/streaming_provider_stub.py --port 8199 --chunk-delay-ms 120

Endpoints:
    POST /v1/chat/completions   (stream=true -> SSE, stream=false -> JSON)
    GET  /v1/models
    GET  /health

Env/args that matter for tests:
    --content       fixed completion content (skips prompt inference)
    --chunks        number of SSE deltas to split the content into
    --chunk-delay-ms  delay between deltas (simulates a slow provider)
    --fail-after    abort the SSE stream after N deltas (transport failure)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple


def _prompt_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return str(messages or "")
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(block.get("text") or "") for block in content if isinstance(block, dict)
            )
    return ""


_TARGET_RE = re.compile(r"Target file(?: path)?:\s*([^\s`'\"]+)", re.IGNORECASE)
_SYMBOL_RE = re.compile(r"Required public symbol\(s\):\s*([A-Za-z_][\w, ]*)", re.IGNORECASE)


def infer_content(prompt: str, override: str | None) -> str:
    if override:
        return override
    match = _TARGET_RE.search(prompt)
    target = (match.group(1) if match else "").lower()
    symbols = []
    sym = _SYMBOL_RE.search(prompt)
    if sym:
        symbols = [s.strip() for s in sym.group(1).split(",") if s.strip()]
    if target.endswith((".py", ".ts", ".js")):
        name = symbols[0] if symbols else "run"
        if "divide" in prompt.lower() or name == "divide":
            body = (
                "def divide(a, b):\n"
                "    if b == 0:\n"
                '        raise ZeroDivisionError("division by zero")\n'
                "    return a / b\n"
            )
        elif "clamp" in prompt.lower() or name == "clamp":
            body = (
                "def clamp(value, minimum, maximum):\n"
                "    if minimum > maximum:\n"
                '        raise ValueError("minimum exceeds maximum")\n'
                "    return max(minimum, min(value, maximum))\n"
            )
        else:
            body = f'def {name}():\n    return "ok"\n'
        return f"```python\n{body}```"
    if target.endswith(".md"):
        return "# Notes\n\nHello from the streaming provider stub.\n"
    return "Done."


def split_content(content: str, chunks: int) -> List[str]:
    if chunks <= 1 or len(content) <= 1:
        return [content]
    size = max(1, len(content) // chunks)
    parts = [content[i:i + size] for i in range(0, len(content), size)]
    return parts or [content]


class State:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.lock = threading.Lock()
        self.requests = 0
        self.failures = 0


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: State

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        print(f"[stub] {fmt % args}", file=sys.stderr, flush=True)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        if self.path.rstrip("/").endswith("/v1/models"):
            self._send_json(200, {"object": "list", "data": [{"id": self.state.args.model, "object": "model"}]})
            return
        if self.path.rstrip("/").endswith("/health"):
            self._send_json(200, {"ok": True, "requests": self.state.requests})
            return
        self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": {"message": "invalid json"}})
            return
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send_json(404, {"error": {"message": "not found"}})
            return

        with self.state.lock:
            self.state.requests += 1

        messages = request.get("messages") or []
        prompt = _prompt_text(messages)
        content = infer_content(prompt, self.state.args.content)
        stream = bool(request.get("stream"))
        usage = {
            "prompt_tokens": max(1, len(prompt) // 4),
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": max(1, len(prompt) // 4) + max(1, len(content) // 4),
        }
        completion_id = f"chatcmpl-stub-{self.state.requests}"
        created = int(time.time())

        if not stream:
            self._send_json(200, {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": request.get("model") or self.state.args.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }],
                "usage": usage,
            })
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def frame(payload: Dict[str, Any]) -> None:
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
            self.wfile.flush()

        base = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": request.get("model") or self.state.args.model,
        }
        try:
            frame({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
            parts = split_content(content, max(1, int(self.state.args.chunks)))
            fail_after = int(self.state.args.fail_after or 0)
            for index, part in enumerate(parts):
                if fail_after and index >= fail_after:
                    # Abrupt transport death: no finish chunk, no [DONE].
                    with self.state.lock:
                        self.state.failures += 1
                    return
                if self.state.args.chunk_delay_ms:
                    time.sleep(self.state.args.chunk_delay_ms / 1000.0)
                frame({**base, "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]})
            frame({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            # OpenAI sends a usage-only chunk when stream_options.include_usage
            # is set; the real client merges it into the final message.
            frame({**base, "choices": [], "usage": usage})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            with self.state.lock:
                self.state.failures += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8199)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model", default="z-ai/glm-5.3-flash")
    parser.add_argument("--content", default=None)
    parser.add_argument("--chunks", type=int, default=24)
    parser.add_argument("--chunk-delay-ms", type=int, default=80)
    parser.add_argument("--fail-after", type=int, default=0)
    args = parser.parse_args()

    Handler.state = State(args)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[stub] listening on http://{args.host}:{args.port}/v1 (chunks={args.chunks}, delay={args.chunk_delay_ms}ms)", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

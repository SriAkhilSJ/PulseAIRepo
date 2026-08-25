"""Minimal OpenAI-compatible stub provider for LOCAL, keyless engine runs.

Returns a fixed assistant reply with valid usage. Used to attribute which
engine subsystems make provider calls (planner / main / aux / reflection)
without spending a single credit. NOT product evidence — a test lane only.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        body = {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": 0,
            "model": "stub-1",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "{\"action\": \"continue\", \"updated_task\": \"Explain workspace_proof.py\"}"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        }
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()

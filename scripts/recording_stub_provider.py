"""Recording OpenAI-compatible stub provider for LOCAL, keyless engine runs.

Extends the idea of scripts/stub_provider_server.py with two abilities needed
for wire-level verification:

1. RECORDS every request body (JSONL) so a test can assert exactly what the
   engine put on the wire -- e.g. that the per-turn ``reasoning_effort`` pick
   actually reached the provider request.
2. Behaves enough like a real endpoint for ONE full agent turn:
   - GET /models            -> model metadata (context window probe)
   - POST /chat/completions -> TaskDecision classifier replies, then a scripted
     write_file tool call, then a wrap-up answer.
   - POST /embeddings       -> tiny deterministic vectors (defensive).

NOT product evidence about model quality -- a test lane only. Zero credits.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RECORD_LOCK = threading.Lock()
RECORD_PATH: Path | None = None
MAIN_CALLS = 0


def record(path: str, body: dict) -> None:
    if RECORD_PATH is None:
        return
    line = json.dumps({"ts": time.time(), "path": path, "body": body}, ensure_ascii=False)
    with RECORD_LOCK:
        with RECORD_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _is_task_classifier(body: dict) -> bool:
    rf = body.get("response_format") or {}
    schema = rf.get("json_schema") or {}
    return schema.get("name") == "TaskDecision" or rf.get("name") == "TaskDecision"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/v1/models", "/models"):
            self._send_json({
                "object": "list",
                "data": [{
                    "id": "stub-model", "object": "model", "owned_by": "stub",
                    "context_window": 131072, "context_length": 131072,
                    "max_position_embeddings": 131072,
                }],
            })
        else:
            self._send_json({"error": {"message": f"no GET route {p}"}}, 404)

    def do_POST(self):
        global MAIN_CALLS
        p = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except Exception:
            body = {"_unparseable": raw[:2000].decode("utf-8", "replace")}
        record(p, body)

        if p in ("/v1/chat/completions", "/chat/completions"):
            if _is_task_classifier(body):
                content = json.dumps({
                    "action": "execute",
                    "updated_task": "Write the one-line proof file",
                })
            else:
                MAIN_CALLS += 1
                if MAIN_CALLS == 1:
                    # First main call: answer + scripted workspace write.
                    payload = {
                        "id": "chatcmpl-rec-1", "object": "chat.completion",
                        "created": 0, "model": "stub-model",
                        "choices": [{
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Writing the proof file now.",
                                "tool_calls": [{
                                    "id": "call_rec_stub_1",
                                    "type": "function",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": json.dumps({
                                            "path": "proof_reasoning_effort.txt",
                                            "content": "reasoning_effort reached the provider request\n",
                                        }),
                                    },
                                }],
                            },
                            "finish_reason": "tool_calls",
                        }],
                        "usage": {"prompt_tokens": 500, "completion_tokens": 20, "total_tokens": 520},
                    }
                    self._send_json(payload)
                    return
                payload = {
                    "id": "chatcmpl-rec-2", "object": "chat.completion",
                    "created": 0, "model": "stub-model",
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Done: wrote proof_reasoning_effort.txt with the proof line.",
                        },
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 600, "completion_tokens": 15, "total_tokens": 615},
                }
                self._send_json(payload)
                return
            payload = {
                "id": "chatcmpl-rec-classifier", "object": "chat.completion",
                "created": 0, "model": "stub-model",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            }
            self._send_json(payload)
        elif p in ("/v1/embeddings", "/embeddings"):
            inputs = body.get("input") or []
            if isinstance(inputs, str):
                inputs = [inputs]
            self._send_json({
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.1] * 8}
                    for i in range(len(inputs))
                ],
                "model": "stub-embed",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            })
        else:
            self._send_json({"error": {"message": f"no POST route {p}"}}, 404)


def main() -> int:
    global RECORD_PATH
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    if len(sys.argv) > 2:
        RECORD_PATH = Path(sys.argv[2]).resolve()
        RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"recording stub on http://127.0.0.1:{port} -> {RECORD_PATH}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

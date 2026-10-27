from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from benchmarks.colibri_agent_core import probe


def _server(*, model_id: str = "qwen3.6-colibri", published_context: int | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def _send(self, body: dict, status: int = 200):
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path == "/health":
                self._send({"status": "ready", "model_id": model_id, "arch": "qwen36"})
                return
            if self.path == "/v1/models":
                entry = {
                    "id": model_id,
                    "object": "model",
                    "capabilities": ["chat", "systemone"],
                }
                if published_context is not None:
                    entry["context_window"] = published_context
                self._send({"object": "list", "data": [entry]})
                return
            self._send({"error": "not found"}, status=404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length))
            messages = body["messages"]
            content = str(messages[-1].get("content") or "")
            message: dict
            finish = "stop"
            if body.get("tools"):
                nonce = re.search(r"probe-[0-9a-f]+", content).group(0)
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-probe",
                            "type": "function",
                            "function": {
                                "name": "report_colibri_probe",
                                "arguments": json.dumps(
                                    {"nonce": nonce, "status": "ready"}
                                ),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            elif messages[-1].get("role") == "tool":
                assert "After the tool result arrives" in messages[0]["content"]
                assert (
                    messages[1]["tool_calls"][0]["id"] == messages[-1]["tool_call_id"]
                )
                receipt = json.loads(content)["receipt"]
                message = {"role": "assistant", "content": f"confirmed {receipt}"}
            elif "PULSEAI_COLIBRI_READY_" in content:
                sentinel = re.search(r"PULSEAI_COLIBRI_READY_[0-9a-f]+", content).group(
                    0
                )
                message = {"role": "assistant", "content": sentinel}
            elif "START_" in content and "END_" in content:
                start = re.search(r"START_[0-9a-f]+", content).group(0)
                end = re.search(r"END_[0-9a-f]+", content).group(0)
                message = {"role": "assistant", "content": f"{start} {end}"}
            else:
                message = {"role": "assistant", "content": "unexpected"}
            self._send(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "choices": [
                        {"index": 0, "message": message, "finish_reason": finish}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_probe_exercises_health_chat_tools_round_trip_and_context(tmp_path):
    server, thread = _server()
    output = tmp_path / "probe.json"
    secret = "this-key-must-not-be-persisted"
    try:
        code = probe.main(
            [
                "--base-url",
                f"http://127.0.0.1:{server.server_port}/v1",
                "--api-key",
                secret,
                "--model",
                "qwen3.6-colibri",
                "--expected-context",
                "65536",
                "--long-context-tokens",
                "32",
                "--output",
                str(output),
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert code == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["status"] == "passed"
    assert [phase["name"] for phase in receipt["phases"]] == [
        "health",
        "models",
        "basic_chat",
        "forced_tool_call",
        "tool_result_round_trip",
        "long_context",
    ]
    assert all(phase["status"] == "passed" for phase in receipt["phases"])
    models = next(phase for phase in receipt["phases"] if phase["name"] == "models")
    assert models["evidence"]["published_context_window"] is None
    assert models["evidence"]["context_source"] == "runner_configuration"
    assert secret not in output.read_text(encoding="utf-8")
    assert receipt["api_key_present"] is True
    assert receipt["api_key_persisted"] is False


def test_probe_rejects_catalog_context_below_configured_window(tmp_path):
    server, thread = _server(published_context=8192)
    output = tmp_path / "probe.json"
    try:
        code = probe.main(
            [
                "--base-url",
                f"http://127.0.0.1:{server.server_port}/v1",
                "--model",
                "qwen3.6-colibri",
                "--expected-context",
                "65536",
                "--long-context-tokens",
                "0",
                "--output",
                str(output),
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert code == 1
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    models = next(phase for phase in receipt["phases"] if phase["name"] == "models")
    assert models["status"] == "failed"
    assert "below expected 65536" in models["error"]

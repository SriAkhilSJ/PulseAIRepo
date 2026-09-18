"""Logging reverse proxy: records request bodies, forwards to the REAL provider.

Point the engine's CUSTOM_BASE_URL at this proxy; it forwards every request
verbatim (path, auth header, body) to the real OpenAI-compatible endpoint and
records the outgoing body to a JSONL file. Real provider calls, real answers,
zero ambiguity about what actually left the machine.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM = ""
RECORD_PATH: Path | None = None
LOCK = threading.Lock()


def record(path: str, body) -> None:
    if RECORD_PATH is None:
        return
    line = json.dumps({"ts": time.time(), "path": path, "body": body}, ensure_ascii=False)
    with LOCK:
        with RECORD_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        auth = self.headers.get("Authorization") or ""
        req = urllib.request.Request(
            UPSTREAM + self.path, data=raw if raw else None, method=self.command
        )
        if auth:
            req.add_header("Authorization", auth)
        # Forward the caller's User-Agent verbatim: Cloudflare 1010 bans
        # urllib's default signature too, and the engine may carry a UA
        # override (CRUSORAI_HTTP_USER_AGENT) that must survive the hop.
        caller_ua = self.headers.get("User-Agent")
        if caller_ua:
            req.add_header("User-Agent", caller_ua)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", self.headers.get("Accept") or "application/json")
        try:
            if self.command == "POST" and raw:
                try:
                    record(self.path, json.loads(raw))
                except Exception:
                    record(self.path, {"_unparseable": raw[:2000].decode("utf-8", "replace")})
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
        except Exception as exc:
            payload = json.dumps({"error": f"proxy: {type(exc).__name__}: {exc}"}).encode()
            status = 502
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _forward
    do_POST = _forward


def main() -> int:
    global UPSTREAM, RECORD_PATH
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    UPSTREAM = sys.argv[2].rstrip("/")
    if len(sys.argv) > 3:
        RECORD_PATH = Path(sys.argv[3]).resolve()
        RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"proxy 127.0.0.1:{port} -> {UPSTREAM} (record -> {RECORD_PATH})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

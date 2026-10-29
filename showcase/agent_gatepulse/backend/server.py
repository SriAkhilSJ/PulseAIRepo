"""GatePulse - API rate-limiting gateway simulator.

Pure sliding-window rate limiter backed by SQLite (WAL mode), served over the
Python standard-library HTTP server. Zero external dependencies.

Endpoints:
    POST /api/consume   -> 200 accepted | 429 rejected (Retry-After header)
    GET  /api/metrics   -> aggregate counters + per-client breakdown
    POST /api/reset     -> clear all quota state and history
    GET  /api/health    -> liveness probe
    GET  /, /index.html, /styles.css, /app.js -> dashboard static files

Environment overrides:
    GATEPULSE_DB / DB_PATH  - SQLite database file location
    GATEPULSE_HOST          - bind host (default 127.0.0.1)
    GATEPULSE_PORT          - bind port (default 8000)
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = WORKSPACE_ROOT / "frontend"

DEFAULT_LIMIT = 5
DEFAULT_WINDOW_SECONDS = 10.0
MAX_BODY_BYTES = 64 * 1024

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS request_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  TEXT NOT NULL,
    timestamp  REAL NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('accepted', 'rejected'))
);
CREATE INDEX IF NOT EXISTS idx_request_log_client_timestamp
    ON request_log (client_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_request_log_timestamp
    ON request_log (timestamp);
"""


def default_db_path() -> str:
    """Resolve the database location, honoring GATEPULSE_DB / DB_PATH."""
    override = os.environ.get("GATEPULSE_DB") or os.environ.get("DB_PATH")
    if override:
        return override
    data_dir = WORKSPACE_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "gatepulse.db")


class GatePulseGateway:
    """Thread-safe sliding-window rate limiter with SQLite persistence.

    The sliding window is evaluated from the persisted log of *accepted*
    requests, so quota state survives restarts. Rejected requests are logged
    for metrics but never consume quota. A re-entrant write lock plus a
    BEGIN IMMEDIATE transaction makes the evaluate-and-record step atomic, so
    simultaneous requests cannot bypass the limit.
    """

    def __init__(
        self,
        db_path: str | None = None,
        limit: int = DEFAULT_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock=None,
    ) -> None:
        self.db_path = str(db_path) if db_path else default_db_path()
        self.limit = int(limit)
        self.window_seconds = float(window_seconds)
        self.clock = clock or time.time
        self._write_lock = threading.Lock()
        self._init_db()

    # -- plumbing ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
            finally:
                conn.close()

    # -- core operations --------------------------------------------------

    def consume(self, client_id: str) -> dict:
        now = float(self.clock())
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    "SELECT timestamp FROM request_log"
                    " WHERE client_id = ? AND status = 'accepted' AND timestamp > ?"
                    " ORDER BY timestamp ASC",
                    (client_id, now - self.window_seconds),
                ).fetchall()

                if len(rows) < self.limit:
                    conn.execute(
                        "INSERT INTO request_log (client_id, timestamp, status)"
                        " VALUES (?, ?, 'accepted')",
                        (client_id, now),
                    )
                    conn.execute("COMMIT")
                    return {
                        "status": "accepted",
                        "client_id": client_id,
                        "remaining": self.limit - len(rows) - 1,
                        "limit": self.limit,
                        "window_seconds": self.window_seconds,
                    }

                oldest_relevant = rows[0][0]
                retry_after = math.ceil(
                    max(0.0, oldest_relevant + self.window_seconds - now)
                )
                conn.execute(
                    "INSERT INTO request_log (client_id, timestamp, status)"
                    " VALUES (?, ?, 'rejected')",
                    (client_id, now),
                )
                conn.execute("COMMIT")
                return {
                    "status": "rejected",
                    "client_id": client_id,
                    "error": "rate limit exceeded",
                    "retry_after": retry_after,
                    "limit": self.limit,
                    "window_seconds": self.window_seconds,
                }
            finally:
                conn.close()

    def metrics(self) -> dict:
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM request_log").fetchone()[0]
            accepted = conn.execute(
                "SELECT COUNT(*) FROM request_log WHERE status = 'accepted'"
            ).fetchone()[0]
            clients: dict = {}
            for client_id, status, count in conn.execute(
                "SELECT client_id, status, COUNT(*) FROM request_log"
                " GROUP BY client_id, status"
            ).fetchall():
                clients.setdefault(client_id, {"accepted": 0, "rejected": 0})[status] = count
        finally:
            conn.close()
        rejected = total - accepted
        rejection_rate = round((rejected / total) * 100.0, 2) if total else 0.0
        return {
            "total_requests": total,
            "accepted_requests": accepted,
            "rejected_requests": rejected,
            "rejection_rate": rejection_rate,
            "clients": clients,
        }

    def reset(self) -> dict:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM request_log")
            finally:
                conn.close()
        return {"status": "reset", "message": "All quotas and history cleared"}


class GatePulseHandler(BaseHTTPRequestHandler):
    server_version = "GatePulse/1.0"
    protocol_version = "HTTP/1.1"
    quiet = False

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        if self.quiet:
            return
        sys.stderr.write("[gatepulse] %s %s\n" % (self.address_string(), format % args))

    # -- helpers ----------------------------------------------------------

    def _send_json(self, status_code: int, payload: dict, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _body_length(self) -> int:
        try:
            return int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return 0

    def _read_json_body(self) -> dict | None:
        length = self._body_length()
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _drain_body(self) -> None:
        remaining = self._body_length()
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def _serve_static(self, path: str) -> None:
        filename, content_type = STATIC_FILES[path]
        try:
            body = (FRONTEND_DIR / filename).read_bytes()
        except OSError:
            self._send_json(500, {"status": "error", "error": f"missing frontend asset: {filename}"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_consume(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            self._send_json(400, {"status": "error", "error": "request body must be a JSON object"})
            return
        client_id = payload.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip():
            self._send_json(
                400,
                {"status": "error", "error": "client_id is required and must be a non-empty string"},
            )
            return
        result = self.gateway.consume(client_id.strip())
        if result["status"] == "accepted":
            self._send_json(200, result)
        else:
            self._send_json(429, result, {"Retry-After": str(result["retry_after"])})

    # -- routing ----------------------------------------------------------

    def _route_path(self) -> str:
        return urllib.parse.urlsplit(self.path).path

    def do_GET(self) -> None:
        path = self._route_path()
        if path == "/api/metrics":
            self._send_json(200, self.server.gateway.metrics())  # type: ignore[attr-defined]
        elif path == "/api/health":
            self._send_json(200, {"status": "ok"})
        elif path in ("/api/consume", "/api/reset"):
            self._send_json(405, {"status": "error", "error": "method not allowed"})
        elif path in STATIC_FILES:
            self._serve_static(path)
        else:
            self._send_json(404, {"status": "error", "error": f"unknown endpoint: {path}"})

    def do_POST(self) -> None:
        path = self._route_path()
        if path == "/api/consume":
            self._handle_consume()
        elif path == "/api/reset":
            self._drain_body()
            self._send_json(200, self.server.gateway.reset())  # type: ignore[attr-defined]
        elif path in ("/api/metrics", "/api/health"):
            self._send_json(405, {"status": "error", "error": "method not allowed"})
        else:
            self._send_json(404, {"status": "error", "error": f"unknown endpoint: {path}"})


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    gateway: GatePulseGateway | None = None,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    """Build a ThreadingHTTPServer bound to (host, port).

    port=0 lets the OS pick a free port (used by the test suite).
    """
    gw = gateway or GatePulseGateway()
    handler = GatePulseHandler
    if quiet:
        handler = type("QuietGatePulseHandler", (GatePulseHandler,), {"quiet": True})
    httpd = _GatewayServer((host, port), handler)
    httpd.gateway = gw
    return httpd


def main() -> None:
    host = os.environ.get("GATEPULSE_HOST", "127.0.0.1")
    port = int(os.environ.get("GATEPULSE_PORT", "8000"))
    gateway = GatePulseGateway()
    httpd = create_server(host, port, gateway)
    print(f"GatePulse gateway on http://{host}:{port} (db: {gateway.db_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nGatePulse shutting down")
   
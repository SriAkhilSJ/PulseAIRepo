"""PulseTask backend -- a self-contained REST API for task management.

Endpoints:
    GET    /api/health        -> service + database health
    GET    /api/tasks         -> list tasks (optional ?status=todo|doing|done)
    POST   /api/tasks         -> create task        {"title": str, "status": str}
    PATCH  /api/tasks/<id>    -> update task        {"title": str, "status": str}
    DELETE /api/tasks/<id>    -> delete task
    GET    /api/stats         -> {"total": n, "todo": n, "doing": n, "done": n}

Persistence: SQLite (file on disk when run as a server, ``:memory:`` for tests).
The frontend under ../frontend is also served at ``/`` so the whole app runs
from a single process:  python backend/server.py  ->  http://127.0.0.1:8000

Only the Python standard library is used.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VALID_STATUSES = ("todo", "doing", "done")

_STATIC_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}


class TaskStore:
    """Thread-safe SQLite-backed task storage."""

    def __init__(self, db_path: str = ":memory:"):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'todo',
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    def _validate_title(self, title) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        return title.strip()

    def _validate_status(self, status) -> str:
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {list(VALID_STATUSES)}")
        return status

    # -- operations ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def healthcheck(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def list_tasks(self, status: str | None = None) -> list[dict]:
        sql = "SELECT id, title, status, created_at FROM tasks"
        params: tuple = ()
        if status is not None:
            status = self._validate_status(status)
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY id ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, title, status, created_at FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return self._row_to_task(row) if row is not None else None

    def create_task(self, title, status="todo") -> dict:
        title = self._validate_title(title)
        status = self._validate_status(status)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO tasks (title, status, created_at) VALUES (?, ?, ?)",
                (title, status, created_at),
            )
            self._conn.commit()
            task_id = cursor.lastrowid
            row = self._conn.execute(
                "SELECT id, title, status, created_at FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return self._row_to_task(row)

    def update_task(self, task_id: int, fields: dict) -> dict | None:
        updates: dict = {}
        if "title" in fields:
            updates["title"] = self._validate_title(fields["title"])
        if "status" in fields:
            updates["status"] = self._validate_status(fields["status"])
        if not updates:
            raise ValueError(
                "no updatable fields provided (use 'title' and/or 'status')"
            )
        set_sql = ", ".join(f"{column} = ?" for column in updates)
        params = [*updates.values(), task_id]
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE tasks SET {set_sql} WHERE id = ?", params
            )
            self._conn.commit()
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT id, title, status, created_at FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return self._row_to_task(row)

    def delete_task(self, task_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM tasks WHERE id = ?", (task_id,)
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
            ).fetchall()
        counts = {row["status"]: row["n"] for row in rows}
        by_status = {status: counts.get(status, 0) for status in VALID_STATUSES}
        return {
            "total": sum(by_status.values()),
            "todo": by_status["todo"],
            "doing": by_status["doing"],
            "done": by_status["done"],
        }


class TaskAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler for the PulseTask API (and static frontend files)."""

    server_version = "PulseTaskAPI/1.0"
    protocol_version = "HTTP/1.1"
    _TASK_ID_RE = re.compile(r"^/api/tasks/(\d+)$")

    # Injected by make_server():
    store: TaskStore = None
    frontend_dir: str | None = None

    def log_message(self, fmt, *args):  # keep server/test output clean
        pass

    # -- response plumbing --------------------------------------------------
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS"
        )
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, payload, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            raise ValueError("request body must be valid JSON")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _serve_static(self, filename: str):
        if filename not in _STATIC_TYPES or not self.frontend_dir:
            self._send_json({"error": "not found"}, status=404)
            return
        path = os.path.join(self.frontend_dir, filename)
        if not os.path.isfile(path):
            self._send_json({"error": "not found"}, status=404)
            return
        with open(path, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", _STATIC_TYPES[filename])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routes ---------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/api/health":
                healthy = self.store.healthcheck()
                self._send_json(
                    {
                        "status": "ok" if healthy else "degraded",
                        "db": "connected" if healthy else "unavailable",
                    }
                )
            elif path == "/api/tasks":
                status = parse_qs(parsed.query).get("status", [None])[0]
                tasks = self.store.list_tasks(status=status)
                self._send_json({"tasks": tasks, "count": len(tasks)})
            elif path == "/api/stats":
                self._send_json(self.store.stats())
            elif path == "/":
                self._serve_static("index.html")
            elif path.lstrip("/") in _STATIC_TYPES:
                self._serve_static(path.lstrip("/"))
            else:
                self._send_json({"error": f"not found: {path}"}, status=404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:  # defensive: never crash the worker thread
            self._send_json({"error": f"internal server error: {exc}"}, status=500)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            if path == "/api/tasks":
                body = self._read_json_body()
                task = self.store.create_task(
                    body.get("title"), body.get("status", "todo")
                )
                self._send_json(task, status=201)
            else:
                self._send_json({"error": f"not found: {path}"}, status=404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"error": f"internal server error: {exc}"}, status=500)

    def do_PATCH(self):
        match = self._TASK_ID_RE.match(urlparse(self.path).path.rstrip("/"))
        try:
            if not match:
                self._send_json(
                    {"error": "not found; use /api/tasks/<id>"}, status=404
                )
                return
            body = self._read_json_body()
            task = self.store.update_task(int(match.group(1)), body)
            if task is None:
                self._send_json(
                    {"error": f"task {match.group(1)} not found"}, status=404
                )
            else:
                self._send_json(task)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"error": f"internal server error: {exc}"}, status=500)

    def do_DELETE(self):
        match = self._TASK_ID_RE.match(urlparse(self.path).path.rstrip("/"))
        try:
            if not match:
                self._send_json(
                    {"error": "not found; use /api/tasks/<id>"}, status=404
                )
                return
            task_id = int(match.group(1))
            if self.store.delete_task(task_id):
                self._send_json({"ok": True, "deleted": task_id})
            else:
                self._send_json(
                    {"error": f"task {task_id} not found"}, status=404
                )
        except Exception as exc:
            self._send_json({"error": f"internal server error: {exc}"}, status=500)


def make_server(store: TaskStore, port: int = 0, frontend_dir: str | None = None):
    """Create a ThreadingHTTPServer bound to 127.0.0.1:port (port 0 = ephemeral)."""
    handler = type(
        "BoundTaskAPIHandler",
        (TaskAPIHandler,),
        {"store": store, "frontend_dir": frontend_dir},
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    return httpd


def run(host: str = "127.0.0.1", port: int | None = None, db_path: str | None = None):
    """Run the app (API + frontend) as a standalone server."""
    port = int(port if port is not None else os.environ.get("PORT", "8000"))
    db_path = (
        db_path
        or os.environ.get("TASKS_DB")
        or os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.db")
    )
    frontend_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
    )
    store = TaskStore(db_path)
    httpd = make_server(store, port, frontend_dir=frontend_dir)
    bound_host, bound_port = httpd.server_address[:2]
    print(f"PulseTask listening on http://{bound_host}:{bound_port} (db: {db_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()


if __name__ == "__main__":
    run()

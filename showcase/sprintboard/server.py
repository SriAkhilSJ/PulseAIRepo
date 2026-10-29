#!/usr/bin/env python3
"""SprintBoard — a single-file task board server built on the Python 3 standard library.

Routes:
    GET    /                    -> index.html
    GET    /styles.css          -> stylesheet
    GET    /app.js              -> frontend script
    GET    /api/health          -> {"status": "ok"}
    GET    /api/tasks           -> {"tasks": [...]} newest first
    POST   /api/tasks           -> create task (201) {"task": ...}
    PATCH  /api/tasks/{id}      -> update status {"task": ...}
    DELETE /api/tasks/{id}      -> delete task (204)
    GET    /api/stats           -> {"total": n, "todo": n, "doing": n, "done": n}

Persistence: SQLite. Honors the SPRINTBOARD_DB environment variable,
otherwise uses tasks.db beside this file.
"""

import argparse
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SPRINTBOARD_DB") or os.path.join(BASE_DIR, "tasks.db")

VALID_PRIORITIES = ("low", "medium", "high")
VALID_STATUSES = ("todo", "doing", "done")

# SQLite connection creation is cheap and connections are per-request,
# but a write lock keeps concurrent writers from hitting SQLITE_BUSY.
_DB_WRITE_LOCK = threading.Lock()


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _DB_WRITE_LOCK:
        conn = get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    title      TEXT NOT NULL,
                    priority   TEXT NOT NULL DEFAULT 'medium',
                    status     TEXT NOT NULL DEFAULT 'todo',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def task_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "priority": row["priority"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


class SprintBoardHandler(BaseHTTPRequestHandler):
    server_version = "SprintBoard/1.0"

    # ---------- response helpers ----------

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_empty(self, status=204):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_error_json(self, status, message):
        self._send_json(status, {"error": message})

    # ---------- static helpers ----------

    STATIC_FILES = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    }

    def _serve_static(self, path):
        filename, content_type = self.STATIC_FILES[path]
        full_path = os.path.join(BASE_DIR, filename)
        try:
            with open(full_path, "rb") as fh:
                body = fh.read()
        except OSError:
            self._send_error_json(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---------- request routing ----------

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in self.STATIC_FILES:
            self._serve_static(path if path != "/" else "/")
            return
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return
        if path == "/api/tasks":
            self._handle_list_tasks()
            return
        if path == "/api/stats":
            self._handle_stats()
            return
        self._send_error_json(404, "Not found")

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/tasks":
            self._handle_create_task()
            return
        self._send_error_json(404, "Not found")

    def do_PATCH(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "tasks" and parts[2].isdigit():
            self._handle_update_task(int(parts[2]))
            return
        self._send_error_json(404, "Not found")

    def do_DELETE(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "tasks" and parts[2].isdigit():
            self._handle_delete_task(int(parts[2]))
            return
        self._send_error_json(404, "Not found")

    # ---------- API handlers ----------

    def _handle_list_tasks(self):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC"
            ).fetchall()
        finally:
            conn.close()
        self._send_json(200, {"tasks": [task_to_dict(r) for r in rows]})

    def _handle_stats(self):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
            ).fetchall()
        finally:
            conn.close()
        counts = {row["status"]: row["count"] for row in rows}
        total = sum(counts.values())
        self._send_json(
            200,
            {
                "total": int(total),
                "todo": int(counts.get("todo", 0)),
                "doing": int(counts.get("doing", 0)),
                "done": int(counts.get("done", 0)),
            },
        )

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None, "Request body is required"
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "Request body must be valid JSON"
        if not isinstance(data, dict):
            return None, "Request body must be a JSON object"
        return data, None

    def _handle_create_task(self):
        data, error = self._read_json_body()
        if error:
            self._send_error_json(400, error)
            return
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            self._send_error_json(400, "A non-blank 'title' is required")
            return
        priority = data.get("priority")
        if priority is None:
            priority = "medium"
        if not isinstance(priority, str) or priority not in VALID_PRIORITIES:
            self._send_error_json(
                400, "'priority' must be one of: low, medium, high"
            )
            return
        with _DB_WRITE_LOCK:
            conn = get_connection()
            try:
                cursor = conn.execute(
                    "INSERT INTO tasks (title, priority, status) VALUES (?, ?, 'todo')",
                    (title.strip(), priority),
                )
                conn.commit()
                task_id = cursor.lastrowid
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
            finally:
                conn.close()
        self._send_json(201, {"task": task_to_dict(row)})

    def _handle_update_task(self, task_id):
        data, error = self._read_json_body()
        if error:
            self._send_error_json(400, error)
            return
        status = data.get("status")
        if not isinstance(status, str) or status not in VALID_STATUSES:
            self._send_error_json(
                400, "'status' must be one of: todo, doing, done"
            )
            return
        with _DB_WRITE_LOCK:
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    self._send_error_json(404, "Task not found")
                    return
                conn.execute(
                    "UPDATE tasks SET status = ? WHERE id = ?", (status, task_id)
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
            finally:
                conn.close()
        self._send_json(200, {"task": task_to_dict(row)})

    def _handle_delete_task(self, task_id):
        with _DB_WRITE_LOCK:
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT id FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    self._send_error_json(404, "Task not found")
                    return
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
            finally:
                conn.close()
        self._send_empty(204)

    # ---------- plumbing ----------

    def log_message(self, fmt, *args):  # keep the console tidy but informative
        print("[SprintBoard] %s - %s" % (self.address_string(), fmt % args))

    def do_HEAD(self):
        self.do_GET()


def main():
    parser = argparse.ArgumentParser(description="SprintBoard server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8000, help="bind port")
    args = parser.parse_args()

    init_db()

    server = ThreadingHTTPServer((args.host, args.port), SprintBoardHandler)
    print("SprintBoard serving on http://%s:%d (db: %s)" % (args.host, args.port, DB_PATH))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SprintBoardAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tempdir.name) / "acceptance.db"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = dict(os.environ)
        env["SPRINTBOARD_DB"] = str(cls.db_path)
        cls.process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "server.py"),
                "--host", "127.0.0.1",
                "--port", str(cls.port),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.time() + 10
        last_error = ""
        while time.time() < deadline:
            if cls.process.poll() is not None:
                output = cls.process.stdout.read() if cls.process.stdout else ""
                raise RuntimeError(f"server exited early: {output[-2000:]}")
            try:
                status, payload, _ = cls.request("GET", "/api/health")
                if status == 200 and payload.get("status") == "ok":
                    return
            except Exception as exc:
                last_error = repr(exc)
            time.sleep(0.1)
        cls.process.terminate()
        output = cls.process.communicate(timeout=5)[0]
        raise RuntimeError(f"server never became ready: {last_error}; {output[-2000:]}")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "process", None) is not None:
            cls.process.terminate()
            try:
                cls.process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.communicate(timeout=5)
        if getattr(cls, "tempdir", None) is not None:
            cls.tempdir.cleanup()

    @classmethod
    def request(cls, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            cls.base + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        parsed = json.loads(raw) if raw and "json" in content_type else {}
        return response.status, parsed, raw.decode("utf-8", "replace")

    def test_01_required_files_are_substantial(self):
        minimums = {
            "server.py": 1000,
            "index.html": 900,
            "styles.css": 1200,
            "app.js": 1200,
            "README.md": 300,
        }
        for name, minimum in minimums.items():
            path = ROOT / name
            self.assertTrue(path.is_file(), name)
            self.assertGreaterEqual(path.stat().st_size, minimum, name)

    def test_02_health_and_frontend_assets(self):
        status, payload, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})

        status, _, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("SprintBoard", html)
        self.assertIn('id="task-form"', html)
        self.assertIn('id="task-list"', html)
        self.assertIn('id="stat-total"', html)
        self.assertIn("styles.css", html)
        self.assertIn("app.js", html)

        status, _, css = self.request("GET", "/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("@media", css)
        status, _, javascript = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("fetch(", javascript)
        self.assertIn("/api/tasks", javascript)
        self.assertIn("/api/stats", javascript)

    def test_03_rejects_invalid_tasks(self):
        status, _, _ = self.request("POST", "/api/tasks", {"title": "   "})
        self.assertEqual(status, 400)
        status, _, _ = self.request(
            "POST", "/api/tasks", {"title": "Valid", "priority": "urgent"}
        )
        self.assertEqual(status, 400)

    def test_04_crud_stats_and_sqlite_persistence(self):
        status, created, _ = self.request(
            "POST",
            "/api/tasks",
            {"title": "Ship the launch", "priority": "high"},
        )
        self.assertEqual(status, 201)
        task = created["task"]
        self.assertIsInstance(task["id"], int)
        self.assertEqual(task["title"], "Ship the launch")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["status"], "todo")

        status, listed, _ = self.request("GET", "/api/tasks")
        self.assertEqual(status, 200)
        self.assertIn(task["id"], [item["id"] for item in listed["tasks"]])

        status, updated, _ = self.request(
            "PATCH", f"/api/tasks/{task['id']}", {"status": "doing"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["task"]["status"], "doing")

        status, stats, _ = self.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(stats["total"], 1)
        self.assertGreaterEqual(stats["doing"], 1)
        self.assertEqual(
            stats["total"], stats["todo"] + stats["doing"] + stats["done"]
        )

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT title, priority, status FROM tasks WHERE id = ?",
                (task["id"],),
            ).fetchone()
        self.assertEqual(row, ("Ship the launch", "high", "doing"))

        status, _, _ = self.request("DELETE", f"/api/tasks/{task['id']}")
        self.assertEqual(status, 204)
        status, listed, _ = self.request("GET", "/api/tasks")
        self.assertNotIn(task["id"], [item["id"] for item in listed["tasks"]])

    def test_05_missing_task_and_bad_status_are_honest(self):
        status, _, _ = self.request(
            "PATCH", "/api/tasks/999999", {"status": "done"}
        )
        self.assertEqual(status, 404)
        status, created, _ = self.request(
            "POST", "/api/tasks", {"title": "Check errors", "priority": "low"}
        )
        task_id = created["task"]["id"]
        status, _, _ = self.request(
            "PATCH", f"/api/tasks/{task_id}", {"status": "blocked"}
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
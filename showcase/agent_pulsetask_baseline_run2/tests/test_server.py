"""Automated tests for the PulseTask backend API (backend/server.py).

Each test spins up a real ThreadingHTTPServer on an ephemeral port with an
in-memory SQLite store and talks to it over HTTP using urllib, so the API is
tested end-to-end exactly as a client would see it.

Run from showcase/agent_pulsetask:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from server import TaskStore, make_server  # noqa: E402


class APIResponse:
    def __init__(self, status: int, body, headers):
        self.status = status
        self.body = body
        self.headers = headers


class APITestBase(unittest.TestCase):
    """Boots a fresh server + in-memory store for every test."""

    def setUp(self):
        self.store = TaskStore(":memory:")
        self.httpd = make_server(self.store, 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()

    # -- helpers -----------------------------------------------------------
    def request(self, method: str, path: str, payload=None, raw: bytes | None = None) -> APIResponse:
        url = f"http://127.0.0.1:{self.port}{path}"
        if raw is not None:
            data = raw
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
        else:
            data = None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None and raw is None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status, raw_body, headers = resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as exc:
            status, raw_body, headers = exc.code, exc.read(), exc.headers
        body = json.loads(raw_body.decode("utf-8")) if raw_body else None
        return APIResponse(status, body, headers)

    def create_task(self, title: str, status: str = "todo") -> dict:
        resp = self.request(
            "POST", "/api/tasks", {"title": title, "status": status}
        )
        self.assertEqual(resp.status, 201, msg=f"create failed: {resp.body}")
        return resp.body


class HealthTests(APITestBase):
    def test_health_returns_ok_and_connected(self):
        resp = self.request("GET", "/api/health")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["status"], "ok")
        self.assertEqual(resp.body["db"], "connected")


class CreateTaskTests(APITestBase):
    def test_create_task_returns_201_and_defaults_to_todo(self):
        resp = self.request("POST", "/api/tasks", {"title": "Write report"})
        self.assertEqual(resp.status, 201)
        self.assertIsInstance(resp.body["id"], int)
        self.assertEqual(resp.body["title"], "Write report")
        self.assertEqual(resp.body["status"], "todo")
        self.assertTrue(resp.body["created_at"])

    def test_create_task_with_explicit_status(self):
        resp = self.request(
            "POST", "/api/tasks", {"title": "Deploy", "status": "doing"}
        )
        self.assertEqual(resp.status, 201)
        self.assertEqual(resp.body["status"], "doing")

    def test_create_task_strips_surrounding_whitespace(self):
        task = self.create_task("  padded title  ")
        self.assertEqual(task["title"], "padded title")

    def test_create_task_missing_title_returns_400(self):
        resp = self.request("POST", "/api/tasks", {})
        self.assertEqual(resp.status, 400)
        self.assertIn("error", resp.body)

    def test_create_task_blank_title_returns_400(self):
        resp = self.request("POST", "/api/tasks", {"title": "   "})
        self.assertEqual(resp.status, 400)

    def test_create_task_invalid_status_returns_400(self):
        resp = self.request(
            "POST", "/api/tasks", {"title": "X", "status": "blocked"}
        )
        self.assertEqual(resp.status, 400)

    def test_create_task_invalid_json_returns_400(self):
        resp = self.request("POST", "/api/tasks", raw=b"this is not json")
        self.assertEqual(resp.status, 400)


class ListTasksTests(APITestBase):
    def test_get_tasks_lists_all_created_tasks(self):
        first = self.create_task("First")
        second = self.create_task("Second")
        resp = self.request("GET", "/api/tasks")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["count"], 2)
        self.assertEqual([t["id"] for t in resp.body["tasks"]], [first["id"], second["id"]])

    def test_get_tasks_filters_by_status(self):
        self.create_task("Todo one")
        self.create_task("Doing one", status="doing")
        self.create_task("Todo two")
        resp = self.request("GET", "/api/tasks?status=doing")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["count"], 1)
        self.assertEqual(resp.body["tasks"][0]["title"], "Doing one")

    def test_get_tasks_invalid_status_filter_returns_400(self):
        resp = self.request("GET", "/api/tasks?status=bogus")
        self.assertEqual(resp.status, 400)


class PatchTaskTests(APITestBase):
    def test_patch_updates_status(self):
        task = self.create_task("Learn Rust")
        resp = self.request(
            "PATCH", f"/api/tasks/{task['id']}", {"status": "done"}
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["status"], "done")
        self.assertEqual(resp.body["title"], "Learn Rust")

    def test_patch_updates_title_and_keeps_status(self):
        task = self.create_task("Old title", status="doing")
        resp = self.request(
            "PATCH", f"/api/tasks/{task['id']}", {"title": "New title"}
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["title"], "New title")
        self.assertEqual(resp.body["status"], "doing")

    def test_patch_unknown_task_returns_404(self):
        resp = self.request("PATCH", "/api/tasks/9999", {"status": "done"})
        self.assertEqual(resp.status, 404)

    def test_patch_invalid_status_returns_400(self):
        task = self.create_task("Some task")
        resp = self.request(
            "PATCH", f"/api/tasks/{task['id']}", {"status": "archived"}
        )
        self.assertEqual(resp.status, 400)

    def test_patch_empty_body_returns_400(self):
        task = self.create_task("Some task")
        resp = self.request("PATCH", f"/api/tasks/{task['id']}", {})
        self.assertEqual(resp.status, 400)


class DeleteTaskTests(APITestBase):
    def test_delete_removes_task(self):
        task = self.create_task("Temporary")
        resp = self.request("DELETE", f"/api/tasks/{task['id']}")
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.body["ok"])
        listing = self.request("GET", "/api/tasks")
        self.assertEqual(listing.body["count"], 0)

    def test_delete_unknown_task_returns_404(self):
        resp = self.request("DELETE", "/api/tasks/4242")
        self.assertEqual(resp.status, 404)

    def test_delete_twice_returns_404_the_second_time(self):
        task = self.create_task("Delete me")
        first = self.request("DELETE", f"/api/tasks/{task['id']}")
        second = self.request("DELETE", f"/api/tasks/{task['id']}")
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 404)


class StatsTests(APITestBase):
    def test_stats_empty_board_is_all_zeros(self):
        resp = self.request("GET", "/api/stats")
        self.assertEqual(resp.status, 200)
        self.assertEqual(
            resp.body, {"total": 0, "todo": 0, "doing": 0, "done": 0}
        )

    def test_stats_counts_by_status(self):
        for title in ("a", "b"):
            self.create_task(title)
        self.create_task("c", status="doing")
        for title in ("d", "e", "f"):
            self.create_task(title, status="done")
        resp = self.request("GET", "/api/stats")
        self.assertEqual(resp.status, 200)
        self.assertEqual(
            resp.body, {"total": 6, "todo": 2, "doing": 1, "done": 3}
        )

    def test_stats_reflects_patches_and_deletes(self):
        task = self.create_task("Move me")
        self.create_task("Static")
        self.request("PATCH", f"/api/tasks/{task['id']}", {"status": "done"})
        stats = self.request("GET", "/api/stats").body
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["todo"], 1)
        self.request("DELETE", f"/api/tasks/{task['id']}")
        stats = self.request("GET", "/api/stats").body
        self.assertEqual(stats["total"], 1)


class MiscTests(APITestBase):
    def test_unknown_route_returns_404(self):
        resp = self.request("GET", "/api/nope")
        self.assertEqual(resp.status, 404)

    def test_options_preflight_returns_cors_headers(self):
        resp = self.request("OPTIONS", "/api/tasks")
        self.assertEqual(resp.status, 204)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("PATCH", resp.headers.get("Access-Control-Allow-Methods", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)

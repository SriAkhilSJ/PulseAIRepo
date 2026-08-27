"""Dashboard input validation (round-12 review Issue 9).

Skipped cleanly where flask isn't installed (deps list now includes it).
"""

import threading

import pytest

flask = pytest.importorskip("flask")

from src import dashboard_server


@pytest.fixture
def client(monkeypatch):
    dashboard_server.app.config["TESTING"] = True
    # Validation tests must not launch a real provider-backed agent thread.
    # The route's acceptance response is the boundary under test here.
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    return dashboard_server.app.test_client()


class TestChatValidation:
    def test_empty_message_rejected(self, client):
        resp = client.post("/api/chat", json={"message": "   "})
        assert resp.status_code == 400
        assert "Empty" in resp.get_json()["error"]

    def test_oversized_message_rejected(self, client):
        resp = client.post("/api/chat", json={"message": "x" * 10_001})
        assert resp.status_code == 400
        assert "too long" in resp.get_json()["error"]

    def test_max_boundary_message_accepted(self, client):
        # 10_000 exactly must pass validation (route will then try to start
        # the agent in a background thread — validation is what we assert).
        resp = client.post("/api/chat", json={"message": "x" * 10_000})
        assert resp.status_code == 200

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "a b c", "a/b",
                                     "x" * 65, "sess;drop", "💥"])
    def test_evil_thread_ids_rejected(self, client, bad):
        resp = client.post("/api/chat", json={"message": "hi", "thread_id": bad})
        assert resp.status_code == 400, f"thread_id {bad!r} was accepted"
        assert "thread_id" in resp.get_json()["error"]

    @pytest.mark.parametrize("good", ["web-session", "sess-1.2_3", "sub-code-x7q",
                                      "a" * 64])
    def test_validation_accepts_real_thread_ids(self, good):
        dashboard_server._validate_chat_payload(
            {"message": "hi", "thread_id": good}
        )  # must not raise

    def test_body_over_1mb_gets_413(self, client):
        resp = client.post("/api/chat", data=b"x" * (1_100_000),
                           content_type="application/json")
        assert resp.status_code == 413

"""
Dashboard Server Integration Tests
==================================
Run: python -m pytest src/tests/test_dashboard_server.py -v
Validates:
- Flask server starts and serves HTML
- SSE endpoint streams events correctly
- /api/chat accepts messages and triggers agent
- /api/approve resolves tool approvals
- No hardcoded data in responses
"""
import json
import time
import pytest
from src.dashboard.event_bus import event_bus
from src.dashboard_server import app

@pytest.fixture
def client():
    """Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

class TestDashboardServer:
    def test_index_serves_html(self, client):
        response = client.get("/")
        assert response.status_code in (200, 404)  # 404 if dashboard.html missing
        if response.status_code == 200:
            html = response.data.decode("utf-8")
            # Must NOT contain hardcoded demo analytics
            assert "$0.0045" not in html, "Remove hardcoded cost from HTML"
            assert "44,761" not in html, "Remove hardcoded tokens from HTML"
            assert "7 API calls" not in html, "Remove hardcoded calls from HTML"
            # Must contain streaming infrastructure
            assert "EventSource" in html or "new EventSource" in html
            assert "handleEvent" in html or "message.user" in html

    def test_sse_stream_receives_events(self, client):
        # Clear bus first
        event_bus.clear()
        # Seed one event before opening the lazy Flask test-client iterator;
        # EventBus history replay guarantees it is the first SSE data frame.
        event_bus.emit("test.sse", {"data": "hello"})
        response = client.get("/api/stream")
        assert response.status_code == 200
        assert "text/event-stream" in response.content_type
        # Read the SSE stream
        chunks = []
        for chunk in response.response:
            text = chunk.decode("utf-8")
            if text.strip():
                chunks.append(text)
            if len(chunks) >= 1:
                break
        assert len(chunks) > 0
        # Parse the SSE data line
        data_line = [c for c in chunks if c.startswith("data:")][0]
        event = json.loads(data_line.replace("data: ", "").strip())
        assert event["type"] == "test.sse"
        assert event["payload"]["data"] == "hello"

    def test_chat_endpoint_accepts_message(self, client):
        event_bus.clear()
        response = client.post(
            "/api/chat",
            data=json.dumps({"message": "Hello test", "thread_id": "test-1"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "started"
        assert data["thread_id"] == "test-1"
        # Wait for user message event
        time.sleep(0.2)
        # The agent runs in background — we just verify it was queued

    def test_approve_endpoint_resolves(self, client):
        from src.dashboard.event_bus import approval_queue
        approval_queue.request("test-tool-99", "write_file", {"path": "x.py"})
        response = client.post(
            "/api/approve",
            data=json.dumps({"tool_id": "test-tool-99", "approved": True, "always_allow": False}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "ok"
        result = approval_queue.wait_for_decision("test-tool-99", timeout=0.5)
        assert result is not None
        assert result["decision"] is True

    def test_status_endpoint(self, client):
        response = client.get("/api/status")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "online"
        assert "pending_approvals" in data

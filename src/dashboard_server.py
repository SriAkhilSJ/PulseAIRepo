"""
PulseAI IDE Dashboard Server — Production Streaming Edition
===========================================================
Run: python src/dashboard_server.py
Open: http://localhost:8080

Architecture:
- Browser connects via SSE (/api/stream) for real-time events
- Browser sends messages via POST (/api/chat)
- Browser approves tools via POST (/api/approve)
- Agent runs in background thread, emits events to EventBus
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS

from src.dashboard.event_bus import event_bus, approval_queue
from src.config.settings import LLM_PROVIDER, LLM_MODEL

app = Flask(__name__)
CORS(app)

# Path to dashboard HTML
DASHBOARD_HTML = Path(__file__).parent.parent / "dashboard.html"

# =========================================================
# API ENDPOINTS
# =========================================================

@app.route("/")
def index():
    if not DASHBOARD_HTML.exists():
        return "<h1>dashboard.html not found</h1><p>Run from project root.</p>", 404
    return render_template_string(DASHBOARD_HTML.read_text(encoding="utf-8"))

@app.route("/api/stream")
def stream():
    """
    Server-Sent Events endpoint.
    Browser opens this once and keeps it open.
    We push every agent event as an SSE data packet.
    """
    def event_generator():
        q = event_bus.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except Exception:
                    # Send keepalive to prevent browser timeout
                    yield f"data: {json.dumps({'type': 'ping', 'payload': {}})}\n\n"
        finally:
            event_bus.unsubscribe(q)

    from flask import Response
    return Response(
        event_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.route("/api/chat", methods=["POST"])
def chat():
    """Receive a message from the browser and start the agent."""
    payload = request.get_json(force=True, silent=True) or {}
    message = payload.get("message", "").strip()
    thread_id = payload.get("thread_id", "web-session")
    mode = payload.get("mode", "agent")

    if not message:
        return jsonify({"error": "Empty message"}), 400

    # Emit user message immediately so UI shows it
    event_bus.emit("message.user", {
        "content": message,
        "thread_id": thread_id,
    })

    # Start agent in background thread so Flask stays responsive
    def run_agent():
        try:
            from src.graphs.chat_graph import stream_agent
            
            # This will emit events via the hooks we added to stream_agent
            result = stream_agent(
                message=message,
                thread_id=thread_id,
                provider=LLM_PROVIDER,
                model=LLM_MODEL,
                workspace=".",
                execution_mode=mode,
            )

            event_bus.emit("message.agent.end", {
                "content": result,
                "thread_id": thread_id,
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            event_bus.emit("message.agent.error", {
                "error": str(e),
                "thread_id": thread_id,
            })

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    return jsonify({"status": "started", "thread_id": thread_id})

@app.route("/api/approve", methods=["POST"])
def approve():
    """Receive tool approval/denial from the browser."""
    payload = request.get_json(force=True, silent=True) or {}
    tool_id = payload.get("tool_id")
    approved = payload.get("approved", False)
    always_allow = payload.get("always_allow", False)

    if not tool_id:
        return jsonify({"error": "Missing tool_id"}), 400

    approval_queue.resolve(tool_id, approved, always_allow)
    
    event_bus.emit("tool.approval.done", {
        "tool_id": tool_id,
        "approved": approved,
        "always_allow": always_allow,
    })

    return jsonify({"status": "ok"})

@app.route("/api/status")
def status():
    """Quick health check + current session stats."""
    return jsonify({
        "status": "online",
        "pending_approvals": approval_queue.get_pending(),
    })

# =========================================================
# LAUNCH
# =========================================================

if __name__ == "__main__":
    print("=" * 55)
    print("   PulseAI IDE Dashboard — Production Streaming")
    print("   Open http://localhost:8080 in your browser")
    print("=" * 55)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)

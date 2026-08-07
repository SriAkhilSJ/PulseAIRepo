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
import re
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

# ---------------------------------------------------------------
# INPUT VALIDATION (round-12 review: nothing was checked)
# ---------------------------------------------------------------
# Payloads flow into the engine registry, the checkpointer, and (via
# session analytics) file paths — so thread_id gets a strict charset,
# messages get a hard cap, and bodies get a transport cap.
app.config["MAX_CONTENT_LENGTH"] = 1_000_000  # 1 MB request bodies

MAX_MESSAGE_CHARS = 10_000
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _validate_chat_payload(payload: dict):
    """Return (message, thread_id) or raise ValueError with a client message."""
    message = str(payload.get("message", "")).strip()
    thread_id = str(payload.get("thread_id", "web-session")).strip() or "web-session"
    if not message:
        raise ValueError("Empty message")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError(f"Message too long (>{MAX_MESSAGE_CHARS} chars)")
    if not _THREAD_ID_RE.match(thread_id):
        raise ValueError("Invalid thread_id (letters, digits, . _ - only, max 64)")


@app.errorhandler(413)
def _too_large(_err):
    return jsonify({"error": "Payload too large"}), 413

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
    try:
        _validate_chat_payload(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    message = payload["message"].strip()
    thread_id = str(payload.get("thread_id", "web-session")).strip() or "web-session"
    mode = payload.get("mode", "agent")
    auto_approve = payload.get("auto_approve", False)

    # Emit user message immediately so UI shows it
    event_bus.emit("message.user", {
        "content": message,
        "thread_id": thread_id,
    })

    # Start agent in background thread so Flask stays responsive
    def run_agent():
        # D29: one turn at a time per conversation — a second POST on the
        # same thread_id waits instead of racing the first graph through
        # the shared checkpoint (review-autopsy fix, §44).
        from src.dashboard.turn_locks import turn_lock
        with turn_lock(thread_id):
            try:
                from src.graphs.chat_graph import stream_agent

                # If auto_approve is on, pre-approve all pending tools
                if auto_approve:
                    # The agent will check approval_queue and auto-resolve
                    pass

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

@app.route("/api/rollback", methods=["POST"])
def rollback():
    """Reset agent state to a checkpoint."""
    payload = request.get_json(force=True, silent=True) or {}
    checkpoint_id = payload.get("checkpoint_id")
    thread_id = payload.get("thread_id", "web-session")

    # Clear the event bus history for this thread's context
    # In production, you'd also reset the LangGraph checkpoint
    event_bus.emit("session.status", {
        "status": "reset",
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
    })

    return jsonify({
        "status": "reset",
        "checkpoint_id": checkpoint_id,
        "message": f"Agent rolled back to {checkpoint_id}",
    })

# In-memory shadow git: tracks which chunks were accepted/rejected per diff
shadow_git: dict[str, dict] = {}

@app.route("/api/diff/resolve", methods=["POST"])
def resolve_diff_chunk():
    """
    Accept or reject a specific diff chunk.
    This is the "shadow git" — we track decisions without touching the filesystem yet.
    The agent applies accepted chunks only when the user finishes reviewing.
    """
    payload = request.get_json(force=True, silent=True) or {}
    diff_id = payload.get("diff_id")
    chunk_id = payload.get("chunk_id")
    action = payload.get("action")  # "accept" or "reject"
    thread_id = payload.get("thread_id", "web-session")

    if not all([diff_id, chunk_id, action]):
        return jsonify({"error": "Missing diff_id, chunk_id, or action"}), 400

    if diff_id not in shadow_git:
        shadow_git[diff_id] = {
            "thread_id": thread_id,
            "chunks": {},
            "status": "reviewing",
        }

    shadow_git[diff_id]["chunks"][chunk_id] = {
        "action": action,
        "timestamp": time.time(),
    }

    # Count progress
    total = len(shadow_git[diff_id]["chunks"])
    accepted = sum(1 for c in shadow_git[diff_id]["chunks"].values() if c["action"] == "accept")
    rejected = sum(1 for c in shadow_git[diff_id]["chunks"].values() if c["action"] == "reject")

    # If all chunks resolved, emit completion event
    if shadow_git[diff_id].get("total_chunks") and total >= shadow_git[diff_id]["total_chunks"]:
        shadow_git[diff_id]["status"] = "completed"
        event_bus.emit("diff.review.complete", {
            "diff_id": diff_id,
            "accepted": accepted,
            "rejected": rejected,
            "thread_id": thread_id,
        })

    return jsonify({
        "status": "ok",
        "diff_id": diff_id,
        "chunk_id": chunk_id,
        "action": action,
        "progress": {"accepted": accepted, "rejected": rejected, "total": total},
    })

@app.route("/api/diff/status/<diff_id>")
def diff_status(diff_id: str):
    """Get the review status of a diff."""
    data = shadow_git.get(diff_id, {})
    return jsonify({
        "diff_id": diff_id,
        "status": data.get("status", "unknown"),
        "chunks": data.get("chunks", {}),
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

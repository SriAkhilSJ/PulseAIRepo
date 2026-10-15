"""Human-in-the-loop reaches sub-agent children (OpenCode parity).

OpenCode's question tool asks with the CHILD's session id, and the
client surfaces pending questions from the whole session TREE in
whichever view is open (session-request-tree.ts): a child's
question is answerable from the parent view, and the reply routes
to the asking session. Crusor's version of that contract, pinned
at the engine seam here: a child's clarify BLOCKS (no silent
auto-skip — an earlier gate that instantly "walked away" was
reverted once OpenCode's design was read), and a queue resolution
addressed to the child's session releases it with the answers.
"""

from __future__ import annotations

import json
import threading
import time

from src.dashboard.event_bus import clarify_queue
from src.tools.clarify_tool import clarify


_CHILD_CONFIG = {"configurable": {
    "thread_id": "sub-research-abc123",
    "workspace": ".",
    "scope_capabilities": ["research", "workspace_read"],
    "scope_capabilities_strict": True,
}}


def _pending_for(session_id: str) -> dict | None:
    for item in clarify_queue._pending.values():
        if item.get("session_id") == session_id and item.get("status") == "pending":
            return item
    return None


def test_child_clarify_blocks_until_answered_for_its_session():
    outcome: dict = {}

    def ask():
        outcome["raw"] = clarify.invoke(
            {"questions": [{"question": "Keep going?", "choices": ["Continue research"]}]},
            config=_CHILD_CONFIG,
        )

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    # The request must really pend (blocked HITL), addressed to the child.
    deadline = time.monotonic() + 10
    item = None
    while time.monotonic() < deadline:
        item = _pending_for("sub-research-abc123")
        if item:
            break
        time.sleep(0.02)
    assert item is not None, "child clarify never registered a pending request"
    assert worker.is_alive(), "child clarify returned instead of waiting for the user"

    ok = clarify_queue.resolve(
        item["id"], {"q0": "Continue research"},
        timed_out=False, session_id="sub-research-abc123",
    )
    assert ok
    worker.join(timeout=10)
    assert not worker.is_alive(), "answered child clarify never released"
    payload = json.loads(outcome["raw"])
    assert payload["responses"][0]["user_response"] == "Continue research"
    assert not payload.get("timed_out")


def test_clarify_reply_must_name_the_asking_session():
    """The bridge resolves by request id + asking session; a reply
    addressed to the VIEWED (parent) session must not release a
    child's wait — the service now always sends the asker's id."""
    outcome: dict = {}

    def ask():
        outcome["raw"] = clarify.invoke(
            {"question": "Which file?", "choices": ["a.py", "b.py"]},
            config=_CHILD_CONFIG,
        )

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    item = None
    while time.monotonic() < deadline:
        item = _pending_for("sub-research-abc123")
        if item:
            break
        time.sleep(0.02)
    assert item is not None
    assert clarify_queue.resolve(
        item["id"], {"q0": "a.py"}, timed_out=False, session_id="parent-session",
    ) is False
    assert worker.is_alive()
    assert clarify_queue.resolve(
        item["id"], {"q0": "a.py"}, timed_out=False, session_id="sub-research-abc123",
    ) is True
    worker.join(timeout=10)
    assert not worker.is_alive()

"""Children never block on clarify (field 2026-10-15).

A research child asked a model-authored placeholder question
("Placeholder to keep turn structure — ignore") and froze: the
clarify tool waits up to 300s for a bridge reply, but a sub-agent
session is read-only in the desktop (prompt disabled) and the
parent turn is blocked inside the delegation, so nobody could
ever answer. The child session read as a dead, unscrollable page
for five minutes. Children now get the walk-away outcome
immediately; the parent (non-strict) still asks normally.
"""

from __future__ import annotations

import json
import time

from src.tools.clarify_tool import clarify


_CHILD_CONFIG = {"configurable": {
    "thread_id": "sub-research-abc123",
    "workspace": ".",
    "scope_capabilities": ["research", "workspace_read"],
    "scope_capabilities_strict": True,
}}


def test_child_clarify_batch_returns_walk_away_immediately():
    started = time.monotonic()
    out = clarify.invoke(
        {"questions": [{"question": "Keep going?", "choices": ["Continue research"]}]},
        config=_CHILD_CONFIG,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 5, f"child clarify blocked for {elapsed:.1f}s"
    payload = json.loads(out)
    assert payload.get("timed_out") is True
    assert payload["responses"][0]["user_response"] == ""


def test_child_clarify_single_question_returns_sentinel_immediately():
    started = time.monotonic()
    out = clarify.invoke(
        {"question": "Which file?", "choices": ["a.py", "b.py"]},
        config=_CHILD_CONFIG,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 5, f"child clarify blocked for {elapsed:.1f}s"
    payload = json.loads(out)
    assert "did not provide a response" in payload["user_response"]

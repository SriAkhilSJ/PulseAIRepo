"""Approval-dock testimony + the removed dock timeout.

Field run-3 (c54ccebf): two `flutter create` calls waited out the
full 300s approval timeout at an unanswered dock while the founder
was away, and the engine log showed only "[tool_node] 0 tool
result(s) ready" — an unanswered dock was indistinguishable from a
swallowed tool call. f342dca2 made every wait testify; founder
2026-10-20 then removed the timeout itself: an ask pends until the
human answers or Stop cancels the turn (the wait heartbeats, so the
bridge stall watchdog — which counts approval waits as liveness —
never mistakes a pending dock for a dead turn). These tests pin:

- an unanswered ask WAITS (no self-denial, no execution) until Stop;
- the waiting line names the judged path verbatim;
- answered / cancelled waits testify with their elapsed time;
- the queue's indefinite wait heartbeats and never self-denies
  (a finite timeout still denies — pinned in the hermes suite).
"""
from __future__ import annotations

import json
import threading
import time

import pytest
from langchain_core.messages import AIMessage


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "no-home"))


def _config(session: str, workspace: str) -> dict:
    return {
        "configurable": {
            "thread_id": session,
            "workspace": workspace,
            "approval_channel": True,
            "approval_policy": "workspace_session",
        }
    }


def _state(tool_id: str, name: str, args: dict) -> dict:
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": tool_id, "name": name, "args": args}],
            )
        ]
    }


def _node(tmp_path):
    from src.context.safety_guard import SafetyGuard
    from src.graphs.chat_graph import SafeToolNode, tools

    return SafeToolNode(tools, SafetyGuard(str(tmp_path)))


def _run_node(node, state, config):
    box: dict = {}

    def _target():
        try:
            box["result"] = node(state, config)
        except Exception as exc:  # surfaced by the assertions below
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread, box


def _await_pending(session: str, tool_id: str, timeout: float = 10.0):
    from src.dashboard.event_bus import approval_queue

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for item in approval_queue.get_pending(session):
            if item["id"] == tool_id:
                return item
        time.sleep(0.02)
    return None


def _finish(thread, box):
    thread.join(timeout=15)
    assert not thread.is_alive(), "the node must finish once resolved"
    if "error" in box:
        raise box["error"]
    return box["result"]


def test_unanswered_dock_pends_until_stop_cancels_it(tmp_path, capsys):
    """Nobody answers: the ask WAITS (the 300s self-denial is gone),
    nothing executes, the log names the judged path — and Stop ends
    the wait as a before-execution denial."""
    from src.runtime.turn_control import turn_controls

    session = "testimony-stuck"
    outside = tmp_path.parent / "testimony-outside.txt"
    node = _node(tmp_path)
    turn_controls.begin(session)
    try:
        thread, box = _run_node(
            node,
            _state(
                "t-stuck", "terminal",
                {"command": f"echo pwned > {outside}"},
            ),
            _config(session, str(tmp_path)),
        )
        item = _await_pending(session, "t-stuck")
        assert item is not None, "the ask must reach the queue"

        # Far beyond any test-scale wait: still pending, still unexecuted.
        time.sleep(1.5)
        assert thread.is_alive(), "no timeout may kill the wait"
        assert not outside.exists(), "a pending dock means NOT executed"

        # Stop wakes the wait immediately.
        assert turn_controls.cancel(session)
        result = _finish(thread, box)
    finally:
        turn_controls.end(session)

    message = result["messages"][0]
    assert message.status == "error"
    assert "cancelled before execution" in message.content
    assert not outside.exists(), "a cancelled dock means NOT executed"

    out = capsys.readouterr().out
    waiting = [
        line for line in out.splitlines()
        if "[approval] terminal needs approval" in line
    ]
    assert len(waiting) == 1
    assert str(outside) in waiting[0], "the ask must name the judged path"
    assert "up to" not in waiting[0], "no timeout may be advertised"
    assert "[approval] terminal cancelled after" in out
    assert "call denied before execution" in out


def test_answered_dock_testifies_allowed(tmp_path, capsys):
    settings = tmp_path / ".crusorai"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "settings.json").write_text(
        json.dumps({"permission": {"bash": "ask"}}), encoding="utf-8"
    )
    from src.dashboard.event_bus import approval_queue

    node = _node(tmp_path)
    thread, box = _run_node(
        node,
        _state("t-allow", "terminal", {"command": "echo hi-testimony"}),
        _config("testimony-allow", str(tmp_path)),
    )
    item = _await_pending("testimony-allow", "t-allow")
    assert item is not None, "the ask must reach the queue"
    assert approval_queue.resolve(
        "t-allow", True, session_id="testimony-allow"
    )
    result = _finish(thread, box)

    message = result["messages"][0]
    assert message.status != "error"
    assert "hi-testimony" in message.content

    out = capsys.readouterr().out
    assert "[approval] terminal needs approval — waiting for human" in out
    assert "[approval] terminal allowed after" in out


def test_queue_wait_pends_and_heartbeats_until_resolved():
    """timeout=None never self-denies; the heartbeat keeps firing so
    the wait stays visible (log) and alive (stall watchdog)."""
    from src.dashboard.event_bus import ApprovalQueue

    queue = ApprovalQueue()
    queue.request("hb-1", "terminal", {}, session_id="hb")
    beats: list[float] = []
    box: dict = {}

    def _target():
        box["result"] = queue.wait_for_decision(
            "hb-1", heartbeat=beats.append, heartbeat_interval=0.05
        )

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    time.sleep(0.22)
    assert thread.is_alive(), "an unbounded wait must not self-deny"
    assert len(beats) >= 2, "the heartbeat must keep testifying"
    assert beats == sorted(beats), "elapsed time only moves forward"

    assert queue.resolve("hb-1", True, session_id="hb")
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert box["result"]["decision"] is True

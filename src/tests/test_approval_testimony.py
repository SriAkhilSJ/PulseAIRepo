"""Approval-dock testimony in the engine log (field run-3, c54ccebf).

Two `flutter create` calls waited out the full 300s approval timeout
and the engine log showed only "[tool_node] 0 tool result(s) ready" —
an unanswered dock was indistinguishable from a swallowed tool call.
Every dock wait now prints: asked, answered, or timed out. These tests
pin the lines, and that the denial semantics themselves are unchanged
(unanswered still means denied before execution).
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


def _config(session: str, workspace: str, timeout: float = 30.0) -> dict:
    return {
        "configurable": {
            "thread_id": session,
            "workspace": workspace,
            "approval_channel": True,
            "approval_policy": "workspace_session",
            "approval_timeout": timeout,
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


def test_unanswered_dock_denies_and_testifies(tmp_path, capsys):
    """Nobody answers: the call is denied before execution (unchanged
    semantics) AND the log says the dock was waited on and timed out."""
    outside = tmp_path.parent / "testimony-outside.txt"
    node = _node(tmp_path)
    result = node(
        _state(
            "t-timeout", "terminal",
            {"command": f"echo pwned > {outside}"},
        ),
        _config("testimony-timeout", str(tmp_path), timeout=1.0),
    )
    message = result["messages"][0]
    assert message.status == "error"
    assert "timed out before execution" in message.content
    assert not outside.exists(), "a timed-out dock means NOT executed"

    out = capsys.readouterr().out
    assert "[approval] terminal needs approval — waiting for human" in out
    assert "[approval] terminal timed out after" in out
    assert "call denied before execution" in out
    # The line that used to stand alone, now explained by the ones above.
    assert "[tool_node] 0 tool result(s) ready" in out


def test_answered_dock_testifies_allowed(tmp_path, capsys):
    settings = tmp_path / ".crusorai"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "settings.json").write_text(
        json.dumps({"permission": {"bash": "ask"}}), encoding="utf-8"
    )
    from src.dashboard.event_bus import approval_queue

    node = _node(tmp_path)
    box: dict = {}

    def _target():
        try:
            box["result"] = node(
                _state("t-allow", "terminal", {"command": "echo hi-testimony"}),
                _config("testimony-allow", str(tmp_path)),
            )
        except Exception as exc:  # surfaced below
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    item = None
    while time.monotonic() < deadline:
        for pending in approval_queue.get_pending("testimony-allow"):
            if pending["id"] == "t-allow":
                item = pending
                break
        if item is not None:
            break
        time.sleep(0.02)
    assert item is not None, "the ask must reach the queue"
    assert approval_queue.resolve(
        "t-allow", True, session_id="testimony-allow"
    )
    thread.join(timeout=15)
    assert not thread.is_alive(), "the node must finish once answered"
    if "error" in box:
        raise box["error"]

    message = box["result"]["messages"][0]
    assert message.status != "error"
    assert "hi-testimony" in message.content

    out = capsys.readouterr().out
    assert "[approval] terminal needs approval — waiting for human" in out
    assert "[approval] terminal allowed after" in out

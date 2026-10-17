"""OpenCode "Allow always" session grants (founder 2026-10-17: full
human-in-the-loop guardrails, how OpenCode does them).

The dock's three verdicts are once / always / reject. "Always" used
to be recorded on the decision and then dropped — the next identical
call asked again, against the dialog's own promise. Now the verdict
grants (session, tool, resource) in the ApprovalQueue, the graph
consults it before queueing, and the guard's veto classes (sensitive
files, git-ignored paths) are re-asked every time.
"""
from __future__ import annotations

import threading
import time

import pytest
from langchain_core.messages import AIMessage


def _config(session: str, workspace: str) -> dict:
    return {
        "configurable": {
            "thread_id": session,
            "workspace": workspace,
            "approval_channel": True,
            "approval_policy": "workspace_session",
            "approval_timeout": 30.0,
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


def test_queue_grant_store_is_session_scoped():
    from src.dashboard.event_bus import ApprovalQueue

    queue = ApprovalQueue()
    key = "write_file\nnotes.py"
    assert not queue.is_granted("s-1", key)
    queue.grant("s-1", key)
    assert queue.is_granted("s-1", key)
    assert not queue.is_granted("s-2", key), "grants never leak across sessions"
    assert not queue.is_granted("s-1", "write_file\nother.py"), (
        "a grant names its resource, not the whole tool"
    )


def test_veto_classes_are_named_by_the_guard():
    from src.context.safety_guard import SafetyGuard, session_grant_vetoed

    guard = SafetyGuard(".")
    assert session_grant_vetoed(guard._critical_file_warning(".env"))
    assert session_grant_vetoed(guard._ignored_file_warning("write_file", "path", "x.log"))
    assert not session_grant_vetoed(guard._overwrite_warning("notes.py"))
    assert not session_grant_vetoed(
        guard._dangerous_command_warning("rm -rf build", "recursive delete")
    )
    assert not session_grant_vetoed("")


def _drive_write(tmp_path, session: str, tool_id: str, args: dict, *, always: bool):
    """Run one write_file call through SafeToolNode; if it asks, answer."""
    from src.dashboard.event_bus import approval_queue
    from src.graphs.chat_graph import SafeToolNode, tools
    from src.context.safety_guard import SafetyGuard

    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    thread, box = _run_node(node, _state(tool_id, "write_file", args), _config(session, str(tmp_path)))
    item = _await_pending(session, tool_id, timeout=3.0)
    asked = item is not None
    if asked:
        assert approval_queue.resolve(tool_id, True, always_allow=always, session_id=session)
    thread.join(timeout=15)
    assert not thread.is_alive(), "the node must finish once answered"
    if "error" in box:
        raise box["error"]
    return asked, box["result"]["messages"][0]


def test_allow_always_skips_the_next_identical_ask(tmp_path):
    session = "grant-test-always"
    (tmp_path / "notes.py").write_text("old\n", encoding="utf-8")
    args = {"path": "notes.py", "content": "new\n"}

    asked, message = _drive_write(tmp_path, session, "g-1", args, always=True)
    assert asked, "the first overwrite must ask"
    assert message.status != "error"
    assert (tmp_path / "notes.py").read_text(encoding="utf-8") == "new\n"

    asked, message = _drive_write(tmp_path, session, "g-2", args, always=True)
    assert not asked, "the granted (tool, resource) must not ask again this session"
    assert message.status != "error"

    # The grant names its resource: a different file still asks.
    (tmp_path / "other.py").write_text("old\n", encoding="utf-8")
    asked, _ = _drive_write(
        tmp_path, session, "g-3", {"path": "other.py", "content": "new\n"}, always=False
    )
    assert asked, "a grant for notes.py must not wave through other.py"


def test_allow_once_asks_again_next_time(tmp_path):
    session = "grant-test-once"
    (tmp_path / "notes.py").write_text("old\n", encoding="utf-8")
    args = {"path": "notes.py", "content": "new\n"}

    asked, _ = _drive_write(tmp_path, session, "o-1", args, always=False)
    assert asked
    asked, _ = _drive_write(tmp_path, session, "o-2", args, always=False)
    assert asked, "Allow once buys exactly one run"


def test_veto_class_reasks_even_after_allow_always(tmp_path):
    session = "grant-test-veto"
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    args = {"path": ".env", "content": "SECRET=2\n"}

    asked, _ = _drive_write(tmp_path, session, "v-1", args, always=True)
    assert asked, "a sensitive file must ask"
    asked, _ = _drive_write(tmp_path, session, "v-2", args, always=True)
    assert asked, "secrets are re-asked every time — no grant can silence them"

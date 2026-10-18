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

import json
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


# ── OpenCode permission config (ask / allow / deny rule table) ──────

def _write_settings(tmp_path, payload: dict) -> None:
    folder = tmp_path / ".crusorai"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "no-home"))


def _drive_tool(tmp_path, session, tool_id, name, args, *, state=None, always=False):
    """One call through SafeToolNode; answer the dock if it asks."""
    from src.dashboard.event_bus import approval_queue
    from src.graphs.chat_graph import SafeToolNode, tools
    from src.context.safety_guard import SafetyGuard

    node = SafeToolNode(tools, SafetyGuard(str(tmp_path)))
    thread, box = _run_node(
        node, state or _state(tool_id, name, args), _config(session, str(tmp_path))
    )
    item = _await_pending(session, tool_id, timeout=3.0)
    asked = item is not None
    if asked:
        approval_queue.resolve(tool_id, True, always_allow=always, session_id=session)
    thread.join(timeout=15)
    assert not thread.is_alive()
    if "error" in box:
        raise box["error"]
    return asked, box["result"]["messages"][0]


def test_rule_evaluation_is_upstreams():
    from src.context.permission_config import effect_for, evaluate, load_permission_rules

    rules = load_permission_rules("", "")
    assert evaluate("bash", "git status", rules) == "allow", "defaults allow"
    assert evaluate("doom_loop", "*", rules) == "ask"
    assert evaluate("external_directory", "/etc/passwd", rules) == "ask"
    assert evaluate("read", "app.env", rules) == "deny"
    assert evaluate("read", "app.env.local", rules) == "deny"
    assert evaluate("read", "app.env.example", rules) == "allow", "later rule wins"

    custom = rules + [
        ("bash", "*", "ask"),
        ("bash", "git *", "allow"),
        ("bash", "rm *", "deny"),
    ]
    assert effect_for("bash", ["git status"], custom) == "allow"
    assert effect_for("bash", ["npm test"], custom) == "ask"
    assert effect_for("bash", ["rm -rf x"], custom) == "deny"
    assert effect_for("edit", ["a.py", "b.py"], custom + [("edit", "b.py", "deny")]) == "deny", (
        "any resource denying denies the call"
    )


def test_config_ask_routes_bash_to_the_dock(tmp_path):
    _write_settings(tmp_path, {"permission": {"bash": "ask"}})
    asked, message = _drive_tool(
        tmp_path, "cfg-ask", "c-1", "run_terminal", {"command": "echo hi"}
    )
    assert asked, "a config ask must reach the human"
    assert message.status != "error"


def test_config_deny_blocks_without_asking(tmp_path):
    _write_settings(tmp_path, {"permission": {"edit": "deny"}})
    asked, message = _drive_tool(
        tmp_path, "cfg-deny", "c-2", "write_file",
        {"path": "new_file.py", "content": "x = 1\n"},
    )
    assert not asked, "a denial is refused outright, never asked about"
    assert message.status == "error" and "Permission denied" in message.content
    assert not (tmp_path / "new_file.py").exists(), "denied means NOT executed"


def test_env_read_is_denied_by_default(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    asked, message = _drive_tool(tmp_path, "cfg-env", "c-3", "read_file", {"path": ".env"})
    assert not asked
    assert message.status == "error" and "Permission denied" in message.content


def test_env_via_shell_is_still_denied(tmp_path):
    """Field 2026-10-17: the model reached the secret with
    `(test -f .env && cat .env ...)` through the shell — the read
    deny follows the file, not the tool."""
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    asked, message = _drive_tool(
        tmp_path, "cfg-env-shell", "c-30", "run_terminal",
        {"command": "test -f .env && cat .env || echo missing"},
    )
    assert not asked, "a config deny must never reach the dock"
    assert message.status == "error" and "Permission denied" in message.content


def test_home_relative_shell_path_asks(tmp_path):
    """Field 2026-10-17: `cat ~/.bashrc` must ask (home is outside
    the project) — previously only absolute paths were mined."""
    asked, message = _drive_tool(
        tmp_path, "cfg-home-shell", "c-31", "run_terminal",
        {"command": "cat ~/.bashrc"},
    )
    assert asked, "home-relative shell paths must hit the outside-project ask"
    assert message.status != "error"


def test_external_directory_asks_by_default(tmp_path):
    outside = tmp_path.parent / "outside-cfg-test.txt"
    outside.write_text("outside\n", encoding="utf-8")
    try:
        asked, message = _drive_tool(
            tmp_path, "cfg-ext", "c-4", "run_terminal",
            {"command": f"cat {outside}"},
        )
        assert asked, "a shell reaching outside the project asks first"
        assert message.status != "error" and "outside" in message.content
    finally:
        outside.unlink(missing_ok=True)


def test_per_agent_rules_override_for_the_main_agent(tmp_path):
    _write_settings(tmp_path, {"agent": {"build": {"permission": {"bash": "deny"}}}})
    asked, message = _drive_tool(
        tmp_path, "cfg-agent", "c-5", "run_terminal", {"command": "echo hi"}
    )
    assert not asked and message.status == "error", "agent.build rules govern the main agent"


def test_doom_loop_asks_on_the_third_identical_call(tmp_path):
    from langchain_core.messages import HumanMessage, ToolMessage

    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")

    def _turn(call_id):
        return AIMessage(
            content="",
            tool_calls=[{"id": call_id, "name": "read_file", "args": {"path": "a.txt"}}],
        )

    state = {
        "messages": [
            HumanMessage(content="read it"),
            _turn("d-1"),
            ToolMessage(content="hello", tool_call_id="d-1", name="read_file"),
            _turn("d-2"),
            ToolMessage(content="hello", tool_call_id="d-2", name="read_file"),
            _turn("d-3"),
        ]
    }
    asked, message = _drive_tool(
        tmp_path, "cfg-doom", "d-3", "read_file", {"path": "a.txt"}, state=state
    )
    assert asked, "the third identical call in a row asks (doom_loop)"
    assert message.status != "error", "approved, the call runs"


def test_doom_loop_allow_in_config_runs_silently(tmp_path):
    from langchain_core.messages import HumanMessage, ToolMessage

    _write_settings(tmp_path, {"permission": {"doom_loop": "allow"}})
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")

    def _turn(call_id):
        return AIMessage(
            content="",
            tool_calls=[{"id": call_id, "name": "read_file", "args": {"path": "a.txt"}}],
        )

    state = {
        "messages": [
            HumanMessage(content="read it"),
            _turn("e-1"),
            ToolMessage(content="hello", tool_call_id="e-1", name="read_file"),
            _turn("e-2"),
            ToolMessage(content="hello", tool_call_id="e-2", name="read_file"),
            _turn("e-3"),
        ]
    }
    asked, message = _drive_tool(
        tmp_path, "cfg-doom-allow", "e-3", "read_file", {"path": "a.txt"}, state=state
    )
    assert not asked and message.status != "error"


def test_always_verdict_is_session_only_and_writes_nothing(tmp_path):
    """Founder 2026-10-17: permission handling supports only its own
    session. An "always" verdict grants (session, tool, resource)
    in memory; nothing is written to the workspace, and a fresh
    session asks again for the very same file."""
    target = tmp_path / "keep.py"
    target.write_text("x = 1\n", encoding="utf-8")
    asked1, _ = _drive_write(
        tmp_path, "p-1", "w1", {"path": "keep.py", "content": "x = 2\n"}, always=True
    )
    assert asked1
    assert not (tmp_path / ".crusorai" / "permissions-saved.json").exists(), (
        "an always verdict must not persist anything to disk"
    )
    # The granting session stays granted (also covered above, kept
    # here so this test reads whole on its own).
    asked_same, _ = _drive_write(
        tmp_path, "p-1", "w1b", {"path": "keep.py", "content": "x = 3\n"}, always=False
    )
    assert not asked_same, "the granting session must not re-ask"
    asked2, _ = _drive_write(
        tmp_path, "p-2-fresh-session", "w2",
        {"path": "keep.py", "content": "x = 4\n"}, always=False,
    )
    assert asked2, "a fresh session must re-ask: grants die with their session"


def test_legacy_saved_patterns_file_is_ignored(tmp_path):
    """A permissions-saved.json left behind by the persisted-grant
    builds is never read: it must not release a config ask."""
    _write_settings(tmp_path, {"permission": {"bash": "ask"}})
    folder = tmp_path / ".crusorai"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "permissions-saved.json").write_text(
        json.dumps([{"action": "bash", "resource": "echo hi"}]), encoding="utf-8"
    )
    asked, _ = _drive_tool(tmp_path, "p-4", "c-10", "run_terminal", {"command": "echo hi"})
    assert asked, "a leftover saved-patterns file must not release the ask"


def test_no_persistence_layer_remains():
    """The write/read side of the per-project layer is gone, so a
    future change cannot quietly re-persist verdicts."""
    import src.context.permission_config as pc

    assert not hasattr(pc, "save_grant")
    assert not hasattr(pc, "saved_rules")
    assert not hasattr(pc, "saved_releases")

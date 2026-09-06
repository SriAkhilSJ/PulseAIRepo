"""Behavior contracts for the Hermes-derived runtime invariants."""
from __future__ import annotations

import contextlib
import os
import pathlib
import queue
import sqlite3
import threading
import time

import pytest

from src.context.verification_evidence import VerificationLedger
from src.dashboard.event_bus import ApprovalQueue, EventBus
from src.runtime.event_journal import EventJournal
from src.runtime.factory import create_runtime_services
from src.runtime.identity import TurnIdentity
from src.runtime.turn_control import TurnControlRegistry


def test_explicit_turn_identity_is_stable_and_separated(tmp_path):
    identity = TurnIdentity.create(session_id="session-a", workspace=str(tmp_path))
    assert identity.session_id == "session-a"
    assert identity.runtime_session_id.startswith("runtime-")
    assert identity.turn_id.startswith("turn-")
    assert identity.workspace_id.startswith("ws-")
    assert identity.lineage_root_id == "session-a"


def test_event_bus_isolates_sessions_and_replay():
    bus = EventBus()
    qa = bus.subscribe("a")
    qb = bus.subscribe("b")
    bus.emit("token", {"thread_id": "a", "text": "secret-a"})
    assert qa.get(timeout=0.2)["payload"]["text"] == "secret-a"
    try:
        qb.get(timeout=0.05)
        assert False, "session b received session a event"
    except queue.Empty:
        pass
    late = bus.subscribe("a")
    assert late.get(timeout=0.2)["payload"]["text"] == "secret-a"


def test_approval_timeout_denies_and_session_mismatch_cannot_resolve():
    broker = ApprovalQueue()
    broker.request("tc1", "write_file", {"path": "x"}, session_id="a", diff={"new_text": "x"})
    assert broker.resolve("tc1", True, session_id="b") is False
    result = broker.wait_for_decision("tc1", timeout=0.01)
    assert result["decision"] is False and result["timeout"] is True


def test_approval_waits_for_correct_session_resolution():
    broker = ApprovalQueue()
    broker.request("tc2", "write_file", {}, session_id="a")
    threading.Thread(
        target=lambda: (time.sleep(0.02), broker.resolve("tc2", True, session_id="a")),
        daemon=True,
    ).start()
    assert broker.wait_for_decision("tc2", timeout=1)["decision"] is True


def test_journal_replays_intent_before_result(tmp_path):
    journal = EventJournal(tmp_path / "events.db")
    journal.append("tool.intent", {"tool_name": "write_file"}, session_id="s", tool_call_id="t")
    journal.append("tool.result", {"status": "ok"}, session_id="s", tool_call_id="t")
    events = journal.list_events("s")
    assert [e["type"] for e in events] == ["tool.intent", "tool.result"]
    assert events[0]["seq"] < events[1]["seq"]
    journal.close()


def test_verification_evidence_becomes_stale_after_edit(tmp_path):
    ledger = VerificationLedger(tmp_path / "verification.db")
    ev = ledger.record_command(
        session_id="s", workspace=str(tmp_path), command="pytest",
        exit_code=0, output="3 passed",
    )
    assert ev["status"] == "passed" and ev["scope"] == "full"
    assert ledger.status(session_id="s", workspace=str(tmp_path))["status"] == "passed"
    ledger.mark_edited(session_id="s", workspace=str(tmp_path), paths=["a.py"])
    status = ledger.status(session_id="s", workspace=str(tmp_path))
    assert status["status"] == "stale" and status["changed_paths"] == ["a.py"]


def test_targeted_verification_is_not_repo_green(tmp_path):
    ledger = VerificationLedger(tmp_path / "verification.db")
    ev = ledger.record_command(
        session_id="s", workspace=str(tmp_path),
        command="pytest tests/test_auth.py::test_login", exit_code=0,
    )
    assert ev["scope"] == "targeted"


def test_cancel_steer_and_queue_are_distinct():
    controls = TurnControlRegistry()
    controls.begin("s")
    assert controls.steer("s", "use the existing file") is True
    assert controls.queue("s", "then write docs") == 1
    assert controls.cancel("s") is True
    assert controls.cancelled("s") is True
    assert controls.drain_steer("s") == ["use the existing file"]
    assert controls.pop_queued("s") == ("then write docs", "agent")


def test_queue_preserves_the_prompt_execution_mode():
    """A queued prompt is a NEW turn in waiting: the renderer's selected mode
    rides with it, or the drained Ask/Plan/Debug prompt silently ran as a
    full agent turn (field 2026-09-06: "Ask is not working" — the picker said
    Ask and the drained turn bound the terminal)."""
    controls = TurnControlRegistry()
    controls.queue("s", "list the files", mode="ask")
    controls.queue("s", "draft the approach", mode="plan")
    controls.queue("s", "no mode given")
    assert controls.pop_queued("s") == ("list the files", "ask")
    assert controls.pop_queued("s") == ("draft the approach", "plan")
    assert controls.pop_queued("s") == ("no mode given", "agent")
    assert controls.pop_queued("s") is None


def test_tool_transaction_never_executes_when_intent_persistence_fails(monkeypatch):
    from src.runtime import tool_middleware
    called = []
    class BrokenJournal:
        def append(self, *args, **kwargs):
            raise RuntimeError("disk full")
    class Services:
        journal = BrokenJournal()
    monkeypatch.setattr("src.runtime.factory.get_runtime_services", lambda: Services())
    try:
        tool_middleware.execute_tool_transaction(
            name="write_file", args={"path": "x"}, tool_call_id="tc",
            config={"configurable": {"thread_id": "s", "workspace": "."}},
            invoke=lambda: called.append(True),
        )
        assert False, "persistence failure must raise"
    except RuntimeError:
        pass
    assert called == []


def test_foreground_terminal_observes_session_cancel(tmp_path):
    import os
    import shlex
    import subprocess
    import sys
    from src.runtime.turn_control import turn_controls
    from src.tools.terminal_tools import run_terminal
    session = "cancel-terminal-test"
    turn_controls.begin(session)
    timer = threading.Timer(0.15, lambda: turn_controls.cancel(session))
    timer.start()
    try:
        argv = [sys.executable, "-c", "import time; time.sleep(10)"]
        command = (
            subprocess.list2cmdline(argv)
            if os.name == "nt"
            else shlex.join(argv)
        )
        result = run_terminal.invoke(
            {"command": command},
            config={"configurable": {"thread_id": session, "workspace": str(tmp_path)}},
        )
    finally:
        timer.cancel()
        turn_controls.end(session)
    assert "cancelled by the user" in result


def test_runtime_factory_creates_isolated_stores(tmp_path):
    a = create_runtime_services(tmp_path / "a")
    b = create_runtime_services(tmp_path / "b")
    a.journal.append("x", {}, session_id="s")
    assert len(a.journal.list_events("s")) == 1
    assert b.journal.list_events("s") == []
    a.close(); b.close()


def test_foreground_cancel_answers_when_a_grandchild_holds_the_pipes(monkeypatch, tmp_path):
    """The Windows cancel path, emulated on any host (live round found it dead).

    Cancelling a foreground `run_terminal` must answer "cancelled by the user" —
    not fall through to the timeout text. The bug was shape, not platform: the
    kill only reached the shell wrapper, the real child survived holding
    stdout/stderr, and the unguarded `communicate()` afterwards blocked, raised
    out of the poll loop, and let the outer handler reply with the TIMEOUT
    message. Here the tree kill is made to "succeed" while nothing dies, which
    is exactly Windows.
    """
    import os, shlex, sys, threading, time
    from src.runtime.turn_control import turn_controls
    from src.tools import terminal_tools

    monkeypatch.setattr(terminal_tools.os, "killpg", lambda *a, **k: None)
    # Keep the test quick; the shipped value is what the fix protects.
    monkeypatch.setattr(terminal_tools, "_CANCEL_DRAIN_TIMEOUT_S", 0.5)

    session = "cancel-drain-test"
    turn_controls.begin(session)
    timer = threading.Timer(0.1, lambda: turn_controls.cancel(session))
    timer.start()
    started = time.monotonic()
    try:
        # The surviving child must outlive the drain window, or the pipes close
        # on their own and the blocked read never happens.
        sleeper = shlex.join([sys.executable, "-c", "import time; time.sleep(10)"])
        result = terminal_tools.run_terminal.invoke(
            {"command": f"{sleeper} & sleep 10"},   # shell wrapper + grandchild, like Windows
            config={"configurable": {"thread_id": session, "workspace": str(tmp_path)}},
        )
        elapsed = time.monotonic() - started
    finally:
        timer.cancel()
        turn_controls.end(session)

    assert "cancelled by the user" in result, result
    assert "timed out" not in result, "a cancellation must never be answered with the timeout text"
    assert elapsed < 5.0, f"blocked on a pipe held by a surviving child: {elapsed:.1f}s"


@contextlib.contextmanager
def _stdin_is_an_open_pipe(fd: int = 0):
    """Point fd 0 at a pipe nobody writes to — the bridge's exact shape."""
    import os
    read_fd, write_fd = os.pipe()
    saved = os.dup(fd)
    os.dup2(read_fd, fd)
    os.close(read_fd)
    try:
        yield
    finally:
        os.dup2(saved, fd)
        os.close(saved)
        os.close(write_fd)


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "the probe redirects POSIX fd 0 and watches what the child inherits; a "
        "Windows child inherits the parent's *process handles*, not its CRT file "
        "descriptors, so os.dup2(0) is invisible to it and this hang cannot be "
        "reproduced here. The white-box pin below carries the contract on every "
        "platform by reading what both Popen sites actually pass."
    ),
)
def test_terminal_children_never_inherit_the_parents_stdin(tmp_path, monkeypatch):
    """A tool child must not be able to read (or block on) our own stdin.

    Under the bridge, fd 0 is the client's JSON-RPC pipe. Inheriting it is doubly
    wrong: an interactive child eats protocol frames, and on Windows the inherited
    write end leaves cmd.exe waiting for an EOF that never comes — the live round's
    hang, which no amount of pipe-reading cleverness could fix because the child was
    never going to exit.
    """
    import shlex, subprocess, sys, time

    monkeypatch.setenv("PULSEAI_TERMINAL_TIMEOUT", "5")
    from src.tools import terminal_tools

    # Quoting has to match the shell that will parse it: shlex emits POSIX single
    # quotes that cmd.exe reads as literal characters, so a Windows-built command
    # fails before stdin is ever involved and the test would fail for the wrong
    # reason (as it did on the first Windows run of this file).
    argv = [sys.executable, "-c", "import sys; sys.stdin.read(); print('saw-eof')"]
    command = (
        subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    )
    with contextlib.redirect_stderr(None):
        started = time.monotonic()
        with _stdin_is_an_open_pipe():
            result = terminal_tools.run_terminal.invoke(
                {"command": command},
                config={"configurable": {"thread_id": "stdin-isolation", "workspace": str(tmp_path)}},
            )
        elapsed = time.monotonic() - started

    assert "saw-eof" in result, f"child did not get an immediate EOF on stdin: {result!r}"
    assert "timed out" not in result, f"stdin inheritance resurrected the hang after {elapsed:.1f}s"


def test_foreground_popen_passes_devnull_stdin(monkeypatch, tmp_path):
    """White-box pin: BOTH spawn sites set it, not just the foreground one."""
    from src.tools import terminal_tools

    captured: list[dict] = []

    class _Fake:
        pid = 4242
        returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(command, **kwargs):
        captured.append(kwargs)
        return _Fake()

    monkeypatch.setattr(terminal_tools.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(terminal_tools, "checkpoint_before_mutation", lambda *a, **k: None, raising=False)
    terminal_tools.run_terminal.invoke(
        {"command": "echo hi"},
        config={"configurable": {"thread_id": "kwargs-pin", "workspace": str(tmp_path)}},
    )
    assert captured, "run_terminal never reached Popen"
    assert captured[0].get("stdin") is terminal_tools.subprocess.DEVNULL

    src = pathlib.Path(terminal_tools.__file__).read_text(encoding="utf-8")
    assert src.count("stdin=subprocess.DEVNULL") >= 2, "start_terminal must not inherit stdin either"

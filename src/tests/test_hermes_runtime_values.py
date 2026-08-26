"""Behavior contracts for the Hermes-derived runtime invariants."""
from __future__ import annotations

import queue
import sqlite3
import threading
import time

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
    assert controls.pop_queued("s") == "then write docs"


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

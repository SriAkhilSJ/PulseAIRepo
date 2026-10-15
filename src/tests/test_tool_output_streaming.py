"""Live terminal output streaming: tool -> bus -> bridge v2 -> pane.

OpenCode shell-output wiring (2026-10-15): the terminal tool pumps lines
as it runs; execute_tool_transaction owns the tool identity; the bridge
projects chunks to the ephemeral `tool_output` frame. The durable record
stays tool_call_end — chunks are a preview, never a second truth.
"""
from __future__ import annotations

import subprocess
import sys

from src.bridge.__main__ import BridgeServer
from src.bridge.protocol import SERVER_EVENTS
from src.dashboard.event_bus import event_bus
from src.runtime.identity import TurnIdentity
from src.runtime.tool_middleware import (
    current_tool_emitter,
    emit_tool_output,
    execute_tool_transaction,
)


def _collect(monkeypatch):
    events = []
    monkeypatch.setattr(event_bus, "emit", lambda t, p: events.append((t, p)))
    return events


def test_tool_output_is_a_v2_server_event():
    assert "tool_output" in SERVER_EVENTS


def test_bridge_projects_tool_output_chunks(tmp_path):
    identity = TurnIdentity.create(session_id="s1", workspace=str(tmp_path))
    frame = BridgeServer._project_event(
        {"type": "tool.output", "event_id": "e9",
         "payload": {"tool_id": "s1-call-3", "tool_name": "terminal", "chunk": "line one\n"}},
        identity,
    )
    assert frame["type"] == "tool_output"
    assert frame["tool_id"] == "call-3"
    assert frame["name"] == "terminal"
    assert frame["text"] == "line one\n"


def test_emit_tool_output_is_noop_outside_a_transaction(monkeypatch):
    events = _collect(monkeypatch)
    emit_tool_output("orphan\n")
    assert events == []


def test_transaction_binds_identity_for_streaming(monkeypatch):
    events = _collect(monkeypatch)

    def invoke():
        emit_tool_output("hello\n")
        current_tool_emitter()("from a worker\n")
        return "done"

    outcome = execute_tool_transaction(
        name="terminal", args={"command": "echo hi"}, tool_call_id="call-9",
        config={"configurable": {"thread_id": "s1", "workspace": "."}},
        invoke=invoke, project=False,
    )
    assert outcome.content == "done"
    chunks = [p for t, p in events if t == "tool.output"]
    assert [c["chunk"] for c in chunks] == ["hello\n", "from a worker\n"]
    assert all(c["tool_id"] == "call-9" and c["tool_name"] == "terminal" for c in chunks)


def test_terminal_tool_streams_lines_and_keeps_envelope(tmp_path, monkeypatch):
    events = _collect(monkeypatch)
    from src.tools import terminal_tools

    config = {"configurable": {"workspace": str(tmp_path), "thread_id": "s1"}}
    command = (
        f'"{sys.executable}" -c "import time; '
        "print('alpha', flush=True); time.sleep(0.3); print('beta', flush=True)\""
    )

    def invoke():
        return terminal_tools.terminal.func(command, config, None)

    outcome = execute_tool_transaction(
        name="terminal", args={"command": command}, tool_call_id="call-1",
        config=config, invoke=invoke, project=False,
    )
    chunks = "".join(p["chunk"] for t, p in events if t == "tool.output")
    assert "alpha" in chunks and "beta" in chunks
    # The durable envelope is byte-for-byte the old contract.
    assert "STDOUT:" in outcome.content
    assert "alpha" in outcome.content and "beta" in outcome.content
    assert "Exit code: 0" in outcome.content


def test_terminal_tool_still_kills_on_timeout(tmp_path):
    from src.tools import terminal_tools

    config = {"configurable": {"workspace": str(tmp_path), "thread_id": "s1"}}
    command = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    result = terminal_tools.terminal.func(command, config, 1)
    assert "timed out" in result

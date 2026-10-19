"""Readiness-probe contracts for verify_ui_workspace / verify_ui_routes.

Field 2026-10-19: `flutter run -d web-server` was still compiling its
first web build when the old 120s stdout-marker probe gave up — and the
failure path left the server process RUNNING, holding the port while
the agent planned around a ghost. The probe now also polls the target
URL over HTTP, waits through slow first builds, and stops the process
it started before reporting failure.
"""
from __future__ import annotations

import pytest

from src.tools import ui_verification


class _FakeTool:
    def __init__(self, fn):
        self._fn = fn
        self.calls: list[dict] = []

    def invoke(self, args, config=None):
        self.calls.append(args)
        return self._fn(args)


@pytest.fixture()
def _fake_terminal(monkeypatch):
    stops: list[str] = []
    state = {"status_text": "Status: RUNNING\ncompiling the web bundle..."}

    def _start(args):
        return "Started background process.\nProcess ID: proc-123"

    def _check(args):
        return state["status_text"]

    def _stop(args):
        stops.append(args["process_id"])
        return "Stopped proc-123"

    import src.tools.terminal_tools as terminal_tools

    monkeypatch.setattr(terminal_tools, "start_terminal", _FakeTool(_start))
    monkeypatch.setattr(terminal_tools, "check_terminal", _FakeTool(_check))
    monkeypatch.setattr(terminal_tools, "stop_terminal", _FakeTool(_stop))
    return state, stops


def test_give_up_stops_the_started_process(_fake_terminal, monkeypatch):
    _state, stops = _fake_terminal
    monkeypatch.setattr(ui_verification, "_READY_DEADLINE_SECONDS", 1)
    monkeypatch.setattr(ui_verification, "_url_answers", lambda url: False)

    process_id, receipt = ui_verification._start_ready_server(
        "flutter run -d web-server", {"configurable": {}}, "http://localhost:8137"
    )
    assert process_id == "proc-123"
    # Caller contract: failure is still detectable by this substring.
    assert "never became ready" in receipt
    # ...and nothing is left listening afterwards.
    assert "stopped" in receipt
    assert stops == ["proc-123"]


def test_http_answer_counts_as_ready(_fake_terminal, monkeypatch):
    _state, stops = _fake_terminal
    monkeypatch.setattr(ui_verification, "_READY_DEADLINE_SECONDS", 30)
    monkeypatch.setattr(ui_verification, "_url_answers", lambda url: True)

    process_id, _receipt = ui_verification._start_ready_server(
        "flutter run -d web-server", {"configurable": {}}, "http://localhost:8137"
    )
    assert process_id == "proc-123"
    assert stops == []  # a ready server is handed to the caller, not stopped


def test_exited_process_breaks_early_and_is_stopped(_fake_terminal, monkeypatch):
    state, stops = _fake_terminal
    state["status_text"] = "Status: COMPLETED\nError: port 8137 already in use"
    monkeypatch.setattr(ui_verification, "_READY_DEADLINE_SECONDS", 300)
    monkeypatch.setattr(ui_verification, "_url_answers", lambda url: False)

    process_id, receipt = ui_verification._start_ready_server(
        "flutter run -d web-server", {"configurable": {}}, "http://localhost:8137"
    )
    assert process_id == "proc-123"
    assert "never became ready" in receipt
    assert stops == ["proc-123"]

"""Foreground->background promotion — hermes terminal_tool.py:966-971.

"An over-cap foreground timeout is a bounded job the caller wants to wait
for (test suites, builds). Refusing it only bought a mechanical retry: 454
refusals in one run, every one re-sent lower/split/background. Promote to a
tracked background process instead; the caller is told in the result. The
`&`/nohup/server guidance stays a refusal: those need the command itself
rewritten, which the tool cannot do safely."

Pulse rejected over-cap requests until now (field 2026-09-04: a
timeout=30000s ask read as 'life long' panic material). This pins the
promotion AND the order: the guidance refusal wins over promotion.
"""
from __future__ import annotations

import os

import pytest

from src.tools import terminal_tools


def _invoke(command: str, timeout, tmp_path, session: str = "promotion-test") -> str:
    return terminal_tools.run_terminal.invoke(
        {"command": command, "timeout": timeout},
        config={"configurable": {"thread_id": session, "workspace": str(tmp_path)}},
    )


def test_over_cap_clean_command_promotes_to_tracked_background(monkeypatch, tmp_path):
    spawned: dict = {}

    def _fake_spawn(command, config):
        spawned["command"] = command
        return f"Process started.\nProcess ID: abc12345\nCommand: {command}"

    monkeypatch.setattr(terminal_tools, "_spawn_tracked_background", _fake_spawn)
    result = _invoke("python -m pytest -x", 30000, tmp_path)  # bounded job, over-cap ask
    # the SAME command runs through the tracked-background spawn, unchanged
    assert spawned["command"] == "python -m pytest -x"
    assert "Process ID: abc12345" in result
    # hermes _PROMOTED_NOTE_POLL_ONLY shape: the caller is told IN the result
    assert "30000s exceeds the" in result and "instead of being refused" in result
    assert "Do NOT re-run it" in result
    # the note names pulse's actual poll tools (hermes names its own)
    assert "check_terminal" in result and "read_terminal_output" in result


def test_over_cap_server_command_still_refused_not_promoted(monkeypatch, tmp_path):
    # hermes :956-964: the `&`/nohup/server guidance STAYS a refusal even
    # over-cap — those need the command itself rewritten, which the tool
    # cannot do safely.
    def _boom(command, config):
        raise AssertionError("promotion must not spawn for guidance shapes")

    monkeypatch.setattr(terminal_tools, "_spawn_tracked_background", _boom)
    result = _invoke("npm run dev", 30000, tmp_path)
    assert result.startswith("⛔ run_terminal refused:")
    assert "start_terminal" in result  # the pivot guidance names the re-send


def test_bounded_request_never_promotes(monkeypatch, tmp_path):
    def _boom(command, config):
        raise AssertionError("bounded foreground must stay foreground")

    monkeypatch.setattr(terminal_tools, "_spawn_tracked_background", _boom)
    result = _invoke("echo bounded-check", 30, tmp_path)
    assert "Exit code: 0" in result
    assert "Process ID" not in result


def test_promotion_spawn_refusal_passes_through_unchanged(monkeypatch, tmp_path):
    # hermes _with_promoted_note: the note attaches only to a successful
    # spawn; an error result is returned unchanged.
    def _refuse(command, config):
        return "⛔ posix floor"

    monkeypatch.setattr(terminal_tools, "_spawn_tracked_background", _refuse)
    result = _invoke("rm -rf /tmp/x", 30000, tmp_path)
    assert result == "⛔ posix floor"
    assert "Do NOT re-run it" not in result


def test_non_positive_timeout_still_rejected_before_any_promotion(tmp_path):
    result = _invoke("echo hi", 0, tmp_path)
    assert "positive number of seconds" in result


def test_cap_env_is_per_call():
    old = os.environ.get("PULSEAI_TERMINAL_MAX_FOREGROUND_TIMEOUT")
    try:
        os.environ["PULSEAI_TERMINAL_MAX_FOREGROUND_TIMEOUT"] = "45"
        assert terminal_tools._foreground_max_timeout() == 45
        os.environ["PULSEAI_TERMINAL_MAX_FOREGROUND_TIMEOUT"] = "junk"
        assert terminal_tools._foreground_max_timeout() == 600  # default
    finally:
        if old is None:
            os.environ.pop("PULSEAI_TERMINAL_MAX_FOREGROUND_TIMEOUT", None)
        else:
            os.environ["PULSEAI_TERMINAL_MAX_FOREGROUND_TIMEOUT"] = old

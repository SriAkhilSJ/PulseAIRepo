"""Hermes foreground/background terminal guard (tools/terminal_tool_guards.py).

The tool refuses, BEFORE any wait, a foreground command it structurally
cannot serve: long-lived server/watch processes and shell backgrounding.
Field tuition without it: `npm run dev` in run_terminal burned the full
foreground timeout twice on 2026-09-07 (316.5s, then again ~2:19 PM)
before the exit-124 pivot. Hermes refuses in zero seconds with the exact
re-send. --help/--version and quoted content are exempt (hermes
_looks_like_help_or_version_command / _strip_quotes).
"""
from __future__ import annotations

from src.tools.terminal_tools import (
    _foreground_background_guidance,
    _looks_like_help_or_version_command,
    _strip_quotes,
)


def test_dev_server_commands_refused_with_the_pivot():
    for cmd in (
        "npm run dev",
        "npm run dev 2>&1 | head -30",          # the exact field command
        "cd D:\\app && npx next dev --port 3000",
        "npx next dev --port 3000",
        "yarn serve",
        "pnpm start",
        "vite",
        "nodemon server.js",
        "uvicorn main:app",
        "python -m http.server 8000",
        "docker compose up",
    ):
        msg = _foreground_background_guidance(cmd)
        assert msg is not None, cmd
        assert "start_terminal" in msg, cmd


def test_bounded_commands_pass_through():
    for cmd in (
        "npm run build",
        "npm run build 2>&1 | tail -50",
        "npm test",
        "npm install",
        "node -e console.log(1)",
        "git status",
        "ls .next/BUILD_ID 2>/dev/null || echo no",
    ):
        assert _foreground_background_guidance(cmd) is None, cmd


def test_help_and_version_exempt():
    assert _looks_like_help_or_version_command("npx next dev --help")
    assert _looks_like_help_or_version_command("vite --version")
    assert _foreground_background_guidance("npx next dev --help") is None
    assert not _looks_like_help_or_version_command("next dev --port 3000")


def test_quoted_content_cannot_trigger_the_guard():
    # hermes _strip_quotes: keywords inside strings never match
    assert _strip_quotes('echo "npm run dev"') == 'echo ""'
    assert _foreground_background_guidance('echo "npm run dev"') is None
    assert _foreground_background_guidance("cat 'vite' ") is None


def test_shell_backgrounding_refused():
    # hermes _FOREGROUND_GUIDANCE is ordered first-hit-wins: a command can hit
    # both the server pattern and the '&' pattern; either refusal is correct.
    assert "nohup" in _foreground_background_guidance("nohup npm run dev &")
    for cmd in ("(npx next dev > log 2>&1 &) && sleep 5", "npm run dev &"):
        msg = _foreground_background_guidance(cmd)
        assert msg is not None, cmd
        assert "start_terminal" in msg, cmd


def test_guard_fires_in_run_terminal_before_any_wait(tmp_path, monkeypatch):
    """End-to-end: run_terminal refuses the field command in zero seconds --
    no spawn, no timeout burn (hermes terminal_tool.py :965 position)."""
    from src.tools.terminal_tools import run_terminal

    spawned = []

    class FakePopen:
        def __init__(self, *a, **kw):
            spawned.append(a)
            raise AssertionError("run_terminal must not spawn a guarded command")

    monkeypatch.setattr("src.tools.terminal_tools.subprocess.Popen", FakePopen)
    config = {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}}
    out = run_terminal.invoke(
        {"command": "cd D:\\x && npm run dev 2>&1 | head -30"}, config=config)
    assert "run_terminal refused" in out
    assert "start_terminal" in out
    assert spawned == []

"""Windows shell hints — hermes prompt_builder._WINDOWS_BASH_SHELL_HINT.

Verified against hermes source (owner directive 2026-09-08: "error is
related to prompt engineering <high chances> so check hermes"): hermes
runs the Windows terminal through git-bash (environments/local.py
_find_bash — "Hermes Agent requires Git for Windows on Windows") AND
teaches the model the dialect in the system prompt (prompt_builder.py:826:
POSIX syntax, MSYS paths alongside native ones, PowerShell builtins will
NOT work, native-tool paths are NOT translated). Pulse had the execution
half (select_shell -> bash) but only a one-line "Terminal dialect: ..."
hint — field 2026-09-08: the model mixed `D:\\...` and `/d/...` shapes
across calls in one turn, guessing its dialect. The dialect must be
taught; and when bash is absent the model must be told cmd.exe is the
shell, just as loudly.
"""
from __future__ import annotations

from src.prompts.hermes import environment as env


def test_windows_bash_hint_is_taugth_not_named(monkeypatch):
    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr(
        "src.runtime.windows_shell.windows_bash_available", lambda: True
    )
    hints = env.build_environment_hints(cwd=None)
    # hermes hint content, adapted to pulse's tool names
    assert "runs commands through bash (git-bash / MSYS)" in hints
    assert "NOT PowerShell or cmd.exe" in hints
    assert "Use POSIX shell syntax" in hints
    assert "will NOT" in hints and "Get-ChildItem" in hints
    # native-tool path caveat (hermes: MSYS does not translate argv)
    assert "NATIVE Windows programs" in hints
    # the old weak one-liner must not coexist with the taught block
    assert "Terminal dialect: bash" not in hints


def test_windows_cmd_hint_names_the_fallback_truthfully(monkeypatch):
    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr(
        "src.runtime.windows_shell.windows_bash_available", lambda: False
    )
    hints = env.build_environment_hints(cwd=None)
    assert "runs commands through cmd.exe" in hints
    assert "NOT bash" in hints
    assert "MSYS paths (`/d/...`) will NOT work" in hints


def test_posix_hosts_keep_the_plain_dialect_line(monkeypatch):
    monkeypatch.setattr(env, "is_windows", lambda: False)
    hints = env.build_environment_hints(cwd=None)
    assert "Terminal dialect: POSIX shell dialect." in hints
    assert "runs commands through bash (git-bash / MSYS)" not in hints


def test_bash_probe_includes_user_scope_git(monkeypatch):
    """hermes _windows_bash_candidates: %LOCALAPPDATA%\Programs\Git is a
    first-class candidate (user-scope install, no admin)."""
    import src.runtime.windows_shell as ws
    probed = []
    monkeypatch.setattr(ws, "_IS_WINDOWS", True)
    monkeypatch.setattr(ws, "_probe_path", lambda c: probed.append(c) or None)
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/u/AppData/Local")
    ws._probe_cache = False
    try:
        assert ws.windows_bash() is None
    finally:
        ws._probe_cache = False
    assert any("Programs" in p and "Git" in p for p in probed), probed
    assert probed[-1] == "bash.exe", "PATH must be probed LAST (WSL-bash guard)"

"""The prompt must state what the terminal gate ENFORCES -- one truth.

Owner desktop run (2026-09-03): the Windows environment block appended the
upstream hermes bash hint ("runs commands through bash ... Use `ls` ...
PowerShell builtins will NOT work") DIRECTLY OPPOSITE the gate's enforced
reality ("Terminal dialect: cmd.exe ... POSIX-only verbs are NOT available").
The model's own think-tool text shows it reading both and gambling on bash;
`ls` was refused pre-spawn and the turn burned. Pinned: on Windows the block
names cmd/PowerShell truth and NEVER the bash hint.
"""
from __future__ import annotations


def test_windows_environment_block_never_preaches_bash(monkeypatch):
    from src.prompts.hermes import environment as env

    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr(env, "WINDOWS_BASH_SHELL_HINT", (
        "Shell: on this Windows host your run_terminal tool runs commands "
        "through bash (git-bash / MSYS), NOT PowerShell or cmd.exe."
    ))
    block = env.build_environment_hints()

    assert "git-bash" not in block, "the banned bash hint leaked into the block"
    assert "through bash" not in block
    assert "Terminal dialect:" in block
    assert "NOT available" in block, "the enforced pivot guidance must stay"


def test_windows_block_still_guides_to_powershell(monkeypatch):
    from src.prompts.hermes import environment as env

    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr(env, "WINDOWS_BASH_SHELL_HINT", "through bash (git-bash / MSYS)")
    block = env.build_environment_hints()
    assert "PowerShell/cmd" in block or "Get-ChildItem" in block


def test_non_windows_blocks_unchanged(monkeypatch):
    from src.prompts.hermes import environment as env

    monkeypatch.setattr(env, "is_windows", lambda: False)
    monkeypatch.setattr(env, "_is_wsl", lambda: False)
    block = env.build_environment_hints()
    assert "Windows terminal dialect" not in block


# ------------------------------------------------ hermes timeout contract
def test_foreground_timeout_contract():
    """Hermes terminal contract (tools/terminal_tool.py:943-957), ported:
    model-owned timeout — coerced from strings (models send '30000'),
    rejected when non-positive, capped at the foreground max with the
    background pivot. The owner's 'terminal ran life long' was a 30000s
    request the engine silently ignored into a 300s wait — and a repo-wide
    recursive listing that should never have been attempted."""
    from src.tools.terminal_tools import _foreground_timeout

    # model's explicit timeout is honored (string-safe)
    assert _foreground_timeout("45") == (45, None)
    assert _foreground_timeout(120) == (120, None)
    # default when absent/blank/garbage
    assert _foreground_timeout(None)[0] >= 1
    assert _foreground_timeout("  ")[0] >= 1
    assert _foreground_timeout("abc")[0] >= 1
    # non-positive rejected
    eff, rejection = _foreground_timeout("0")
    assert eff == 0 and "positive number of seconds" in rejection
    # over-cap rejected with the background pivot (hermes wording)
    eff, rejection = _foreground_timeout(30000)
    assert eff == 0
    assert "exceeds the maximum" in rejection and "start_terminal" in rejection


def test_foreground_timeout_cap_env(monkeypatch):
    from src.tools.terminal_tools import _foreground_timeout

    monkeypatch.setenv("PULSEAI_TERMINAL_MAX_FOREGROUND_TIMEOUT", "120")
    eff, rejection = _foreground_timeout(121)
    assert eff == 0 and "exceeds the maximum of 120s" in rejection
    assert _foreground_timeout(120) == (120, None)
    # cap sanity floor: 30s minimum even if env says something silly
    monkeypatch.setenv("PULSEAI_TERMINAL_MAX_FOREGROUND_TIMEOUT", "1")
    eff, rejection = _foreground_timeout(31)
    assert eff == 0 and "exceeds the maximum of 30s" in rejection

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

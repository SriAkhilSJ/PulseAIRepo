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


def test_windows_block_matches_backend_bash(monkeypatch):
    """Backend truth (2026-09-05): with git-bash present the terminal SPAWNS
    bash (hermes' Windows backend; terminal_tools bypasses the POSIX gate),
    so the block must preach bash — the old ban was the cmd-gate era."""
    from src.prompts.hermes import environment as env

    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr("src.runtime.windows_shell.windows_bash_available", lambda: True)
    block = env.build_environment_hints()

    assert "through bash (git-bash / MSYS)" in block
    assert "PowerShell builtins" in block and "will NOT work" in block
    assert "cmd.exe dialect" not in block


def test_windows_block_cmd_fallback_still_honest(monkeypatch):
    """No git-bash (or PULSEAI_WINDOWS_BASH=off): cmd.exe truth — no bash
    hint, and PowerShell cmdlets named as NOT commands (field 2026-09-05:
    Get-ChildItem|Select-Object into cmd.exe -> exit 255 -> recovery limit)."""
    from src.prompts.hermes import environment as env

    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr("src.runtime.windows_shell.windows_bash_available", lambda: False)
    block = env.build_environment_hints()

    assert "through bash" not in block, "the bash hint leaked into the cmd block"
    assert "Terminal dialect:" in block
    assert "cmd" in block
    assert "powershell -NoProfile -Command" in block


def test_windows_cmd_fallback_guides_cmd_equivalents(monkeypatch):
    from src.prompts.hermes import environment as env

    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr("src.runtime.windows_shell.windows_bash_available", lambda: False)
    block = env.build_environment_hints()
    assert "dir, findstr, type" in block or "Get-ChildItem" in block


def test_windows_dialect_name_follows_backend(monkeypatch):
    """terminal_dialect() states the ACTUAL spawn shell."""
    from src.prompts.hermes import environment as env

    monkeypatch.setattr(env, "is_windows", lambda: True)
    monkeypatch.setattr("src.runtime.windows_shell.windows_bash_available", lambda: True)
    assert "bash" in env.terminal_dialect()
    monkeypatch.setattr("src.runtime.windows_shell.windows_bash_available", lambda: False)
    assert "cmd.exe" in env.terminal_dialect()


def test_select_shell_bash_backend(monkeypatch):
    """Hermes backend: [bash, -c, command] with shell=False; gate bypass is
    keyed on the same selection."""
    import src.tools.terminal_tools as tt
    from src.runtime.windows_shell import select_shell

    monkeypatch.setattr(tt, "_IS_WINDOWS", True)
    monkeypatch.setattr("src.runtime.windows_shell.windows_bash", lambda o="": r"C:\Program Files\Git\bin\bash.exe")
    monkeypatch.setattr("src.runtime.windows_shell._IS_WINDOWS", True)
    argv, shell_flag, dialect = select_shell("dir /b")
    assert argv == [r"C:\Program Files\Git\bin\bash.exe", "-c", "dir /b"]
    assert shell_flag is False and dialect == "bash"
    # gate bypass lives at the run_terminal call site: under the bash
    # dialect POSIX IS the dialect, so the guard never fires
    assert select_shell("ls -la | grep foo")[2] == "bash"


def test_select_shell_cmd_fallback(monkeypatch):
    import src.tools.terminal_tools as tt
    from src.runtime.windows_shell import select_shell

    monkeypatch.setattr(tt, "_IS_WINDOWS", True)
    monkeypatch.setattr("src.runtime.windows_shell.windows_bash", lambda o="": None)
    monkeypatch.setattr("src.runtime.windows_shell._IS_WINDOWS", True)
    argv, shell_flag, dialect = select_shell("dir /b")
    assert argv is None and shell_flag is True and dialect == "cmd"
    assert tt._posix_violations("ls -la") != []


def test_windows_bash_override_off(monkeypatch):
    """PULSEAI_WINDOWS_BASH=off forces the cmd fallback even with git-bash."""
    import src.runtime.windows_shell as ws

    monkeypatch.setenv("PULSEAI_WINDOWS_BASH", "off")
    assert ws.windows_bash_available() is False


def test_read_only_commands_skip_shadow_checkpoint():
    """Field 2026-09-05: `dir /b /s` paid a 24.3s shadow checkpoint before a
    listing. Hermes checkpoints MUTATIONS, not reads; the classifier must
    skip pure reads and still snapshot mutations/unknowns."""
    import src.tools.terminal_tools as tt

    for read in ("dir /b /s D:\\x", "dir /b D:\\x | findstr /i test",
                 "git status", "git log --oneline", "rg --files src",
                 "Get-Content a.txt", "type README.md"):
        assert not tt._looks_mutating(read), read
    for mutation in ("rm -rf build", "del /q x.txt", "git reset --hard",
                     "git commit -m x", "echo hi > out.txt", "npm install",
                     "python script.py"):
        assert tt._looks_mutating(mutation), mutation


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


def test_hermes_terminal_name_alias_executes(tmp_path):
    """Field run 2026-09-05: the model emitted the tool name `terminal`
    (hermes' name) — pulse only knew `run_terminal`, the unknown-name
    rejection ended the turn as "Tool failed: terminal" / "Ended
    incomplete: list the files". The hermes name must EXECUTE with the
    run_terminal contract, not reject."""
    from src.tools.terminal_tools import terminal

    assert terminal.name == "terminal"
    out = terminal.invoke(
        {"command": "echo pulse_alias_probe"},
        {"configurable": {"workspace": str(tmp_path)}},
    )
    assert "pulse_alias_probe" in out
    assert "Exit code: 0" in out


def test_hermes_terminal_alias_in_execution_toolset():
    """The alias binds wherever run_terminal binds — a hermes-trained tool
    call must never hit the unknown-name path again."""
    from src.tools.toolsets import _EXECUTION_TOOLS

    assert "terminal" in _EXECUTION_TOOLS
    assert "run_terminal" in _EXECUTION_TOOLS

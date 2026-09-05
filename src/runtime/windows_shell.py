"""The Windows shell behind the terminal tools — hermes' backend, stated.

Hermes (tools/terminal_tool_config.py + prompt_builder._WINDOWS_BASH_SHELL_HINT):
on a Windows host, the local terminal backend runs commands through
git-bash / MSYS, NOT cmd.exe or PowerShell. Field proof 2026-09-05: models
repeatedly blended PowerShell cmdlets (`Get-ChildItem | Select-Object`,
`2>$null`) into cmd.exe — cmd runs NEITHER POSIX NOR PowerShell cmdlets —
and two exit-255 failures drove a turn to the recovery limit. The POSIX
gate + cmd teaching were pulse's invention for a backend hermes never
runs; with bash present the gate is obsolete (POSIX IS the dialect) and
hermes' bash hint becomes the honest environment truth.

`PULSEAI_WINDOWS_BASH` — explicit override: a path to bash.exe, or
`off`/`0`/`false` to force the cmd.exe fallback. Read PER CALL (standing
rule); only the PATH probe below it is cached per process.
"""
from __future__ import annotations

import os
import platform
import shutil

_IS_WINDOWS = platform.system() == "Windows"

# Standard Git-for-Windows installs (hermes' setup expects git-bash on
# Windows; every machine that clones the repo has at least one of these).
_CANDIDATE_PATHS = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)

_probe_cache: str | None | bool = False  # False = not yet probed


def _probe_path(candidate: str) -> str | None:
    if os.path.isabs(candidate):
        return candidate if os.path.isfile(candidate) else None
    return shutil.which(candidate)


def windows_bash(override: str = "") -> str | None:
    """Absolute path to bash.exe for this host, or None (cmd.exe fallback)."""
    global _probe_cache
    if override:
        if override.lower() in {"off", "0", "false", "no", "disabled"}:
            return None
        found = _probe_path(override)
        return found
    if _probe_cache is not False:
        return _probe_cache or None
    if not _IS_WINDOWS:
        _probe_cache = None
        return None
    found: str | None = None
    for candidate in (*_CANDIDATE_PATHS, "bash.exe"):
        found = _probe_path(candidate)
        if found:
            break
    _probe_cache = found or None
    return _probe_cache


def windows_bash_available() -> bool:
    """Env-truth for the prompt block: does the terminal run bash here?"""
    override = os.environ.get("PULSEAI_WINDOWS_BASH", "").strip()
    if override.lower() in {"off", "0", "false", "no", "disabled"}:
        return False
    return windows_bash(override) is not None


def select_shell(command: str) -> tuple[list[str] | None, bool, str]:
    """(argv, shell, dialect) for spawning `command` on this host.

    bash present  -> ([bash, "-c", command], False, "bash")  hermes backend
    otherwise     -> (None, True, "cmd")                     legacy fallback
    """
    if _IS_WINDOWS and windows_bash_available():
        override = os.environ.get("PULSEAI_WINDOWS_BASH", "").strip()
        bash = windows_bash(override) or windows_bash("")
        if bash:
            return [bash, "-c", command], False, "bash"
    return None, True, "cmd"

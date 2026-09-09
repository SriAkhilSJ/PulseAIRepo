"""Environment hints — port of ``build_environment_hints`` + platform-hint resolution.

Upstream renders the facts the model cannot infer from its own persona (which
OS, which shell dialect, whether the workspace is a git repo, whether the host
is remote) into the *stable* tier, because they are stable for the life of the
process and therefore cache-safe. Pulse's equivalents come from its own
runtime: the Windows dialect rule already paid for itself in Attempt-5 (POSIX
verbs sent to ``cmd.exe``), so it rides the same slot here.
"""
from __future__ import annotations

import logging
import os
import platform as _platform
import sys
from pathlib import Path
from typing import Any, Optional

from src.prompts.hermes.context_files import find_git_root
from src.prompts.hermes.guidance import WINDOWS_BASH_SHELL_HINT, WSL_ENVIRONMENT_HINT

logger = logging.getLogger(__name__)

_POSIX_ONLY_VERBS = "ls, pwd, find, head, tail, grep, cat"

# ── Single-source shell teachings (field 2026-09-09 @7a7111b9) ────────────
# The environment block AND the runtime banner (chat_graph) must never
# disagree: that run's banner claimed "Windows cmd.exe. NEVER use ls" on a
# git-bash host (receipts: /usr/bin/bash) while this block taught POSIX in
# the same prompt — the model obeyed the banner and issued Get-ChildItem /
# `cd /d "..."` into bash (both failed). One text, both carriers.
_WINDOWS_BASH_TERMINAL_TEACHING = (
    "Shell: on this Windows host your `terminal` tool runs commands "
    "through bash (git-bash / "
    "MSYS), NOT PowerShell or cmd.exe. Use POSIX shell syntax "
    "(`ls`, `$HOME`, `&&`, `|`, single-quoted strings) inside "
    "terminal calls. MSYS-style paths like `/d/TestPulseAI/...` "
    "work alongside native `D:\\TestPulseAI\\...` paths for bash "
    "builtins (`cd`, `echo`, redirection). PowerShell builtins "
    "(`Get-ChildItem`, `$env:FOO`, `Select-String`) will NOT "
    "work — use their POSIX equivalents (`ls`, `$FOO`, `grep`). "
    "Path arguments for NATIVE Windows programs (git, rg, node, "
    "npm, python, ...) are NOT translated by MSYS: pass them "
    "`D:/TestPulseAI/x`-style forward-slash native paths, and "
    "prefer a temp dir inside the workspace over `/tmp` when a "
    "native tool must read the file."
)


def _windows_cmd_terminal_teaching() -> str:
    shell = (os.environ.get("COMSPEC") or "").lower()
    shell_name = ("PowerShell" if ("pwsh" in shell or "powershell" in shell)
                  else "cmd.exe")
    return (
        f"Shell: on this Windows host your `terminal` tool runs commands "
        f"through {shell_name} — NOT "
        "bash. POSIX syntax (`ls`, `grep`, `|`, `$HOME`, `2>/dev/null`) "
        "and MSYS paths (`/d/...`) will NOT work. Use cmd.exe syntax "
        "(`dir`, `findstr`, `set`, `%VAR%`, `2>nul`) or native "
        "forward-slash paths (`D:/folder/file`) for tools."
    )


def windows_terminal_banner() -> str:
    """The dialect teaching for the runtime banner — the SAME truth the
    environment block carries, keyed by the same `windows_bash_available()`
    detection. Returns "" off-Windows (no banner is inserted there).

    The banner rides `_insert_system_prefix` AFTER context assembly, so it
    survives layer trims that could drop the environment block; that is why
    both carriers exist — and why they must share this one text.
    """
    if not is_windows():
        return ""
    from src.runtime.windows_shell import windows_bash_available
    if windows_bash_available():
        return _WINDOWS_BASH_TERMINAL_TEACHING
    return _windows_cmd_terminal_teaching()


def _is_wsl() -> bool:
    try:
        if Path("/proc/version").exists():
            return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except Exception:
        pass
    return "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ


def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def terminal_dialect() -> str:
    """The shell the terminal tool actually spawns — stated, never assumed."""
    if is_windows():
        from src.runtime.windows_shell import windows_bash_available
        if windows_bash_available():
            return "bash (git-bash / MSYS) dialect"
        shell = (os.environ.get("COMSPEC") or "").lower()
        if "pwsh" in shell or "powershell" in shell:
            return "Windows PowerShell/cmd.exe dialect"
        return "cmd.exe dialect"
    return "POSIX shell dialect"


def git_snapshot(cwd: Path) -> dict:
    root = find_git_root(cwd)
    if root is None:
        return {"is_repo": False, "root": "", "branch": ""}
    branch = ""
    try:
        head = (root / ".git" / "HEAD")
        if head.exists():
            raw = head.read_text(encoding="utf-8").strip()
            if raw.startswith("ref: refs/heads/"):
                branch = raw[len("ref: refs/heads/"):]
    except Exception as exc:
        logger.debug("git branch read failed: %s", exc)
    return {"is_repo": True, "root": str(root), "branch": branch}


def build_environment_hints(cwd: Optional[Path] = None) -> str:
    """Compose the stable environment block for this process ("" when nothing to say).

    Hermes shape (agent/prompt_builder.py:_local_host_hints): the model gets
    Host / User home directory / Current working directory as FLAT FACTS, plus
    on Windows the hostname-is-not-username note. The working-directory line is
    what lets an unqualified request ("list the files") resolve without a
    clarifying question — field 2026-09-06: the model asked which directory to
    explore because no prompt fact named one.
    """
    parts: list[str] = []

    workspace = Path(cwd) if cwd is not None else Path.cwd()

    # ── Hermes local-host block (verbatim fact lines) ────────────────────
    system = _platform.system() or ("Windows" if is_windows() else ("Darwin" if sys.platform == "darwin" else "Linux"))
    release = _platform.release()
    parts.append(f"Host: {system} ({release}). Python {sys.version_info.major}.{sys.version_info.minor}.")
    parts.append(f"User home directory: {Path.home()}")
    parts.append(f"Current working directory: {workspace}")

    if is_windows():
        parts.append(
            "Note: on Windows, the machine hostname (e.g. from `hostname` or uname) is NOT the "
            "username. Use the 'User home directory' above to construct paths under "
            "C:\\Users\\<user>\\, never the hostname."
        )

    if is_windows():
        from src.runtime.windows_shell import windows_bash_available
        if windows_bash_available():
            # hermes agent/prompt_builder.py:_WINDOWS_BASH_SHELL_HINT — the
            # dialect must be TAUGHT, not named (field 2026-09-08: with only
            # "Terminal dialect: bash ..." the model mixed `D:\...` and
            # `/d/...` across calls in one turn because it was guessing).
            parts.append(_WINDOWS_BASH_TERMINAL_TEACHING)
        else:
            parts.append(_windows_cmd_terminal_teaching())
    else:
        parts.append(f"Terminal dialect: {terminal_dialect()}.")

    # hermes paints toolset availability at load (agent_init :1080-1088);
    # the model-facing carrier here is the env block. Browser-stack absence
    # is a host STATE fact: without it the model improvises (built a stray
    # page instead of testing — field 2026-09-07 1:34 PM).
    try:
        from src.tools.browser_tools import find_agent_browser
        find_agent_browser()
    except Exception:
        parts.append(
            "Browser tools: NOT available on this host (agent-browser CLI "
            "not found). Install with `npm install -g agent-browser`, then "
            "run `agent-browser install` once. Until then, a testing ask "
            "cannot be executed in a browser — say so and name the install "
            "step; do not substitute building pages or scripts."
        )

    if is_windows():
        from src.runtime.windows_shell import windows_bash_available
        if windows_bash_available():
            # Backend flipped to hermes' own: bash (git-bash/MSYS) spawns the
            # commands, so the gate that banned POSIX is bypassed in
            # terminal_tools and hermes' hint is the TRUTH here. Ported
            # verbatim up to the sentence that references hermes-only tools
            # (pty `process(submit)`/`process(write)` do not exist in pulse —
            # same rule that banned this hint under cmd: the block never
            # names a tool the runtime lacks).
            parts.append(
                "# Windows terminal dialect\n"
                "Shell: on this Windows host your `terminal` tool runs commands "
                "through bash (git-bash / MSYS), NOT PowerShell or cmd.exe. Use "
                "POSIX shell syntax (`ls`, `$HOME`, `&&`, `|`, single-quoted "
                "strings) inside terminal calls. MSYS-style paths like "
                "`/c/Users/<user>/...` work alongside native "
                "`C:\\Users\\<user>\\...` paths. PowerShell builtins "
                "(`Get-ChildItem`, `$env:FOO`, `Select-String`) will NOT work — "
                "use their POSIX equivalents (`ls`, `$FOO`, `grep`). Path "
                "arguments for NATIVE Windows programs (git, rg, node, python, "
                "...) are NOT translated: MSYS path conversion is disabled "
                "here, so `git -C /c/Users/x` or `node /tmp/a.js` fails with "
                "'cannot change to'/'not found' even though `cd /c/Users/x` (a "
                "bash builtin) works. Pass `C:/Users/x`-style forward-slash "
                "native paths to native tools, and prefer `$LOCALAPPDATA/Temp` "
                "over `/tmp` for scratch files a native tool must read."
            )
        else:
            # cmd.exe fallback (PULSEAI_WINDOWS_BASH=off or no git-bash):
            # SINGLE SOURCE OF TRUTH (owner desktop run 2026-09-03): the
            # terminal gate refuses POSIX verbs on EVERY cmd host, so the
            # block states the enforced reality and nothing else.
            parts.append(
                "# Windows terminal dialect\n"
                f"The terminal tool runs {terminal_dialect()}. POSIX-only verbs "
                f"({_POSIX_ONLY_VERBS}) are NOT available — use the cmd "
                "equivalents (dir, findstr, type). PowerShell cmdlets "
                "(Get-ChildItem, Select-Object) are NOT commands here either: "
                "cmd.exe cannot run them — prefix real PowerShell with "
                "`powershell -NoProfile -Command \"...\"`. Shell backgrounding "
                "(`( cmd & )`) and `/tmp` do not exist here either: long-running "
                "processes go through the start_terminal tool, and scratch "
                "files go under %TEMP%. Do not emit a shape the shell cannot run."
            )
    elif _is_wsl():
        parts.append(
            WSL_ENVIRONMENT_HINT
            or "# WSL\nRunning inside Windows Subsystem for Linux: /mnt/c paths are on the Windows drive."
        )

    workspace = Path(cwd) if cwd is not None else Path.cwd()
    git = git_snapshot(workspace) if workspace.exists() else {"is_repo": False, "root": "", "branch": ""}
    if git["is_repo"]:
        branch = f" on branch `{git['branch']}`" if git["branch"] else ""
        parts.append(f"Workspace: {workspace} — git repository rooted at {git['root']}{branch}.")
    elif workspace.exists():
        parts.append(f"Workspace: {workspace} — not a git repository.")
    # A workspace that does not exist on THIS host (a Windows drive path probed
    # from a POSIX engine) reports no git facts at all: find_git_root would
    # resolve the missing path upward and name a bogus root (probed live).

    return "\n\n".join(p for p in parts if p).strip()


def resolve_platform_hint(default_hint: str, platform_key: str, overrides: Optional[dict]) -> str:
    """Apply a per-platform prompt-hint override (``replace`` / ``append`` / bare string).

    Precedence: ``replace`` wins over ``append``. Malformed entries fall back to
    the unmodified default so a bad config value can never break prompt assembly
    or leak text across platforms.
    """
    if not platform_key:
        return default_hint
    if not isinstance(overrides, dict) or not overrides:
        return default_hint
    spec = overrides.get(platform_key)
    if spec is None:
        return default_hint
    if isinstance(spec, str):
        extra = spec.strip()
        return f"{default_hint}\n\n{extra}".strip() if extra else default_hint
    if not isinstance(spec, dict):
        return default_hint
    replace_text = spec.get("replace")
    if isinstance(replace_text, str) and replace_text.strip():
        return replace_text.strip()
    append_text = spec.get("append")
    if isinstance(append_text, str) and append_text.strip():
        return f"{default_hint}\n\n{append_text.strip()}".strip()
    return default_hint


#: Pulse's execution modes (bridge protocol v2) as a prompt surface note.
#: Same slot as upstream's per-platform hint: stable for the life of a session.
MODE_HINTS: dict[str, str] = {
    "agent": (
        "Execution mode: agent — full guarded workflow. Act with tools, verify "
        "before claiming completion."
    ),
    "plan": (
        "Execution mode: plan — planning only. Read-only inspection is allowed; "
        "do not implement, do not run mutating commands, do not perform external "
        "actions. Your deliverable is the plan itself."
    ),
    "debug": (
        "Execution mode: debug — diagnosis first. Reproduce and read before you "
        "change; every claim about the failure needs an observed receipt."
    ),
    "ask": "Execution mode: ask — answer from context. No tools are bound this turn; say what you would do instead of doing it.",
}


def mode_hint(mode: Optional[str]) -> str:
    return MODE_HINTS.get((mode or "").strip().lower(), "")


__all__ = [
    "MODE_HINTS",
    "build_environment_hints",
    "git_snapshot",
    "is_windows",
    "mode_hint",
    "resolve_platform_hint",
    "terminal_dialect",
    "windows_terminal_banner",
]

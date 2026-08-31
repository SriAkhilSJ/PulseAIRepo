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
    """Compose the stable environment block for this process ("" when nothing to say)."""
    parts: list[str] = []
    system = _platform.system() or ("Windows" if is_windows() else ("Darwin" if sys.platform == "darwin" else "Linux"))
    release = _platform.release()
    parts.append(f"Environment: {system} {release}, Python {sys.version_info.major}.{sys.version_info.minor}.")
    parts.append(f"Terminal dialect: {terminal_dialect()}.")

    if is_windows():
        parts.append(
            "# Windows terminal dialect\n"
            f"The terminal tool runs {terminal_dialect()}. POSIX-only verbs "
            f"({_POSIX_ONLY_VERBS}) are NOT available — use the PowerShell/cmd "
            "equivalents (Get-ChildItem, Select-Object -First, findstr). Do not "
            "emit a POSIX shape and hope. "
            + (WINDOWS_BASH_SHELL_HINT if WINDOWS_BASH_SHELL_HINT else "")
        )
    elif _is_wsl():
        parts.append(
            WSL_ENVIRONMENT_HINT
            or "# WSL\nRunning inside Windows Subsystem for Linux: /mnt/c paths are on the Windows drive."
        )

    workspace = Path(cwd) if cwd is not None else Path.cwd()
    git = git_snapshot(workspace)
    if git["is_repo"]:
        branch = f" on branch `{git['branch']}`" if git["branch"] else ""
        parts.append(f"Workspace: {workspace} — git repository rooted at {git['root']}{branch}.")
    else:
        parts.append(f"Workspace: {workspace} — not a git repository.")

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
]

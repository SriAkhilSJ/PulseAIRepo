"""Git Context Layer — branch, working-tree, and history awareness.

Answers "what did I change?", "fix the bug I just introduced", "write a
commit message" without the agent burning tool calls on shell commands.

Every git invocation is a local, read-only subprocess with an OWNED hard
deadline.  Hard requirements for desktop safety:

* the whole layer, not each command, carries ONE aggregate budget — on a
  healthy machine the six read-only commands finish well inside it, and a
  wedged/shimsy git can never turn a single turn into ~18s of git work;
* each command may only use the budget remaining on the layer deadline; once
  that deadline passes, no further git process is started and the layer
  returns the partial context it already has;
* ownership-safe termination: on timeout we kill the exact spawned process
  tree (`taskkill /PID <pid> /T /F` on Windows, the owned process group on
  POSIX) and only then reap the Popen object — never a broad `taskkill
  git.exe`.  Windows git shims (Scoop/MSYS2/VS SHA) spawn helper processes
  that inherit pipe handles; `subprocess.run`'s timeout kills only the direct
  child, so `communicate()` can block on a pipe EOF that never arrives.

The layer returns None outside a git repository, so non-git workspaces are
unaffected.  Marked VOLATILE in ContextEngine: the working tree changes
outside the graph state dict, so this layer is rebuilt every turn instead of
being served from the differential layer cache.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage

# Whole-layer aggregate budget (seconds).  The six candidate commands share
# it: on a healthy box all six finish well inside it (measured ~0.3s warm,
# ~1.0s cold), while a wedged git can never consume more than this per turn.
# The layer may return partial context; it must never block the prompt.
_GIT_BUDGET_S = 1.0
# Per-command fallback cap if a caller invokes _run_git directly.
_GIT_TIMEOUT_S = 3.0
# Give taskkill / os.killpg enough time to reap before the fallback kill.
_REAP_TIMEOUT_S = 5.0
_TASKKILL_TIMEOUT_S = 5.0

# Indirections the tests replace so every code path is exercised without a
# real repo or a long sleep on the test runner's wall clock.
_MONOTONIC = time.monotonic
_SPAWN = subprocess.Popen
_GIT_BIN = "git"

# Windows git commanders (git.exe, its shims, their grandchildren) are console
# apps.  CREATE_NO_WINDOW stops a stray console from flapping on the user's
# desktop; CREATE_NEW_PROCESS_GROUP gives the direct child a group we own so a
# POSIX-ports-like fallback could still address it.
if os.name == "nt":
    _GIT_CREATION_FLAGS = 0x08000000 | subprocess.CREATE_NEW_PROCESS_GROUP
else:
    _GIT_CREATION_FLAGS = 0

# No interactive prompts, ever: this layer is unattended and read-only.
_GIT_ENV_OVERRIDES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "Never",
    "GIT_OPTIONAL_LOCKS": "0",
}

_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


def _taskkill_tree(pid: int) -> None:
    """Kill the exact owned process tree, non-interactively, best-effort."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_TASKKILL_TIMEOUT_S,
        )
    except Exception:
        pass


def _kill_group(proc: "subprocess.Popen[str]") -> None:
    try:
        os.killpg(os.getpgid(proc.pid), _KILL_SIGNAL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            pass


def _reap(proc: "subprocess.Popen[str]") -> None:
    """Reap the Popen (drain pipes, join communicate's read threads)."""
    try:
        proc.wait(timeout=_REAP_TIMEOUT_S)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _terminate(proc: "subprocess.Popen[str]") -> None:
    if os.name == "nt":
        _taskkill_tree(proc.pid)  # exact owned root only — never a global name
    else:
        _kill_group(proc)
    _reap(proc)


def _run_git(cmd: list[str], cwd: str | Path, timeout: float | None = None) -> str:
    """Run a read-only git command; empty string on any failure.

    Read-only matters: this runs unattended every turn, so the command set
    must never include anything that writes (no fetch, no gc, no config).
    """
    per_command = _GIT_TIMEOUT_S if timeout is None else timeout
    env = dict(os.environ)
    env.update(_GIT_ENV_OVERRIDES)
    try:
        proc = _SPAWN(
            [_GIT_BIN, *cmd],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,   # no repo can ask us for a password
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            creationflags=_GIT_CREATION_FLAGS,
            start_new_session=(os.name != "nt"),
        )
    except Exception:
        # git missing, cwd missing — the layer is optional, degrade.
        return ""
    try:
        stdout, _stderr = proc.communicate(timeout=per_command)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        return ""
    except Exception:
        _reap(proc)
        return ""
    return stdout if proc.returncode == 0 else ""


def get_git_context(workspace: str | Path) -> dict[str, str]:
    """Gather git context for the workspace; {} if not a git repo.

    The whole layer runs under one aggregate deadline.  Every command may use
    only the time left before that deadline; once it expires, no further git
    process is started and the partial context gathered so far is returned.
    """
    cwd = Path(workspace).resolve()
    deadline = _MONOTONIC() + _GIT_BUDGET_S

    def run(cmd: list[str]) -> str:
        remaining = deadline - _MONOTONIC()
        if remaining <= 0:
            return ""  # aggregate deadline passed: do not spawn another git
        return _run_git(cmd, cwd, timeout=remaining)

    # Cheap gate: one subprocess when outside a repo, five when inside.
    # Fields are gathered value-first so the most useful context (branch,
    # status, recent history) lands before the aggregate deadline; the heavier
    # diffs are the first to yield if the budget runs low.
    if not run(["rev-parse", "--git-dir"]):
        return {}

    return {
        "branch": run(["branch", "--show-current"]).strip(),
        "status_short": run(["status", "--short"]).strip(),
        "recent_commits": run(["log", "--oneline", "-5"]).strip(),
        "staged_diff": run(["diff", "--cached", "--stat"]).strip(),
        "uncommitted_diff": run(["diff", "--stat"]).strip(),
    }


# Hard presentation caps (chars) so a dirty tree can't flood the budget.
_STATUS_CAP = 800
_DIFFSTAT_CAP = 800
_LOG_CAP = 600


def build_git_context_layer(state: dict[str, Any]) -> SystemMessage | None:
    """ContextEngine layer: inject git awareness into the prompt."""
    workspace = state.get("workspace", ".")
    git = get_git_context(workspace)

    if not git:
        return None  # Not a git repo

    lines = [
        "=== GIT CONTEXT ===",
        "Live state of the working tree. Use this before running git commands.",
    ]

    if git.get("branch"):
        lines.append(f"Branch: {git['branch']}")

    if git.get("status_short"):
        lines.append("\nWorking tree changes (git status --short):")
        lines.append(git["status_short"][:_STATUS_CAP])

    if git.get("staged_diff"):
        lines.append("\nStaged changes (git diff --cached --stat):")
        lines.append(git["staged_diff"][:_DIFFSTAT_CAP])

    if git.get("uncommitted_diff"):
        lines.append("\nUnstaged changes (git diff --stat):")
        lines.append(git["uncommitted_diff"][:_DIFFSTAT_CAP])

    if git.get("recent_commits"):
        lines.append("\nRecent commits:")
        lines.append(git["recent_commits"][:_LOG_CAP])

    return SystemMessage(content="\n".join(lines))
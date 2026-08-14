"""Git Context Layer — branch, working-tree, and history awareness.

Answers "what did I change?", "fix the bug I just introduced", "write a
commit message" without the agent burning tool calls on shell commands.

Every git invocation is a local, read-only subprocess with a hard timeout.
The layer returns None outside a git repository, so non-git workspaces are
unaffected. Marked VOLATILE in ContextEngine: the working tree changes
outside the graph state dict, so this layer is rebuilt every turn instead of
being served from the differential layer cache.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage

_GIT_TIMEOUT_S = 3.0

# Hard presentation caps (chars) so a dirty tree can't flood the budget.
_STATUS_CAP = 800
_DIFFSTAT_CAP = 800
_LOG_CAP = 600


def _run_git(cmd: list[str], cwd: str | Path) -> str:
    """Run a read-only git command; empty string on any failure.

    Read-only matters: this runs unattended every turn, so the command set
    must never include anything that writes (no fetch, no gc, no config).
    """
    try:
        result = subprocess.run(
            ["git", *cmd],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        # git missing, cwd missing, timeout — the layer is optional, degrade.
        return ""


def get_git_context(workspace: str | Path) -> dict[str, str]:
    """Gather git context for the workspace; {} if not a git repo."""
    cwd = Path(workspace).resolve()

    # Cheap gate: one subprocess when outside a repo, five when inside.
    if not _run_git(["rev-parse", "--git-dir"], cwd):
        return {}

    return {
        "branch": _run_git(["branch", "--show-current"], cwd).strip(),
        "status_short": _run_git(["status", "--short"], cwd).strip(),
        "staged_diff": _run_git(["diff", "--cached", "--stat"], cwd).strip(),
        "uncommitted_diff": _run_git(["diff", "--stat"], cwd).strip(),
        "recent_commits": _run_git(["log", "--oneline", "-5"], cwd).strip(),
    }


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

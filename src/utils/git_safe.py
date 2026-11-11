"""Bounded, non-wedging ``git`` invocations for read-only inspection.

``subprocess.run(..., timeout=N)`` is not sufficient on Windows. When the
timeout expires, CPython kills the direct child and then re-enters
``communicate()`` *without* a timeout to drain the pipes; if git left a
grandchild holding stdout (fsmonitor, gc, credential helper, a shell alias),
that second wait blocks forever and the caller never returns — observed in
P0.6.5/P0.6.6 as a desktop turn stuck at "Thinking"/"Implementing" with the
stall watchdog pointing at `subprocess._communicate`.

``run_git`` therefore: disables prompts/daemons, gives git no stdin, and on
timeout kills the WHOLE process tree (`taskkill /T` on Windows) before
returning.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class GitCommandError(RuntimeError):
    """A bounded git invocation failed (non-zero exit or timeout)."""


def run_git(
    root: str | Path,
    args: Sequence[str],
    *,
    timeout: float = 5.0,
) -> str:
    """Run a read-only git command and return its stripped stdout.

    Raises :class:`GitCommandError` on non-zero exit or timeout. Callers that
    treat git as best-effort should catch it.
    """
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "LC_ALL": "C",
    })
    proc = subprocess.Popen(
        ["git", "-c", "core.fsmonitor=false", "-c", "gc.auto=0", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        creationflags=creationflags,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:  # pragma: no cover - posix
            proc.kill()
        try:
            proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            pass
        raise GitCommandError(f"git {' '.join(args)} timed out after {timeout}s") from None
    if proc.returncode != 0:
        raise GitCommandError(
            f"git {' '.join(args)} exited {proc.returncode}: {(out or '').strip()[:200]}"
        )
    return (out or "").strip()

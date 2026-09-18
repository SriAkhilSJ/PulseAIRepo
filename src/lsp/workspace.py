"""Workspace and project-root resolution for LSP.

Two concerns:

1. **Workspace gate** — only run LSP when the cwd or file sits inside
   a git worktree.

2. **NearestRoot** — per-server project-root walk.  Each language server
   cares about a different marker (``pyproject.toml`` for Python,
   ``Cargo.toml`` for Rust, etc.).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, Optional, Tuple

logger = logging.getLogger("src.lsp.workspace")

_workspace_cache: dict = {}


def normalize_path(path: str) -> str:
    """Normalize a path for use as a stable map key."""
    return os.path.abspath(os.path.expanduser(path))


def find_git_worktree(start: str) -> Optional[str]:
    """Walk up from ``start`` looking for a ``.git`` entry (file or dir).

    Returns the directory containing ``.git``, or ``None`` if no git
    root is found before hitting the filesystem root.
    """
    try:
        start_path = Path(normalize_path(start))
        if start_path.is_file():
            start_path = start_path.parent
    except (OSError, RuntimeError, ValueError):
        return None

    cached = _workspace_cache.get(str(start_path))
    if cached is not None:
        root, _is_git = cached
        return root

    cur = start_path
    for _ in range(64):
        git_marker = cur / ".git"
        try:
            if git_marker.exists():
                resolved = str(cur)
                _workspace_cache[str(start_path)] = (resolved, True)
                return resolved
        except OSError:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent

    _workspace_cache[str(start_path)] = (None, False)
    return None


def is_inside_workspace(path: str, workspace_root: str) -> bool:
    """Return True iff ``path`` is inside (or equal to) ``workspace_root``."""
    p = normalize_path(path)
    root = normalize_path(workspace_root)
    if p == root:
        return True
    try:
        common = os.path.commonpath([p, root])
    except ValueError:
        return False
    return common == root


def nearest_root(
    start: str,
    markers: Iterable[str],
    *,
    excludes: Optional[Iterable[str]] = None,
    ceiling: Optional[str] = None,
) -> Optional[str]:
    """Walk up from ``start`` looking for any of the given marker files.

    Returns the **directory containing** the first matched marker, or
    ``None`` if no marker is found before hitting ``ceiling``.
    """
    start_path = Path(normalize_path(start))
    try:
        if start_path.is_file():
            start_path = start_path.parent
    except (OSError, RuntimeError, ValueError):
        return None
    ceiling_path = Path(normalize_path(ceiling)) if ceiling else None

    markers_list = list(markers)
    excludes_list = list(excludes) if excludes else []

    cur = start_path
    for _ in range(64):
        for exc in excludes_list:
            try:
                if (cur / exc).exists():
                    return None
            except OSError:
                continue
        for marker in markers_list:
            try:
                if (cur / marker).exists():
                    return str(cur)
            except OSError:
                continue
        if ceiling_path is not None and cur == ceiling_path:
            return None
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent
    return None


def resolve_workspace_for_file(
    file_path: str,
    *,
    cwd: Optional[str] = None,
) -> Tuple[Optional[str], bool]:
    """Resolve the workspace root for a file.

    Returns ``(workspace_root, gated_in)`` where ``gated_in`` is True
    iff LSP should run for this file.
    """
    cwd = cwd or os.getcwd()
    cwd_root = find_git_worktree(cwd)
    if cwd_root is not None:
        if is_inside_workspace(file_path, cwd_root):
            return cwd_root, True
    file_root = find_git_worktree(file_path)
    if file_root is not None:
        return file_root, True
    return None, False


def clear_cache() -> None:
    """Clear the workspace-resolution cache."""
    _workspace_cache.clear()


__all__ = [
    "find_git_worktree",
    "is_inside_workspace",
    "nearest_root",
    "normalize_path",
    "resolve_workspace_for_file",
    "clear_cache",
]

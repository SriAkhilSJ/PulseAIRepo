"""Application-data paths for workspace-internal runtime state.

The user's workspace must contain project files, not Crusor's sessions,
FinOps ledger, diagnostics, journals, or temporary execution metadata.

Canonical desktop turns set a per-workspace app-data root
(``~/.crusorai/workspaces/<hash>``). Direct library/test callers that never set
it keep the historical ``<workspace>/.crusorai`` layout for compatibility.
"""
from __future__ import annotations

import contextvars
import hashlib
import os
from pathlib import Path

_APP_DATA_ROOT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "crusor_app_data_root", default=None
)


def app_data_root(workspace: str | Path) -> Path:
    explicit = _APP_DATA_ROOT.get() or os.environ.get("CRUSORAI_APP_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path(workspace).resolve() / ".crusorai"


def workspace_app_data_root(workspace: str | Path) -> Path:
    """Deterministic per-workspace root under the application home."""
    digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".crusorai" / "workspaces" / digest


def activate_workspace_app_data(workspace: str | Path):
    """Set the current context's app-data root; returns the reset token.

    An explicit ``CRUSORAI_APP_DATA_ROOT`` (packaging/test isolation) wins over
    the per-workspace default so callers can redirect all runtime state.
    """
    explicit = os.environ.get("CRUSORAI_APP_DATA_ROOT")
    root = (
        str(Path(explicit).expanduser().resolve())
        if explicit
        else str(workspace_app_data_root(workspace))
    )
    return _APP_DATA_ROOT.set(root)


def reset_workspace_app_data(token) -> None:
    try:
        _APP_DATA_ROOT.reset(token)
    except Exception:
        pass

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
    """Deterministic per-workspace root under the application home.

    ``CRUSORAI_HOME`` relocates the application home (packaging/tests) while
    keeping the per-workspace subtree, so isolated runs do not write under the
    developer's real ``~/.crusorai/workspaces``.
    """
    digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
    home = os.environ.get("CRUSORAI_HOME", "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".crusorai"
    return base / "workspaces" / digest


def session_db_path() -> Path:
    """Resolve the canonical conversation database (sessions + checkpoints).

    Precedence matches the durable session store:
    ``CRUSORAI_SESSIONS_DB`` > ``CRUSORAI_SESSIONS_DB_PATH`` >
    ``CRUSORAI_HOME`` > ``~/.crusorai/sessions.db``.
    """
    explicit = os.environ.get("CRUSORAI_SESSIONS_DB") or os.environ.get(
        "CRUSORAI_SESSIONS_DB_PATH"
    )
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("CRUSORAI_HOME", "").strip()
    if home:
        return Path(home).expanduser() / "sessions.db"
    return Path.home() / ".crusorai" / "sessions.db"


def checkpoint_db_path() -> Path:
    """Resolve the LangGraph checkpoint database path.

    A checkpoint-specific override wins over the shared conversation DB so a
    test (or an isolated run) can relocate checkpoints without moving session
    rows or any other runtime state:

    1. ``CRUSORAI_CHECKPOINT_DB`` — exact file path.
    2. ``CRUSORAI_CHECKPOINT_HOME`` — directory; ``<home>/sessions.db``.
    3. ``session_db_path()`` — the normal shared database.

    Defaults are unchanged: with no environment overrides this returns
    ``~/.crusorai/sessions.db``.
    """
    explicit = os.environ.get("CRUSORAI_CHECKPOINT_DB", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("CRUSORAI_CHECKPOINT_HOME", "").strip()
    if home:
        return Path(home).expanduser() / "sessions.db"
    return session_db_path()


def sqlite_readonly_uri(db_path: str | Path) -> str:
    """Return an absolute, percent-encoded SQLite URI in read-only mode.

    ``Path.as_uri()`` encodes legal filename characters that SQLite would
    otherwise treat as URI delimiters — ``#`` (fragment), ``?`` (query),
    ``%`` (escape), spaces and non-ASCII text — so the connection can never
    silently resolve to a different database.
    """
    return f"{Path(db_path).resolve().as_uri()}?mode=ro"


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

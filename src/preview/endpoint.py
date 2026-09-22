"""Crusor Preview — the proxy handshake file (how the IDE finds a running preview server).

The preview proxy listens on an ephemeral loopback port and guards every proxied path with a
capability token, so the workbench cannot guess either one. It publishes them the way the rest of
the runtime publishes machine state: a small JSON file under ``$CRUSORAI_HOME/preview`` (default
``~/.crusorai/preview``), named by session.

    { "session_id": "...", "origin": "http://127.0.0.1:8931", "token": "...",
      "workspace": "/abs/path", "pid": 4711, "started_at": 1760000000.0 }

Why a file and not a protocol frame: Bridge Protocol v2 is a *session* channel (prompts, tools,
approvals), and the preview endpoint is machine state that must survive a renderer reload, a
window move, or a bridge restart without any of them having to renegotiate. A file is also
inspectable by a human with ``cat`` when the preview will not load — which is exactly when you
need it. Writes are atomic (temp + ``os.replace``) so a reader never sees half a document, and
the file is ``0600``: the token in it is the only thing between a stray browser tab and the
workspace.

The TypeScript side (``contrib/crusorai/browser/crusorAIPreviewService.ts``) reads this file; the
CLI in :mod:`src.preview.server` writes it.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "clear_endpoint",
    "endpoint_path",
    "preview_home",
    "prune_stale",
    "read_endpoint",
    "runtime_home",
    "write_endpoint",
]

#: An endpoint older than this is treated as abandoned by ``prune_stale``. Long-lived IDE sessions
#: are normal, so this is generous: the point is to stop dead files accumulating, not to expire a
#: working proxy.
DEFAULT_MAX_AGE_SECONDS = 12 * 60 * 60

_SAFE_SESSION = re.compile(r"[^A-Za-z0-9._-]+")


def runtime_home() -> Path:
    """``$CRUSORAI_HOME`` or ``~/.crusorai`` — the same root the rest of the runtime uses."""
    configured = os.environ.get("CRUSORAI_HOME", "").strip()
    base = Path(configured).expanduser() if configured else Path.home() / ".crusorai"
    return base


def preview_home() -> Path:
    return runtime_home() / "preview"


def _safe(name: str, fallback: str = "default") -> str:
    """A session id is attacker-adjacent input (it can come from a URL); never a path."""
    cleaned = _SAFE_SESSION.sub("_", str(name or "").strip()).strip("._")
    return cleaned[:96] or fallback


def endpoint_path(session_id: str) -> Path:
    return preview_home() / f"{_safe(session_id)}.json"


def write_endpoint(
    session_id: str,
    *,
    origin: str,
    token: str = "",
    workspace: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Publish the endpoint atomically. Returns the path written."""
    directory = preview_home()
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "session_id": str(session_id),
        "origin": str(origin).rstrip("/"),
        "token": str(token),
        "workspace": str(workspace) if workspace is not None else "",
        "pid": os.getpid(),
        "started_at": time.time(),
        "ui_path": "/crusor-preview/ui/",
        "overlay_path": "/crusor-preview/overlay/crusor-preview-overlay.js",
        "target_path": "/crusor-preview/target",
        "health_path": "/crusor-preview/health",
    }
    if extra:
        payload.update(extra)
    path = endpoint_path(session_id)
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:  # pragma: no cover - Windows/odd filesystems
        pass
    os.replace(temp, path)
    return path


def read_endpoint(session_id: str) -> dict[str, Any] | None:
    """Read a published endpoint, or ``None`` when it is absent or unreadable."""
    path = endpoint_path(session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("origin") else None


def clear_endpoint(session_id: str) -> bool:
    """Remove a published endpoint. ``True`` when a file was actually removed."""
    path = endpoint_path(session_id)
    try:
        path.unlink()
        return True
    except OSError:
        return False


def prune_stale(max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS) -> list[Path]:
    """Delete endpoint files older than ``max_age_seconds``; returns what was removed."""
    cutoff = time.time() - max_age_seconds
    removed: list[Path] = []
    directory = preview_home()
    if not directory.is_dir():
        return removed
    for path in sorted(directory.glob("*.json")):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path)
        except OSError:  # pragma: no cover - racing deletion
            continue
    return removed

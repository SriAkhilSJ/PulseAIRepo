"""Explicit runtime identities—never overload one thread id for everything."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def normalize_id(value: str | None, *, prefix: str) -> str:
    raw = str(value or "").strip()
    if raw and _ID_RE.fullmatch(raw):
        return raw
    return f"{prefix}-{uuid.uuid4().hex}"


def workspace_id(path: str) -> str:
    import hashlib
    resolved = str(Path(path).expanduser().resolve())
    return "ws-" + hashlib.sha256(resolved.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class TurnIdentity:
    session_id: str
    runtime_session_id: str
    lineage_root_id: str
    workspace_id: str
    turn_id: str
    created_at: float

    @classmethod
    def create(
        cls,
        *,
        session_id: str | None,
        workspace: str,
        runtime_session_id: str | None = None,
        lineage_root_id: str | None = None,
    ) -> "TurnIdentity":
        sid = normalize_id(session_id, prefix="session")
        runtime = normalize_id(runtime_session_id, prefix="runtime")
        lineage = normalize_id(lineage_root_id or sid, prefix="lineage")
        return cls(
            session_id=sid,
            runtime_session_id=runtime,
            lineage_root_id=lineage,
            workspace_id=workspace_id(workspace),
            turn_id=f"turn-{uuid.uuid4().hex}",
            created_at=time.time(),
        )

    def event_fields(self) -> dict:
        return {
            "session_id": self.session_id,
            "runtime_session_id": self.runtime_session_id,
            "lineage_root_id": self.lineage_root_id,
            "workspace_id": self.workspace_id,
            "turn_id": self.turn_id,
        }

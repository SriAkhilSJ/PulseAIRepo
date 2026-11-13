"""Phase 2D - turn-scoped human grants for paths outside the workspace.

Modelled on the two patterns that have held up in production coding agents:

* OpenCode's ``external_directory`` permission action with ``allow once`` /
  ``allow for this session`` / ``reject`` verdicts and canonical directory
  boundaries.
* Claude Code's separate read/write controls for paths outside the working
  directories.

Crusor's grant object is deliberately narrower than both:

* grants are **turn-scoped** and never persisted;
* a grant covers exactly one canonical file or directory boundary;
* ``read`` grants never authorise a write;
* grants never override the sensitive-name block (``.ssh``, ``.env`` ...);
* grants are checked at the tool boundary and cannot be minted by the model.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.workspace.path_safety import PathSafetyValidator

READ = "read"
WRITE = "write"
ONCE = "once"
TURN = "turn"


class WorkspaceAccessRequired(PermissionError):
    """A path outside the workspace needs a human grant before it is used."""

    def __init__(self, path: str, operation: str = READ, reason: str = "") -> None:
        self.path = str(path)
        self.operation = str(operation)
        self.reason = str(reason or "")
        super().__init__(
            f"{self.operation} access to {self.path} requires human approval"
        )


def canonical_path(path: str | Path) -> Path:
    """Canonical absolute path (Windows short/long names, symlinks, case)."""
    return PathSafetyValidator.canonical_path(str(path))


def _norm(path: str | Path) -> str:
    return os.path.normcase(str(canonical_path(path)))


def is_sensitive_external_path(path: str | Path) -> bool:
    """Known-sensitive names stay blocked even with a grant.

    The check is intentionally coarse: a grant for a project folder must never
    turn into read access to keys or credential files inside it.
    """
    from src.workspace.path_safety import SENSITIVE_TARGETS

    try:
        parts = canonical_path(path).parts
    except Exception:
        return True
    for part in parts:
        lowered = str(part).lower()
        if lowered in SENSITIVE_TARGETS or lowered.startswith(".env"):
            return True
        if lowered in {".ssh", ".aws", ".gnupg", ".kube", "id_rsa", "id_ed25519"}:
            return True
    return False


@dataclass
class WorkspaceAccessGrant:
    """One human decision for one exact path boundary."""

    path: str
    operation: str = READ
    scope: str = TURN
    approval_id: str = ""
    granted_at: float = field(default_factory=time.time)
    used: bool = False
    reason: str = ""

    def covers(self, candidate: str | Path) -> bool:
        try:
            target = _norm(candidate)
            boundary = _norm(self.path)
        except Exception:
            return False
        return target == boundary or target.startswith(boundary + os.sep)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "operation": self.operation,
            "scope": self.scope,
            "approval_id": self.approval_id,
            "granted_at": self.granted_at,
            "used": self.used,
            "reason": self.reason,
        }


class AccessGrantSet:
    """Turn-scoped grants, checked on every external path resolution."""

    def __init__(self, grants: Optional[Iterable[WorkspaceAccessGrant]] = None) -> None:
        self._grants: List[WorkspaceAccessGrant] = list(grants or [])

    def add(self, grant: WorkspaceAccessGrant) -> WorkspaceAccessGrant:
        if is_sensitive_external_path(grant.path):
            raise PermissionError(
                f"refusing a grant for sensitive path {grant.path}"
            )
        self._grants.append(grant)
        return grant

    def matching(self, path: str | Path, operation: str = READ) -> List[WorkspaceAccessGrant]:
        wanted = str(operation or READ).lower()
        found: List[WorkspaceAccessGrant] = []
        for grant in self._grants:
            if grant.scope == ONCE and grant.used:
                continue
            if wanted == READ and grant.operation not in {READ, WRITE}:
                continue
            if wanted == WRITE and grant.operation != WRITE:
                continue
            if grant.covers(path):
                found.append(grant)
        return found

    def allows(self, path: str | Path, operation: str = READ) -> bool:
        if is_sensitive_external_path(path):
            return False
        return bool(self.matching(path, operation))

    def consume(self, path: str | Path, operation: str = READ) -> None:
        """Mark a matching ``once`` grant as spent after a successful access."""
        for grant in self.matching(path, operation):
            if grant.scope == ONCE:
                grant.used = True

    def __len__(self) -> int:
        return len(self._grants)

    def to_list(self) -> List[Dict[str, Any]]:
        return [grant.to_dict() for grant in self._grants]


__all__ = [
    "READ",
    "WRITE",
    "ONCE",
    "TURN",
    "WorkspaceAccessGrant",
    "AccessGrantSet",
    "WorkspaceAccessRequired",
    "canonical_path",
    "is_sensitive_external_path",
]

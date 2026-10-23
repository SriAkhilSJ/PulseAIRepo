"""Canonical protocol envelope for verification evidence updates.

The verification ledger owns state and stale-on-edit semantics. This module
projects every resulting status into the runtime journal in one versioned
shape so replay, UI, and future policy evaluators consume the same contract.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Mapping

from src.runtime.identity import workspace_id
from src.runtime.persistence import sanitize_for_persistence

EvidenceKind = Literal["command", "edit", "explicit", "unavailable"]
VERIFICATION_EVIDENCE_SCHEMA_VERSION = 1


def make_verification_envelope(
    status: Mapping[str, Any],
    *,
    evidence_kind: EvidenceKind,
) -> dict[str, Any]:
    """Create a versioned, JSON-safe verification update."""

    safe = sanitize_for_persistence(dict(status))
    details = safe if isinstance(safe, dict) else {"status": "unavailable", "detail": safe}
    return {
        **details,
        "schema_version": VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        "evidence_id": f"verify-{uuid.uuid4().hex}",
        "evidence_kind": evidence_kind,
        "observed_at": time.time(),
    }


def journal_verification_update(
    services: Any,
    status: Mapping[str, Any],
    *,
    session_id: str,
    workspace: str,
    evidence_kind: EvidenceKind,
    turn_id: str | None = None,
) -> dict[str, Any]:
    """Persist and return the canonical update, degrading explicitly on error.

    The dedicated verification ledger remains durable even if the runtime
    journal is unavailable. In that case callers still receive a typed update,
    but ``journal_status`` makes the missing replay row unambiguous.
    """

    envelope = make_verification_envelope(status, evidence_kind=evidence_kind)
    try:
        row = services.journal.append(
            "verification.updated",
            envelope,
            session_id=session_id,
            turn_id=turn_id,
            workspace_id=workspace_id(workspace),
            event_id=envelope["evidence_id"],
        )
        persisted = dict(row["payload"])
        persisted["journal_seq"] = row["seq"]
        persisted["journal_status"] = "persisted"
        return persisted
    except Exception as exc:
        safe_error = sanitize_for_persistence(f"{type(exc).__name__}: {exc}")
        return {
            **envelope,
            "journal_status": "unavailable",
            "journal_error": safe_error,
        }

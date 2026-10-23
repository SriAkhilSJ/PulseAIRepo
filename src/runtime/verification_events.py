"""Canonical, versioned envelope for verification evidence updates.

The verification ledger owns status and stale-on-edit semantics. This module
projects each outcome into the runtime journal so live UI, restart replay, and
future policy consumers all observe one contract rather than ad-hoc payloads.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from src.runtime.identity import workspace_id
from src.runtime.persistence import sanitize_for_persistence

EvidenceKind = Literal["command", "edit", "explicit", "unavailable"]
VERIFICATION_EVIDENCE_SCHEMA_VERSION = 1


def _raw_verification_envelope(
    status: Mapping[str, Any],
    *,
    evidence_kind: EvidenceKind,
) -> dict[str, Any]:
    return {
        **dict(status),
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
    """Persist and return the canonical update, degrading explicitly.

    On the normal path EventJournal performs the one required recursive
    sanitization pass and returns that exact replay payload. If its database is
    unavailable, the dedicated verification ledger still remains authoritative
    and callers receive a separately sanitized envelope whose journal status
    is explicit rather than silently pretending replay succeeded.
    """

    envelope = _raw_verification_envelope(
        status, evidence_kind=evidence_kind
    )
    try:
        row = services.journal.append(
            "verification.updated",
            envelope,
            session_id=session_id,
            turn_id=turn_id,
            workspace_id=workspace_id(workspace),
            event_id=str(envelope["evidence_id"]),
        )
        persisted = dict(row["payload"])
        persisted["journal_seq"] = row["seq"]
        persisted["journal_status"] = "persisted"
        return persisted
    except Exception as exc:
        safe = sanitize_for_persistence(envelope)
        fallback = safe if isinstance(safe, dict) else {"detail": safe}
        fallback.update(
            {
                "journal_status": "unavailable",
                "journal_error": sanitize_for_persistence(
                    f"{type(exc).__name__}: {exc}"
                ),
            }
        )
        return fallback

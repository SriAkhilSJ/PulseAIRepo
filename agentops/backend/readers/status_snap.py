"""Context-health snapshot reader.

Demo / journaled mode: the simulator (or a future engine hook) writes
`context_status` rows into the journal carrying the get_status() shape
(usage_percent, pressure, compaction, prompt_cache, context_breakdown…).
Live mode: routes proxy the engine's /api/context/status on demand (engine_proxy).
"""
from __future__ import annotations

from typing import Any

from . import journal


def latest_per_session(limit_sessions: int = 50) -> list[dict[str, Any]]:
    rows = [r for r in journal.audit(limit=5000, since_seq=0) if r["event_type"] == "context_status"]
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        latest[r["session_id"]] = {
            "session_id": r["session_id"],
            "at": r["created_at"],
            **(r.get("payload") or {}),
        }
    out = sorted(latest.values(), key=lambda x: x.get("at") or 0, reverse=True)
    return out[:limit_sessions]


def history(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = [
        r for r in journal.audit(limit=5000, since_seq=0)
        if r["event_type"] == "context_status" and r["session_id"] == session_id
    ]
    return [{"at": r["created_at"], **(r.get("payload") or {})} for r in rows[-limit:]]

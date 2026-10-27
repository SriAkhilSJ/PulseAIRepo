"""Durable append-only runtime journal.

The journal is the canonical execution timeline. A side-effecting tool may run
only after its `tool.intent` row commits. A completion event is emitted only
after its `tool.result` row commits.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from src.runtime.persistence import sanitize_event_payload


class JournalUnavailable(RuntimeError):
    pass


_EVENT_CHAIN_VERSION = 1
_TERMINAL_EVENT_TYPES = frozenset(
    {
        "turn.completed",
        "turn.cancelled",
        "turn.failed",
        "turn.watchdog",
        "turn.interrupted",
    }
)


def compute_event_integrity_hash(
    *,
    event_id: str,
    created_at: float,
    event_type: str,
    session_id: str,
    turn_id: str | None,
    workspace_id: str | None,
    tool_call_id: str | None,
    payload_json: str,
    prev_hash: str,
) -> str:
    """Hash one canonical event envelope and its previous session event.

    The chain is scoped to ``session_id`` so concurrent sessions cannot race
    each other's evidence order.  ``payload_json`` is the exact sanitized byte
    representation stored in SQLite, not a second lossy serialization. The
    verifier imports this pure function without opening the journal for write.
    """
    canonical = json.dumps(
        {
            "chain_version": _EVENT_CHAIN_VERSION,
            "event_id": event_id,
            "created_at": format(float(created_at), ".9f"),
            "event_type": event_type,
            "session_id": session_id,
            "turn_id": turn_id,
            "workspace_id": workspace_id,
            "tool_call_id": tool_call_id,
            "payload_json": payload_json,
            "prev_hash": prev_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EventJournal:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (Path.home() / ".crusorai" / "runtime_events.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
        except sqlite3.DatabaseError:
            pass
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS runtime_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL,
                event_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                turn_id TEXT,
                workspace_id TEXT,
                tool_call_id TEXT,
                payload_json TEXT NOT NULL,
                prev_hash TEXT,
                event_hash TEXT
            )"""
        )
        columns = {
            str(row[1])
            for row in self._conn.execute(
                "PRAGMA table_info(runtime_events)"
            ).fetchall()
        }
        for column in ("prev_hash", "event_hash"):
            if column not in columns:
                self._conn.execute(
                    f"ALTER TABLE runtime_events ADD COLUMN {column} TEXT"
                )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runtime_events_session_seq "
            "ON runtime_events(session_id, seq)"
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS runtime_journal_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )
        initialized = self._conn.execute(
            "SELECT value FROM runtime_journal_meta WHERE key='event_chain_version'"
        ).fetchone()
        if initialized is None:
            self._backfill_legacy_hashes()
            self._conn.execute(
                "INSERT OR IGNORE INTO runtime_journal_meta(key,value) VALUES(?,?)",
                ("event_chain_version", str(_EVENT_CHAIN_VERSION)),
            )
        self._conn.commit()
        self._harden_permissions()

    def _harden_permissions(self) -> None:
        """Keep the database and SQLite WAL sidecars owner-private."""
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
        ):
            try:
                if candidate.exists():
                    os.chmod(candidate, 0o600)
            except OSError:
                pass

    def _backfill_legacy_hashes(self) -> None:
        """Chain rows written before integrity columns existed, once only."""
        rows = self._conn.execute(
            "SELECT * FROM runtime_events ORDER BY session_id, seq"
        ).fetchall()
        heads: dict[str, str] = {}
        for row in rows:
            session_id = str(row["session_id"])
            existing_hash = str(row["event_hash"] or "")
            if existing_hash:
                heads[session_id] = existing_hash
                continue
            prev_hash = heads.get(session_id, "")
            event_hash = compute_event_integrity_hash(
                event_id=str(row["event_id"]),
                created_at=float(row["created_at"]),
                event_type=str(row["event_type"]),
                session_id=session_id,
                turn_id=row["turn_id"],
                workspace_id=row["workspace_id"],
                tool_call_id=row["tool_call_id"],
                payload_json=str(row["payload_json"]),
                prev_hash=prev_hash,
            )
            self._conn.execute(
                "UPDATE runtime_events SET prev_hash=?, event_hash=? WHERE seq=?",
                (prev_hash, event_hash, int(row["seq"])),
            )
            heads[session_id] = event_hash

    @staticmethod
    def _stored_event(
        row: sqlite3.Row,
        *,
        existing_event: bool,
        existing_terminal: bool = False,
    ) -> dict[str, Any]:
        return {
            "seq": int(row["seq"]),
            "event_id": row["event_id"],
            "timestamp": float(row["created_at"]),
            "type": row["event_type"],
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "workspace_id": row["workspace_id"],
            "tool_call_id": row["tool_call_id"],
            "payload": json.loads(row["payload_json"]),
            "prev_hash": row["prev_hash"],
            "event_hash": row["event_hash"],
            "chain_version": _EVENT_CHAIN_VERSION,
            "existing_event": existing_event,
            "existing_terminal": existing_terminal,
        }

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        session_id: str,
        turn_id: str | None = None,
        workspace_id: str | None = None,
        tool_call_id: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required for durable events")
        eid = event_id or f"evt-{uuid.uuid4().hex}"
        created = time.time()
        try:
            # Durable replay is stricter than live output. Event-aware shaping
            # omits tool bodies and the recursive pass forcibly redacts and
            # bounds every value before SQLite sees it.
            safe_payload = sanitize_event_payload(event_type, payload)
            encoded = json.dumps(
                safe_payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            with self._lock:
                try:
                    # Serialize the head read + append across other processes,
                    # not only threads sharing this EventJournal instance.
                    self._conn.execute("BEGIN IMMEDIATE")
                    existing_id = self._conn.execute(
                        "SELECT * FROM runtime_events WHERE event_id=?",
                        (eid,),
                    ).fetchone()
                    if existing_id is not None:
                        same_event = (
                            existing_id["event_type"] == event_type
                            and existing_id["session_id"] == session_id
                            and existing_id["turn_id"] == turn_id
                            and existing_id["workspace_id"] == workspace_id
                            and existing_id["tool_call_id"] == tool_call_id
                            and existing_id["payload_json"] == encoded
                        )
                        if not same_event:
                            raise JournalUnavailable(
                                f"event_id collision for {eid}"
                            )
                        self._conn.commit()
                        return self._stored_event(
                            existing_id,
                            existing_event=True,
                            existing_terminal=(
                                event_type in _TERMINAL_EVENT_TYPES
                            ),
                        )
                    if (
                        event_type in {"tool.intent", "tool.result"}
                        and tool_call_id
                        and turn_id
                    ):
                        existing_tool_event = self._conn.execute(
                            "SELECT * FROM runtime_events "
                            "WHERE session_id=? AND turn_id IS ? "
                            "AND tool_call_id=? AND event_type=? "
                            "ORDER BY seq LIMIT 1",
                            (session_id, turn_id, tool_call_id, event_type),
                        ).fetchone()
                        if existing_tool_event is not None:
                            if (
                                existing_tool_event["payload_json"] != encoded
                                or existing_tool_event["workspace_id"] != workspace_id
                            ):
                                raise JournalUnavailable(
                                    "tool event identity reused with different payload"
                                )
                            self._conn.commit()
                            return self._stored_event(
                                existing_tool_event,
                                existing_event=True,
                            )
                    if event_type == "turn.started":
                        if not turn_id:
                            raise ValueError(
                                "turn.started requires turn_id"
                            )
                        existing_start = self._conn.execute(
                            "SELECT * FROM runtime_events "
                            "WHERE session_id=? AND turn_id=? "
                            "AND event_type='turn.started' "
                            "ORDER BY seq LIMIT 1",
                            (session_id, turn_id),
                        ).fetchone()
                        if existing_start is not None:
                            if (
                                existing_start["payload_json"] != encoded
                                or existing_start["workspace_id"] != workspace_id
                            ):
                                raise JournalUnavailable(
                                    "turn start identity reused with different payload"
                                )
                            self._conn.commit()
                            return self._stored_event(
                                existing_start,
                                existing_event=True,
                            )
                    if event_type in _TERMINAL_EVENT_TYPES:
                        if not turn_id:
                            raise ValueError(
                                "terminal lifecycle events require turn_id"
                            )
                        placeholders = ",".join(
                            "?" for _ in _TERMINAL_EVENT_TYPES
                        )
                        existing = self._conn.execute(
                            "SELECT * FROM runtime_events "
                            "WHERE session_id=? AND turn_id=? "
                            f"AND event_type IN ({placeholders}) "
                            "ORDER BY seq LIMIT 1",
                            (
                                session_id,
                                turn_id,
                                *sorted(_TERMINAL_EVENT_TYPES),
                            ),
                        ).fetchone()
                        if existing is not None:
                            self._conn.commit()
                            return self._stored_event(
                                existing,
                                existing_event=True,
                                existing_terminal=True,
                            )
                    previous = self._conn.execute(
                        "SELECT event_hash FROM runtime_events "
                        "WHERE session_id=? ORDER BY seq DESC LIMIT 1",
                        (session_id,),
                    ).fetchone()
                    prev_hash = str(previous["event_hash"] or "") if previous else ""
                    if previous is not None and not prev_hash:
                        raise JournalUnavailable(
                            "previous event has no integrity hash"
                        )
                    event_hash = compute_event_integrity_hash(
                        event_id=eid,
                        created_at=created,
                        event_type=event_type,
                        session_id=session_id,
                        turn_id=turn_id,
                        workspace_id=workspace_id,
                        tool_call_id=tool_call_id,
                        payload_json=encoded,
                        prev_hash=prev_hash,
                    )
                    cur = self._conn.execute(
                        "INSERT INTO runtime_events("
                        "event_id,created_at,event_type,session_id,turn_id,"
                        "workspace_id,tool_call_id,payload_json,prev_hash,event_hash"
                        ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            eid,
                            created,
                            event_type,
                            session_id,
                            turn_id,
                            workspace_id,
                            tool_call_id,
                            encoded,
                            prev_hash,
                            event_hash,
                        ),
                    )
                    seq = int(cur.lastrowid)
                    self._conn.commit()
                    self._harden_permissions()
                except Exception:
                    self._conn.rollback()
                    raise
        except Exception as exc:
            raise JournalUnavailable(f"could not persist {event_type}: {exc}") from exc
        return {
            "seq": seq,
            "event_id": eid,
            "timestamp": created,
            "type": event_type,
            "session_id": session_id,
            "turn_id": turn_id,
            "workspace_id": workspace_id,
            "tool_call_id": tool_call_id,
            "payload": safe_payload,
            "prev_hash": prev_hash,
            "event_hash": event_hash,
            "chain_version": _EVENT_CHAIN_VERSION,
            "existing_event": False,
            "existing_terminal": False,
        }

    def list_events(self, session_id: str, *, after_seq: int = 0, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runtime_events WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?",
                (session_id, max(0, int(after_seq)), max(1, min(int(limit), 2000))),
            ).fetchall()
        return [
            {
                "seq": row["seq"], "event_id": row["event_id"],
                "timestamp": row["created_at"], "type": row["event_type"],
                "session_id": row["session_id"], "turn_id": row["turn_id"],
                "workspace_id": row["workspace_id"], "tool_call_id": row["tool_call_id"],
                "payload": json.loads(row["payload_json"]),
                "prev_hash": row["prev_hash"], "event_hash": row["event_hash"],
                "chain_version": _EVENT_CHAIN_VERSION,
            }
            for row in rows
        ]

    def list_turn_events(
        self,
        session_id: str,
        turn_id: str,
        *,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        """Return one turn's canonical ordered timeline."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runtime_events "
                "WHERE session_id=? AND turn_id=? ORDER BY seq LIMIT ?",
                (
                    session_id,
                    turn_id,
                    max(1, min(int(limit), 50_000)),
                ),
            ).fetchall()
        return [
            {
                "seq": row["seq"],
                "event_id": row["event_id"],
                "timestamp": row["created_at"],
                "type": row["event_type"],
                "session_id": row["session_id"],
                "turn_id": row["turn_id"],
                "workspace_id": row["workspace_id"],
                "tool_call_id": row["tool_call_id"],
                "payload": json.loads(row["payload_json"]),
                "prev_hash": row["prev_hash"],
                "event_hash": row["event_hash"],
                "chain_version": _EVENT_CHAIN_VERSION,
            }
            for row in rows
        ]

    def verify_chain(self, session_id: str) -> dict[str, Any]:
        """Verify the complete session chain against exact stored envelopes."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runtime_events WHERE session_id=? ORDER BY seq",
                (session_id,),
            ).fetchall()
        prev_hash = ""
        for position, row in enumerate(rows, 1):
            stored_prev = str(row["prev_hash"] or "")
            stored_hash = str(row["event_hash"] or "")
            expected_hash = compute_event_integrity_hash(
                event_id=str(row["event_id"]),
                created_at=float(row["created_at"]),
                event_type=str(row["event_type"]),
                session_id=str(row["session_id"]),
                turn_id=row["turn_id"],
                workspace_id=row["workspace_id"],
                tool_call_id=row["tool_call_id"],
                payload_json=str(row["payload_json"]),
                prev_hash=prev_hash,
            )
            if stored_prev != prev_hash or stored_hash != expected_hash:
                return {
                    "valid": False,
                    "checked": position,
                    "event_count": len(rows),
                    "first_bad_seq": int(row["seq"]),
                    "head_hash": prev_hash or None,
                    "chain_version": _EVENT_CHAIN_VERSION,
                }
            prev_hash = stored_hash
        return {
            "valid": True,
            "checked": len(rows),
            "event_count": len(rows),
            "first_bad_seq": None,
            "head_hash": prev_hash or None,
            "chain_version": _EVENT_CHAIN_VERSION,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()

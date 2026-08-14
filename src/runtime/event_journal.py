"""Durable append-only runtime journal.

The journal is the canonical execution timeline. A side-effecting tool may run
only after its `tool.intent` row commits. A completion event is emitted only
after its `tool.result` row commits.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class JournalUnavailable(RuntimeError):
    pass


class EventJournal:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (Path.home() / ".pulseai" / "runtime_events.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
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
                payload_json TEXT NOT NULL
            )"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runtime_events_session_seq "
            "ON runtime_events(session_id, seq)"
        )
        self._conn.commit()

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
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            with self._lock, self._conn:
                cur = self._conn.execute(
                    "INSERT INTO runtime_events(event_id,created_at,event_type,session_id,turn_id,workspace_id,tool_call_id,payload_json) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (eid, created, event_type, session_id, turn_id, workspace_id, tool_call_id, encoded),
                )
                seq = int(cur.lastrowid)
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
            "payload": payload,
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
            }
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

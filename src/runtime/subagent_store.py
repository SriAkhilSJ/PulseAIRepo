"""Subagent session persistence — OpenCode-style parentID hierarchy.

Stores child sessions with parent linkage in the same sqlite file as LangGraph checkpoints
(~/.crusorai/sessions.db) but in a separate table `subagent_sessions`.

Design:
- Same file as checkpoint DB for locality, WAL mode, busy_timeout 5000
- Separate table to avoid coupling to langgraph-checkpoint-sqlite opaque schema
- In-memory _active_agents remains fast path, store is source of truth for navigation & depth
- Cap: keep newest 1000 total, evict oldest (like _MAX_COMPLETED_AGENTS but larger for UI)
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB = Path.home() / ".crusorai" / "sessions.db"
_MAX_SESSIONS = 1000

@dataclass
class SubagentSessionRow:
    subagent_id: str
    parent_session_id: str
    child_thread_id: str
    mode: str
    goal: str
    description: str
    agent_name: str
    state: str
    created_at: float
    updated_at: float
    tool_call_id: Optional[str] = None
    tool_calls: int = 0
    background: bool = False
    result: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        duration = self.updated_at - self.created_at if self.updated_at and self.created_at else 0
        if duration < 60:
            dur_str = f"{duration:.0f}s"
        else:
            m = int(duration // 60)
            s = int(duration % 60)
            dur_str = f"{m}:{s:02d}"
        return {
            "subagent_id": self.subagent_id,
            "child_thread_id": self.child_thread_id,
            "parent_session_id": self.parent_session_id,
            "mode": self.mode,
            "goal": (self.goal or "")[:200],
            "description": (self.description or "")[:200],
            "agent_name": self.agent_name,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tool_call_id": self.tool_call_id,
            "tool_calls": self.tool_calls,
            "background": self.background,
            "duration": dur_str,
            "result": (self.result or "")[:2000] if self.result else None,
            "error": (self.error or "")[:500] if self.error else None,
        }

class SubagentStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or _DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        self._init_schema()

    def _init_schema(self):
        with self._lock, self._conn:
            self._conn.execute("""
            CREATE TABLE IF NOT EXISTS subagent_sessions (
                subagent_id TEXT PRIMARY KEY,
                parent_session_id TEXT NOT NULL,
                child_thread_id TEXT NOT NULL UNIQUE,
                mode TEXT NOT NULL,
                goal TEXT NOT NULL,
                description TEXT,
                agent_name TEXT,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                tool_call_id TEXT,
                tool_calls INTEGER DEFAULT 0,
                background INTEGER DEFAULT 0,
                result TEXT,
                error TEXT
            )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_subagent_parent ON subagent_sessions(parent_session_id, created_at)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_subagent_child ON subagent_sessions(child_thread_id)")
            # migration: add columns if old table exists without them
            cols = {row[1] for row in self._conn.execute("PRAGMA table_info(subagent_sessions)").fetchall()}
            if "description" not in cols:
                try:
                    self._conn.execute("ALTER TABLE subagent_sessions ADD COLUMN description TEXT")
                except Exception:
                    pass
            if "agent_name" not in cols:
                try:
                    self._conn.execute("ALTER TABLE subagent_sessions ADD COLUMN agent_name TEXT")
                except Exception:
                    pass
            if "tool_call_id" not in cols:
                try:
                    self._conn.execute("ALTER TABLE subagent_sessions ADD COLUMN tool_call_id TEXT")
                except Exception:
                    pass
            if "tool_calls" not in cols:
                try:
                    self._conn.execute("ALTER TABLE subagent_sessions ADD COLUMN tool_calls INTEGER DEFAULT 0")
                except Exception:
                    pass
            if "background" not in cols:
                try:
                    self._conn.execute("ALTER TABLE subagent_sessions ADD COLUMN background INTEGER DEFAULT 0")
                except Exception:
                    pass

    def create(self, row: SubagentSessionRow) -> None:
        with self._lock, self._conn:
            self._conn.execute("""
            INSERT OR REPLACE INTO subagent_sessions
            (subagent_id, parent_session_id, child_thread_id, mode, goal, description, agent_name, state, created_at, updated_at, tool_call_id, tool_calls, background, result, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.subagent_id, row.parent_session_id, row.child_thread_id, row.mode, row.goal[:16000],
                (row.description or "")[:200], row.agent_name, row.state, row.created_at, row.updated_at,
                row.tool_call_id, row.tool_calls, 1 if row.background else 0,
                (row.result or "")[:32000] if row.result else None,
                (row.error or "")[:32000] if row.error else None,
            ))
            # cap eviction: keep newest _MAX_SESSIONS
            cnt = self._conn.execute("SELECT COUNT(*) FROM subagent_sessions").fetchone()[0]
            if cnt > _MAX_SESSIONS:
                to_del = cnt - _MAX_SESSIONS
                self._conn.execute("""
                DELETE FROM subagent_sessions WHERE subagent_id IN (
                    SELECT subagent_id FROM subagent_sessions ORDER BY created_at ASC LIMIT ?
                )
                """, (to_del,))

    def update(self, subagent_id: str, **fields) -> None:
        if not fields:
            return
        # whitelist
        allowed = {"state", "updated_at", "result", "error", "tool_calls", "background", "description", "tool_call_id", "agent_name", "goal"}
        set_clauses = []
        vals = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in {"result", "error"} and v is not None:
                v = str(v)[:32000]
            if k == "goal" and v is not None:
                v = str(v)[:16000]
            if k == "description" and v is not None:
                v = str(v)[:200]
            set_clauses.append(f"{k}=?")
            vals.append(v)
        if not set_clauses:
            return
        vals.append(subagent_id)
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE subagent_sessions SET {', '.join(set_clauses)} WHERE subagent_id=?", vals)

    def get(self, subagent_id: str) -> Optional[SubagentSessionRow]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM subagent_sessions WHERE subagent_id=?", (subagent_id,)).fetchone()
        if not row:
            return None
        return self._row_to_dataclass(row)

    def get_by_child(self, child_thread_id: str) -> Optional[SubagentSessionRow]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM subagent_sessions WHERE child_thread_id=?", (child_thread_id,)).fetchone()
        if not row:
            return None
        return self._row_to_dataclass(row)

    def list_by_parent(self, parent_session_id: str) -> list[SubagentSessionRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM subagent_sessions WHERE parent_session_id=? ORDER BY created_at DESC",
                (parent_session_id,)
            ).fetchall()
        return [self._row_to_dataclass(r) for r in rows]

    def list_all(self, limit: int = 100) -> list[SubagentSessionRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM subagent_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [self._row_to_dataclass(r) for r in rows]

    def depth_of(self, thread_id: str) -> int:
        """Walk parent chain to compute nesting depth. Returns 0 for root, 1 for child of root, etc."""
        depth = 0
        current = thread_id
        seen = set()
        with self._lock:
            while True:
                if current in seen:
                    break
                seen.add(current)
                row = self._conn.execute("SELECT parent_session_id FROM subagent_sessions WHERE child_thread_id=?", (current,)).fetchone()
                if not row:
                    # also check subagent_id = thread_id (legacy)
                    row2 = self._conn.execute("SELECT parent_session_id FROM subagent_sessions WHERE subagent_id=?", (current,)).fetchone()
                    if not row2:
                        break
                    parent = row2["parent_session_id"]
                else:
                    parent = row["parent_session_id"]
                if not parent:
                    break
                depth += 1
                current = parent
                if depth > 10:  # safety cap
                    break
        return depth

    def _row_to_dataclass(self, row: sqlite3.Row) -> SubagentSessionRow:
        return SubagentSessionRow(
            subagent_id=row["subagent_id"],
            parent_session_id=row["parent_session_id"],
            child_thread_id=row["child_thread_id"],
            mode=row["mode"],
            goal=row["goal"],
            description=row["description"] or "",
            agent_name=row["agent_name"] or "",
            state=row["state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tool_call_id=row["tool_call_id"],
            tool_calls=row["tool_calls"] or 0,
            background=bool(row["background"]),
            result=row["result"],
            error=row["error"],
        )

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

# Global singleton lazy
_store: Optional[SubagentStore] = None
_store_lock = threading.Lock()

def get_store(db_path: str | Path | None = None) -> SubagentStore:
    global _store
    if db_path is not None:
        return SubagentStore(db_path)
    with _store_lock:
        if _store is None:
            _store = SubagentStore()
        return _store

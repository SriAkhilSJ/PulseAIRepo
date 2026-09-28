"""Durable Crusor session rows — Hermes desktop session pipeline port.

Hermes keeps every conversation in a per-profile ``state.db`` (``sessions`` +
``messages`` tables, see ``hermes_state_sessions.py`` / ``hermes_state_messages.py``)
and serves the desktop through ``session.create`` / ``session.resume`` /
``session.list`` (``tui_gateway/methods_session.py``) plus the REST
``/api/sessions`` resource (``gateway/platforms/api_server.py``).

Crusor's bridge historically kept sessions in an in-memory dict
(``BridgeServer._sessions``) with durability only in the LangGraph checkpointer
(``sessions.db`` ``checkpoints*`` tables, keyed by thread id) and the
append-only event journal (``runtime_events.db``). The desktop therefore could
not list past sessions, page history, or resume after a restart — the Manager
and the workbench Agent Sessions list were projections of sightings, not rows.

This store is the durable half of that pipeline, in the same sqlite file as
the checkpointer and the subagent store (``~/.crusorai/sessions.db``) so one
WAL file carries the whole conversation state:

- ``crusor_sessions`` rows: identity, title, workspace, lifecycle flags
  (pinned / archived / hidden / unread), activity (``last_active``,
  ``message_count``, ``preview``), and lineage (``parent_session_id`` /
  ``lineage_root_id`` for fork children).
- Lazy drafts: ``session.create`` mints an in-memory draft and persists the
  row on the first prompt (Hermes: "no Untitled litter"), except seeded /
  branch children which persist immediately because the renderer's post-create
  resume reads the DB.
- Pinned back-fill: pins are appended past the recency window so "always
  reachable" means reachable (``pageWindow`` in
  ``apps/desktop/src/api/sessions.ts``).
- Lineage tip: a stored id resolves to its latest descendant, so a resumed
  fork/compression lineage lands on the live tip (Hermes ``resolve_tip`` /
  ``get_compression_tip`` family).
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Literal, Optional

# Same env resolution as the subagent store so tests and containers can
# redirect the whole conversation state with one variable.
def _default_db_path() -> Path:
    custom = os.getenv("CRUSORAI_SESSIONS_DB") or os.getenv("CRUSORAI_SESSIONS_DB_PATH")
    if custom:
        return Path(custom).expanduser()
    home_override = os.getenv("CRUSORAI_HOME")
    if home_override:
        return Path(home_override).expanduser() / "sessions.db"
    return Path.home() / ".crusorai" / "sessions.db"


_TITLE_MAX_CHARS = 200
_PREVIEW_MAX_CHARS = 500
_ID_UNSAFE_RE = re.compile(r"[\r\n\x00]")


def sanitize_title(value: Any) -> str:
    """Collapse whitespace and cap length. Empty stays empty (caller decides)."""
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > _TITLE_MAX_CHARS:
        text = text[: _TITLE_MAX_CHARS - 1].rstrip() + "…"
    return text


def derive_title_from_text(text: str) -> str:
    """First user message -> row title (Hermes message-preview naming)."""
    collapsed = re.sub(r"\s+", " ", str(text or "").strip())
    if not collapsed:
        return ""
    if len(collapsed) > 90:
        return collapsed[:89].rstrip() + "…"
    return collapsed


def _is_id_unsafe(session_id: str) -> bool:
    if not session_id or not session_id.strip():
        return True
    if _ID_UNSAFE_RE.search(session_id):
        return True
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return True
    return False


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for flag in ("pinned", "archived", "hidden", "unread"):
        if flag in payload:
            payload[flag] = bool(payload[flag])
    return payload


ArchivedFilter = Literal["exclude", "include", "only"]
SessionOrder = Literal["recent", "created"]


class CrusorSessionStore:
    """Durable session rows in ``sessions.db`` (table ``crusor_sessions``)."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or _default_db_path())
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

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crusor_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT DEFAULT '',
                    workspace TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'desktop',
                    model TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    last_active REAL NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    preview TEXT DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    unread INTEGER NOT NULL DEFAULT 0,
                    parent_session_id TEXT,
                    lineage_root_id TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_crusor_sessions_last_active "
                "ON crusor_sessions(last_active DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_crusor_sessions_workspace "
                "ON crusor_sessions(workspace, last_active DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_crusor_sessions_parent "
                "ON crusor_sessions(parent_session_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_crusor_sessions_lineage "
                "ON crusor_sessions(lineage_root_id, last_active DESC)"
            )
            # Migration: older rows predate lineage columns.
            cols = {row[1] for row in self._conn.execute("PRAGMA table_info(crusor_sessions)").fetchall()}
            for col, ddl in (
                ("parent_session_id", "ALTER TABLE crusor_sessions ADD COLUMN parent_session_id TEXT"),
                ("lineage_root_id", "ALTER TABLE crusor_sessions ADD COLUMN lineage_root_id TEXT"),
                ("unread", "ALTER TABLE crusor_sessions ADD COLUMN unread INTEGER NOT NULL DEFAULT 0"),
                ("hidden", "ALTER TABLE crusor_sessions ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"),
            ):
                if col not in cols:
                    try:
                        self._conn.execute(ddl)
                    except Exception:
                        pass
            # Backfill lineage roots for rows minted before the column existed.
            try:
                self._conn.execute(
                    "UPDATE crusor_sessions SET lineage_root_id = COALESCE(parent_session_id, id) "
                    "WHERE lineage_root_id IS NULL OR lineage_root_id = ''"
                )
            except Exception:
                pass

    # -- writes ---------------------------------------------------------

    def create_session(
        self,
        session_id: str,
        workspace: str = "",
        *,
        source: str = "desktop",
        title: str | None = None,
        model: str | None = None,
        parent_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Upsert a session row without overwriting what an earlier writer set.

        Mirrors Hermes ``_insert_session_row``: the gateway creates a bare row
        before the real model/prompt arrives, so only NULL/empty fields are
        filled. Returns the row as a dict.
        """
        sid = str(session_id or "").strip()
        if _is_id_unsafe(sid):
            raise ValueError(f"invalid session id: {session_id!r}")
        now = time.time()
        clean_title = sanitize_title(title) if title is not None else None
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT * FROM crusor_sessions WHERE id = ?", (sid,)
            ).fetchone()
            if existing is not None:
                updates: list[str] = []
                params: list[Any] = []
                if workspace and not (existing["workspace"] or ""):
                    updates.append("workspace = ?")
                    params.append(workspace)
                if clean_title and not (existing["title"] or ""):
                    updates.append("title = ?")
                    params.append(clean_title)
                if model and not (existing["model"] or ""):
                    updates.append("model = ?")
                    params.append(str(model))
                if parent_session_id and not existing["parent_session_id"]:
                    updates.append("parent_session_id = ?")
                    params.append(parent_session_id)
                    root = self._lineage_root_for_parent(parent_session_id, sid)
                    updates.append("lineage_root_id = ?")
                    params.append(root)
                if updates:
                    params.append(sid)
                    self._conn.execute(
                        f"UPDATE crusor_sessions SET {', '.join(updates)} WHERE id = ?",
                        params,
                    )
                row = self._conn.execute(
                    "SELECT * FROM crusor_sessions WHERE id = ?", (sid,)
                ).fetchone()
                return _row_to_dict(row)
            lineage_root = self._lineage_root_for_parent(parent_session_id, sid)
            self._conn.execute(
                """
                INSERT INTO crusor_sessions
                    (id, title, workspace, source, model, created_at, last_active,
                     message_count, preview, pinned, archived, hidden, unread,
                     parent_session_id, lineage_root_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', 0, 0, 0, 0, ?, ?)
                """,
                (
                    sid,
                    clean_title or "",
                    workspace or "",
                    (source or "desktop").strip() or "desktop",
                    str(model or "") if model else "",
                    now,
                    now,
                    parent_session_id,
                    lineage_root,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM crusor_sessions WHERE id = ?", (sid,)
            ).fetchone()
            return _row_to_dict(row)

    def _lineage_root_for_parent(self, parent_id: str | None, sid: str) -> str:
        if not parent_id:
            return sid
        try:
            parent = self._conn.execute(
                "SELECT lineage_root_id, id FROM crusor_sessions WHERE id = ?",
                (parent_id,),
            ).fetchone()
        except Exception:
            parent = None
        if parent is None:
            return parent_id
        return str(parent["lineage_root_id"] or parent["id"] or parent_id)

    def ensure_row(self, session_id: str, workspace: str = "", **kwargs: Any) -> bool:
        """INSERT OR IGNORE for the lazy first-prompt path. True if inserted."""
        sid = str(session_id or "").strip()
        if _is_id_unsafe(sid):
            raise ValueError(f"invalid session id: {session_id!r}")
        try:
            self.create_session(sid, workspace, **kwargs)
        except Exception:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT created_at, last_active FROM crusor_sessions WHERE id = ?",
                (sid,),
            ).fetchone()
        return row is not None

    def set_title(self, session_id: str, title: str) -> bool:
        clean = sanitize_title(title)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE crusor_sessions SET title = ?, last_active = ? WHERE id = ?",
                (clean, time.time(), session_id),
            )
            return cur.rowcount > 0

    def set_pinned(self, session_id: str, pinned: bool) -> bool:
        return self._set_flag(session_id, "pinned", pinned)

    def set_archived(self, session_id: str, archived: bool) -> bool:
        return self._set_flag(session_id, "archived", archived)

    def set_hidden(self, session_id: str, hidden: bool) -> bool:
        return self._set_flag(session_id, "hidden", hidden)

    def set_read(self, session_id: str, read: bool = True) -> bool:
        return self._set_flag(session_id, "unread", not read)

    def _set_flag(self, session_id: str, column: str, enabled: bool) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE crusor_sessions SET {column} = ? WHERE id = ?",
                (1 if enabled else 0, session_id),
            )
            return cur.rowcount > 0

    def touch_activity(
        self,
        session_id: str,
        *,
        preview: str | None = None,
        message_count_inc: int = 0,
        message_count: int | None = None,
    ) -> bool:
        """Bump last_active; optionally refresh preview / message count."""
        sets = ["last_active = ?"]
        params: list[Any] = [time.time()]
        if preview is not None:
            sets.append("preview = ?")
            params.append(str(preview)[:_PREVIEW_MAX_CHARS])
        if message_count is not None:
            sets.append("message_count = ?")
            params.append(max(0, int(message_count)))
        elif message_count_inc:
            sets.append("message_count = message_count + ?")
            params.append(int(message_count_inc))
        params.append(session_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE crusor_sessions SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            return cur.rowcount > 0

    # -- reads ----------------------------------------------------------

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM crusor_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def resolve_tip(self, session_id: str) -> str:
        """Latest descendant of a lineage (Hermes compression-tip family).

        Follows ``parent_session_id`` edges from the stored id (or its lineage
        root) and returns the id with the greatest ``last_active``. Unknown
        ids resolve to themselves so callers fail open to the requested id.
        """
        sid = str(session_id or "").strip()
        if not sid:
            return sid
        with self._lock:
            row = self._conn.execute(
                "SELECT id, lineage_root_id FROM crusor_sessions WHERE id = ?",
                (sid,),
            ).fetchone()
            root = str(row["lineage_root_id"] or sid) if row is not None else sid
            candidates = self._conn.execute(
                "SELECT id, last_active FROM crusor_sessions "
                "WHERE id = ? OR lineage_root_id = ? OR parent_session_id = ?",
                (sid, root, sid),
            ).fetchall()
        if not candidates:
            return sid
        best = max(candidates, key=lambda r: float(r["last_active"] or 0))
        return str(best["id"])

    def session_matches_stored_id(self, row: dict[str, Any], stored_id: str) -> bool:
        """Same-conversation test across lineage (Hermes ``sessionMatchesStoredId``)."""
        if not stored_id:
            return False
        return (
            row.get("id") == stored_id
            or (row.get("lineage_root_id") or "") == stored_id
            or (row.get("parent_session_id") or "") == stored_id
        )

    def list_sessions_rich(
        self,
        *,
        limit: int = 40,
        offset: int = 0,
        order: SessionOrder = "recent",
        archived: ArchivedFilter = "exclude",
        workspace: str | None = None,
        search_query: str | None = None,
        min_messages: int = 0,
        include_pinned: bool = True,
    ) -> list[dict[str, Any]]:
        """Durable session listing (Hermes ``list_sessions_rich`` shape)."""
        limit = max(1, min(int(limit or 40), 200))
        offset = max(0, int(offset or 0))
        order_col = "created_at DESC" if order == "created" else "last_active DESC"
        where = ["1 = 1"]
        params: list[Any] = []
        if archived == "exclude":
            where.append("archived = 0")
        elif archived == "only":
            where.append("archived = 1")
        if workspace:
            where.append("workspace = ?")
            params.append(workspace)
        if min_messages > 0:
            where.append("message_count >= ?")
            params.append(int(min_messages))
        if search_query and search_query.strip():
            needle = f"%{search_query.strip()}%"
            where.append("(title LIKE ? OR preview LIKE ? OR id LIKE ?)")
            params.extend([needle, needle, needle])
        where_sql = " AND ".join(where)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM crusor_sessions WHERE {where_sql} "
                f"ORDER BY {order_col} LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            result = [_row_to_dict(r) for r in rows]
            # Pinned back-fill past the recency window (Hermes sidebar parity):
            # a pin means "always reachable", so aged-out pins are appended
            # after the window instead of vanishing from the list.
            if include_pinned and archived != "only" and offset == 0 and not search_query:
                seen = {r["id"] for r in result}
                pin_where = list(where) + ["pinned = 1"]
                pin_sql = " AND ".join(pin_where)
                pin_rows = self._conn.execute(
                    f"SELECT * FROM crusor_sessions WHERE {pin_sql} ORDER BY {order_col}",
                    tuple(params),
                ).fetchall()
                for pr in pin_rows:
                    d = _row_to_dict(pr)
                    if d["id"] not in seen:
                        result.append(d)
                        seen.add(d["id"])
        return result

    def count_sessions(
        self,
        *,
        archived: ArchivedFilter = "exclude",
        workspace: str | None = None,
    ) -> int:
        where = ["1 = 1"]
        params: list[Any] = []
        if archived == "exclude":
            where.append("archived = 0")
        elif archived == "only":
            where.append("archived = 1")
        if workspace:
            where.append("workspace = ?")
            params.append(workspace)
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM crusor_sessions WHERE {' AND '.join(where)}",
                tuple(params),
            ).fetchone()
        return int(row[0]) if row else 0

    # -- delete ---------------------------------------------------------

    def delete_session(
        self,
        session_id: str,
        *,
        journal_path: str | Path | None = None,
    ) -> bool:
        """Delete a session row and its durable transcript (Hermes cascade).

        Removes the ``crusor_sessions`` row, the LangGraph ``checkpoints*``
        rows for the thread, child subagent rows parented to it, and —
        best-effort — the ``runtime_events`` journal rows (separate DB file).
        Returns True when a session row was removed.
        """
        sid = str(session_id or "").strip()
        if not sid:
            return False
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM crusor_sessions WHERE id = ?", (sid,))
            removed = cur.rowcount > 0
            # LangGraph checkpointer tables (opaque schema, stable table names).
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                try:
                    self._conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (sid,))
                except Exception:
                    pass
            try:
                self._conn.execute(
                    "DELETE FROM subagent_sessions WHERE parent_session_id = ? OR child_thread_id = ?",
                    (sid, sid),
                )
            except Exception:
                pass
        # Journal lives in runtime_events.db — separate connection, best effort.
        try:
            jpath = Path(journal_path) if journal_path else self.db_path.parent / "runtime_events.db"
            if jpath.exists():
                jconn = sqlite3.connect(str(jpath), timeout=5.0)
                try:
                    jconn.execute("DELETE FROM runtime_events WHERE session_id = ?", (sid,))
                    jconn.commit()
                finally:
                    jconn.close()
        except Exception:
            pass
        return removed

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


_store: CrusorSessionStore | None = None
_store_lock = threading.Lock()


def get_session_store(db_path: str | Path | None = None) -> CrusorSessionStore:
    global _store
    if db_path is not None:
        return CrusorSessionStore(db_path)
    with _store_lock:
        if _store is None:
            _store = CrusorSessionStore()
        return _store


def reset_session_store_for_tests() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            try:
                _store.close()
            except Exception:
                pass
        _store = None

"""
SessionIndex -- zero-LLM long-term conversation recall
======================================================

FTS5 full-text index over PAST conversations (LangGraph checkpoint
threads). Shape lifted from hermes-agent's session_search_tool (§29 ->
D16), including their hard-won lessons:

* **No LLM in the search path.** They once indexed LLM session summaries;
  a cron job demoted them and recall went blind (#19434). Full text never
  drifts; summaries do. This module imports no LLM code and never will.
* **Source demotion** (#19434's other half): automation sessions must not
  starve interactive ones. Our automation class is sub-agent threads
  (``sub-`` prefix); they are returned ONLY when no interactive session
  matches, and are labeled.
* **Compaction-payload exclusion** (#43175): machine-generated handoff
  summaries are skipped AT INGEST (we adopt their marker prefixes so D22's
  compressor writes markers the index already knows to skip).

Storage-side facts these choices stand on (verified, not assumed):

* LangGraph SqliteSaver at ``~/.pulseai/sessions.db`` keeps one row per
  checkpoint, msgpack-serialized; the LATEST checkpoint per thread holds
  the full message list. Decoding MUST go through langgraph's own serde
  (``SqliteSaver.serde.loads_typed``) -- never hand-parse the blob.
* The context engine's 16 layers are REQUEST-ONLY
  (context_engine.build_ai_messages returns a fresh list; state is never
  mutated), so persisted threads are clean user/assistant/tool history.
  Only user + assistant text is indexed; system personas and tool dumps
  would poison BM25 with repeated boilerplate.
* Watermark sync: per thread we store the ingested checkpoint_id; a sync
  re-ingests only threads whose latest checkpoint moved. Same shape as
  chunk_index's per-file mtime sync.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any

# chat_graph.py:_CHECKPOINT_DB duplicates this path (graph checkpointer).
# Keep the literal in both places: importing chat_graph from here would be
# circular (chat_graph imports the tool that imports this).
DEFAULT_CHECKPOINT_DB = os.path.join(
    os.path.expanduser("~"), ".pulseai", "sessions.db"
)
DEFAULT_INDEX_DB = os.path.join(
    os.path.expanduser("~"), ".pulseai", "session_index.db"
)

# Machine-generated handoff summaries (never user content). Adopted from
# hermes (#43175); our D22 compressor will write these same markers.
_COMPACTION_PREFIXES = (
    "[CONTEXT COMPACTION",
    "[CONTEXT SUMMARY]:",
)

# How many raw FTS rows discovery scans before per-thread dedup. Well above
# the handful of sessions a query returns, so interactive matches buried
# under a wall of sub-agent hits still surface (their _DISCOVER_SCAN_LIMIT).
_DISCOVER_SCAN_LIMIT = 300

_SUBAGENT_PREFIX = "sub-"
_UA_ROLES = ("user", "assistant")


def _content_to_text(content: Any) -> str:
    """Flatten LangChain message content (str or list-of-parts) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(p for p in parts if p)
    return ""


def _is_compaction_summary(text: str) -> bool:
    stripped = text.lstrip()
    return any(stripped.startswith(p) for p in _COMPACTION_PREFIXES)


class SessionIndex:
    """Incremental FTS5 index over checkpointed conversation threads."""

    def __init__(
        self,
        checkpoint_db: str = DEFAULT_CHECKPOINT_DB,
        index_db: str = DEFAULT_INDEX_DB,
    ):
        self._checkpoint_db = checkpoint_db
        self._index_db = index_db
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(index_db)), exist_ok=True)
        self._fts_ok = True
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions(
                    thread_id TEXT PRIMARY KEY,
                    title TEXT,
                    started_ts TEXT,
                    last_ts TEXT,
                    msg_count INTEGER,
                    source TEXT,
                    last_checkpoint_id TEXT
                );
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_thread
                    ON messages(thread_id, idx);
                """
            )
            try:
                con.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                        content,
                        thread_id UNINDEXED,
                        message_id UNINDEXED
                    );
                    """
                )
            except sqlite3.OperationalError:
                # FTS5 unavailable (exotic sqlite build): discovery falls
                # back to LIKE scans over `messages`. Same spirit as
                # chunk_index's degraded paths -- recall should degrade,
                # not die.
                self._fts_ok = False

    # ------------------------------------------------------------ plumbing
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._index_db, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    # ---------------------------------------------------------------- sync
    def sync(self) -> dict[str, int]:
        """Re-ingest threads whose latest checkpoint moved. Watermark-cheap:
        one scan of the checkpoints table when nothing changed."""
        if not os.path.exists(self._checkpoint_db):
            return {"threads": 0, "reingested": 0}

        from langgraph.checkpoint.sqlite import SqliteSaver

        src = sqlite3.connect(self._checkpoint_db, timeout=30)
        try:
            latest = src.execute(
                """
                SELECT thread_id, checkpoint_id, type, checkpoint
                FROM checkpoints
                WHERE checkpoint_ns = ''
                  AND rowid IN (
                      SELECT MAX(rowid) FROM checkpoints
                      WHERE checkpoint_ns = '' GROUP BY thread_id
                  )
                """
            ).fetchall()
        except sqlite3.OperationalError:
            # checkpoints table not created yet (fresh install).
            src.close()
            return {"threads": 0, "reingested": 0}

        saver = SqliteSaver(src)  # only used for its serde; no .setup()

        stats = {"threads": len(latest), "reingested": 0}
        with self._lock, self._connect() as con:
            alive_ids = set()
            for thread_id, ckpt_id, typ, blob in latest:
                alive_ids.add(thread_id)
                done = con.execute(
                    "SELECT last_checkpoint_id FROM sessions WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
                if done and done[0] == ckpt_id:
                    continue  # watermark: unchanged thread
                try:
                    checkpoint = saver.serde.loads_typed((typ, blob))
                except Exception:
                    continue  # one corrupt checkpoint must not stall sync
                self._ingest_thread(con, thread_id, ckpt_id, checkpoint)
                stats["reingested"] += 1

            # Threads pruned from the checkpoint DB disappear from recall
            # too (they're gone; pretending otherwise would resurrect them).
            stale = con.execute(
                "SELECT thread_id FROM sessions"
            ).fetchall()
            for (tid,) in stale:
                if tid not in alive_ids:
                    self._delete_thread(con, tid)
        src.close()
        return stats

    def _delete_thread(self, con: sqlite3.Connection, thread_id: str) -> None:
        con.execute("DELETE FROM sessions WHERE thread_id = ?", (thread_id,))
        con.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        if self._fts_ok:
            con.execute("DELETE FROM messages_fts WHERE thread_id = ?", (thread_id,))

    def _ingest_thread(
        self, con: sqlite3.Connection, thread_id: str, ckpt_id: str, checkpoint: dict
    ) -> None:
        """Replace a thread's rows transactionally (caller holds the txn)."""
        raw_msgs = checkpoint.get("channel_values", {}).get("messages", [])
        ts = str(checkpoint.get("ts", ""))

        ua: list[tuple[str, str]] = []
        for msg in raw_msgs:
            kind = type(msg).__name__
            if kind == "HumanMessage":
                role = "user"
            elif kind == "AIMessage":
                role = "assistant"
            else:
                continue  # system personas, tool dumps: BM25 poison
            text = _content_to_text(getattr(msg, "content", ""))
            if not text.strip() or _is_compaction_summary(text):
                continue
            ua.append((role, text))

        self._delete_thread(con, thread_id)
        for idx, (role, text) in enumerate(ua):
            cur = con.execute(
                "INSERT INTO messages(thread_id, idx, role, content) VALUES(?,?,?,?)",
                (thread_id, idx, role, text),
            )
            if self._fts_ok:
                con.execute(
                    "INSERT INTO messages_fts(content, thread_id, message_id) VALUES(?,?,?)",
                    (text, thread_id, cur.lastrowid),
                )

        title = next((t for r, t in ua if r == "user"), "(no user messages)")
        title = title.strip().splitlines()[0][:80] if title.strip() else "(empty)"
        source = "sub" if str(thread_id).startswith(_SUBAGENT_PREFIX) else "interactive"
        con.execute(
            """
            INSERT OR REPLACE INTO sessions
                (thread_id, title, started_ts, last_ts, msg_count, source, last_checkpoint_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (thread_id, title, ts, ts, len(ua), source, ckpt_id),
        )

    # -------------------------------------------------------------- queries
    def fts_hits(self, query: str, scan_limit: int = _DISCOVER_SCAN_LIMIT) -> list[dict]:
        """BM25-ordered raw hits: [{thread_id, message_id, snippet}]."""
        with self._lock, self._connect() as con:
            if self._fts_ok:
                try:
                    rows = con.execute(
                        """
                        SELECT thread_id, message_id,
                               snippet(messages_fts, 0, '', '', '…', 32)
                        FROM messages_fts
                        WHERE messages_fts MATCH ?
                        ORDER BY rank LIMIT ?
                        """,
                        (query, scan_limit),
                    ).fetchall()
                    return [
                        {"thread_id": t, "message_id": m, "snippet": s}
                        for t, m, s in rows
                    ]
                except sqlite3.OperationalError:
                    return []  # un-parseable MATCH syntax = no hits
            # LIKE fallback (FTS5 missing)
            like = f"%{query}%"
            rows = con.execute(
                "SELECT id, thread_id, content FROM messages WHERE content LIKE ? LIMIT ?",
                (like, scan_limit),
            ).fetchall()
            out = []
            for mid, tid, content in rows:
                pos = content.lower().find(query.lower())
                start = max(0, pos - 60)
                out.append({
                    "thread_id": tid,
                    "message_id": mid,
                    "snippet": ("…" if start else "") + content[start:pos + 60] + "…",
                })
            return out

    def sessions_for(self, thread_ids: list[str]) -> dict[str, dict]:
        """Session metadata rows keyed by thread_id (preserves input order)."""
        if not thread_ids:
            return {}
        marks = ",".join("?" for _ in thread_ids)
        with self._lock, self._connect() as con:
            rows = con.execute(
                f"SELECT thread_id, title, started_ts, msg_count, source "
                f"FROM sessions WHERE thread_id IN ({marks})",
                thread_ids,
            ).fetchall()
        by_id = {
            r[0]: {"title": r[1], "started_ts": r[2], "msg_count": r[3], "source": r[4]}
            for r in rows
        }
        return {tid: by_id[tid] for tid in thread_ids if tid in by_id}

    def message_by_id(self, message_id: int) -> tuple[str, int] | None:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT thread_id, idx FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return (row[0], row[1]) if row else None

    def window(self, thread_id: str, center_idx: int, radius: int) -> list[dict]:
        """Messages idx in [center-radius, center+radius] for a thread."""
        with self._lock, self._connect() as con:
            rows = con.execute(
                "SELECT idx, role, content FROM messages "
                "WHERE thread_id = ? AND idx BETWEEN ? AND ? ORDER BY idx",
                (thread_id, center_idx - radius, center_idx + radius),
            ).fetchall()
        return [{"idx": i, "role": r, "content": c} for i, r, c in rows]

    def bookends(self, thread_id: str, n: int = 3) -> tuple[list[dict], list[dict]]:
        """First n and last n user/assistant messages (their bookend shape)."""
        with self._lock, self._connect() as con:
            first = con.execute(
                "SELECT idx, role, content FROM messages WHERE thread_id = ? "
                "ORDER BY idx LIMIT ?",
                (thread_id, n),
            ).fetchall()
            last = con.execute(
                "SELECT idx, role, content FROM messages WHERE thread_id = ? "
                "ORDER BY idx DESC LIMIT ?",
                (thread_id, n),
            ).fetchall()
        head = [{"idx": i, "role": r, "content": c} for i, r, c in first]
        tail = [{"idx": i, "role": r, "content": c} for i, r, c in reversed(last)]
        return head, tail

    def recent_sessions(self, limit: int = 10, exclude_thread: str | None = None) -> list[dict]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                "SELECT thread_id, title, started_ts, msg_count, source "
                "FROM sessions WHERE thread_id IS NOT ? "
                "ORDER BY last_ts DESC LIMIT ?",
                (exclude_thread or "", limit),
            ).fetchall()
        return [
            {
                "thread_id": t,
                "title": ti,
                "started_ts": st,
                "msg_count": mc,
                "source": src_,
            }
            for t, ti, st, mc, src_ in rows
        ]

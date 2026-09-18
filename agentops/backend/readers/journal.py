"""Read-only reader over the engine's durable event journal (SQLite, WAL).

Opened with mode=ro so the dashboard can NEVER corrupt agent state. The journal
is the canonical execution timeline: `tool.intent` commits before a side-effecting
tool runs; `tool.result` commits before its completion event — which makes it an
audit trail by construction.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .. import config

ACTIVE_WINDOW_S = 300  # last activity within 5 min => session considered active

_ROW_COLS = (
    "seq", "event_id", "created_at", "event_type", "session_id",
    "turn_id", "workspace_id", "tool_call_id", "payload_json",
)


def _connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        d = {c: r[c] for c in _ROW_COLS}
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


def available() -> bool:
    return config.journal_path().exists()


def list_sessions(limit: int = 200) -> list[dict[str, Any]]:
    conn = _connect(config.journal_path())
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT session_id,
                   MIN(created_at) AS first_at,
                   MAX(created_at) AS last_at,
                   COUNT(*) AS events,
                   COUNT(DISTINCT turn_id) AS turns,
                   SUM(event_type = 'turn_failed') AS failures,
                   SUM(event_type = 'turn_done') AS dones,
                   MAX(workspace_id) AS workspace
            FROM runtime_events
            GROUP BY session_id
            ORDER BY last_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        modes: dict[str, str] = {}
        for r in rows:
            sid = r["session_id"]
            m = conn.execute(
                "SELECT payload_json FROM runtime_events WHERE session_id=? AND event_type='session_create' ORDER BY seq LIMIT 1",
                (sid,),
            ).fetchone()
            mode = ""
            if m:
                try:
                    mode = (json.loads(m["payload_json"] or "{}")).get("mode", "")
                except Exception:
                    mode = ""
            modes[sid] = mode or "agent"
        now = time.time()
        out = []
        for r in rows:
            last = float(r["last_at"])
            if float(r["failures"]) > float(r["dones"]):
                status = "failed"
            elif now - last <= ACTIVE_WINDOW_S:
                status = "active"
            else:
                status = "idle"
            out.append({
                "session_id": r["session_id"],
                "first_at": last - (last - float(r["first_at"])),
                "started_at": float(r["first_at"]),
                "last_at": last,
                "events": int(r["events"]),
                "turns": int(r["turns"]),
                "failures": int(r["failures"]),
                "workspace": r["workspace"] or "",
                "mode": modes.get(r["session_id"], "agent"),
                "status": status,
            })
        return out
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def session_trace(session_id: str) -> list[dict[str, Any]]:
    conn = _connect(config.journal_path())
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM runtime_events WHERE session_id=? ORDER BY seq",
            (session_id,),
        ).fetchall()
        return _rows_to_dicts(rows)
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def audit(limit: int = 500, since_seq: int = 0) -> list[dict[str, Any]]:
    conn = _connect(config.journal_path())
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM runtime_events WHERE seq > ? ORDER BY seq DESC LIMIT ?",
            (since_seq, limit),
        ).fetchall()
        return list(reversed(_rows_to_dicts(rows)))
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def tail(since_seq: int, limit: int = 200) -> list[dict[str, Any]]:
    return audit(limit=limit, since_seq=since_seq)


def tool_stats(days: int = 7) -> list[dict[str, Any]]:
    """Per-tool calls / failures / latency from intent→result pairs."""
    conn = _connect(config.journal_path())
    if conn is None:
        return []
    cutoff = time.time() - days * 86400
    try:
        rows = conn.execute(
            """
            SELECT i.tool_call_id AS tcid,
                   i.payload_json AS ipay,
                   i.created_at AS iat,
                   r.payload_json AS rpay,
                   r.created_at AS rat
            FROM runtime_events i
            LEFT JOIN runtime_events r
              ON r.tool_call_id = i.tool_call_id AND r.event_type = 'tool.result'
             AND r.session_id = i.session_id
            WHERE i.event_type = 'tool.intent' AND i.created_at >= ?
            """,
            (cutoff,),
        ).fetchall()
        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            try:
                name = (json.loads(r["ipay"] or "{}")).get("tool_name", "?")
            except Exception:
                name = "?"
            a = agg.setdefault(name, {"tool": name, "calls": 0, "failures": 0, "latency_sum": 0.0, "latency_n": 0})
            a["calls"] += 1
            if r["rpay"]:
                try:
                    status = (json.loads(r["rpay"] or "{}")).get("status", "ok")
                except Exception:
                    status = "ok"
                if status not in ("ok", "success"):
                    a["failures"] += 1
                a["latency_sum"] += max(0.0, float(r["rat"]) - float(r["iat"]))
                a["latency_n"] += 1
        out = []
        for a in agg.values():
            out.append({
                "tool": a["tool"],
                "calls": a["calls"],
                "failures": a["failures"],
                "avg_latency_s": round(a["latency_sum"] / a["latency_n"], 3) if a["latency_n"] else None,
            })
        out.sort(key=lambda x: x["calls"], reverse=True)
        return out
    except sqlite3.Error:
        return []
    finally:
        conn.close()

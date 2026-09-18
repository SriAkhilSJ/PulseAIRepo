"""Debris-tolerant reader over the engine's JSONL turn receipts.

One record per turn (session, turn, model, provider, token buckets, cost,
duration, tool calls, execution mode, task type, completed, error). Bad lines
are skipped — receipts can never break the dashboard, and the dashboard can
never write to the sink.
"""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config
from ..pricing import turn_cost


def _load(path: Path, since_ts: float | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                rec["_cost"] = turn_cost(rec)
                tok = rec.get("tokens") or {}
                rec["_tokens"] = int(tok.get("input") or 0) + int(tok.get("output") or 0)
                rec["_ts"] = _epoch(rec.get("ts", ""))
                if since_ts is not None and rec["_ts"] < since_ts:
                    continue
                out.append(rec)
    except OSError:
        return []
    return out


def _epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


def available() -> bool:
    return config.receipts_path().exists()


def turns(days: int = 7, limit: int = 500) -> list[dict[str, Any]]:
    since = time.time() - days * 86400
    recs = _load(config.receipts_path(), since_ts=since)
    recs.sort(key=lambda r: r["_ts"])
    return recs[-limit:]


def sessions_from_receipts() -> list[dict[str, Any]]:
    """Receipts-only session view: the observability sink alone powers Sessions
    when the journal has no rows for a session (typical live deployment)."""
    recs = turns(days=30, limit=20000)
    agg: dict[str, dict[str, Any]] = {}
    for r in recs:
        sid = str(r.get("session") or "?")
        a = agg.setdefault(sid, {
            "session_id": sid, "started_at": r["_ts"], "last_at": r["_ts"],
            "events": 0, "turns": 0, "failures": 0, "workspace": "",
            "mode": r.get("execution_mode") or "agent", "model": r.get("model"),
            "cost_usd": 0.0, "tokens": 0,
        })
        a["last_at"] = max(a["last_at"], r["_ts"])
        a["started_at"] = min(a["started_at"], r["_ts"])
        a["turns"] += 1
        a["cost_usd"] = round(a["cost_usd"] + r["_cost"], 4)
        a["tokens"] += r["_tokens"]
        if not r.get("completed"):
            a["failures"] += 1
    import time as _t
    now = _t.time()
    out = []
    for a in agg.values():
        a["status"] = "failed" if a["failures"] and a["failures"] >= a["turns"] else (
            "active" if now - a["last_at"] <= 300 else "idle")
        out.append(a)
    out.sort(key=lambda x: x["last_at"], reverse=True)
    return out


def synthetic_trace_events(session_id: str) -> list[dict[str, Any]]:
    """Replay-able timeline synthesized from receipts when the journal has no rows."""
    out = []
    seq = 0
    for r in turns(days=30, limit=20000):
        if r.get("session") != session_id:
            continue
        seq += 1
        tok = r.get("tokens") or {}
        out.append({
            "seq": seq, "event_id": f"rcpt-{seq}", "created_at": r["_ts"],
            "event_type": "turn_receipt", "session_id": session_id,
            "turn_id": r.get("turn"), "workspace_id": None, "tool_call_id": None,
            "payload": {
                "model": r.get("model"), "provider": r.get("provider"),
                "tokens_in": tok.get("input"), "tokens_out": tok.get("output"),
                "tokens_cache": tok.get("cache"), "cost_usd": round(r["_cost"], 6),
                "duration_s": r.get("duration_s"), "mode": r.get("execution_mode"),
                "task_type": r.get("task_type"), "completed": r.get("completed"),
                "error": r.get("error"), "tool_calls": r.get("tool_calls"),
                "source": "receipts-sink",
            },
        })
    return out


def kpis(days: int = 1) -> dict[str, Any]:
    recs = turns(days=days, limit=10000)
    prev = _load(config.receipts_path(), since_ts=time.time() - 2 * days * 86400)
    prev = [r for r in prev if r["_ts"] < time.time() - days * 86400]

    def block(rs: list[dict[str, Any]]) -> dict[str, Any]:
        tokens = sum(r["_tokens"] for r in rs)
        cost = sum(r["_cost"] for r in rs)
        done = sum(1 for r in rs if r.get("completed"))
        durs = sorted(float(r.get("duration_s") or 0) for r in rs)
        return {
            "turns": len(rs),
            "tokens": tokens,
            "cost_usd": round(cost, 4),
            "completion": round(done / len(rs), 4) if rs else None,
            "p95_latency_s": round(durs[min(len(durs) - 1, int(0.95 * len(durs)))], 2) if durs else None,
        }

    cur = block(recs)
    old = block(prev)
    return {"current": cur, "previous": old, "window_days": days}


def series(days: int = 7) -> list[dict[str, Any]]:
    """Daily buckets for sparklines / control charts."""
    recs = _load(config.receipts_path(), since_ts=time.time() - days * 86400)
    buckets: dict[str, dict[str, Any]] = {}
    for r in recs:
        day = datetime.fromtimestamp(r["_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        b = buckets.setdefault(day, {"day": day, "turns": 0, "tokens": 0, "cost_usd": 0.0, "errors": 0})
        b["turns"] += 1
        b["tokens"] += r["_tokens"]
        b["cost_usd"] = round(b["cost_usd"] + r["_cost"], 4)
        if not r.get("completed"):
            b["errors"] += 1
    return [buckets[k] for k in sorted(buckets)]


def summary(group_by: str, days: int = 7) -> list[dict[str, Any]]:
    recs = _load(config.receipts_path(), since_ts=time.time() - days * 86400)
    keymap = {
        "day": lambda r: datetime.fromtimestamp(r["_ts"], tz=timezone.utc).strftime("%Y-%m-%d"),
        "model": lambda r: r.get("model") or "?",
        "provider": lambda r: r.get("provider") or "?",
        "mode": lambda r: r.get("execution_mode") or "?",
        "task": lambda r: r.get("task_type") or "?",
        "session": lambda r: r.get("session") or "?",
    }
    fn = keymap.get(group_by, keymap["day"])
    agg: dict[str, dict[str, Any]] = {}
    for r in recs:
        k = str(fn(r))
        a = agg.setdefault(k, {"key": k, "turns": 0, "tokens": 0, "cache_tokens": 0, "cost_usd": 0.0, "errors": 0, "duration_sum": 0.0})
        a["turns"] += 1
        a["tokens"] += r["_tokens"]
        a["cache_tokens"] += int((r.get("tokens") or {}).get("cache") or 0)
        a["cost_usd"] = round(a["cost_usd"] + r["_cost"], 4)
        a["duration_sum"] += float(r.get("duration_s") or 0)
        if not r.get("completed"):
            a["errors"] += 1
    out = []
    for a in agg.values():
        a["avg_duration_s"] = round(a["duration_sum"] / a["turns"], 2) if a["turns"] else 0.0
        a["cache_hit_ratio"] = round(a["cache_tokens"] / a["tokens"], 4) if a["tokens"] else 0.0
        del a["duration_sum"]
        out.append(a)
    out.sort(key=lambda x: x["cost_usd"], reverse=True)
    return out


def errors(days: int = 7, limit: int = 200) -> list[dict[str, Any]]:
    recs = _load(config.receipts_path(), since_ts=time.time() - days * 86400)
    bad = [r for r in recs if (not r.get("completed")) or str(r.get("error") or "").strip()]
    bad.sort(key=lambda r: r["_ts"], reverse=True)
    out = []
    for r in bad[:limit]:
        out.append({
            "ts": r.get("ts"),
            "session": r.get("session"),
            "turn": r.get("turn"),
            "model": r.get("model"),
            "mode": r.get("execution_mode"),
            "error": r.get("error") or "turn completed=False",
            "tool_calls": r.get("tool_calls"),
        })
    return out


def runtime_receipts(days: int = 7) -> list[dict[str, Any]]:
    """Latched runtime.* anomalies carried in receipt `extra` (cache_break, degraded)."""
    recs = _load(config.receipts_path(), since_ts=time.time() - days * 86400)
    out = []
    for r in recs:
        extra = r.get("extra") or {}
        for key in ("runtime.cache_break", "runtime.degraded", "cache_break", "degraded"):
            if key in extra:
                out.append({
                    "ts": r.get("ts"),
                    "session": r.get("session"),
                    "kind": key,
                    "detail": extra[key],
                })
    out.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return out

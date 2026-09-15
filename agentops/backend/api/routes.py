"""CrusorAI AgentOps API routes (Phase 1 surface)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .. import config
from ..readers import journal, receipts

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "product": "CrusorAI AgentOps",
        "version": "0.1.0",
        "status": "ok",
        "data_source": "demo" if config.demo_mode() else "live",
        "journal": {"path": str(config.journal_path()), "available": journal.available()},
        "receipts": {"path": str(config.receipts_path()), "available": receipts.available()},
        "auth_required": bool(config.token()),
        "time": time.time(),
    }


@router.get("/sessions")
def sessions(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    rows = journal.list_sessions(limit=limit)
    recv = {r.get("session"): r for r in receipts.turns(days=30, limit=5000)}
    for row in rows:
        r = recv.get(row["session_id"])
        row["cost_usd"] = round(r["_cost"], 4) if r else None
        row["tokens"] = r["_tokens"] if r else None
        row["model"] = r.get("model") if r else None
    return {"sessions": rows}


@router.get("/sessions/{session_id}/trace")
def trace(session_id: str) -> dict[str, Any]:
    events = journal.session_trace(session_id)
    if not events:
        # receipts-only fallback: sessions that predate journaling still show usage
        recv = [r for r in receipts.turns(days=30, limit=5000) if r.get("session") == session_id]
        if not recv:
            raise HTTPException(404, "session not found")
    tools: dict[str, dict[str, Any]] = {}
    turns: list[dict[str, Any]] = []
    cur_turn: dict[str, Any] | None = None
    for ev in events:
        if ev["event_type"] == "turn_started":
            cur_turn = {"turn_id": ev["turn_id"], "started_at": ev["created_at"], "ended_at": None, "status": "running", "events": []}
            turns.append(cur_turn)
        target = cur_turn if cur_turn is not None else None
        if target is not None:
            target["events"].append(ev)
        if ev["event_type"] in ("turn_done", "turn_failed"):
            if cur_turn is not None:
                cur_turn["ended_at"] = ev["created_at"]
                cur_turn["status"] = "failed" if ev["event_type"] == "turn_failed" else "done"
                cur_turn = None
        if ev["event_type"] in ("tool.intent", "tool.result") and ev.get("tool_call_id"):
            t = tools.setdefault(ev["tool_call_id"], {
                "tool_call_id": ev["tool_call_id"],
                "name": (ev.get("payload") or {}).get("tool_name", "?"),
                "intent_at": None, "result_at": None,
                "args": None, "status": None, "content_preview": None,
            })
            if ev["event_type"] == "tool.intent":
                t["intent_at"] = ev["created_at"]
                t["args"] = (ev.get("payload") or {}).get("args")
            else:
                t["result_at"] = ev["created_at"]
                t["status"] = (ev.get("payload") or {}).get("status", "ok")
                content = (ev.get("payload") or {}).get("content")
                t["content_preview"] = (str(content)[:400] + ("…" if len(str(content)) > 400 else "")) if content is not None else None
    tool_list = sorted(tools.values(), key=lambda t: t["intent_at"] or 0)
    for t in tool_list:
        if t["intent_at"] and t["result_at"]:
            t["duration_s"] = round(t["result_at"] - t["intent_at"], 3)
    turn_receipts = [
        {
            "turn": r.get("turn"), "model": r.get("model"), "provider": r.get("provider"),
            "tokens": r.get("tokens"), "cost_usd": round(r["_cost"], 6),
            "duration_s": r.get("duration_s"), "tool_calls": r.get("tool_calls"),
            "completed": r.get("completed"), "error": r.get("error"),
            "mode": r.get("execution_mode"), "task_type": r.get("task_type"),
        }
        for r in receipts.turns(days=30, limit=5000) if r.get("session") == session_id
    ]
    return {
        "session_id": session_id,
        "events": events,
        "turns": turns,
        "tools": tool_list,
        "receipts": turn_receipts,
    }


@router.get("/audit")
def audit(limit: int = Query(300, ge=1, le=2000), since_seq: int = 0) -> dict[str, Any]:
    return {"events": journal.audit(limit=limit, since_seq=since_seq)}


@router.get("/kpis")
def kpis(days: int = Query(1, ge=1, le=30)) -> dict[str, Any]:
    return receipts.kpis(days=days)


@router.get("/usage/summary")
def usage_summary(group_by: str = Query("day"), days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    return {"group_by": group_by, "rows": receipts.summary(group_by, days)}


@router.get("/usage/series")
def usage_series(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    return {"series": receipts.series(days)}


@router.get("/usage/turns")
def usage_turns(days: int = Query(7, ge=1, le=90), limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    recs = receipts.turns(days=days, limit=limit)
    out = [{
        "ts": r.get("ts"), "session": r.get("session"), "turn": r.get("turn"),
        "model": r.get("model"), "provider": r.get("provider"),
        "tokens": r.get("tokens"), "cost_usd": round(r["_cost"], 6),
        "duration_s": r.get("duration_s"), "mode": r.get("execution_mode"),
        "task_type": r.get("task_type"), "completed": r.get("completed"),
        "error": r.get("error"), "tool_calls": r.get("tool_calls"),
    } for r in reversed(recs)]
    return {"turns": out}


@router.get("/tools/stats")
def tools_stats(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    return {"tools": journal.tool_stats(days)}


@router.get("/errors")
def errors(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    return {"errors": receipts.errors(days), "runtime_receipts": receipts.runtime_receipts(days)}


@router.get("/stream")
async def stream(request: Request):
    """SSE live tail: journal rows + new receipts, crash-safe and read-only."""
    last_seq = 0
    rows = journal.audit(limit=1, since_seq=0)
    if rows:
        last_seq = rows[-1]["seq"]
    else:
        allrows = journal.audit(limit=1, since_seq=0)
        last_seq = allrows[-1]["seq"] if allrows else 0
    # start at current journal head so replays don't flood new subscribers
    head = journal.audit(limit=5000, since_seq=0)
    last_seq = head[-1]["seq"] if head else 0
    receipt_count = len(receipts.turns(days=365, limit=100000))

    async def gen():
        nonlocal last_seq, receipt_count
        yield f"event: hello\ndata: {json.dumps({'ts': time.time()})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            new_rows = journal.tail(since_seq=last_seq, limit=200)
            for row in new_rows:
                last_seq = max(last_seq, row["seq"])
                yield f"event: journal\ndata: {json.dumps(row, default=str)}\n\n"
            now_count = len(receipts.turns(days=365, limit=100000))
            if now_count > receipt_count:
                fresh = receipts.turns(days=365, limit=100000)[receipt_count:]
                receipt_count = now_count
                for r in fresh:
                    payload = {k: v for k, v in r.items() if not k.startswith("_")}
                    payload["cost_usd"] = round(r["_cost"], 6)
                    yield f"event: receipt\ndata: {json.dumps(payload, default=str)}\n\n"
            yield ": hb\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

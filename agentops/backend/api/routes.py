"""CrusorAI AgentOps API routes (Phase 1 surface)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .. import config, engine_proxy, spc
from ..readers import approvals, journal, perf, prompts, receipts, status_snap

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
    seen = {r["session_id"] for r in rows}
    recv = {r.get("session"): r for r in receipts.turns(days=30, limit=5000)}
    for row in rows:
        r = recv.get(row["session_id"])
        row["cost_usd"] = round(r["_cost"], 4) if r else None
        row["tokens"] = r["_tokens"] if r else None
        row["model"] = r.get("model") if r else None
    # receipts-only sessions (live deployments where the journal lacks rows)
    for rs in receipts.sessions_from_receipts():
        if rs["session_id"] not in seen:
            rows.append(rs)
            seen.add(rs["session_id"])
    rows.sort(key=lambda x: x.get("last_at") or 0, reverse=True)
    return {"sessions": rows[:limit]}


@router.get("/sessions/{session_id}/trace")
def trace(session_id: str) -> dict[str, Any]:
    events = journal.session_trace(session_id)
    if not events:
        # receipts-only fallback: synthesize a replay-able timeline from the sink
        recv = [r for r in receipts.turns(days=30, limit=5000) if r.get("session") == session_id]
        if not recv:
            raise HTTPException(404, "session not found")
        events = receipts.synthetic_trace_events(session_id)
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


# ---------------------------------------------------------------- Phase 2 ----

@router.get("/context/sessions")
def context_sessions() -> dict[str, Any]:
    return {"sessions": status_snap.latest_per_session()}


@router.get("/context/{session_id}/history")
def context_history(session_id: str) -> dict[str, Any]:
    return {"history": status_snap.history(session_id)}


@router.get("/context/live")
def context_live(thread_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    """On-demand proxy of the engine's get_status() when live proxy is configured."""
    if not engine_proxy.ENGINE_URL:
        return {"error": "live proxy not configured (set CRUSORAI_OPS_ENGINE_URL)", "status": 501}
    status, body = engine_proxy.context_status(thread_id)
    if status != 200:
        raise HTTPException(status, body.get("error", "engine context status failed"))
    return body


@router.get("/approvals")
def approvals_list(state: str = Query("pending")) -> dict[str, Any]:
    if state == "pending":
        return {"pending": approvals.pending(), "engine_live": engine_proxy.live_connected()}
    return {"history": approvals.history()}


@router.get("/approvals/stats")
def approvals_stats(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    return approvals.stats(days)


@router.post("/approvals/{tool_id}/resolve")
async def approvals_resolve(tool_id: str, body: dict[str, Any] = {}) -> dict[str, Any]:
    approved = bool(body.get("approved", False))
    always = bool(body.get("always_allow", False))
    thread_id = body.get("thread_id") or None
    if engine_proxy.ENGINE_URL:
        status, resp = await asyncio.to_thread(engine_proxy.resolve, tool_id, approved, always, thread_id)
        if status >= 400:
            raise HTTPException(status, resp.get("error", "engine rejected decision"))
        return {"forwarded": True, "engine": resp}
    if config.demo_mode():
        pend = {p["tool_id"]: p for p in approvals.pending()}
        approvals.record_decision(tool_id, approved, always, (pend.get(tool_id) or {}).get("session_id", ""))
        return {"forwarded": False, "demo": True}
    raise HTTPException(501, "no engine proxy and not in demo mode — decision not recorded")


@router.get("/perf")
def perf_view(days: int = Query(7, ge=1, le=90), group_by: str = Query("model")) -> dict[str, Any]:
    return {"percentiles": perf.percentiles(days, group_by), "throughput": perf.throughput(days)}


@router.get("/slo")
def slo(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    series = receipts.series(days)
    recs = receipts.turns(days=days, limit=20000)
    n = len(recs)
    done = sum(1 for r in recs if r.get("completed"))
    cost = sum(r["_cost"] for r in recs)
    durs = sorted(float(r.get("duration_s") or 0) for r in recs)
    p95 = durs[min(len(durs) - 1, int(0.95 * len(durs)))] if durs else None
    targets = config.slo_targets()
    current = {
        "completion": round(done / n, 4) if n else None,
        "p95_latency_s": p95,
        "cost_per_task": round(cost / n, 6) if n else None,
        "uptime_proxy": round(done / n, 4) if n else None,  # journal-backed availability proxy
    }
    return {
        "targets": targets,
        "current": current,
        "control": {
            "cost_per_day": spc.chart(series, "cost_usd"),
            "errors_per_day": spc.chart(series, "errors"),
            "tokens_per_day": spc.chart(series, "tokens"),
        },
        "window_days": days,
    }


@router.get("/prompts")
def prompts_view() -> dict[str, Any]:
    return prompts.registry()


@router.post("/control/stop")
async def control_stop(body: dict[str, Any] = {}) -> dict[str, Any]:
    """Kill switch [PDF §6]. Demo: signals the simulator via the control sidecar.
    Live: the engine exposes no HTTP cancel route yet — surfaced as 501 with guidance."""
    session_id = str(body.get("session_id") or "").strip()
    if config.demo_mode():
        p = config.data_dir() / "control.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        import time as _time
        with open(p, "a", encoding="utf-8") as f:
            f.write(_json.dumps({"action": "stop", "session_id": session_id or "*", "at": _time.time()}) + "\n")
        return {"ok": True, "demo": True, "session_id": session_id or "*"}
    if engine_proxy.ENGINE_URL:
        raise HTTPException(501, "engine HTTP surface has no cancel route yet (bridge-only); use the IDE stop command")
    raise HTTPException(501, "kill switch requires demo mode or an engine cancel route")

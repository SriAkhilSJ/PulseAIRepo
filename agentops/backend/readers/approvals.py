"""Approval broker reader.

Sources, unified:
  * journal rows  tool.approval.request / tool.approval.done  (durable history + demo)
  * sidecar file  approvals_decisions.jsonl                   (demo-mode operator decisions)
  * in-memory     live pending queue mirrored from the engine SSE proxy (engine_proxy.py)

Fail-closed semantics are the ENGINE's contract (timeout = deny, cross-session rejected);
this module only observes and forwards operator decisions.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import journal
from .. import config


def _sidecar() -> list[dict[str, Any]]:
    p = config.data_dir() / "approvals_decisions.jsonl"
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def pending() -> list[dict[str, Any]]:
    """Open approval requests: journaled requests without a done/decision, plus live mirror."""
    from ..engine_proxy import live_pending

    rows = journal.audit(limit=2000, since_seq=0)
    reqs: dict[str, dict[str, Any]] = {}
    done: set[str] = set()
    for ev in rows:
        if ev["event_type"] == "tool.approval.request":
            tid = (ev.get("payload") or {}).get("tool_id") or ev.get("tool_call_id") or ev["event_id"]
            reqs[tid] = {
                "tool_id": tid,
                "session_id": ev["session_id"],
                "requested_at": ev["created_at"],
                "tool_name": (ev.get("payload") or {}).get("tool_name", "?"),
                "args": (ev.get("payload") or {}).get("args"),
                "source": "journal",
            }
        elif ev["event_type"] == "tool.approval.done":
            done.add((ev.get("payload") or {}).get("tool_id") or ev.get("tool_call_id") or "")
    for d in _sidecar():
        done.add(d.get("tool_id", ""))
    out = [r for tid, r in reqs.items() if tid not in done]
    out.extend(live_pending())
    out.sort(key=lambda r: r.get("requested_at") or 0)
    return out


def history(limit: int = 100) -> list[dict[str, Any]]:
    rows = journal.audit(limit=4000, since_seq=0)
    req_at: dict[str, float] = {}
    out: list[dict[str, Any]] = []
    for ev in rows:
        p = ev.get("payload") or {}
        tid = p.get("tool_id") or ev.get("tool_call_id") or ""
        if ev["event_type"] == "tool.approval.request":
            req_at[tid] = ev["created_at"]
        elif ev["event_type"] == "tool.approval.done":
            out.append({
                "tool_id": tid,
                "session_id": ev["session_id"],
                "resolved_at": ev["created_at"],
                "requested_at": req_at.get(tid),
                "latency_s": round(ev["created_at"] - req_at[tid], 2) if tid in req_at else None,
                "approved": bool(p.get("approved")),
                "timed_out": bool(p.get("timed_out")),
                "always_allow": bool(p.get("always_allow")),
                "tool_name": p.get("tool_name", "?"),
                "source": "journal",
            })
    for d in _sidecar():
        out.append({**d, "source": "operator"})
    out.sort(key=lambda r: r.get("resolved_at") or 0, reverse=True)
    return out[:limit]


def stats(days: int = 7) -> dict[str, Any]:
    cutoff = time.time() - days * 86400
    hist = [h for h in history(limit=1000) if (h.get("resolved_at") or 0) >= cutoff]
    n = len(hist)
    denied = sum(1 for h in hist if not h.get("approved"))
    timed_out = sum(1 for h in hist if h.get("timed_out"))
    always = sum(1 for h in hist if h.get("always_allow"))
    lats = sorted(h["latency_s"] for h in hist if h.get("latency_s") is not None)
    return {
        "total": n,
        "denied": denied,
        "deny_rate": round(denied / n, 4) if n else None,
        "timed_out": timed_out,
        "always_allow": always,
        "median_latency_s": lats[len(lats) // 2] if lats else None,
        "pending_now": len(pending()),
    }


def record_decision(tool_id: str, approved: bool, always_allow: bool, session_id: str) -> None:
    """Demo-mode operator decision sidecar (live mode forwards to the engine instead)."""
    p = config.data_dir() / "approvals_decisions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "tool_id": tool_id, "approved": approved, "always_allow": always_allow,
            "session_id": session_id, "resolved_at": time.time(),
            "tool_name": "", "timed_out": False,
        }) + "\n")

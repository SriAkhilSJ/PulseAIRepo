"""Multi-agent coordination reader [PDF §6; plan L35].

Journaled sub-agent lifecycle rows (subagent_spawn / subagent_result) become a
parent→children tree per session. The engine's SubAgentCoordinator does not
journal yet (documented gap); demo telemetry exercises the view end-to-end.
"""
from __future__ import annotations

from typing import Any

from . import journal


def tree(session_id: str) -> list[dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for ev in journal.audit(limit=5000, since_seq=0):
        if ev["session_id"] != session_id:
            continue
        p = ev.get("payload") or {}
        aid = p.get("agent_id") or ev.get("tool_call_id") or ""
        if ev["event_type"] == "subagent_spawn":
            nodes[aid] = {
                "agent_id": aid, "role": p.get("role", "?"), "task": str(p.get("task", ""))[:160],
                "spawned_at": ev["created_at"], "done_at": None, "status": "running",
                "tokens": None, "cost_usd": None, "error": None,
            }
            order.append(aid)
        elif ev["event_type"] == "subagent_result" and aid in nodes:
            n = nodes[aid]
            n["done_at"] = ev["created_at"]
            n["status"] = "ok" if p.get("status", "ok") == "ok" else "failed"
            n["tokens"] = p.get("tokens")
            n["cost_usd"] = p.get("cost_usd")
            n["error"] = p.get("error")
    return [nodes[a] for a in order if a in nodes]

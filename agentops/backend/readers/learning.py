"""Feedback-learning explorer [PDF §6 continuous learning; plan G].

Reads the engine's append-only feedback store (one row per completed task:
{timestamp, task, success, layers_used} — see src/context/feedback_memory.make_profile)
and derives per-layer attribution stats with the engine's confidence rule
(>=10 records overall, >=5 attributed to a layer before weights are nudged).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import config

MIN_RECORDS = 10
MIN_ATTRIBUTED = 5


def feedback_path() -> Path:
    custom = os.environ.get("CRUSORAI_OPS_FEEDBACK_PATH", "").strip()
    if custom:
        return Path(custom).expanduser()
    local = config.data_dir() / "context_feedback.jsonl"
    if local.exists():
        return local
    return Path.home() / ".pulseai" / "context_feedback.jsonl"


def rows(limit: int = 2000) -> list[dict[str, Any]]:
    p = feedback_path()
    out: list[dict[str, Any]] = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict) and "layers_used" in rec:
            out.append(rec)
    out.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
    return out[:limit]


def summary() -> dict[str, Any]:
    rs = rows()
    per_layer: dict[str, dict[str, int]] = {}
    for r in rs:
        ok = bool(r.get("success"))
        for lay in r.get("layers_used") or []:
            a = per_layer.setdefault(str(lay), {"used": 0, "success": 0})
            a["used"] += 1
            a["success"] += 1 if ok else 0
    layers = []
    base = sum(1 for r in rs if r.get("success")) / len(rs) if rs else None
    for lay, a in sorted(per_layer.items(), key=lambda kv: kv[1]["used"], reverse=True):
        rate = a["success"] / a["used"] if a["used"] else 0
        layers.append({
            "layer": lay, "used": a["used"], "success": a["success"],
            "success_rate": round(rate, 4),
            "confidence": a["used"] >= MIN_ATTRIBUTED and len(rs) >= MIN_RECORDS,
            "delta_vs_base": round(rate - base, 4) if base is not None else None,
        })
    return {
        "path": str(feedback_path()),
        "available": feedback_path().exists(),
        "records": len(rs),
        "success_rate": round(base, 4) if base is not None else None,
        "confidence_rule": f">={MIN_RECORDS} records and >={MIN_ATTRIBUTED} attributed per layer",
        "layers": layers,
        "recent": [
            {"ts": r.get("timestamp"), "success": bool(r.get("success")),
             "task": str(r.get("task") or "")[:120], "layers": r.get("layers_used")}
            for r in rs[:25]
        ],
    }

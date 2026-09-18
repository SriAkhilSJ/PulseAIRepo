"""Eval & regression reader over the repo's own benchmark artifacts.

Sources: lab/*.json run records ({thread, task, status, error, wall_seconds, …})
and bench-results/* evidence dirs (screenshots/console logs). Plus A/B slices
computed from live receipts (execution modes and prompt variants).
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from . import receipts

_REPO = Path(__file__).resolve().parents[3]


def evals_dir() -> Path:
    custom = os.environ.get("CRUSORAI_OPS_EVALS_DIR", "").strip()
    return Path(custom).expanduser() if custom else _REPO / "lab"


def evidence_root() -> Path:
    return _REPO / "bench-results"


_OK = {"success", "pass", "passed", "ok", "true", "completed"}


def _is_ok(rec: dict) -> bool:
    st = str(rec.get("status", "")).strip().lower()
    if (rec.get("failures") or {}).get("count"):
        return False
    if st:
        return st in _OK
    return not str(rec.get("error") or "").strip()


def _flatten(rec: dict) -> dict:
    """Reports come in two shapes: flat run records, or run state wrapped
    under a top-level `status` dict. Normalize to one view."""
    inner = rec.get("status") if isinstance(rec.get("status"), dict) else rec
    return {
        "thread": rec.get("thread") or inner.get("thread") or "",
        "status": str(inner.get("status", "unknown")),
        "error": str(rec.get("error") or inner.get("error") or "")[:200],
        "wall_s": rec.get("wall_seconds") or inner.get("wall_seconds"),
        "cost_usd": (inner.get("cost") or {}).get("estimated_cost_usd"),
        "traces": inner.get("trace_count"),
        "failures": inner.get("failures") or {},
        "plan_done": (inner.get("plan") or {}).get("completed"),
        "plan_total": (inner.get("plan") or {}).get("total"),
        "_inner": inner,
    }


def runs(limit: int = 60) -> list[dict[str, Any]]:
    root = evals_dir()
    out: list[dict[str, Any]] = []
    if root.exists():
        for p in sorted(root.glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            f = _flatten(rec)
            st = p.stat()
            out.append({
                "id": p.stem,
                "thread": f["thread"],
                "status": f["status"],
                "ok": _is_ok(f),
                "error": f["error"],
                "wall_s": f["wall_s"],
                "cost_usd": f["cost_usd"],
                "traces": f["traces"],
                "plan_done": f["plan_done"],
                "plan_total": f["plan_total"],
                "ts": st.st_mtime,
                "bytes": st.st_size,
            })
    out.sort(key=lambda r: r["ts"], reverse=True)
    return out[:limit]


def evidence() -> list[dict[str, Any]]:
    root = evidence_root()
    out = []
    if root.exists():
        for d in sorted(root.iterdir()):
            if d.is_dir():
                files = list(d.rglob("*"))
                pngs = sum(1 for f in files if f.suffix == ".png")
                out.append({
                    "id": d.name, "files": len(files), "screenshots": pngs,
                    "ts": max((f.stat().st_mtime for f in files), default=0),
                })
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:30]


def regression() -> dict[str, Any]:
    rs = runs(limit=60)
    rs.sort(key=lambda r: r["ts"])
    points = [{"label": r["id"][:22], "ok": r["ok"], "ts": r["ts"]} for r in rs]
    n = len(rs)
    return {
        "total": n,
        "passed": sum(1 for r in rs if r["ok"]),
        "pass_rate": round(sum(1 for r in rs if r["ok"]) / n, 4) if n else None,
        "points": points,
    }


def _p95(vals: list[float]) -> float | None:
    if not vals:
        return None
    vals = sorted(vals)
    return round(vals[min(len(vals) - 1, int(0.95 * len(vals)))], 2)


def ab(days: int = 14) -> dict[str, Any]:
    recs = receipts.turns(days=days, limit=20000)

    def slice_by(keyfn) -> list[dict[str, Any]]:
        agg: dict[str, list[dict]] = {}
        for r in recs:
            agg.setdefault(str(keyfn(r)), []).append(r)
        out = []
        for key, rs in agg.items():
            costs = [r["_cost"] for r in rs]
            out.append({
                "key": key, "n": len(rs),
                "completion": round(sum(1 for r in rs if r.get("completed")) / len(rs), 4),
                "avg_cost": round(sum(costs) / len(costs), 6),
                "p95_s": _p95([float(r.get("duration_s") or 0) for r in rs]),
                "avg_tokens": round(statistics.mean([r["_tokens"] for r in rs]), 0),
            })
        out.sort(key=lambda x: x["n"], reverse=True)
        return out

    return {
        "by_mode": slice_by(lambda r: r.get("execution_mode") or "?"),
        "by_prompt_variant": slice_by(lambda r: (r.get("extra") or {}).get("prompt_id") or "none"),
        "by_task": slice_by(lambda r: r.get("task_type") or "?"),
    }

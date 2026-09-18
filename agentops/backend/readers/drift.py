"""Distribution-drift monitor [PDF §4.4; plan K34].

JS divergence between consecutive days' tool-mix and task-mix distributions;
flags shifts above CRUSORAI_OPS_DRIFT_THRESHOLD (default 0.25 nats).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import journal, receipts
from .. import config
from ..spc import js_divergence


def _daily(dist_fn, rows) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        day = datetime.fromtimestamp(r["_ts"] if "_ts" in r else r["created_at"], tz=timezone.utc).strftime("%Y-%m-%d")
        d = out.setdefault(day, {})
        for k in dist_fn(r):
            d[k] = d.get(k, 0.0) + 1.0
    return out


def series(days: int = 14, threshold: float | None = None) -> dict[str, Any]:
    thr = threshold if threshold is not None else float(
        __import__("os").environ.get("CRUSORAI_OPS_DRIFT_THRESHOLD", "0.25"))
    tool_rows = [
        {"created_at": e["created_at"], "keys": [(e.get("payload") or {}).get("tool_name", "?")]}
        for e in journal.audit(limit=8000, since_seq=0) if e["event_type"] == "tool.intent"
    ]
    recs = receipts.turns(days=days, limit=20000)
    tool_days = _daily(lambda r: r["keys"], tool_rows)
    task_days = _daily(lambda r: [r.get("task_type") or "?"], recs)

    def chain(days_map: dict[str, dict[str, float]]):
        ks = sorted(days_map)
        out = []
        for i in range(1, len(ks)):
            d = js_divergence(days_map[ks[i - 1]], days_map[ks[i]])
            out.append({"day": ks[i], "js": d, "flagged": d > thr})
        return out

    tool_chain, task_chain = chain(tool_days), chain(task_days)
    return {
        "threshold": thr,
        "tool_mix": tool_chain,
        "task_mix": task_chain,
        "flagged": [x for x in tool_chain + task_chain if x["flagged"]],
    }

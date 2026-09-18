"""Latency percentiles & throughput [plan H25, PDF §3.2 observability]."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from . import receipts


def _pct(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(p * len(sorted_vals)))
    return round(sorted_vals[idx], 2)


def percentiles(days: int = 7, group_by: str = "model") -> list[dict[str, Any]]:
    recs = receipts.turns(days=days, limit=10000)
    groups: dict[str, list[float]] = {}
    for r in recs:
        key = {
            "model": r.get("model") or "?",
            "provider": r.get("provider") or "?",
            "mode": r.get("execution_mode") or "?",
        }.get(group_by, r.get("model") or "?")
        groups.setdefault(str(key), []).append(float(r.get("duration_s") or 0))
    out = []
    for key, vals in groups.items():
        vals.sort()
        out.append({
            "key": key, "n": len(vals),
            "p50": _pct(vals, 0.50), "p95": _pct(vals, 0.95), "p99": _pct(vals, 0.99),
            "max": round(vals[-1], 2) if vals else None,
        })
    out.sort(key=lambda x: x["n"], reverse=True)
    return out


def throughput(days: int = 7) -> list[dict[str, Any]]:
    """Hourly buckets: turns/hour + tokens/minute."""
    recs = receipts.turns(days=days, limit=20000)
    buckets: dict[str, dict[str, Any]] = {}
    for r in recs:
        hour = datetime.fromtimestamp(r["_ts"], tz=timezone.utc).strftime("%m-%d %H:00")
        b = buckets.setdefault(hour, {"hour": hour, "turns": 0, "tokens": 0})
        b["turns"] += 1
        b["tokens"] += r["_tokens"]
    out = [buckets[k] for k in sorted(buckets)]
    for b in out:
        b["tokens_per_min"] = round(b["tokens"] / 60.0, 1)
    return out[-96:]

"""Statistical process control [PDF §4.4]: individuals control charts.

UCL/LCL = X̄ ± A₂·R̄ with A₂ = 2.66 (moving-range of span 2, individuals chart).
Days falling outside the limits are flagged out-of-control → anomaly alerts.
"""
from __future__ import annotations

A2_INDIVIDUALS = 2.66


def control_limits(values: list[float]) -> dict:
    xs = [float(v) for v in values if v is not None]
    if len(xs) < 3:
        return {"mean": None, "ucl": None, "lcl": None, "violations": []}
    mean = sum(xs) / len(xs)
    mrs = [abs(xs[i + 1] - xs[i]) for i in range(len(xs) - 1)]
    mr_bar = sum(mrs) / len(mrs)
    ucl = mean + A2_INDIVIDUALS * mr_bar
    lcl = max(0.0, mean - A2_INDIVIDUALS * mr_bar)
    violations = [i for i, v in enumerate(xs) if v > ucl or v < lcl]
    return {"mean": round(mean, 4), "ucl": round(ucl, 4), "lcl": round(lcl, 4), "violations": violations}


def chart(series: list[dict], key: str) -> dict:
    vals = [s.get(key) for s in series]
    limits = control_limits([v for v in vals if v is not None])
    points = []
    for i, s in enumerate(series):
        v = s.get(key)
        points.append({
            "label": s.get("day") or s.get("key") or str(i),
            "value": v,
            "ooc": i in limits["violations"],
        })
    return {**limits, "points": points}

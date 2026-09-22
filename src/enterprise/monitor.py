"""Agent monitor — latency, cost, tokens per turn.

Wraps src/observability.record_turn_receipt + src/context/token_tracker
to expose enterprise monitoring without uploading prompts (hermes contract:
no prompts, no session IDs).

Stored locally: ~/.crusorai/observability/turns.jsonl + in-memory ring for dashboard.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class TurnMetrics:
    duration_s: float
    first_token_latency_ms: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost_usd: float = 0.0
    tool_calls: int = 0
    failed_tools: int = 0
    model: str = ""
    provider: str = ""

_recent: list[TurnMetrics] = []
_MAX_RECENT = 50

def record_turn_metrics(m: TurnMetrics) -> None:
    _recent.append(m)
    if len(_recent) > _MAX_RECENT:
        _recent.pop(0)
    try:
        from src.observability import record_turn_receipt, enabled
        if enabled():
            record_turn_receipt(
                thread_id="monitor",
                model=m.model,
                provider=m.provider,
                input_tokens=m.input_tokens,
                output_tokens=m.output_tokens,
                cache_tokens=m.cached_tokens,
                estimated_cost_usd=m.estimated_cost_usd,
                duration_s=m.duration_s,
                tool_calls=m.tool_calls,
            )
    except Exception:
        pass

def recent_metrics() -> list[dict]:
    return [asdict(m) for m in _recent]

def health() -> dict:
    if not _recent:
        return {"status": "idle", "avg_latency_s": 0, "avg_cost_usd": 0, "failed_rate": 0}
    avg_lat = sum(m.duration_s for m in _recent) / len(_recent)
    avg_cost = sum(m.estimated_cost_usd for m in _recent) / len(_recent)
    failed = sum(1 for m in _recent if m.failed_tools > 0) / len(_recent)
    status = "healthy"
    if avg_lat > 8 or failed > 0.3:
        status = "degraded"
    if avg_cost > 1.0:
        status = "cost_high"
    return {"status": status, "avg_latency_s": round(avg_lat, 2), "avg_cost_usd": round(avg_cost, 4), "failed_rate": round(failed, 2)}

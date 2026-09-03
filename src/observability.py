"""Observability sink (Floor 6): the cost/receipt exporter.

hermes' langfuse plugin (1,801 lines) wraps their turn in OpenTelemetry
spans: root trace per turn, a generation per LLM call, spans per tool,
session + metadata attached, background flush, credentials checked at
construction but dropped at flush. Pulse gets the right-sized, dependency-
free core: a JSONL receipt exporter with the SAME shape (one record per
turn: session, turn, model, token buckets, cost, duration, tool calls,
error) that any analyzer can ingest — and it is what powers Pulse's own
cost-per-task story.

Zero hardcoding (the standing rule): everything from env, read per call.

  PULSEAI_OBSERVABILITY       on | off        (default: off)
  PULSEAI_OBSERVABILITY_PATH  output path     (default: ~/.pulseai/observability/turns.jsonl)

Fail-closed by contract: every failure is swallowed; receipts can never
break a turn (D17 crash-net idiom, hermes-identical).
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("PULSEAI_OBSERVABILITY", "off").strip().lower() in {
        "1", "true", "yes", "on",
    }


def sink_path() -> Path:
    custom = os.environ.get("PULSEAI_OBSERVABILITY_PATH", "").strip()
    if custom:
        return Path(custom)
    home = Path(os.path.expanduser("~")) / ".pulseai"
    return home / "observability" / "turns.jsonl"


def record_turn_receipt(
    *,
    thread_id: str,
    turn_id: str = "",
    model: str = "",
    provider: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    duration_s: float = 0.0,
    tool_calls: int = 0,
    tool_names: list[str] | None = None,
    execution_mode: str = "",
    task_type: str = "",
    completed: bool = True,
    error: str = "",
    extra: dict[str, Any] | None = None,
) -> bool:
    """Append one turn receipt. Best-effort: returns False on any failure."""
    if not enabled():
        return False
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": thread_id,
        "turn": turn_id,
        "model": model,
        "provider": provider,
        "tokens": {
            "input": int(input_tokens or 0),
            "output": int(output_tokens or 0),
            "cache": int(cache_tokens or 0),
        },
        "estimated_cost_usd": round(float(estimated_cost_usd or 0.0), 6),
        "duration_s": round(float(duration_s or 0.0), 3),
        "tool_calls": int(tool_calls or 0),
        "tool_names": list(tool_names or []),
        "execution_mode": execution_mode,
        "task_type": task_type,
        "completed": bool(completed),
        "error": error,
    }
    if extra:
        record.update(extra)
    path = sink_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return True
    except Exception:
        return False

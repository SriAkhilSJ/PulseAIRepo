"""Telemetry for the skills MCP server.

Two rules decide the shape of this module:

1. **stdout carries the protocol.** Every byte written to stdout is a JSON-RPC
   message, so logs go to stderr and nowhere else.
2. **A silent failure is a bug.** Every error is counted by code, so the same
   failure repeating in one session is visible instead of inferred.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from typing import Any

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}
_LEVEL = _LEVELS.get(os.environ.get("SKILLS_MCP_LOG", "info").lower(), 20)


class Metrics:
    """Counters the server exposes at `skill://health`."""

    def __init__(self) -> None:
        self.started = time.time()
        self.requests = 0
        self.tools = Counter()
        self.resources = Counter()
        self.errors: Counter[str] = Counter()
        self.index_builds = 0
        self.index_refreshes = 0
        self.bytes_out = 0

    def record_error(self, code: str) -> None:
        self.errors[code] += 1
        log("error", "request failed", code=code)

    def snapshot(self) -> dict[str, Any]:
        return {
            "uptime_s": round(time.time() - self.started, 1),
            "requests": self.requests,
            "tools": dict(self.tools),
            "resources": dict(self.resources),
            "errors": dict(self.errors),
            "index_builds": self.index_builds,
            "index_refreshes": self.index_refreshes,
            "bytes_out": self.bytes_out,
        }


METRICS = Metrics()


def log(level: str, event: str, **fields: Any) -> None:
    """One JSON object per line on stderr. Never stdout."""
    if _LEVELS.get(level, 20) < _LEVEL:
        return
    record = {"ts": round(time.time(), 3), "level": level, "event": event, **fields}
    try:
        print(json.dumps(record, default=str), file=sys.stderr, flush=True)
    except Exception:  # pragma: no cover - logging must never raise
        pass

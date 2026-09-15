"""Prompt-injection suspicion scanner [PDF §2.3 debugging: prompt injection detection].

Heuristic scan over journaled tool.intent args (untrusted content that would
reach the prompt or the shell). Read-only; flags for human review, never blocks.
"""
from __future__ import annotations

import re
from typing import Any

from . import journal

_PATTERNS = [
    (re.compile(r"ignore (all |any )?(previous|prior|above) (instructions|prompts)", re.I), "instruction-override"),
    (re.compile(r"disregard (your|all|any) (rules|instructions|guidelines)", re.I), "instruction-override"),
    (re.compile(r"(reveal|print|show) (your )?(system prompt|hidden instructions)", re.I), "system-prompt-exfil"),
    (re.compile(r"(curl|wget)[^|]*\|\s*(sh|bash|zsh)", re.I), "pipe-to-shell"),
    (re.compile(r"rm\s+-rf\s+/(?:\s|$)"), "destructive-root-delete"),
    (re.compile(r"<\s*/?\s*(system|assistant|tool_call)\s*>", re.I), "role-tag-injection"),
    (re.compile(r"(base64|eval|exec)\s*\(\s*['\"][A-Za-z0-9+/=]{80,}", re.I), "encoded-payload"),
]


def scan(limit: int = 3000, days: int = 7) -> list[dict[str, Any]]:
    import time
    cutoff = time.time() - days * 86400
    out: list[dict[str, Any]] = []
    for ev in journal.audit(limit=limit, since_seq=0):
        if ev["event_type"] != "tool.intent" or ev["created_at"] < cutoff:
            continue
        blob = str((ev.get("payload") or {}).get("args") or "")
        for rx, reason in _PATTERNS:
            m = rx.search(blob)
            if m:
                out.append({
                    "seq": ev["seq"], "ts": ev["created_at"], "session_id": ev["session_id"],
                    "turn_id": ev["turn_id"], "tool_name": (ev.get("payload") or {}).get("tool_name"),
                    "reason": reason, "snippet": blob[max(0, m.start() - 40): m.end() + 60],
                })
                break
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out

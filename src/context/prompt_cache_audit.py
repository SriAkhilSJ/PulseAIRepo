"""
Prompt-cache prefix audit (D19)
===============================

Measures, per turn, how much of the assembled LLM request is BYTE-IDENTICAL
to the previous turn's request — the exact quantity provider prompt caches
(Anthropic/OpenAI KV prefix reuse) pay out on. Hermes treats "the default
path leaves the request byte-identical" as a hard invariant
(their context_engine.py cache-prefix contract, §29); PulseAI never
measured it. This module is the meter.

Design notes:

* **Request-proxy serialization.** We serialize role + flattened text in
  request order and compare consecutive turns. The provider's exact wire
  framing is not replicated, but framing is constant per role — so any
  conclusion 'the prefix held through message K' is framing-independent.
* **Breaker classification.** Each message boundary records what owns it:
  the persona, a named context layer (identity tag stamped by the builder
  loop — never string-sniffed), or history user/assistant/tool. The verdict
  question is 'did the stable prefix reach the history boundary?'.
* **Cheap always-on.** One prefix-compare of two strings per turn; the
  per-session engine already serializes nothing else. Optional JSONL sink
  via env PULSEAI_CACHE_AUDIT_JSONL=path (or =1 for the default
  ~/.pulseai/cache_audit.jsonl) for cross-session forensics; in-memory
  ring buffer otherwise.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

_DEFAULT_JSONL = os.path.join(
    os.path.expanduser("~"), ".pulseai", "cache_audit.jsonl"
)
_jsonl_lock = threading.Lock()


def _flatten(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return ""


def _serialize(messages: list) -> tuple[str, list[tuple[int, str]]]:
    """Deterministic request-proxy string + (end_offset, owner) boundaries.

    Owner strings: 'persona', 'layer:<name>', 'history:user',
    'history:assistant', 'history:tool', 'history:system'.
    """
    chunks: list[str] = []
    boundaries: list[tuple[int, str]] = []
    offset = 0
    for i, msg in enumerate(messages):
        layer = None
        try:
            layer = (msg.response_metadata or {}).get("layer")
        except Exception:
            layer = None
        kind = type(msg).__name__
        if kind == "SystemMessage":
            owner = "persona" if i == 0 and not layer else f"layer:{layer or 'unknown'}"
        elif kind == "HumanMessage":
            owner = "history:user"
        elif kind == "AIMessage":
            owner = "history:assistant"
        elif kind == "ToolMessage":
            owner = "history:tool"
        else:
            owner = f"history:{kind.lower()}"
        # Tool calls change the wire payload too; mark their presence so a
        # same-text/different-call pair never compares equal.
        tool_calls = getattr(msg, "tool_calls", None) or ""
        chunk = f"<{kind}:{owner}>\n{_flatten(msg.content)}\n<toolcalls>{tool_calls}</toolcalls>\n"
        chunks.append(chunk)
        offset += len(chunk)
        boundaries.append((offset, owner))
    return "".join(chunks), boundaries


def _first_diff(a: str, b: str) -> int:
    """First index where a and b diverge (== len(shorter) if one prefixes)."""
    n = min(len(a), len(b))
    step = 4096
    pos = 0
    # Whole-chunk skip (fast on 100KB+ strings), then a bounded char walk.
    while pos + step <= n and a[pos:pos + step] == b[pos:pos + step]:
        pos += step
    while pos < n and a[pos] == b[pos]:
        pos += 1
    return pos


class CachePrefixAudit:
    """Per-session recorder: ring buffer of turn records + aggregates."""

    def __init__(self, keep: int = 200, jsonl_path: str | None = None):
        self._keep = keep
        self._turns: list[dict] = []
        self._prev_text: str | None = None
        self._prev_owners: list[str] = []
        env = os.environ.get("PULSEAI_CACHE_AUDIT_JSONL", "")
        self._jsonl_path = jsonl_path or (
            _DEFAULT_JSONL if env.strip() == "1" else (env.strip() or None)
        )

    def record(self, final_messages: list) -> dict:
        text, boundaries = _serialize(final_messages)
        owners = [owner for _, owner in boundaries]

        if self._prev_text is None:
            rec = {
                "turn": len(self._turns) + 1,
                "total_chars": len(text),
                "stable_chars": None,          # no previous turn to compare
                "stable_ratio": None,
                "breaker": "first_turn",
                "break_msg_idx": None,
            }
        else:
            stable = _first_diff(text, self._prev_text) if text != self._prev_text else len(text)
            breaker = "identical"
            break_idx = None
            if stable < len(text):
                for i, (end, owner) in enumerate(boundaries):
                    if stable < end:
                        breaker = owner
                        break_idx = i
                        break
                else:
                    breaker = owners[-1] if owners else "unknown"
            rec = {
                "turn": len(self._turns) + 1,
                "total_chars": len(text),
                "stable_chars": stable,
                "stable_ratio": round(stable / max(len(text), 1), 4),
                "breaker": breaker,
                "break_msg_idx": break_idx,
            }

        self._turns.append(rec)
        if len(self._turns) > self._keep:
            self._turns = self._turns[-self._keep:]
        self._prev_text = text
        self._prev_owners = owners
        self._sink(rec)
        return rec

    def _sink(self, rec: dict) -> None:
        if not self._jsonl_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._jsonl_path)), exist_ok=True)
            with _jsonl_lock, open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass  # forensics must never break a turn

    def hit_rate(self) -> float | None:
        comparable = [t for t in self._turns if t["stable_ratio"] is not None]
        if not comparable:
            return None
        hits = sum(1 for t in comparable if t["breaker"] == "identical" or str(t["breaker"]).startswith("history:"))
        return round(hits / len(comparable), 4)

    def stats(self) -> dict:
        comparable = [t for t in self._turns if t["stable_ratio"] is not None]
        histogram: dict[str, int] = {}
        for t in comparable:
            histogram[t["breaker"]] = histogram.get(t["breaker"], 0) + 1

        reached_history = sum(
            1 for t in comparable
            if t["breaker"] == "identical" or t["breaker"].startswith("history:")
        )
        ratios = [t["stable_ratio"] for t in comparable]
        verdict = (
            round(reached_history / len(comparable), 3) if comparable else None
        )
        hit_rate = round(reached_history / len(comparable), 4) if comparable else None
        return {
            "turns": len(self._turns),
            "comparable_turns": len(comparable),
            "mean_stable_ratio": round(sum(ratios) / len(ratios), 4) if ratios else None,
            "min_stable_ratio": min(ratios) if ratios else None,
            "prefix_reached_history_pct": verdict,
            "hit_rate": hit_rate,
            "cache_hit_rate": hit_rate,
            "breaker_histogram": dict(sorted(histogram.items(), key=lambda kv: -kv[1])),
            "recent": self._turns[-10:],
        }

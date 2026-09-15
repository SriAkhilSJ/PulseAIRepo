"""Micro-compaction — rolling per-exchange summarization OFF by default.

Ported from hermes-agent agent/micro_compaction.py (420 LOC) simplified for IDE.
Each pass breaks prompt cache once — tradeoff for long sessions.

Env (from .env via settings.py load_dotenv, also loaded defensively here):
- CRUSORAI_MICRO_COMPACTION=on to enable
- CRUSORAI_MICRO_COMPACTION_CADENCE=6 (turns per pass)
- CRUSORAI_MICRO_COMPACTION_DEFRAG=2000 (tokens threshold)

State is kept on ContextEngine: _micro_compact_cursor, _micro_compact_rolling_summary, etc.
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import os
from typing import Any, Dict, List, Optional

def micro_compaction_enabled() -> bool:
    return os.environ.get("CRUSORAI_MICRO_COMPACTION", "").strip().lower() in {"1","on","true","yes"}

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default

class MicroCompactionMixin:
    """Mixin for ContextEngine — rolling summary, cursor, defrag."""

    _micro_compact_enabled: bool = False
    _micro_compact_cursor: int = 0
    _micro_compact_rolling_summary: str = ""
    _micro_compact_consecutive_failures: int = 0
    _micro_compact_last_failure_cursor: int = -1
    _micro_compact_passes: int = 0
    _micro_compact_tokens_saved_total: int = 0
    _micro_compact_turns_since_pass: int = 0

    def _reset_micro_compact_cursor_state(self) -> None:
        self._micro_compact_cursor = 0
        self._micro_compact_rolling_summary = ""
        self._micro_compact_consecutive_failures = 0
        self._micro_compact_last_failure_cursor = -1

    def _should_micro_compact(self, messages: List[Dict[str, Any]]) -> bool:
        if not micro_compaction_enabled():
            return False
        cadence = _env_int("CRUSORAI_MICRO_COMPACTION_CADENCE", 6)
        self._micro_compact_turns_since_pass += 1
        return self._micro_compact_turns_since_pass >= cadence and len(messages) > self.protect_last_n + 10

    def _micro_compact_defrag_needed(self, current_tokens: int) -> bool:
        threshold = _env_int("CRUSORAI_MICRO_COMPACTION_DEFRAG", 2000)
        return current_tokens > threshold

    def micro_compact(
        self,
        messages: List[Dict[str, Any]],
        *,
        summarizer_fn: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """One rolling summary pass — deterministic fallback if no LLM.

        Args:
            messages: full transcript
            summarizer_fn: optional (turns) -> summary string; if None, deterministic placeholder
        Returns pruned list or original if not needed.
        """
        if not self._should_micro_compact(messages):
            return messages

        # Determine window: from cursor to tail protection start
        tail_start = max(0, len(messages) - self.protect_last_n)
        start = max(0, self._micro_compact_cursor)
        if start >= tail_start:
            return messages

        window = messages[start:tail_start]
        if not window:
            return messages

        # Summarize window
        if summarizer_fn:
            try:
                summary = summarizer_fn(window)
            except Exception:
                summary = ""
        else:
            # Deterministic placeholder — no LLM cost
            # Collect user messages verbatim newest-first up to budget
            user_texts = []
            for m in reversed(window):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    user_texts.append(m["content"][:500])
                    if len(user_texts) >= 3:
                        break
            summary = "[MICRO-COMPACT] Rolling summary of earlier turns:\n" + "\n".join(f"- {t[:200]}" for t in user_texts)
            if self._micro_compact_rolling_summary:
                summary = self._micro_compact_rolling_summary + "\n\n" + summary

        # Build new list: keep head, replace window with summary, keep tail
        summary_msg = {
            "role": "user",
            "content": summary,
            "_micro_compact_marker": True,
            "_compressed_summary": True,
        }
        new_messages = messages[:start] + [summary_msg] + messages[tail_start:]

        # Update cursor & stats
        self._micro_compact_cursor = start + 1  # summary occupies one slot
        self._micro_compact_rolling_summary = summary
        self._micro_compact_passes += 1
        self._micro_compact_turns_since_pass = 0

        # Rough token saved estimate
        try:
            from src.context.model_budgets import estimate_messages_tokens_rough
            before = estimate_messages_tokens_rough(window)
            after = estimate_messages_tokens_rough([summary_msg])
            self._micro_compact_tokens_saved_total += max(0, before - after)
        except Exception:
            pass

        return new_messages

    def micro_compaction_stats(self) -> Dict[str, Any]:
        return {
            "enabled": micro_compaction_enabled(),
            "passes": self._micro_compact_passes,
            "tokens_saved_total": self._micro_compact_tokens_saved_total,
            "cursor": self._micro_compact_cursor,
            "rolling_summary_chars": len(self._micro_compact_rolling_summary),
        }

__all__ = ["MicroCompactionMixin", "micro_compaction_enabled"]

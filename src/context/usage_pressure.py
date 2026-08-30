"""P3 (Hermes parity) usage-pressure state machine.

Extracted from ``context_engine.py`` (P6 modularization, behavior-preserving)
so the layered engine delegates the whole "actual usage crossed 75% of the
window" contract to one auditable object.

The contract (Hermes ``threshold_percent`` semantics, re-verified against
their context_compressor):

* The engine owns the compaction decision from the provider's ACTUAL usage,
  not from its own token estimates (which degrade to ``chars/4`` for
  unlisted models — measured for ``sarvam-105b-conversations``).
* Crossing ``threshold_percent`` (0.75) of the REAL window opens a pressure
  episode. During the episode every build tightens the history budget toward
  the lean-tail floor, and the tightening PERSISTS for the whole episode —
  reverting mid-episode would resend the oversized history into the same
  overflow.
* Anti-thrash: the episode re-arms only after usage has relaxed to
  ``REARM_PERCENT`` (0.60) of the window. A genuinely full window gets one
  decisive compaction, not one per graph lap.

The tracker is deliberately stateless with respect to the engine: it holds
the Hermes token-state contract (last_prompt/completion/total tokens,
threshold_tokens) plus the episode flag, and nothing else. The engine keeps
ownership of side effects (counter, log line, receipts) and only asks the
tracker for the decision.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

DEFAULT_THRESHOLD_PERCENT = 0.75
REARM_PERCENT = 0.60


class UsagePressure:
    """Owns the actual-usage episode state for one context engine session."""

    def __init__(self, threshold_percent: float = DEFAULT_THRESHOLD_PERCENT) -> None:
        self.threshold_percent = float(threshold_percent)
        # Hermes token-state contract (mirrors engine.ContextEngine ABC).
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0
        self.last_total_tokens: int = 0
        self.threshold_tokens: int = 0
        # Pressure episode flag (anti-thrash latch).
        self._active: bool = False

    @property
    def active(self) -> bool:
        """Whether a pressure episode is currently open."""
        return self._active

    def update(self, usage: Optional[Dict[str, Any]], window: Optional[int] = None) -> None:
        """Record the provider's ACTUAL token usage for the last response.

        Canonical buckets (Hermes ``update_from_response``): input/prompt,
        completion, total. A window of 0/None (undiscovered) still records
        the buckets but never arms or re-arms — there is no real window to
        measure pressure against.
        """
        if not usage:
            return
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or 0) or (prompt + completion)
        if prompt > 0:
            self.last_prompt_tokens = prompt
        if completion > 0:
            self.last_completion_tokens = completion
        if total > 0:
            self.last_total_tokens = total
        if window:
            self.threshold_tokens = int(window * self.threshold_percent)
            # Anti-thrash re-arm: when the provider says usage has relaxed
            # to <=60% of the window, the pressure episode is over — the
            # next build returns to the normal per-task history ratio.
            if prompt > 0 and prompt <= int(window * REARM_PERCENT):
                self._active = False

    def at_threshold(self, tokens: int, window: Optional[int]) -> bool:
        """Hermes ``should_compress``: at/above 75% of the REAL window.

        No known window or no usage yet -> False (nothing to decide).
        """
        if int(tokens or 0) <= 0 or not window:
            return False
        return int(tokens) >= int(window * self.threshold_percent)

    def usage_percent(self, window: Optional[int]) -> float:
        """Actual prompt usage as a percentage of the window (0..100)."""
        window = int(window or 0)
        if window and self.last_prompt_tokens > 0:
            return min(100.0, self.last_prompt_tokens / window * 100)
        return 0.0

    def tighten(
        self, history_budget: int, window: Optional[int]
    ) -> Tuple[int, bool, int]:
        """Apply the episode at build time.

        Returns ``(budget, fired, floor)`` where ``fired`` is True exactly on
        the FIRST crossing of the episode (the caller bumps its counter and
        logs once — the flag, not the value, is what fires once).
        """
        window = int(window or 0)
        if window <= 0 or self.last_prompt_tokens <= 0:
            return history_budget, False, 0
        if self.last_prompt_tokens < int(window * self.threshold_percent):
            if self.last_prompt_tokens <= int(window * REARM_PERCENT):
                self._active = False
            return history_budget, False, 0
        from src.context.compaction import lean_tail_tokens_for_window

        floor = lean_tail_tokens_for_window(window)
        tightened = min(history_budget, max(int(history_budget * 0.5), floor))
        fired = not self._active
        self._active = True
        return tightened, fired, floor

    def reset(self) -> None:
        """Close the episode (engine ``on_session_reset``).

        The token buckets are reset by the ABC's own ``on_session_reset``;
        this only drops the episode flag so a fresh session starts clean.
        """
        self._active = False

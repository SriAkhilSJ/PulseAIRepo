"""
base.py -- Abstract Base Class and standard contract for Context Engines.
========================================================================

Adopted from NousResearch hermes-agent (agent/context_engine.py).

A context engine controls how conversation context is managed, selected,
compressed, and observed across turns and sessions. It defines a clean,
pluggable interface so alternative strategies (e.g. built-in PulseAI,
LeanTail, Lossless Context Management / LCM, or custom engines) can be
slotted in seamlessly.

Lifecycle:
  1. Engine is instantiated and registered (via registry or factory)
  2. on_session_start() called when a conversation begins
  3. select_context() optionally chooses/replaces context for this request
  4. update_from_response() called after each API response with usage data
  5. should_compress() checked after each turn (or should_compress_preflight)
  6. compress() called when compaction triggers
  7. on_turn_complete() called after the turn finishes to observe & index
  8. on_session_end() called at real session boundaries (exit, reset)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class ContextEngineBase(ABC):
    """Abstract Base Class all context engines must implement."""

    # -- Identity ----------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier (e.g. 'pulse', 'compressor', 'lean', 'lcm')."""

    # -- Token state (read by runtime/dashboard for display and logging) ---

    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0
    last_total_tokens: int = 0
    threshold_tokens: int = 0
    context_length: int = 0
    compression_count: int = 0

    # -- Compaction parameters ---------------------------------------------

    threshold_percent: float = 0.50
    protect_first_n: int = 3
    protect_last_n: int = 6
    emit_automatic_compaction_status: bool = True

    # -- Core interface ----------------------------------------------------

    @abstractmethod
    def update_from_response(self, usage: Dict[str, Any]) -> None:
        """Update tracked token usage from an API response.

        Called after every LLM call with a normalized usage dict. Standard keys
        are prompt_tokens, completion_tokens, and total_tokens, plus optional
        canonical buckets (input_tokens, output_tokens, cache_read_tokens,
        cache_write_tokens, reasoning_tokens).
        """

    @abstractmethod
    def should_compress(self, prompt_tokens: Optional[int] = None) -> bool:
        """Return True if compaction should fire this turn."""

    def should_compress_info(
        self, prompt_tokens: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """Return (should_compress, reason).

        Provides a human-readable reason when compression is triggered or
        blocked (e.g. anti-thrashing guard, cooldown, lock contention).
        """
        return self.should_compress(prompt_tokens), None

    @abstractmethod
    def compress(
        self,
        messages: List[Any],
        current_tokens: Optional[int] = None,
        focus_topic: Optional[str] = None,
        force: bool = False,
        memory_context: str = "",
    ) -> List[Any]:
        """Compact the message list and return the new message list.

        This is the main compaction entry point. The engine receives the
        message list and returns a compacted list that fits within the
        token budget while preserving technical continuity and user intent.
        """

    # -- Optional: proactive tool-result prune -----------------------------

    def prune_tool_results_only(
        self,
        messages: List[Any],
        current_tokens: Optional[int] = None,
    ) -> Tuple[List[Any], int]:
        """Deterministically trim old tool-result payloads without an LLM call.

        Runs as a fast, zero-cost prune independent of full LLM compaction
        so large-window engines can reclaim verbose tool output early.
        Returns (messages, n_pruned).
        """
        return messages, 0

    # -- Optional: per-turn context selection & observation ----------------

    def select_context(
        self,
        request_messages: List[Any],
        *,
        conversation_messages: Optional[List[Any]] = None,
        incoming_message: Optional[Any] = None,
        budget_tokens: int = 0,
    ) -> Optional[List[Any]]:
        """Optionally choose/replace the context for THIS request before dispatch.

        Orthogonal to compress():
          - compress()      : context is too long -> make it shorter.
          - select_context(): this turn needs specific context -> route/select.

        Returns a replacement message list or None to leave unchanged.
        Request-only: persisted conversation history is NEVER mutated.
        """
        return None

    def on_turn_complete(
        self,
        messages: List[Any],
        usage: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Observe a finished user turn (post-turn ingestion / indexing).

        Called after the assistant/tool loop completes, with the finalized
        transcript and canonical token usage. Lets the engine index, summarize,
        or update memory state for subsequent select_context() calls.
        """
        return None

    # -- Optional: preflight checks ----------------------------------------

    def should_compress_preflight(self, messages: List[Any]) -> bool:
        """Quick rough check before the API call (rough token estimate)."""
        return False

    def should_defer_preflight_to_real_usage(self, rough_tokens: int) -> bool:
        """Return True when preflight should trust recent real usage instead."""
        return False

    def has_content_to_compress(self, messages: List[Any]) -> bool:
        """Quick check: is there anything in messages that can be compacted?"""
        return len(messages) > (self.protect_first_n + self.protect_last_n)

    # -- Optional: session lifecycle ---------------------------------------

    def on_session_start(self, session_id: str, **kwargs: Any) -> None:
        """Called when a new conversation session begins."""
        pass

    def on_session_end(self, session_id: str, messages: List[Any]) -> None:
        """Called at real session boundaries (exit, reset)."""
        pass

    def on_session_reset(self) -> None:
        """Called on /new or session reset. Clears per-session counters."""
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.compression_count = 0

    # -- Optional: engine-provided tools -----------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas this engine provides directly to the agent."""
        return []

    def handle_tool_call(self, name: str, args: Dict[str, Any], **kwargs: Any) -> str:
        """Handle an engine tool call from the agent. Must return a JSON string."""
        import json
        return json.dumps({"error": f"Unknown context engine tool: {name}"})

    # -- Optional: status / display ----------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for display/logging."""
        last_prompt = max(0, self.last_prompt_tokens)
        usage_pct = (
            min(100.0, (last_prompt / self.context_length) * 100.0)
            if self.context_length > 0
            else 0.0
        )
        return {
            "name": self.name,
            "last_prompt_tokens": last_prompt,
            "last_completion_tokens": max(0, self.last_completion_tokens),
            "last_total_tokens": max(0, self.last_total_tokens),
            "threshold_tokens": self.threshold_tokens,
            "context_length": self.context_length,
            "usage_percent": round(usage_pct, 1),
            "compression_count": self.compression_count,
        }

    # -- Optional: model switch support ------------------------------------

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
        api_mode: str = "",
    ) -> None:
        """Called when switching models or on provider failover."""
        self.context_length = context_length
        self.threshold_tokens = int(context_length * self.threshold_percent)

# src/context/token_tracker.py
"""
Token Tracker
=============

The accountant for your AI agent.

Every time the agent talks to an LLM, this counts:

- How many tokens went IN (your prompt)
- How many tokens came OUT (the AI's response)
- How much it cost (based on the model's price)

All methods are static — no global state.
Accumulation happens inside AgentState.
"""

from dataclasses import dataclass
from typing import Any

import tiktoken
from langchain_core.messages import AIMessage, BaseMessage


@dataclass
class TokenUsage:
    """One snapshot of token usage."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_known: bool = True
    calls_made: int = 0
    cached_tokens: int = 0  # provider-reported prompt-cache hits (Law 1 visibility)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        if not data:
            return cls()

        return cls(
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            estimated_cost_usd=float(data.get("estimated_cost_usd") or 0.0),
            cost_known=bool(data.get("cost_known", True)),
            calls_made=data.get("calls_made", 0),
            cached_tokens=data.get("cached_tokens", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 10),
            "cost_known": self.cost_known,
            "calls_made": self.calls_made,
            "cached_tokens": self.cached_tokens,
        }

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            estimated_cost_usd=self.estimated_cost_usd + other.estimated_cost_usd,
            cost_known=self.cost_known and other.cost_known,
            calls_made=self.calls_made + other.calls_made,
            cached_tokens=self.cached_tokens + other.cached_tokens,
        )


class TokenTracker:
    """
    Stateless tracker. Call record_call() after every LLM invoke,
    then add the result to AgentState.
    """

    @staticmethod
    def record_call(
        messages: list[BaseMessage],
        response: BaseMessage | Any,
        model: str,
    ) -> TokenUsage:
        """
        Analyze one LLM call and return its usage stats.

        messages: What was sent TO the LLM.
        response: What came back (AIMessage or Pydantic object).
        model: Model name (for pricing lookup).
        """
        prompt_tokens = TokenTracker._count_input_tokens(messages, model)

        if isinstance(response, BaseMessage):
            completion_tokens = TokenTracker._count_output_tokens(response, model)
            actual_prompt, actual_completion, actual_cached = (
                TokenTracker._extract_usage_metadata(response)
            )
        else:
            # Structured output (Pydantic model) — estimate from string.
            completion_tokens = TokenTracker._count_string_tokens(str(response), model)
            actual_prompt, actual_completion, actual_cached = None, None, None

        # Override with real provider metadata if available.
        if actual_prompt is not None:
            prompt_tokens = actual_prompt
        if actual_completion is not None:
            completion_tokens = actual_completion

        total = prompt_tokens + completion_tokens
        cost = TokenTracker._calculate_cost(
            prompt_tokens, completion_tokens, model,
            cached_tokens=actual_cached or 0,
            cache_reported=actual_cached is not None,
        )

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            estimated_cost_usd=cost or 0.0,
            cost_known=cost is not None,
            calls_made=1,
            cached_tokens=actual_cached or 0,
        )

    @staticmethod
    def format_usage(usage: dict[str, Any] | TokenUsage) -> str:
        """Pretty-print token usage."""
        if isinstance(usage, dict):
            u = TokenUsage.from_dict(usage)
        else:
            u = usage

        cost_text = f"${u.estimated_cost_usd:.6f}" if u.cost_known else "unknown (no USD rate)"
        return (
            f"Tokens: {u.prompt_tokens:,} in + {u.completion_tokens:,} out "
            f"= {u.total_tokens:,} total | "
            f"Cost: {cost_text} | "
            f"Calls: {u.calls_made}"
        )

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================

    @staticmethod
    def _encoder_for_model(model: str):
        # ANY acquisition failure (unknown model, BPE download unavailable,
        # offline) degrades to the heuristic encoder — token accounting must
        # never kill a turn (found live: a real turn died on the cl100k_base
        # download behind a blocked network).
        try:
            try:
                return tiktoken.encoding_for_model(model)
            except Exception as exc:
                from src.context.tokenizer_fallback import warn_once
                warn_once(f"encoding_for_model({model!r})", exc, note="using the standard cl100k_base tokenizer (exact counts)")
                return tiktoken.get_encoding("cl100k_base")
        except Exception as exc:
            from src.context.tokenizer_fallback import HEURISTIC_ENCODER, warn_once
            warn_once("tiktoken cache lookup", exc)
            return HEURISTIC_ENCODER

    @staticmethod
    def _count_input_tokens(messages: list[BaseMessage], model: str) -> int:
        """Estimate tokens for the messages sent to the LLM."""
        encoder = TokenTracker._encoder_for_model(model)

        total = 0
        for msg in messages:
            total += 4  # message overhead
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            total += len(encoder.encode(content))
            total += len(encoder.encode(msg.type))
            total += 2  # role overhead

        total += 2  # reply priming
        return total

    @staticmethod
    def _count_output_tokens(response: BaseMessage, model: str) -> int:
        """Estimate tokens for the AI's response."""
        encoder = TokenTracker._encoder_for_model(model)

        content = response.content if isinstance(response.content, str) else str(response.content)

        # If the AI requested tool calls, count those too.
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            content += " " + str(tool_calls)

        return len(encoder.encode(content))

    @staticmethod
    def _count_string_tokens(text: str, model: str) -> int:
        """Estimate tokens for a plain string."""
        encoder = TokenTracker._encoder_for_model(model)
        return len(encoder.encode(text))

    @staticmethod
    def _extract_usage_metadata(response: BaseMessage) -> tuple[int | None, int | None, int | None]:
        """
        Some providers (OpenAI, Groq) return actual token counts.
        Try to extract them from the response. The third value is the
        provider-reported PROMPT-CACHE hit count (Law 1 visibility):
        LangChain's standard ``input_token_details.cache_read`` — where
        OpenAI's ``prompt_tokens_details.cached_tokens`` and Anthropic
        cache reads both land — with the raw OpenAI shape in
        ``additional_kwargs`` as fallback. None when the provider
        reported no cache information.
        """
        if not isinstance(response, AIMessage):
            return None, None, None

        meta = getattr(response, "usage_metadata", None)
        if not meta:
            return None, None, None

        # LangChain standard format.
        input_tokens = meta.get("input_tokens") or meta.get("prompt_tokens")
        output_tokens = meta.get("output_tokens") or meta.get("completion_tokens")

        cached = 0
        try:
            details = meta.get("input_token_details") or {}
            cached = int(details.get("cache_read") or details.get("cached_tokens") or 0)
        except (TypeError, ValueError):
            cached = 0
        if not cached:
            try:
                raw = (getattr(response, "additional_kwargs", {}) or {}).get(
                    "prompt_tokens_details"
                ) or {}
                cached = int(raw.get("cached_tokens") or 0)
            except (TypeError, ValueError):
                cached = 0
        if not cached:
            try:
                resp_meta = getattr(response, "response_metadata", {}) or {}
                usage_dict = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
                raw = usage_dict.get("prompt_tokens_details") or {}
                cached = int(raw.get("cached_tokens") or usage_dict.get("cache_read_input_tokens") or 0)
            except (TypeError, ValueError):
                cached = 0

        return input_tokens, output_tokens, (cached or None)

    @staticmethod
    def _calculate_cost(
        prompt: int,
        completion: int,
        model: str,
        *,
        cached_tokens: int = 0,
        cache_reported: bool = False,
    ) -> float | None:
        """Use the telemetry ledger's live/manual rate card; never guess a fallback."""
        from src.telemetry.call_ledger import estimate_cost_usd

        return estimate_cost_usd(
            model,
            prompt,
            completion,
            cached_tokens=cached_tokens,
            cache_reported=cache_reported,
        )

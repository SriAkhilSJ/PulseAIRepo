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


# =========================================================
# PRICING TABLE: Cost per 1 MILLION tokens (USD)
# Update these as providers change prices.
# =========================================================

PRICING = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},

    # Groq / common OSS model aliases (approximate)
    "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
    "gemma2-9b-it": {"input": 0.20, "output": 0.20},
    "qwen3.6-27b": {"input": 0.50, "output": 0.50},
    "qwen": {"input": 0.50, "output": 0.50},

    # Gemini
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},

    # Custom/local fallback. Override by adding a specific model key above.
    "auto/cheap": {"input": 0.10, "output": 0.10},
    "cheap": {"input": 0.10, "output": 0.10},

    # Default fallback if model not found
    "default": {"input": 1.00, "output": 1.00},
}


@dataclass
class TokenUsage:
    """One snapshot of token usage."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    calls_made: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        if not data:
            return cls()

        return cls(
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            estimated_cost_usd=data.get("estimated_cost_usd", 0.0),
            calls_made=data.get("calls_made", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "calls_made": self.calls_made,
        }

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            estimated_cost_usd=self.estimated_cost_usd + other.estimated_cost_usd,
            calls_made=self.calls_made + other.calls_made,
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
            actual_prompt, actual_completion = TokenTracker._extract_usage_metadata(response)
        else:
            # Structured output (Pydantic model) — estimate from string.
            completion_tokens = TokenTracker._count_string_tokens(str(response), model)
            actual_prompt, actual_completion = None, None

        # Override with real provider metadata if available.
        if actual_prompt is not None:
            prompt_tokens = actual_prompt
        if actual_completion is not None:
            completion_tokens = actual_completion

        total = prompt_tokens + completion_tokens
        cost = TokenTracker._calculate_cost(prompt_tokens, completion_tokens, model)

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
            calls_made=1,
        )

    @staticmethod
    def format_usage(usage: dict[str, Any] | TokenUsage) -> str:
        """Pretty-print token usage."""
        if isinstance(usage, dict):
            u = TokenUsage.from_dict(usage)
        else:
            u = usage

        return (
            f"Tokens: {u.prompt_tokens:,} in + {u.completion_tokens:,} out "
            f"= {u.total_tokens:,} total | "
            f"Cost: ${u.estimated_cost_usd:.6f} | "
            f"Calls: {u.calls_made}"
        )

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================

    @staticmethod
    def _encoder_for_model(model: str):
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")

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
    def _extract_usage_metadata(response: BaseMessage) -> tuple[int | None, int | None]:
        """
        Some providers (OpenAI, Groq) return actual token counts.
        Try to extract them from the response.
        """
        if not isinstance(response, AIMessage):
            return None, None

        meta = getattr(response, "usage_metadata", None)
        if not meta:
            return None, None

        # LangChain standard format.
        input_tokens = meta.get("input_tokens") or meta.get("prompt_tokens")
        output_tokens = meta.get("output_tokens") or meta.get("completion_tokens")

        return input_tokens, output_tokens

    @staticmethod
    def _calculate_cost(prompt: int, completion: int, model: str) -> float:
        """Calculate cost in USD."""
        clean = model.lower()
        last_part = clean.split("/")[-1]

        pricing = PRICING.get(clean) or PRICING.get(last_part)

        if not pricing:
            # Try partial match.
            for key, value in PRICING.items():
                if key in clean or clean in key or key in last_part or last_part in key:
                    pricing = value
                    break

        if not pricing:
            pricing = PRICING["default"]

        input_cost = (prompt / 1_000_000) * pricing["input"]
        output_cost = (completion / 1_000_000) * pricing["output"]

        return input_cost + output_cost

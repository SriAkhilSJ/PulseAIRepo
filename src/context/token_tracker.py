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


class UsageProvenance:
    """Canonical provenance tags for provider token accounting semantics."""
    OPENAI_INCLUSIVE = "openai_inclusive"
    ANTHROPIC_EXCLUSIVE = "anthropic_exclusive"
    GEMINI_INCLUSIVE = "gemini_inclusive"
    GATEWAY_INCLUSIVE = "gateway_inclusive"
    NORMALIZED_TOTAL = "normalized_total"
    UNKNOWN = "unknown"


@dataclass
class UsageBreakdown:
    """Canonical breakdown of model invocation token usage across providers."""
    total_input_tokens: int = 0
    uncached_input_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0  # Aggregate cache writes
    cache_write_5m_tokens: int = 0  # 5m ephemeral writes
    cache_write_1h_tokens: int = 0  # 1h ephemeral writes
    generic_residual_write_tokens: int = 0  # Untyped residual cache writes
    output_tokens: int = 0
    provenance: str = UsageProvenance.UNKNOWN
    is_partial: bool = False

    @property
    def ttl_write_tokens(self) -> int:
        return self.cache_write_5m_tokens + self.cache_write_1h_tokens

    @property
    def total_write_tokens(self) -> int:
        return self.ttl_write_tokens + self.generic_residual_write_tokens

    def is_conserved(self) -> bool:
        """Verify token conservation: uncached + cached + 5m + 1h + generic residual == total input."""
        return (
            self.uncached_input_tokens >= 0
            and self.cached_tokens >= 0
            and self.cache_write_5m_tokens >= 0
            and self.cache_write_1h_tokens >= 0
            and self.generic_residual_write_tokens >= 0
            and self.output_tokens >= 0
            and (
                self.uncached_input_tokens
                + self.cached_tokens
                + self.cache_write_5m_tokens
                + self.cache_write_1h_tokens
                + self.generic_residual_write_tokens
            ) == self.total_input_tokens
        )


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
    cache_write_tokens: int = 0  # provider-reported prompt-cache creation/write tokens (aggregate)
    cache_write_5m_tokens: int = 0  # 5-minute ephemeral cache write tokens (Anthropic / gateway)
    cache_write_1h_tokens: int = 0  # 1-hour ephemeral cache write tokens (Anthropic / gateway)
    generic_residual_write_tokens: int = 0  # untyped residual cache write tokens
    uncached_tokens: int = 0  # uncached input remainder tokens
    provenance: str = UsageProvenance.UNKNOWN
    is_partial: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        if not data:
            return cls()

        ttl_sum = (data.get("cache_write_5m_tokens") or 0) + (data.get("cache_write_1h_tokens") or 0)
        c_write = data.get("cache_write_tokens", 0)
        gen_residual = data.get("generic_residual_write_tokens")
        if gen_residual is None:
            gen_residual = max(0, c_write - ttl_sum)

        return cls(
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            estimated_cost_usd=float(data.get("estimated_cost_usd") or 0.0),
            cost_known=bool(data.get("cost_known", True)),
            calls_made=data.get("calls_made", 0),
            cached_tokens=data.get("cached_tokens", 0),
            cache_write_tokens=c_write,
            cache_write_5m_tokens=data.get("cache_write_5m_tokens", 0),
            cache_write_1h_tokens=data.get("cache_write_1h_tokens", 0),
            generic_residual_write_tokens=gen_residual,
            uncached_tokens=data.get("uncached_tokens", 0),
            provenance=data.get("provenance", UsageProvenance.UNKNOWN),
            is_partial=bool(data.get("is_partial", False)),
        )

    def to_breakdown(self, provenance: str | None = None, is_partial: bool | None = None) -> UsageBreakdown:
        ttl_sum = self.cache_write_5m_tokens + self.cache_write_1h_tokens
        gen_residual = self.generic_residual_write_tokens or max(0, self.cache_write_tokens - ttl_sum)
        uncached = (
            self.uncached_tokens
            if (self.uncached_tokens is not None and self.uncached_tokens > 0)
            else max(0, self.prompt_tokens - self.cached_tokens - ttl_sum - gen_residual)
        )
        return UsageBreakdown(
            total_input_tokens=self.prompt_tokens,
            uncached_input_tokens=uncached,
            cached_tokens=self.cached_tokens,
            cache_write_tokens=self.cache_write_tokens,
            cache_write_5m_tokens=self.cache_write_5m_tokens,
            cache_write_1h_tokens=self.cache_write_1h_tokens,
            generic_residual_write_tokens=gen_residual,
            output_tokens=self.completion_tokens,
            provenance=provenance or self.provenance,
            is_partial=self.is_partial if is_partial is None else is_partial,
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
            "cache_write_tokens": self.cache_write_tokens,
            "cache_write_5m_tokens": self.cache_write_5m_tokens,
            "cache_write_1h_tokens": self.cache_write_1h_tokens,
            "generic_residual_write_tokens": self.generic_residual_write_tokens,
            "uncached_tokens": self.uncached_tokens,
            "provenance": self.provenance,
            "is_partial": self.is_partial,
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
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_write_5m_tokens=self.cache_write_5m_tokens + other.cache_write_5m_tokens,
            cache_write_1h_tokens=self.cache_write_1h_tokens + other.cache_write_1h_tokens,
            generic_residual_write_tokens=self.generic_residual_write_tokens + other.generic_residual_write_tokens,
            uncached_tokens=self.uncached_tokens + other.uncached_tokens,
            provenance=self.provenance if self.provenance == other.provenance else UsageProvenance.UNKNOWN,
            is_partial=self.is_partial or other.is_partial,
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
            (
                actual_prompt,
                actual_completion,
                actual_cached,
                actual_write,
                actual_5m,
                actual_1h,
                actual_uncached,
                actual_gen_residual,
                actual_provenance,
            ) = TokenTracker._extract_usage_metadata(response)
        else:
            # Structured output (Pydantic model) — estimate from string.
            completion_tokens = TokenTracker._count_string_tokens(str(response), model)
            (
                actual_prompt,
                actual_completion,
                actual_cached,
                actual_write,
                actual_5m,
                actual_1h,
                actual_uncached,
                actual_gen_residual,
                actual_provenance,
            ) = (
                None, None, None, None, None, None, None, None, UsageProvenance.UNKNOWN
            )

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
            cache_write_tokens=actual_write or 0,
            cache_write_reported=actual_write is not None,
            cache_write_5m_tokens=actual_5m or 0,
            cache_write_1h_tokens=actual_1h or 0,
        )

        calc_uncached = actual_uncached if actual_uncached is not None else max(
            0, prompt_tokens - (actual_cached or 0) - (actual_write or 0)
        )

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            estimated_cost_usd=cost or 0.0,
            cost_known=cost is not None,
            calls_made=1,
            cached_tokens=actual_cached or 0,
            cache_write_tokens=actual_write or 0,
            cache_write_5m_tokens=actual_5m or 0,
            cache_write_1h_tokens=actual_1h or 0,
            generic_residual_write_tokens=actual_gen_residual or 0,
            uncached_tokens=calc_uncached,
            provenance=actual_provenance or UsageProvenance.UNKNOWN,
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
    def _extract_usage_metadata(
        response: BaseMessage
    ) -> tuple[int | None, int | None, int | None, int | None, int | None, int | None, int | None, int | None, str]:
        """Extract and canonically normalize token usage across OpenAI, Anthropic, Gemini, etc.
        Returns: (total_input, output, cached, cache_write, cache_write_5m, cache_write_1h, uncached, generic_residual, provenance)
        """
        if not isinstance(response, AIMessage):
            return None, None, None, None, None, None, None, None, UsageProvenance.UNKNOWN

        meta = getattr(response, "usage_metadata", None)
        resp_meta = getattr(response, "response_metadata", {}) or {}
        usage_dict = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
        additional = getattr(response, "additional_kwargs", {}) or {}

        if not meta and not usage_dict:
            return None, None, None, None, None, None, None, None, UsageProvenance.UNKNOWN

        meta = meta if isinstance(meta, dict) else {}

        def _get_first_int(dicts: list[dict], *keys: str) -> int | None:
            for d in dicts:
                if isinstance(d, dict):
                    for k in keys:
                        if k in d:
                            v = d[k]
                            if isinstance(v, int) and not isinstance(v, bool):
                                return max(0, v)
            return None

        raw_in = _get_first_int([meta, usage_dict, resp_meta, additional], "input_tokens", "prompt_tokens")
        raw_out = _get_first_int([meta, usage_dict, resp_meta, additional], "output_tokens", "completion_tokens")
        raw_tot = _get_first_int([meta, usage_dict, resp_meta, additional], "total_tokens")

        def _safe_int(val: Any) -> int:
            if isinstance(val, bool) or val is None:
                return 0
            if isinstance(val, int):
                return max(0, val)
            try:
                return max(0, int(val))
            except (ValueError, TypeError):
                return 0

        # Extract cached tokens
        cached = 0
        details = meta.get("input_token_details") or {}
        if isinstance(details, dict):
            cached = _safe_int(details.get("cache_read") or details.get("cached_tokens"))
        if not cached:
            ptd = (meta.get("prompt_tokens_details") or usage_dict.get("prompt_tokens_details") or {})
            if isinstance(ptd, dict):
                cached = _safe_int(ptd.get("cached_tokens"))
        if not cached:
            ptd = additional.get("prompt_tokens_details") or {}
            if isinstance(ptd, dict):
                cached = _safe_int(ptd.get("cached_tokens"))
        if not cached:
            cached = _safe_int(
                usage_dict.get("cache_read_input_tokens")
                or usage_dict.get("cached_content_token_count")
                or resp_meta.get("cached_content_token_count")
                or usage_dict.get("cached_tokens")
            )

        # Extract TTL-specific writes
        w_5m, w_1h = None, None
        for src in (meta, usage_dict, resp_meta, additional):
            if isinstance(src, dict):
                cc = src.get("cache_creation")
                if isinstance(cc, dict):
                    c5 = cc.get("ephemeral_5m_input_tokens") or cc.get("cache_creation_5m")
                    if isinstance(c5, int) and not isinstance(c5, bool):
                        w_5m = max(0, c5)
                    c1 = cc.get("ephemeral_1h_input_tokens") or cc.get("cache_creation_1h")
                    if isinstance(c1, int) and not isinstance(c1, bool):
                        w_1h = max(0, c1)
                itd = src.get("input_token_details")
                if isinstance(itd, dict):
                    c5 = itd.get("cache_creation_5m") or itd.get("ephemeral_5m_input_tokens")
                    if isinstance(c5, int) and not isinstance(c5, bool):
                        w_5m = max(0, c5) if w_5m is None else max(w_5m, c5)
                    c1 = itd.get("cache_creation_1h") or itd.get("ephemeral_1h_input_tokens")
                    if isinstance(c1, int) and not isinstance(c1, bool):
                        w_1h = max(0, c1) if w_1h is None else max(w_1h, c1)

        ttl_sum = (w_5m or 0) + (w_1h or 0)

        # Extract total cache write across all sources
        cache_write = ttl_sum
        if isinstance(details, dict):
            cw = _safe_int(
                details.get("cache_write")
                or details.get("cache_creation")
                or details.get("cache_write_tokens")
                or details.get("cache_creation_tokens")
            )
            cache_write = max(cache_write, cw)

        ptd = (meta.get("prompt_tokens_details") or usage_dict.get("prompt_tokens_details") or additional.get("prompt_tokens_details") or {})
        if isinstance(ptd, dict):
            cw = _safe_int(ptd.get("cache_write_tokens") or ptd.get("cache_creation_tokens") or ptd.get("cache_write"))
            cache_write = max(cache_write, cw)

        for src in (meta, usage_dict, resp_meta, additional):
            if isinstance(src, dict):
                cw = _safe_int(
                    src.get("cache_creation_input_tokens")
                    or src.get("cache_write_input_tokens")
                    or src.get("cache_write_tokens")
                    or src.get("cache_creation_tokens")
                )
                cache_write = max(cache_write, cw)

        gen_residual = max(0, cache_write - ttl_sum)
        sub_sum = (cached or 0) + ttl_sum + gen_residual

        # 1. Check explicit provenance tag
        explicit_prov = (
            resp_meta.get("provenance")
            or resp_meta.get("usage_provenance")
            or meta.get("provenance")
            or meta.get("usage_provenance")
            or additional.get("provenance")
            or additional.get("usage_provenance")
        )
        if explicit_prov and isinstance(explicit_prov, str):
            provenance = explicit_prov.strip().lower()
        else:
            provenance = None

        # 2. Structural wire protocol detection if provenance is not explicit
        if not provenance:
            has_anthropic_wire_keys = any(
                isinstance(src, dict) and (
                    "cache_creation_input_tokens" in src
                    or "cache_read_input_tokens" in src
                    or "cache_creation" in src
                )
                for src in (meta, usage_dict, resp_meta, additional)
            )
            has_openai_prompt_details = any(
                isinstance(src, dict) and (
                    "prompt_tokens_details" in src
                    or ("prompt_tokens" in src and not has_anthropic_wire_keys)
                )
                for src in (meta, usage_dict, resp_meta, additional)
            )
            has_gemini_keys = any(
                isinstance(src, dict) and (
                    "cached_content_token_count" in src
                    or "candidates_token_count" in src
                    or "prompt_token_count" in src
                )
                for src in (meta, usage_dict, resp_meta, additional)
            )

            if has_anthropic_wire_keys and not has_openai_prompt_details:
                already_normalized = (
                    raw_tot is not None
                    and raw_out is not None
                    and raw_tot == (raw_in + raw_out)
                    and raw_in >= sub_sum
                )
                provenance = UsageProvenance.NORMALIZED_TOTAL if already_normalized else UsageProvenance.ANTHROPIC_EXCLUSIVE
            elif has_gemini_keys:
                provenance = UsageProvenance.GEMINI_INCLUSIVE
            elif has_openai_prompt_details:
                prov_str = str(resp_meta.get("provider") or "").lower()
                if "gateway" in prov_str or "velona" in prov_str or "openrouter" in prov_str:
                    provenance = UsageProvenance.GATEWAY_INCLUSIVE
                else:
                    provenance = UsageProvenance.OPENAI_INCLUSIVE
            else:
                provenance = UsageProvenance.UNKNOWN

        # Canonically normalize total input and uncached tokens
        total_in = raw_in
        uncached_tokens = raw_in
        if raw_in is not None:
            if provenance == UsageProvenance.NORMALIZED_TOTAL:
                # Already canonicalized by Crusor — exact-once guarantee
                total_in = raw_in
                uncached_tokens = max(0, raw_in - sub_sum)
            elif provenance == UsageProvenance.ANTHROPIC_EXCLUSIVE:
                # Anthropic wire format: input_tokens strictly represents uncached remainder
                total_in = raw_in + sub_sum
                uncached_tokens = raw_in
            elif provenance in (UsageProvenance.OPENAI_INCLUSIVE, UsageProvenance.GEMINI_INCLUSIVE, UsageProvenance.GATEWAY_INCLUSIVE):
                total_in = raw_in
                uncached_tokens = max(0, raw_in - sub_sum)
            else:
                # Untagged legacy payload: check arithmetic evidence to avoid breaking legacy fixtures
                if has_anthropic_wire_keys and sub_sum > 0:
                    already_normalized = (
                        raw_tot is not None
                        and raw_out is not None
                        and raw_tot == (raw_in + raw_out)
                        and raw_in >= sub_sum
                    )
                    if already_normalized:
                        total_in = raw_in
                        uncached_tokens = max(0, raw_in - sub_sum)
                        provenance = UsageProvenance.NORMALIZED_TOTAL
                    else:
                        total_in = raw_in + sub_sum
                        uncached_tokens = raw_in
                        provenance = UsageProvenance.ANTHROPIC_EXCLUSIVE
                else:
                    total_in = raw_in
                    uncached_tokens = max(0, raw_in - sub_sum)

        return (
            total_in,
            raw_out,
            cached or None,
            cache_write or None,
            w_5m,
            w_1h,
            uncached_tokens,
            gen_residual,
            provenance,
        )

    @staticmethod
    def _calculate_cost(
        prompt: int,
        completion: int,
        model: str,
        *,
        cached_tokens: int = 0,
        cache_reported: bool = False,
        cache_write_tokens: int = 0,
        cache_write_reported: bool = False,
        cache_write_5m_tokens: int = 0,
        cache_write_1h_tokens: int = 0,
    ) -> float | None:
        """Use the telemetry ledger's live/manual rate card; never guess a fallback."""
        from src.telemetry.call_ledger import estimate_cost_usd

        return estimate_cost_usd(
            model,
            prompt,
            completion,
            cached_tokens=cached_tokens,
            cache_reported=cache_reported,
            cache_write_tokens=cache_write_tokens,
            cache_write_reported=cache_write_reported,
            cache_write_5m_tokens=cache_write_5m_tokens,
            cache_write_1h_tokens=cache_write_1h_tokens,
        )

"""The two context errors, kept apart the way upstream keeps them apart.

Ported from hermes-agent @ 8cab422: `agent/model_metadata.py::parse_available_output_tokens_from_error`,
`::parse_context_limit_from_error`, `::get_context_length_from_provider_error`, plus the rule those three
exist to enforce. Their docstrings state it exactly, and Pulse had no equivalent at all:

  1. "Prompt too long"  -- the INPUT exceeds the window.
       Fix: compress history, and only reduce context_length if the provider explicitly reports the actual
       lower limit.
  2. "max_tokens too large" -- input is fine, but input + requested output > window.
       Fix: reduce max_tokens (the output cap) for THIS call. Do NOT touch context_length -- the window
       has not shrunk.

The point of splitting them is what it prevents: a provider that says only "too long" without a number gets
NO new window from us. Upstream refuses to walk down guessed probe tiers (1M -> 256K -> 128K ...) because a
tier is a guess wearing a strategy, and a guessed shrink silently caps every later turn.
"""
from __future__ import annotations

import re

# "available_tokens: 10000" / "available tokens 10000" -- Anthropic states the remainder directly.
_AVAILABLE_PATTERNS = (
    r"available_tokens[:\s]+(\d+)",
    r"available\s+tokens[:\s]+(\d+)",
    r"=\s*(\d+)\s*$",
)

# The shapes that mean "your OUTPUT request is too big", not "your prompt is too big".
_OUTPUT_CAP_MARKERS = (
    ("max_tokens", ("available_tokens", "available tokens")),
    ("maximum context length", "in the output"),
    ("maximum context length", "output tokens"),
    ("range of max_tokens should be", ""),
    ("exceeds model", "maximum output tokens"),
)


def parse_available_output_tokens_from_error(error_msg: str) -> int | None:
    """Output tokens that would fit, when the error is specifically an output-cap rejection."""
    low = (error_msg or "").lower()
    if not low:
        return None

    looks_like_output_cap = False
    for head, tail in _OUTPUT_CAP_MARKERS:
        if head not in low:
            continue
        if not tail or (isinstance(tail, tuple) and any(t in low for t in tail)) or (isinstance(tail, str) and tail in low):
            looks_like_output_cap = True
            break
    # "requested N output tokens" alongside "maximum context length" is the llama.cpp/LM Studio form of
    # the same condition: the input fits, the reply allowance does not.
    if not looks_like_output_cap and "maximum context length" in low and "requested" in low and "output tokens" in low:
        looks_like_output_cap = True
    if not looks_like_output_cap:
        return None

    # Explicit ceiling in the message wins over arithmetic on the window.
    m = re.search(r"exceeds model(?:'s)? maximum output tokens\s*\(?\s*(\d+)", low)
    if m and int(m.group(1)) >= 1:
        return int(m.group(1))
    m = re.search(r"range of max_tokens should be\s*\[\s*\d+\s*,\s*(\d+)\s*\]", low)
    if m and int(m.group(1)) >= 1:
        return int(m.group(1))

    for pattern in _AVAILABLE_PATTERNS:
        m = re.search(pattern, low)
        if m and int(m.group(1)) >= 1:
            return int(m.group(1))

    # OpenRouter/Nous: context minus the input parts it enumerates.
    m_ctx = re.search(r"maximum context length is (\d+)", low)
    m_parts = re.search(r"\((\d+)\s+of text input,\s*(\d+)\s+of tool input,\s*(\d+)\s+in the output\)", low)
    if m_ctx and m_parts:
        available = int(m_ctx.group(1)) - int(m_parts.group(1)) - int(m_parts.group(2))
        if available >= 1:
            return available

    # llama.cpp-family reports the prompt in CHARACTERS while the window is in tokens. Estimate the
    # input conservatively (over-reserving keeps the retried request inside the window) and give the
    # remainder to the reply.
    m_tok = re.search(r"maximum context length is (\d+)\s*token", low)
    m_chars = re.search(r"prompt contains (\d+)\s*character", low)
    if m_tok and m_chars:
        estimated_input = int(int(m_chars.group(1)) / 3)  # ~3 chars/token, deliberately pessimistic
        available = int(m_tok.group(1)) - estimated_input
        if available >= 1:
            return available
    return None


def parse_context_limit_from_error(error_msg: str) -> int | None:
    """The window a provider explicitly named in its rejection, if it named one."""
    low = (error_msg or "").lower()
    patterns = (
        r"max_model_len\s*(?:is\s*)?[:=(]?\s*(\d{4,})",
        r"maximum model length\s*(?:is\s*)?[:=(]?\s*(\d{4,})",
        r"maximum context length is (\d{4,})",
        r"context[_\s]*(?:length|size|window)[^0-9]{0,20}(\d{4,})",  # incl. "context_length_exceeded: 131072"
        r"(\d{4,})\s*(?:token)?\s*(?:context|limit)",
        r">\s*(\d{4,})\s*(?:max|limit|token)",
        r"supports up to (\d{4,})",
    )
    for pattern in patterns:
        m = re.search(pattern, low)
        if m:
            value = int(m.group(1))
            if value >= 1000:
                return value
    return None


def get_context_length_from_provider_error(error_msg: str, current_context_length: int) -> int | None:
    """A provider-reported SMALLER window, or None. Never a guess.

    Two guards, both from upstream: the limit must be explicitly present in the message, and it must be
    smaller than what we already believe. A provider that only says "too long" teaches us nothing about
    the window's size, and shrinking on that would cap the session to a number nobody measured.
    """
    parsed = parse_context_limit_from_error(error_msg)
    if parsed is None:
        return None
    if parsed < current_context_length:
        return parsed
    return None


def apply_reported_limit(model: str | None, provider: str | None, limit: int) -> None:
    """Persist a provider-reported window so the NEXT resolution starts from truth.

    Written to the same cache the discovery ladder reads, rather than poked into a live engine: a
    correction learned mid-turn must not reshape the budgets of the turn that is running (the same rule
    the background warm-up follows). No tier guessing -- this function is only reachable with a number
    the provider itself printed.
    """
    from src.context.model_budgets import _cache_limits_get, _write_cache, cache_key_for

    key = cache_key_for(model, provider)
    # Carry the stated reply cap forward. `_write_cache` stores a whole entry, so a 2-arg write here would
    # correct the window and erase the output ceiling the endpoint published -- turning a 512,000-token
    # model into an uncapped one, discovered only when the next request came back too large.
    existing = _cache_limits_get(key)
    _write_cache(key, int(limit), existing[1] if existing else None)


def handle_context_error(model: str | None, error_text: str) -> bool:
    """The recovery decision for one provider rejection. True = resend allowed, once.

    Kept here, next to the parsers it uses, so the whole flow (recognise -> decide -> apply) is readable in
    one file and testable without a live client. The retry loop's only job is to obey the boolean.

    Recoverable: an output-cap rejection. The prompt fit; our request was too greedy. The provider has
    already told us the allowance, so one resend with that cap is the whole fix.
    Not recoverable: a prompt-too-long rejection. Resending the same oversized prompt wastes the attempt;
    the answer is compression, and we only adopt a new window when the provider states one.
    """
    from src.llm.output_budget import note_available_output

    available = parse_available_output_tokens_from_error(error_text)
    if available:
        note_available_output(model, available)
        print(
            f"[context] provider left {available:,} tokens for the reply on {model!r}; retrying this "
            "request with that cap. The context window is unchanged -- it did not shrink."
        )
        return True

    try:
        from src.context.model_budgets import resolve_context_window

        current, _source = resolve_context_window(model)
        reported = get_context_length_from_provider_error(error_text, current)
        if reported:
            apply_reported_limit(model, None, reported)
            print(
                f"[context] provider reported a {reported:,} window for {model!r} (we held {current:,}); "
                "cached for the next build -- this turn is not re-budgeted mid-flight."
            )
        elif "context" in error_text.lower():
            print(
                "[context] prompt too long and no limit was reported, so nothing is guessed; the window "
                f"stays at {current:,} and compression handles it."
            )
    except Exception as exc:  # a correction is an optimisation, never a reason to fail the turn
        print(f"[context] limit correction skipped: {exc}")
    return False

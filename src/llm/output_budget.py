"""How many tokens we may ask the model to emit -- the provider's number, not a constant.

Two hardcodes used to sit in the send path (`src/graphs/chat_graph.py`, both delivery binds):

    max_tokens=max(512, min(delivery_cap, 8192))

`delivery_cap` is the user's own setting (CRUSORAI_DELIVERY_MAX_TOKENS), and then a bare 8,192 clamped it,
whatever the model said. On an endpoint that reports max_output_tokens = 512,000 that cap is not protection,
it is an unannounced policy: it throttles the reply to a number nobody chose, and it is invisible in every
receipt because it never went through the budget layer. Per the standing instruction -- the provider is asked
about model id, window, token count and max output -- the output ceiling now comes from the same catalog read
that produced the window.

What stays: a 512-token floor (a reply that cannot finish is worse than a throttled one), and the user's
setting as the DESIRED amount. What changes: the provider's stated cap is the upper bound, and when a
provider rejects a request as too large for the remaining window, its own error tells us the allowance for
one retry (see `note_available_output` / `take_available_output`, and src/llm/context_errors.py for why the
window itself is never adjusted on an output-cap error).

Reasoning rides in the same envelope (field 2026-10-22, `z-ai/glm-5.3-flash` @ high effort): an endpoint
that bills hidden reasoning against `max_tokens` truncated a delivery call after ~4k tokens of thinking --
`finish=length` with zero content, the model asked to continue with nothing to continue FROM. The user's
knob describes the desired REPLY, so when thinking is enabled the requested amount grows by the active
thinking budget (src/config/reasoning_config.THINKING_BUDGET_TOKENS). On providers that bill reasoning
separately the extra is harmless headroom; an over-ask meets the same stated-cap clamp and, failing that,
the provider's own rejection -> `note_available_output` retry.
"""
from __future__ import annotations

import os
import threading

# The floor for a delivery call: below this the model cannot finish an answer, so a tiny user setting
# must not produce a truncated reply. This is ours, not a provider's number, and it is the only constant
# left in the path.
_MIN_REPLY_TOKENS = 512

# The user's knob, unchanged in meaning. It used to double as the ceiling via min(..., 8192).
DEFAULT_REQUESTED = 4_096

_lock = threading.Lock()
_available_output: dict[str, int] = {}


def _key(model: str | None) -> str:
    return (model or "").strip().lower()


def requested_output_cap(
    model: str | None,
    provider: str | None = None,
    requested: int | None = None,
    thinking_tokens: int = 0,
) -> int:
    """Tokens to ask for: what the user wants (plus thinking), clamped by what the model says it can emit.

    No invented ceiling. If the endpoint stated nothing, we send what was asked for -- the absence of a
    number is not evidence for 8,192, and guessing one is how a 512,000-token model gets treated like a
    small one.

    ``thinking_tokens``: hidden-reasoning budget the endpoint bills inside ``max_tokens`` for this call
    (0 when thinking is off). The user's knob is the desired visible reply, so the requested amount is the
    reply PLUS reasoning -- not either-or.
    """
    if requested is None:
        raw = os.environ.get("CRUSORAI_DELIVERY_MAX_TOKENS", "").strip()
        try:
            requested = int(raw) if raw else DEFAULT_REQUESTED
        except ValueError:
            requested = DEFAULT_REQUESTED

    try:
        requested = max(0, int(requested)) + max(0, int(thinking_tokens))
    except (TypeError, ValueError):
        requested = DEFAULT_REQUESTED + max(0, int(thinking_tokens or 0))

    from src.context.model_budgets import max_output_for

    stated = max_output_for(model, provider)
    allowed = min(int(requested), int(stated)) if stated else int(requested)
    return max(_MIN_REPLY_TOKENS, allowed)


def note_available_output(model: str | None, tokens: int) -> None:
    """Record the output allowance a provider just reported for this model, for ONE retry."""
    if tokens >= 1:
        with _lock:
            _available_output[_key(model)] = int(tokens)


def take_available_output(model: str | None) -> int | None:
    """Consume the recorded allowance. Immediately, on purpose -- upstream does the same.

    A one-shot override is the whole design: the rejection describes how much room the PROMPT LEFT on
    that request, which says nothing about the next turn's prompt. Carrying it forward would cap later
    calls by an unrelated message.
    """
    with _lock:
        return _available_output.pop(_key(model), None)


def pending_available_output(model: str | None) -> int | None:
    """Read without consuming, for receipts and tests that must not perturb the state."""
    with _lock:
        return _available_output.get(_key(model))

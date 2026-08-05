"""Model-aware context window budgets.

Replaces the historical hardcoded 8000-token cap in ContextEngine with a
per-model lookup, so a 128K/200K/1M-window model is not squeezed into the
same budget as gpt-3.5.

Matching is intentionally conservative:
- exact match first,
- then trailing date suffixes are stripped ("-20241022", "-2024-08-06",
  "-0613") and re-tried,
- then the LONGEST table key that is a proper name-prefix wins.

The longest-prefix rule matters: a naive startswith("gpt") style match once
handed gpt-4-0613 a 128K budget (real window: 8192) — a 16x overshoot that
providers answer with HTTP 400. Unknown models fall back to 8192 on purpose:
undershooting costs context, overshooting costs the whole request.

NOTE: this is the *model* window. The effective engine budget is further
capped by PROVIDER_SAFE_LIMIT (the pre-send token guard in RetryLLMProxy) —
see ContextEngine.__init__.
"""

from __future__ import annotations

import re

MODEL_WINDOWS: dict[str, int] = {
    # Anthropic
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-7-sonnet": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-opus-4": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    # Google
    "gemini-1.5-pro": 1_048_576,
    "gemini-1.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    # Groq-hosted open models (documented 131072 context)
    "llama-3.3-70b-versatile": 131_072,
    "llama-3.1-8b-instant": 131_072,
    "gpt-oss-120b": 131_072,
    "gpt-oss-20b": 131_072,
    "mixtral-8x7b-32768": 32_768,
    # Unknown / local / unverified: deliberately small.
    "default": 8_192,
}

# Reserve for the model's reply; never let the input budget eat the whole
# window, or completions get truncated (or rejected outright).
SAFETY_MARGIN = 4_096

# Never return less than this, even for tiny/unknown windows.
_MIN_USABLE = 4_096

_DATE_SUFFIX = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2}|\d{4})$")


def _normalize(model_name: str) -> str:
    """Lowercase, strip whitespace, and drop a provider prefix.

    The repo's own LLM_MODEL default is provider-prefixed
    ("qwen/qwen3.6-27b"); openrouter-style names too. Without this, every
    prefixed name silently falls through to the 8192 default.
    """
    n = model_name.strip().lower()
    if "/" in n:
        n = n.rsplit("/", 1)[1]
    return n


def model_window(model_name: str | None) -> int:
    """Return the known context window for a model, or the safe default."""
    if not model_name:
        return MODEL_WINDOWS["default"]

    n = _normalize(model_name)

    # 1) exact
    if n in MODEL_WINDOWS:
        return MODEL_WINDOWS[n]

    # 2) strip trailing revision dates ("-20241022", "-2024-08-06", "-0613")
    stripped = n
    while True:
        new = _DATE_SUFFIX.sub("", stripped)
        if new == stripped:
            break
        stripped = new
        if stripped in MODEL_WINDOWS:
            return MODEL_WINDOWS[stripped]

    # 3) longest proper prefix ("gpt-4o-2024-08-06" -> "gpt-4o", NOT "gpt-4")
    best_key: str | None = None
    for key in MODEL_WINDOWS:
        if key == "default":
            continue
        if stripped == key or stripped.startswith(key + "-"):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    if best_key is not None:
        return MODEL_WINDOWS[best_key]

    return MODEL_WINDOWS["default"]


def usable_budget(model_name: str | None) -> int:
    """Window minus reply headroom — the most the input should ever use."""
    return max(model_window(model_name) - SAFETY_MARGIN, _MIN_USABLE)

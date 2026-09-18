"""Reasoning / extended-thinking configuration for provider-side thinking.

Modeled after Hermes' hermes_constants.parse_reasoning_effort() and
anthropic_adapter reasoning_config assembly.  The module provides:

  - ``parse_reasoning_effort(raw)`` → dict | None
  - ``build_model_kwargs_for_reasoning(provider, model, reasoning_config)`` → dict

The output dict is merged into the LangChain constructor's ``model_kwargs``
so extra parameters are sent verbatim in the HTTP request body.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Effort ladder (Hermes-compatible) ─────────────────────────────────
VALID_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max", "ultra")

# Anthropic adaptive-thinking effort levels and their budget_tokens fallback.
# Claude 4.6 only exposes low/medium/high/max; xhigh arrived with 4.7.
ANTHROPIC_BUDGET_TOKENS: dict[str, int] = {
    "xhigh": 32000,
    "high": 16000,
    "medium": 8000,
    "low": 4000,
}

ANTHROPIC_ADAPTIVE_EFFORT_MAP: dict[str, str] = {
    "ultra": "max",
    "max": "max",
    "xhigh": "xhigh",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "minimal": "low",
}

# Older Claude families that use manual thinking (budget_tokens only).
_LEGACY_CLAUDE_SUBSTRINGS = (
    "claude-3",
    "claude-opus-4-0", "claude-opus-4.0",
    "claude-opus-4-1", "claude-opus-4.1",
    "claude-sonnet-4-0", "claude-sonnet-4.0",
    "claude-opus-4-2025", "claude-sonnet-4-2025",
    "claude-opus-4-5", "claude-opus-4.5",
    "claude-sonnet-4-5", "claude-sonnet-4.5",
    "claude-haiku-4-5", "claude-haiku-4.5",
)

# Claude families that reject xhigh (4.6 only).
_NO_XHIGH_CLAUDE = (
    "claude-opus-4-6", "claude-opus-4.6",
    "claude-sonnet-4-6", "claude-sonnet-4.6",
)


def parse_reasoning_effort(raw: str | None) -> dict | None:
    """Parse a reasoning effort string into a config dict.

    Returns None when the input is empty or unrecognized (caller uses provider
    default).  Returns ``{"enabled": False}`` for "none" and
    ``{"enabled": True, "effort": <level>}`` for valid effort levels.
    """
    if not raw or not str(raw).strip():
        return None
    effort = str(raw).strip().lower()
    if effort in ("none", "false", "disabled"):
        return {"enabled": False}
    if effort in VALID_EFFORTS:
        return {"enabled": True, "effort": effort}
    logger.warning("Unknown reasoning_effort '%s', ignoring", raw)
    return None


def _is_claude(model: str) -> bool:
    return "claude" in model.lower()


def _supports_adaptive_thinking(model: str) -> bool:
    """Claude 4.6+ uses adaptive thinking; older models use manual budget."""
    if not _is_claude(model):
        return False
    m = model.lower()
    return not any(v in m for v in _LEGACY_CLAUDE_SUBSTRINGS)


def _supports_xhigh(model: str) -> bool:
    if not _supports_adaptive_thinking(model):
        return False
    m = model.lower()
    return not any(v in m for v in _NO_XHIGH_CLAUDE)


def build_model_kwargs_for_reasoning(
    provider: str,
    model: str,
    reasoning_config: dict | None,
) -> dict[str, Any]:
    """Build extra kwargs to inject into the LangChain LLM constructor.

    These kwargs become ``model_kwargs`` on ChatOpenAI / ChatGroq, which are
    forwarded verbatim in the HTTP request body.

    Provider-specific wire mapping (following Hermes anthropic_adapter):
      - Anthropic: ``thinking`` + ``output_config`` (adaptive) or
        ``thinking`` + ``budget_tokens`` + ``temperature=1`` (manual)
      - OpenAI-compatible: ``reasoning_effort`` (o-series, GPT-5)
      - DeepSeek: ``reasoning_content`` is already handled by StreamingPump;
        this just sets the effort hint if the endpoint supports it.
    """
    if not reasoning_config or not reasoning_config.get("enabled"):
        if reasoning_config and not reasoning_config.get("enabled"):
            # Explicit disable
            if provider == "anthropic" and _is_claude(model):
                return {"thinking": {"type": "disabled"}}
            # OpenAI/o-series: no wire-level disable; omit reasoning_effort
            return {}
        return {}

    effort = reasoning_config.get("effort", "medium")

    # ── Anthropic (Claude) ────────────────────────────────────────────
    if provider == "anthropic":
        if _supports_adaptive_thinking(model):
            adaptive_effort = ANTHROPIC_ADAPTIVE_EFFORT_MAP.get(effort, "medium")
            if adaptive_effort == "xhigh" and not _supports_xhigh(model):
                adaptive_effort = "max"
            kwargs: dict[str, Any] = {
                "thinking": {"type": "adaptive", "display": "summarized"},
                "output_config": {"effort": adaptive_effort},
            }
            return kwargs
        else:
            # Legacy manual thinking
            budget = ANTHROPIC_BUDGET_TOKENS.get(effort, 8000)
            return {
                "thinking": {"type": "enabled", "budget_tokens": budget},
                "temperature": 1,
            }

    # ── OpenAI (o-series, GPT-5) ─────────────────────────────────────
    if provider in ("openai", "custom", "cheap"):
        # OpenAI uses reasoning_effort in the request body for o-series/GPT-5.
        # ChatOpenAI passes model_kwargs verbatim.
        return {"reasoning_effort": effort}

    # ── Groq (openai-compatible) ──────────────────────────────────────
    if provider == "groq":
        # Groq supports reasoning_effort on supported models.
        return {"reasoning_effort": effort}

    # ── Gemini ────────────────────────────────────────────────────────
    if provider == "gemini":
        # Gemini uses thinkingConfig; langchain_google_genai doesn't expose
        # a native param, so we set it via model_kwargs if the endpoint
        # accepts it.
        return {"thinking_config": {"thinking_budget": ANTHROPIC_BUDGET_TOKENS.get(effort, 8000)}}

    # ── NVIDIA (openai-compatible) ────────────────────────────────────
    if provider == "nvidia":
        return {"reasoning_effort": effort}

    return {}

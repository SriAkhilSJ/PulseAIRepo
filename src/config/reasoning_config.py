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

# Standard thinking budget token ladder across providers
THINKING_BUDGET_TOKENS: dict[str, int] = {
    "ultra": 32000,
    "max": 32000,
    "xhigh": 32000,
    "high": 16000,
    "medium": 8000,
    "low": 4000,
    "minimal": 2048,
    "none": 0,
}

# Anthropic adaptive-thinking effort levels and their budget_tokens fallback.
# Claude 4.6 only exposes low/medium/high/max; xhigh arrived with 4.7.
ANTHROPIC_BUDGET_TOKENS: dict[str, int] = THINKING_BUDGET_TOKENS

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

    These kwargs become ``model_kwargs`` or native constructor parameters on
    ChatOpenAI / ChatGroq / ChatGoogleGenerativeAI, which are forwarded
    verbatim in the HTTP request body.

    Provider-specific wire mapping:
      - Anthropic: ``thinking`` + ``output_config`` (adaptive) or
        ``thinking`` + ``budget_tokens`` + ``temperature=1`` (manual)
      - OpenAI / Custom / Cheap: ``reasoning_effort`` + ``extra_body`` thinking
        token caps to strictly prevent unbounded thinking latency runaway.
      - Groq: ``reasoning_effort`` + ``reasoning_format``
      - Gemini: ``thinking_budget``
      - NVIDIA: ``reasoning_effort`` + ``extra_body``
    """
    if not reasoning_config or not reasoning_config.get("enabled"):
        if reasoning_config and not reasoning_config.get("enabled"):
            # Explicit disable across provider adapters
            if provider == "anthropic":
                return {"thinking": {"type": "disabled"}}
            if provider in ("custom", "cheap"):
                return {
                    "reasoning_effort": "none",
                    "extra_body": {
                        "reasoning": {"effort": "none", "max_tokens": 0},
                        "thinking": {"type": "disabled", "budget_tokens": 0},
                        "chat_template_kwargs": {"thinking": False},
                    },
                }
            if provider == "openai":
                return {
                    "reasoning_effort": "none",
                    "extra_body": {
                        "reasoning": {"effort": "none", "max_tokens": 0},
                        "thinking": {"type": "disabled", "budget_tokens": 0},
                    },
                }
            if provider == "groq":
                return {
                    "reasoning_effort": "none",
                    "reasoning_format": "hidden",
                }
            if provider == "gemini":
                return {"thinking_budget": 0}
            if provider == "nvidia":
                return {"reasoning_effort": "none"}
            return {}
        return {}

    effort = reasoning_config.get("effort", "medium")
    budget = THINKING_BUDGET_TOKENS.get(effort, 8000)

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
            return {
                "thinking": {"type": "enabled", "budget_tokens": budget},
                "temperature": 1,
            }

    # ── OpenAI (o-series, GPT-5) ─────────────────────────────────────
    if provider == "openai":
        return {
            "reasoning_effort": effort,
            "extra_body": {
                "reasoning": {"effort": effort, "max_tokens": budget},
                "thinking": {"type": "enabled", "budget_tokens": budget},
            },
        }

    # ── Custom / Cheap OpenAI-compatible (Velona, OpenRouter, DeepSeek, GLM, Qwen) ──
    if provider in ("custom", "cheap"):
        return {
            "reasoning_effort": effort,
            "extra_body": {
                "reasoning": {"effort": effort, "max_tokens": budget},
                "thinking": {"type": "enabled", "budget_tokens": budget},
                "chat_template_kwargs": {"thinking": True},
            },
        }

    # ── Groq (openai-compatible) ──────────────────────────────────────
    if provider == "groq":
        return {
            "reasoning_effort": effort,
            "reasoning_format": "parsed",
        }

    # ── Gemini ────────────────────────────────────────────────────────
    if provider == "gemini":
        return {"thinking_budget": budget}

    # ── NVIDIA (openai-compatible) ────────────────────────────────────
    if provider == "nvidia":
        return {
            "reasoning_effort": effort,
            "extra_body": {
                "reasoning": {"effort": effort, "max_tokens": budget},
            },
        }

    return {}

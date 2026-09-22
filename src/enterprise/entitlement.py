"""Entitlement — feature gating for AI IDE.

Mirrors hermes hermes_cli/nous_subscription.py get_nous_subscription_features():
  free pool excludes video-gen etc; paid gets all. Server flag tool_gateway_entitled_for(cat).

Usage:
  if not is_entitled("video-gen"): show Upgrade prompt

TOOL_COVERAGE like hermes TOOL_COVERAGE_CATEGORIES.
"""
from __future__ import annotations

from typing import Literal

Category = Literal["chat", "agent", "tab-complete", "video-gen", "image-gen", "browser", "stt", "tts"]

# Free tier coverage — what free gets without paying
FREE_COVERAGE: dict[Category, bool] = {
    "chat": True,
    "agent": True,
    "tab-complete": True,
    "video-gen": False,
    "image-gen": False,
    "browser": True,
    "stt": False,
    "tts": False,
}

def is_entitled(category: Category, billing_state=None) -> bool:
    """True if current plan entitles category. Fail-open: no billing -> free rules."""
    if billing_state is None:
        from src.enterprise.billing_state import build_billing_state
        billing_state = build_billing_state()
    if billing_state.logged_in and billing_state.plan_name and billing_state.plan_name.lower() not in ("free",):
        return True  # paid gets all
    return FREE_COVERAGE.get(category, False)

def gated_tools(billing_state=None) -> list[str]:
    """Tools allowed for current entitlement."""
    allowed = []
    for cat, entitled in FREE_COVERAGE.items():
        if is_entitled(cat, billing_state):
            allowed.append(cat)
    return allowed

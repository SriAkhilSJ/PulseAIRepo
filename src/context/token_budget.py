"""
Token Budget — Backward Compatibility Facade
============================================

This module re-exports token budget APIs from `src.context.budgeting.token_budget`.
"""

from __future__ import annotations

from src.context.budgeting.token_budget import (
    count_tokens,
    trim_messages_to_budget,
    _group_turns,
    _enforce_tool_pairing,
    _ALWAYS_REPLAYED_BUDGET_KEYS,
    _NEWEST_TURN_ONLY_BUDGET_KEYS,
    tiktoken,
)

__all__ = [
    "count_tokens",
    "trim_messages_to_budget",
    "_group_turns",
    "_enforce_tool_pairing",
    "_ALWAYS_REPLAYED_BUDGET_KEYS",
    "_NEWEST_TURN_ONLY_BUDGET_KEYS",
    "tiktoken",
]

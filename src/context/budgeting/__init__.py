"""
Context Budgeting Package
=========================

Provides token counting and message trimming (token_budget),
empirical token calibration (token_calibration),
and bounded context limits & ledgers (context_budget).
"""

from src.context.budgeting.token_budget import (
    count_tokens,
    trim_messages_to_budget,
    _group_turns,
    _enforce_tool_pairing,
    _ALWAYS_REPLAYED_BUDGET_KEYS,
    _NEWEST_TURN_ONLY_BUDGET_KEYS,
)
from src.context.budgeting.token_calibration import (
    calibration_factor,
    record_sample,
    reset_for_tests,
    MIN_SAMPLES,
    ALPHA,
    MIN_FACTOR,
    MAX_FACTOR,
)
from src.context.budgeting.context_budget import (
    ContextBudget,
    ScanLimits,
    ScanReport,
    ReadReservation,
    default_scan_limits,
    scan_budget_source,
    _SharedState,
    bounded_read_bytes,
    bounded_read_text,
    default_priority,
    _priority_key,
)

__all__ = [
    "count_tokens",
    "trim_messages_to_budget",
    "calibration_factor",
    "record_sample",
    "reset_for_tests",
    "ContextBudget",
    "ScanLimits",
    "ScanReport",
    "ReadReservation",
    "default_scan_limits",
    "scan_budget_source",
    "_SharedState",
    "bounded_read_bytes",
    "bounded_read_text",
    "default_priority",
    "_priority_key",
    "MIN_SAMPLES",
    "ALPHA",
    "MIN_FACTOR",
    "MAX_FACTOR",
]

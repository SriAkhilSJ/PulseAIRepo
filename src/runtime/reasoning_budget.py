"""
reasoning_budget.py - Dynamic Reasoning Budgeting Engine.

Pillar 5 of the Hardened Production Architecture.
Decouples reasoning budgets into explicit, task-calibrated controls:
- thinking_budget_tokens: scaled by task phase (Explore: 12k, Implementation: 6k, Verification: 2k).
- output_cap_tokens: max deliverable tokens per turn.
- context_window_cap: max prompt history length.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class ReasoningBudgetConfig:
    phase: str
    thinking_budget_tokens: int
    output_cap_tokens: int
    context_window_cap: int


# Standard calibrated budget tiers
DEFAULT_BUDGET_TIERS: Dict[str, ReasoningBudgetConfig] = {
    "explore": ReasoningBudgetConfig(
        phase="explore",
        thinking_budget_tokens=12000,
        output_cap_tokens=4096,
        context_window_cap=65536,
    ),
    "implementation": ReasoningBudgetConfig(
        phase="implementation",
        thinking_budget_tokens=6000,
        output_cap_tokens=8192,
        context_window_cap=65536,
    ),
    "verification": ReasoningBudgetConfig(
        phase="verification",
        thinking_budget_tokens=2000,
        output_cap_tokens=4096,
        context_window_cap=32768,
    ),
    "fast_fix": ReasoningBudgetConfig(
        phase="fast_fix",
        thinking_budget_tokens=2000,
        output_cap_tokens=2048,
        context_window_cap=32768,
    ),
}


def resolve_reasoning_budget(
    phase: str = "implementation",
    model: str = "",
    turn_sequence: int = 1,
) -> ReasoningBudgetConfig:
    """Resolve calibrated thinking & token budgets based on execution phase."""
    normalized_phase = phase.lower().strip()
    if turn_sequence == 1 and normalized_phase != "verification":
        # First turn discovery benefits from deep exploration budget
        normalized_phase = "explore"

    base_config = DEFAULT_BUDGET_TIERS.get(normalized_phase, DEFAULT_BUDGET_TIERS["implementation"])

    # Environment overrides
    env_thinking = os.getenv("CRUSORAI_THINKING_BUDGET_TOKENS")
    env_output = os.getenv("CRUSORAI_OUTPUT_CAP_TOKENS")

    thinking_tokens = int(env_thinking) if env_thinking and env_thinking.isdigit() else base_config.thinking_budget_tokens
    output_tokens = int(env_output) if env_output and env_output.isdigit() else base_config.output_cap_tokens

    return ReasoningBudgetConfig(
        phase=base_config.phase,
        thinking_budget_tokens=thinking_tokens,
        output_cap_tokens=output_tokens,
        context_window_cap=base_config.context_window_cap,
    )

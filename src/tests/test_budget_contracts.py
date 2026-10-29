"""Regression and contract tests for CrusorAI Token & Iteration Budgets.

Validates the architectural separation between:
1. Single-request context window capacity (per-request usable context).
2. Multi-turn cumulative session token budget (credit circuit-breaker).
3. Post-response enforcement: no subsequent model request is dispatched once cumulative budget is reached.
4. Clean execution beyond 121,600 cumulative tokens when session budget permits.
"""
from __future__ import annotations

import os
from unittest.mock import patch
import pytest

from src.context.model_budgets import (
    resolve_context_window,
    usable_window_budget,
)
from src.graphs.budget import (
    _token_budget,
    _budget_exhausted,
    _iteration_budget,
)
from scripts.run_bridge_turn import (
    resolve_default_max_input_tokens,
    should_stop_for_call_budget,
)


def test_single_call_context_vs_cumulative_session_budget_separation():
    """Verify context window limit and cumulative session budget are distinct concepts."""
    # Model with 128k context window (e.g. GPT-4o-mini)
    window, source = resolve_context_window("openai/gpt-4o-mini", provider="custom", allow_network=False)
    assert window == 128_000
    
    # 1. Single-call usable context limit is ~121,600 (95% of window)
    single_call_usable = usable_window_budget(window)
    assert single_call_usable == 121_600

    # 2. Cumulative session budget for multi-turn builds is 500k (not 121.6k!)
    env = {"LLM_MODEL": "openai/gpt-4o-mini", "LLM_PROVIDER": "custom"}
    cumulative_budget = resolve_default_max_input_tokens(env)
    assert cumulative_budget == 500_000
    assert cumulative_budget > single_call_usable


def test_session_exceeds_121600_cumulative_tokens_without_premature_stop():
    """Verify a 128k model can consume >121,600 cumulative tokens under a 500k session budget."""
    with patch.dict(os.environ, {"AGENT_TOKEN_BUDGET": "500000", "AGENT_ITERATION_BUDGET": "60"}):
        assert _token_budget() == 500_000

        # Simulate state after 15 calls accumulating 143,856 prompt tokens (historical GPT-4o-mini cutoff point)
        state_at_143k = {
            "iteration_used": 15,
            "turn_token_usage": {
                "prompt_tokens": 143856,
                "completion_tokens": 5125,
                "total_tokens": 148981,
            },
        }

        # Under the corrected 500k session budget, 148,981 total tokens must NOT trip the budget!
        assert _budget_exhausted(state_at_143k) is False


def test_no_subsequent_request_dispatched_once_budget_exhausted():
    """Verify that once cumulative tokens reach the session cap, budget_exhausted halts dispatch."""
    with patch.dict(os.environ, {"AGENT_TOKEN_BUDGET": "500000", "AGENT_ITERATION_BUDGET": "60"}):
        # Exceeds the 500,000 token session cap
        state_at_exhaustion = {
            "iteration_used": 40,
            "turn_token_usage": {
                "prompt_tokens": 495000,
                "completion_tokens": 8000,
                "total_tokens": 503000,
            },
        }

        # Must trip the budget valve
        assert _budget_exhausted(state_at_exhaustion) is True


def test_iteration_call_limit_enforces_grace_slot_and_runner_backstop():
    """Verify that call budget allows the Nth call for wrap-up and halts N+1."""
    # N calls allowed: 1..N-1 are work calls, call N is tool-free final response
    limit = 60
    assert should_stop_for_call_budget(59, limit) is False
    assert should_stop_for_call_budget(60, limit) is False
    # Call 61 is contract drift and must be stopped by the runner circuit breaker
    assert should_stop_for_call_budget(61, limit) is True

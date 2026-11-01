"""Token-budget provenance: where the cap came from, and what it really cost.

Field 2026-11-01. Two runs were cut mid-build with:

    [budget] exhausted: tokens 172,020/150,000 >= cap
    [grace] Run budget reached [iterations 6/20, tokens 172,020/150,000,
            cost unknown/0.2500, tripped: tokens]

Three separate problems hid inside one line.

1. NOBODY CHOSE 150,000. `src/graphs/budget.py` already defaulted to 600,000 —
   chosen so the ITERATION budget binds first — but `run_bridge_turn.py`
   unconditionally did `env["AGENT_TOKEN_BUDGET"] = str(max_input_tokens)`,
   so the graph's tuned default was replaced by the runner's credit breaker.
   An explicit `AGENT_TOKEN_BUDGET=600000` in the environment was discarded the
   same way. The operator's setting lost to a default, silently.

2. THE CAP COUNTED RE-SENT CACHED PREFIXES AT FULL WEIGHT. `total_tokens` is
   the SUM of every request's prompt, so a 20-call turn pays its ~24k prefix
   twenty times; and 55-73% of those prompt tokens came back as provider cache
   hits. The run that "exhausted" 172k tokens spent about $0.03.

3. `AGENT_TOKEN_BUDGET=0` — documented as the way to disable the cap — would
   have made the runner breaker fire on the first frame (`tokens_in_seen >= 0`),
   cancelling every turn instantly.

Fixes: explicit precedence with the source printed, "disabled" respected by the
breaker, and a trip receipt that carries the cached share and the real spend.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _args(**overrides):
    base = {"max_input_tokens": None, "max_llm_calls": 20}
    base.update(overrides)
    return argparse.Namespace(**base)


# ------------------------------------------------------- precedence ladder


def test_cli_flag_wins_and_is_named():
    from scripts.run_bridge_turn import resolve_token_budget

    env = {"CRUSORAI_MAX_INPUT_TOKENS": "400000", "AGENT_TOKEN_BUDGET": "900000"}
    value, source = resolve_token_budget(_args(max_input_tokens=150000), env)
    assert value == 150000
    assert source == "--max-input-tokens"


def test_crusorai_env_wins_over_agent_budget():
    from scripts.run_bridge_turn import resolve_token_budget

    env = {"CRUSORAI_MAX_INPUT_TOKENS": "400000", "AGENT_TOKEN_BUDGET": "900000"}
    value, source = resolve_token_budget(_args(), env)
    assert value == 400000
    assert source == "CRUSORAI_MAX_INPUT_TOKENS"


def test_explicit_agent_token_budget_is_no_longer_discarded():
    """The field bug: an operator's setting must beat the adaptive default."""
    from scripts.run_bridge_turn import resolve_token_budget

    value, source = resolve_token_budget(_args(), {"AGENT_TOKEN_BUDGET": "600000"})
    assert value == 600000
    assert source == "AGENT_TOKEN_BUDGET"


def test_adaptive_default_is_used_and_labelled_when_nothing_is_set():
    from scripts.run_bridge_turn import resolve_token_budget

    value, source = resolve_token_budget(_args(), {})
    assert value >= 100_000
    assert source == "adaptive default"


def test_zero_means_disabled_and_is_not_rewritten():
    """AGENT_TOKEN_BUDGET=0 disables the leg; it must survive the runner."""
    from scripts.run_bridge_turn import resolve_token_budget

    value, source = resolve_token_budget(_args(), {"AGENT_TOKEN_BUDGET": "0"})
    assert value == 0
    assert source == "AGENT_TOKEN_BUDGET"
    # main() treats <= 0 as "no breaker" — assert the documented intent is
    # encoded somewhere the breaker can read it.
    source_text = (REPO_ROOT / "scripts" / "run_bridge_turn.py").read_text()
    assert "token_budget_enabled = effective_max_input_tokens > 0" in source_text
    assert "token_budget_enabled and tokens_in_seen >= effective_max_input_tokens" in source_text


# --------------------------------------------------------- trip receipts


def test_trip_receipt_names_cached_tokens_and_real_spend(monkeypatch):
    """'tokens 172,020/150,000' must not read like waste."""
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "150000")
    monkeypatch.setenv("AGENT_COST_BUDGET", "0")
    state = {
        "iteration_used": 6,
        "turn_token_usage": {
            "total_tokens": 172_020,
            "cached_tokens": 104_448,
            "prompt_tokens": 168_417,
            "completion_tokens": 3_603,
            "calls_made": 6,
        },
    }
    reason = b._budget_trip_reason(state)
    assert "tokens 172,020/150,000" in reason
    assert "104,448 cached" in reason
    assert "tripped: tokens" in reason


def test_trip_receipt_shows_spend_even_without_a_cost_cap(monkeypatch):
    """A priced run should state what the exhaustion actually cost."""
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "150000")
    monkeypatch.setenv("AGENT_COST_BUDGET", "0")  # cap disabled, spend still known
    state = {
        "iteration_used": 6,
        "turn_token_usage": {
            "total_tokens": 172_020,
            "estimated_cost_usd": 0.0299,
            "cost_known": True,
        },
    }
    assert "spend $0.0299" in b._budget_trip_reason(state)


def test_exhaustion_print_carries_cached_and_spend(monkeypatch, capsys):
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "150000")
    monkeypatch.setenv("AGENT_COST_BUDGET", "0")
    state = {
        "iteration_used": 6,
        "turn_token_usage": {
            "total_tokens": 172_020,
            "cached_tokens": 104_448,
            "estimated_cost_usd": 0.0299,
            "cost_known": True,
        },
    }
    assert b._budget_exhausted(state) is True
    out = capsys.readouterr().out
    assert "tokens 172,020/150,000 (104,448 cached)" in out
    assert "spend $0.0299" in out


def test_disabled_cap_never_reports_exhaustion(monkeypatch):
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "0")
    monkeypatch.setenv("AGENT_COST_BUDGET", "0")
    state = {
        "iteration_used": 1,
        "turn_token_usage": {"total_tokens": 10_000_000, "cached_tokens": 0},
    }
    assert b._budget_exhausted(state) is False


# --------------------------------------------- structural-cap sanity warning


def test_runner_warns_when_the_cap_cannot_cover_the_iteration_budget():
    """A cap worth ~6 calls beside a 20-call budget is a trap, not a guard."""
    source = (REPO_ROOT / "scripts" / "run_bridge_turn.py").read_text()
    # Assert the mechanism, not a wrapped string literal.
    assert "calls_to_cap < args.max_llm_calls" in source
    assert "[budget] WARNING: cap" in source
    assert "budget_exhausted' mid-work" in source

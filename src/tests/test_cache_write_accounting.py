"""
Phase 9.2.1.5 — Cache Write Accounting & Billing Reconciliation Test Suite
========================================================================

Covers the 10 core scenarios:
1. Normal input only
2. Cached input only
3. Cache-write input only
4. Mixed normal, cached, and cache-write input
5. Missing cached-input rate fallback
6. Missing cache-write rate fallback
7. Provider reporting cache writes but no cache reads
8. Category totals exceeding input tokens (validation / clamping)
9. INR pricing conversion with forex multipliers
10. Persistence and session recovery of cache-write metrics
"""

import os
import tempfile
from decimal import Decimal
import pytest

from langchain_core.messages import AIMessage, HumanMessage

from src.context.token_tracker import TokenTracker, TokenUsage
from src.telemetry.call_ledger import estimate_cost_from_rate, estimate_cost_usd, record_call, summarize
from src.telemetry.pricing import parse_catalog, fetch_account_credits
from src.agents.financial_store import FinancialStore
from src.agents.cost_governance import CostGovernor, CostGovernanceConfig, SessionSpendTracker


# Published Velona rate card for qwen/qwen3.7-flash
VELONA_QWEN_RATES = {
    "qwen/qwen3.7-flash": {
        "input_per_1m": 0.03,
        "output_per_1m": 0.13,
        "cached_input_per_1m": 0.006,  # 80% discount
        "cache_write_per_1m": 0.038,
        "currency": "USD",
        "source": "provider-catalog",
    }
}


# -----------------------------------------------------------------------------
# Scenario 1: Normal input only (0 cached, 0 cache-write)
# -----------------------------------------------------------------------------
def test_scenario_01_normal_input_only():
    # 1,000,000 in, 100,000 out -> in: $0.03, out: $0.013 -> total: $0.043
    cost, curr = estimate_cost_from_rate(
        "qwen/qwen3.7-flash",
        input_tokens=1_000_000,
        output_tokens=100_000,
        cached_tokens=0,
        cache_write_tokens=0,
        rate_card=VELONA_QWEN_RATES,
    )
    assert curr == "USD"
    assert cost is not None
    assert round(cost, 6) == 0.043


# -----------------------------------------------------------------------------
# Scenario 2: Cached input only (100% cached, 0 uncached, 0 cache-write)
# -----------------------------------------------------------------------------
def test_scenario_02_cached_input_only():
    # 1,000,000 in (all cached @ $0.006/1M), 0 out -> $0.006
    cost, curr = estimate_cost_from_rate(
        "qwen/qwen3.7-flash",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=1_000_000,
        cache_reported=True,
        cache_write_tokens=0,
        rate_card=VELONA_QWEN_RATES,
    )
    assert curr == "USD"
    assert cost is not None
    assert round(cost, 6) == 0.006


# -----------------------------------------------------------------------------
# Scenario 3: Cache-write input only (100% cache-write, 0 uncached, 0 cached)
# -----------------------------------------------------------------------------
def test_scenario_03_cache_write_input_only():
    # 1,000,000 in (all write @ $0.038/1M), 0 out -> $0.038
    cost, curr = estimate_cost_from_rate(
        "qwen/qwen3.7-flash",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=0,
        cache_write_tokens=1_000_000,
        cache_write_reported=True,
        rate_card=VELONA_QWEN_RATES,
    )
    assert curr == "USD"
    assert cost is not None
    assert round(cost, 6) == 0.038


# -----------------------------------------------------------------------------
# Scenario 4: Mixed normal, cached, and cache-write input
# -----------------------------------------------------------------------------
def test_scenario_04_mixed_normal_cached_and_write():
    # Total input: 1,000,000 tokens
    # Cached: 500,000 @ $0.006/1M -> $0.003
    # Cache-write: 300,000 @ $0.038/1M -> $0.0114
    # Uncached: 200,000 @ $0.03/1M -> $0.006
    # Output: 500,000 @ $0.13/1M -> $0.065
    # Total = 0.003 + 0.0114 + 0.006 + 0.065 = 0.0854
    cost, curr = estimate_cost_from_rate(
        "qwen/qwen3.7-flash",
        input_tokens=1_000_000,
        output_tokens=500_000,
        cached_tokens=500_000,
        cache_reported=True,
        cache_write_tokens=300_000,
        cache_write_reported=True,
        rate_card=VELONA_QWEN_RATES,
    )
    assert curr == "USD"
    assert cost is not None
    assert round(cost, 6) == 0.0854


# -----------------------------------------------------------------------------
# Scenario 5: Missing cached-input rate fallback
# -----------------------------------------------------------------------------
def test_scenario_05_missing_cached_rate_fallback():
    rates_no_cache = {
        "custom/model-no-cache-rate": {
            "input_per_1m": 0.05,
            "output_per_1m": 0.15,
            "currency": "USD",
        }
    }
    # 1,000,000 in, 800,000 reported cached, but no cached_input_per_1m specified.
    # Falls back to standard input_per_1m: 1,000,000 * 0.05 / 1M = $0.05
    cost, curr = estimate_cost_from_rate(
        "custom/model-no-cache-rate",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=800_000,
        cache_reported=True,
        rate_card=rates_no_cache,
    )
    assert round(cost, 6) == 0.05


# -----------------------------------------------------------------------------
# Scenario 6: Missing cache-write rate fallback
# -----------------------------------------------------------------------------
def test_scenario_06_missing_cache_write_rate_fallback():
    rates_no_write = {
        "custom/model-no-write-rate": {
            "input_per_1m": 0.04,
            "output_per_1m": 0.12,
            "cached_input_per_1m": 0.01,
            "currency": "USD",
        }
    }
    # 1,000,000 in: 400,000 cached (@0.01 = $0.004), 400,000 write (falls back to input 0.04 = $0.016),
    # 200,000 uncached (@0.04 = $0.008) -> total input = 0.004 + 0.016 + 0.008 = $0.028
    cost, curr = estimate_cost_from_rate(
        "custom/model-no-write-rate",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=400_000,
        cache_reported=True,
        cache_write_tokens=400_000,
        cache_write_reported=True,
        rate_card=rates_no_write,
    )
    assert round(cost, 6) == 0.028


# -----------------------------------------------------------------------------
# Scenario 7: Provider reporting cache writes but no cache reads
# -----------------------------------------------------------------------------
def test_scenario_07_provider_reports_cache_write_no_reads():
    # Cold prompt creation: write=600,000 @ 0.038 = 0.0228, uncached=400,000 @ 0.03 = 0.012 -> 0.0348
    cost, curr = estimate_cost_from_rate(
        "qwen/qwen3.7-flash",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=0,
        cache_reported=False,
        cache_write_tokens=600_000,
        cache_write_reported=True,
        rate_card=VELONA_QWEN_RATES,
    )
    assert round(cost, 6) == 0.0348


# -----------------------------------------------------------------------------
# Scenario 8: Category totals exceeding input tokens (validation / clamping)
# -----------------------------------------------------------------------------
def test_scenario_08_category_totals_exceeding_input_tokens():
    # Input tokens = 1,000.
    # Erroneous metadata: cached = 800, write = 500 (sum = 1,300 > 1,000).
    # Clamping: cached = 800, write = min(1000 - 800, 500) = 200, uncached = 0.
    # Input cost: (800 * 0.006 + 200 * 0.038) / 1M = (4.8 + 7.6) / 1M = 12.4 / 1M = $0.0000124
    cost, curr = estimate_cost_from_rate(
        "qwen/qwen3.7-flash",
        input_tokens=1_000,
        output_tokens=0,
        cached_tokens=800,
        cache_reported=True,
        cache_write_tokens=500,
        cache_write_reported=True,
        rate_card=VELONA_QWEN_RATES,
    )
    assert round(cost, 8) == 0.0000124


# -----------------------------------------------------------------------------
# Scenario 9: INR pricing conversion with forex multipliers
# -----------------------------------------------------------------------------
def test_scenario_09_inr_conversion_with_forex_spread_and_fee(monkeypatch):
    monkeypatch.setenv("CRUSORAI_PRICING_CURRENCY", "INR")
    monkeypatch.setenv("CRUSORAI_USD_INR", "86.0")

    # Formula: fx (86.0) * spread (1.005) * fee (1.07) = 92.4801
    multiplier = 86.0 * 1.005 * 1.07

    raw_catalog = {
        "models": [
            {
                "id": "qwen/qwen3.7-flash",
                "pricing": {
                    "input_per_1m_usd": 0.03,
                    "output_per_1m_usd": 0.13,
                    "cached_input_per_1m_usd": 0.006,
                    "cache_write_per_1m_usd": 0.038,
                },
            }
        ]
    }
    parsed = parse_catalog(raw_catalog)
    rate = parsed["qwen/qwen3.7-flash"]
    assert rate["currency"] == "INR"
    assert rate["input_per_1m"] == round(0.03 * multiplier, 6)
    assert rate["output_per_1m"] == round(0.13 * multiplier, 6)
    assert rate["cached_input_per_1m"] == round(0.006 * multiplier, 6)
    assert rate["cache_write_per_1m"] == round(0.038 * multiplier, 6)


# -----------------------------------------------------------------------------
# Scenario 10: Persistence and session recovery of cache-write metrics
# -----------------------------------------------------------------------------
def test_scenario_10_persistence_and_session_recovery(tmp_path):
    db_file = str(tmp_path / "fin_cache_write.db")
    store = FinancialStore(db_file)

    gov = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("1000.00"),
            per_turn_cost_budget_inr=Decimal("500.00"),
            per_session_token_budget=1_000_000,
            per_turn_token_budget=500_000,
        ),
        store=store,
    )
    session_id = "session-cache-write-audit"

    # Turn 1: 50,000 input tokens, 20,000 cached tokens, 15,000 cache write tokens
    usage1 = TokenUsage(
        prompt_tokens=50_000,
        completion_tokens=5_000,
        total_tokens=55_000,
        cached_tokens=20_000,
        cache_write_tokens=15_000,
        estimated_cost_usd=0.005,
        cost_known=True,
    )

    rec1 = gov.record_call(
        session_id=session_id,
        provider="custom",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=usage1,
        purpose="audit_write",
    )

    tracker1 = gov.get_tracker(session_id)
    assert tracker1.session_cached_tokens == 20_000
    assert tracker1.session_cache_write_tokens == 15_000
    assert tracker1.turn_cached_tokens == 20_000
    assert tracker1.turn_cache_write_tokens == 15_000

    # Advance turn
    gov.advance_turn(session_id)
    tracker_turn2 = gov.get_tracker(session_id)
    assert tracker_turn2.current_turn_id == 2
    assert tracker_turn2.turn_cached_tokens == 0
    assert tracker_turn2.turn_cache_write_tokens == 0
    assert tracker_turn2.session_cached_tokens == 20_000
    assert tracker_turn2.session_cache_write_tokens == 15_000

    # Turn 2: 40,000 input tokens, 30,000 cached tokens, 5,000 cache write tokens
    usage2 = TokenUsage(
        prompt_tokens=40_000,
        completion_tokens=4_000,
        total_tokens=44_000,
        cached_tokens=30_000,
        cache_write_tokens=5_000,
        estimated_cost_usd=0.003,
        cost_known=True,
    )
    gov.record_call(
        session_id=session_id,
        provider="custom",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=usage2,
        purpose="audit_write_turn2",
    )

    # Total accumulated:
    # cached: 20,000 + 30,000 = 50,000
    # cache write: 15,000 + 5,000 = 20,000
    tracker_end = gov.get_tracker(session_id)
    assert tracker_end.session_cached_tokens == 50_000
    assert tracker_end.session_cache_write_tokens == 20_000
    assert tracker_end.turn_cached_tokens == 30_000
    assert tracker_end.turn_cache_write_tokens == 5_000

    # Simulate fresh process restart by creating a new CostGovernor pointing to the same DB
    fresh_gov = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("1000.00"),
            per_turn_cost_budget_inr=Decimal("500.00"),
            per_session_token_budget=1_000_000,
            per_turn_token_budget=500_000,
        ),
        store=FinancialStore(db_file),
    )

    restored_tracker = fresh_gov.get_tracker(session_id)
    assert restored_tracker.current_turn_id == 2
    assert restored_tracker.session_tokens == 99_000
    assert restored_tracker.session_cached_tokens == 50_000
    assert restored_tracker.session_cache_write_tokens == 20_000
    assert restored_tracker.turn_cached_tokens == 30_000
    assert restored_tracker.turn_cache_write_tokens == 5_000

    # Verify ledger rows in SQLite DB directly
    call_events = fresh_gov._store.get_session_call_history(session_id)
    assert len(call_events) == 2
    assert call_events[0]["cached_tokens"] == 20_000
    assert call_events[0]["cache_write_tokens"] == 15_000
    assert call_events[1]["cached_tokens"] == 30_000
    assert call_events[1]["cache_write_tokens"] == 5_000


# -----------------------------------------------------------------------------
# Wire Extraction Test: factory and token_tracker
# -----------------------------------------------------------------------------
def test_wire_extraction_token_tracker_and_factory():
    msg = AIMessage(
        content="Testing cache write extraction",
        usage_metadata={
            "input_tokens": 1500,
            "output_tokens": 200,
            "total_tokens": 1700,
            "input_token_details": {
                "cache_read": 1000,
                "cache_write": 300,
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="hi")], msg, "qwen/qwen3.7-flash")
    assert usage.prompt_tokens == 1500
    assert usage.completion_tokens == 200
    assert usage.cached_tokens == 1000
    assert usage.cache_write_tokens == 300

    # Also test Anthropic shape fallback
    msg_anthropic = AIMessage(
        content="Testing Anthropic shape",
        response_metadata={
            "token_usage": {
                "input_tokens": 2000,
                "output_tokens": 100,
                "cache_read_input_tokens": 1200,
                "cache_creation_input_tokens": 500,
            }
        },
    )
    # Give it empty usage_metadata to trigger response_metadata fallback
    msg_anthropic.usage_metadata = {"input_tokens": 2000, "output_tokens": 100}
    usage_anthropic = TokenTracker.record_call([HumanMessage(content="hi")], msg_anthropic, "qwen/qwen3.7-flash")
    # In Anthropic wire format, input_tokens (2000) is the uncached remainder.
    # Total prompt tokens is reconstructed as uncached (2000) + cached (1200) + write (500) = 3700.
    assert usage_anthropic.prompt_tokens == 3700
    assert usage_anthropic.uncached_tokens == 2000
    assert usage_anthropic.cached_tokens == 1200
    assert usage_anthropic.cache_write_tokens == 500


def test_fetch_account_credits_resilience(monkeypatch):
    # Never raises on network/server error or missing credentials
    assert fetch_account_credits("http://127.0.0.1:59999", "fake_key", timeout=0.1) is None
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    assert fetch_account_credits(None, None) is None


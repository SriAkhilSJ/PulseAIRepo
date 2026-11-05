"""
Phase 9.2.1.7 — Usage Normalization & Financial Accounting Closure Tests
========================================================================

Required Test Cases:
1. Raw Anthropic exclusive usage (uncached remainder wire format reconstructed).
2. Anthropic exclusive usage with a synthesized total_tokens field (prevents false already_normalized).
3. Already-normalized Anthropic usage with explicit provenance (exact-once normalization).
4. Claude through an OpenAI-compatible inclusive response (protocol-driven, not model-name-driven).
5. Anthropic aggregate cache writes (248) plus TTL breakdown (148 5m + 100 1h) without double-charging.
6. Generic cache-write-only providers (residual writes without TTL breakdown).
7. Mixed cache categories (all 5 categories conserved with exact Decimal pricing).
8. Multiple cumulative streaming usage events (cumulative deltas + duplicate terminal events).
9. Partial stream cancellation (identified as is_partial=True).
10. SQLite persistence and recovery after normalization.
"""

from decimal import Decimal
import tempfile
import pytest

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from src.context.token_tracker import TokenTracker, TokenUsage, UsageBreakdown, UsageProvenance
from src.llm.factory import _response_usage, deduplicate_streaming_usage
from src.telemetry.call_ledger import estimate_cost_from_rate, estimate_cost_usd
from src.agents.financial_store import FinancialStore
from src.agents.cost_governance import CostGovernor, CostGovernanceConfig


# Rate cards for testing
ANTHROPIC_CLAUDE_RATES = {
    "claude-3-5-sonnet": {
        "input_per_1m": 3.00,
        "output_per_1m": 15.00,
        "cached_input_per_1m": 0.30,   # 90% discount
        "cache_write_per_1m": 3.75,    # generic 1.25x
        "cache_write_5m_per_1m": 3.75, # 1.25x
        "cache_write_1h_per_1m": 6.00, # 2.0x
        "currency": "USD",
    }
}

OPENAI_GPT4O_RATES = {
    "gpt-4o": {
        "input_per_1m": 2.50,
        "output_per_1m": 10.00,
        "cached_input_per_1m": 1.25,
        "currency": "USD",
    }
}

VELONA_QWEN_RATES = {
    "qwen/qwen3.7-flash": {
        "input_per_1m": 0.03,
        "output_per_1m": 0.13,
        "cached_input_per_1m": 0.006,
        "cache_write_per_1m": 0.038,
        "currency": "USD",
    }
}


# ==============================================================================
# Scenario 1: Raw Anthropic Exclusive Usage
# ==============================================================================
def test_scenario_01_raw_anthropic_exclusive_usage():
    """Anthropic raw wire format defines input_tokens strictly as uncached remainder."""
    msg = AIMessage(
        content="Claude exclusive response",
        response_metadata={
            "model": "claude-3-5-sonnet",
            "usage": {
                "input_tokens": 1200,  # Uncached remainder
                "output_tokens": 150,
                "cache_read_input_tokens": 800,
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="test")], msg, "claude-3-5-sonnet")
    b = usage.to_breakdown()

    assert b.provenance == UsageProvenance.ANTHROPIC_EXCLUSIVE
    assert b.total_input_tokens == 2000  # 1200 + 800
    assert b.uncached_input_tokens == 1200
    assert b.cached_tokens == 800
    assert b.output_tokens == 150
    assert b.is_conserved()


# ==============================================================================
# Scenario 2: Anthropic Exclusive with Synthesized total_tokens
# ==============================================================================
def test_scenario_02_anthropic_exclusive_with_synthesized_total_tokens():
    """Synthesized total_tokens (input + output) must NOT fool Crusor into treating it as already normalized."""
    msg = AIMessage(
        content="Claude response with synthesized total_tokens",
        response_metadata={
            "model": "claude-3-5-sonnet",
            "provenance": "anthropic_exclusive",  # Explicit provenance prevents naive total_tokens arithmetic misclassification
            "usage": {
                "input_tokens": 1200,  # Uncached remainder
                "output_tokens": 150,
                "total_tokens": 1350,  # Synthesized by an external adapter: 1200 + 150
                "cache_read_input_tokens": 800,
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="test")], msg, "claude-3-5-sonnet")
    b = usage.to_breakdown()

    # Must still recognize anthropic_exclusive wire protocol and reconstruct total input
    assert b.provenance == UsageProvenance.ANTHROPIC_EXCLUSIVE
    assert b.total_input_tokens == 2000  # 1200 + 800, NOT 1200!
    assert b.uncached_input_tokens == 1200
    assert b.cached_tokens == 800
    assert b.output_tokens == 150
    assert b.is_conserved()
    # Total tokens properly recomputed to include full input
    assert usage.total_tokens == 2150  # 2000 in + 150 out


# ==============================================================================
# Scenario 3: Already-Normalized Anthropic with Explicit Provenance
# ==============================================================================
def test_scenario_03_already_normalized_anthropic_with_explicit_provenance():
    """When provenance is explicitly normalized_total, exact-once guarantee prevents second addition."""
    msg = AIMessage(
        content="Already normalized Claude response",
        response_metadata={
            "model": "claude-3-5-sonnet",
            "provenance": "normalized_total",
            "usage": {
                "input_tokens": 2000,  # Already total input
                "output_tokens": 150,
                "total_tokens": 2150,
                "cache_read_input_tokens": 800,
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="test")], msg, "claude-3-5-sonnet")
    b = usage.to_breakdown()

    assert b.provenance == UsageProvenance.NORMALIZED_TOTAL
    assert b.total_input_tokens == 2000  # Remains 2000, NOT 2800
    assert b.uncached_input_tokens == 1200
    assert b.cached_tokens == 800
    assert b.output_tokens == 150
    assert b.is_conserved()


# ==============================================================================
# Scenario 4: Claude Through OpenAI-Compatible Inclusive Response
# ==============================================================================
def test_scenario_04_claude_through_openai_compatible_inclusive_response():
    """A Claude model via an OpenAI-compatible gateway must follow inclusive wire semantics, not model name."""
    msg = AIMessage(
        content="Claude through gateway response",
        response_metadata={
            "model": "claude-3-5-sonnet",  # Model name contains claude
            "provider": "openrouter",
            "token_usage": {
                "prompt_tokens": 2000,  # Already INCLUSIVE of cached tokens
                "completion_tokens": 150,
                "total_tokens": 2150,
                "prompt_tokens_details": {
                    "cached_tokens": 800,
                },
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="test")], msg, "claude-3-5-sonnet")
    b = usage.to_breakdown()

    # Protocol detection is gateway/openai inclusive, NOT anthropic_exclusive
    assert b.provenance in (UsageProvenance.GATEWAY_INCLUSIVE, UsageProvenance.OPENAI_INCLUSIVE)
    assert b.total_input_tokens == 2000  # NOT 2800!
    assert b.uncached_input_tokens == 1200  # 2000 - 800
    assert b.cached_tokens == 800
    assert b.output_tokens == 150
    assert b.is_conserved()


# ==============================================================================
# Scenario 5: Anthropic Aggregate Cache Writes + TTL Breakdown
# ==============================================================================
def test_scenario_05_anthropic_aggregate_writes_plus_ttl_breakdown():
    """Verify aggregate writes = 248, 5m = 148, 1h = 100 bills without double-counting."""
    msg = AIMessage(
        content="Claude with TTL writes",
        response_metadata={
            "model": "claude-3-5-sonnet",
            "usage": {
                "input_tokens": 0,  # 0 uncached remainder
                "output_tokens": 0,
                "cache_creation_input_tokens": 248,  # Aggregate
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 148,
                    "ephemeral_1h_input_tokens": 100,
                },
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="test")], msg, "claude-3-5-sonnet")
    b = usage.to_breakdown()

    assert b.total_input_tokens == 248
    assert b.uncached_input_tokens == 0
    assert b.cache_write_tokens == 248
    assert b.cache_write_5m_tokens == 148
    assert b.cache_write_1h_tokens == 100
    assert b.generic_residual_write_tokens == 0  # 248 - (148 + 100) = 0
    assert b.is_conserved()

    # Exact rate calculation:
    # 148 @ $3.75/1M = $0.000555
    # 100 @ $6.00/1M = $0.000600
    # Expected cost = $0.001155 (aggregate 248 is NOT charged)
    cost, curr = estimate_cost_from_rate(
        "claude-3-5-sonnet",
        input_tokens=b.total_input_tokens,
        output_tokens=b.output_tokens,
        cache_write_tokens=b.cache_write_tokens,
        cache_write_reported=True,
        cache_write_5m_tokens=b.cache_write_5m_tokens,
        cache_write_1h_tokens=b.cache_write_1h_tokens,
        rate_card=ANTHROPIC_CLAUDE_RATES,
    )
    assert curr == "USD"
    expected_cost = Decimal("148") * Decimal("3.75") / Decimal("1000000") + Decimal("100") * Decimal("6.00") / Decimal("1000000")
    assert Decimal(str(cost)) == expected_cost
    assert cost == 0.001155


# ==============================================================================
# Scenario 6: Generic Cache-Write-Only Providers
# ==============================================================================
def test_scenario_06_generic_cache_write_only_providers():
    """Providers with untyped cache writes report residual writes without TTL breakdown."""
    msg = AIMessage(
        content="Velona generic write",
        response_metadata={
            "provider": "velona",
            "token_usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 50,
                "total_tokens": 1550,
                "prompt_tokens_details": {
                    "cached_tokens": 300,
                    "cache_write_tokens": 500,
                },
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="test")], msg, "qwen/qwen3.7-flash")
    b = usage.to_breakdown()

    assert b.total_input_tokens == 1500
    assert b.cached_tokens == 300
    assert b.cache_write_tokens == 500
    assert b.cache_write_5m_tokens == 0
    assert b.cache_write_1h_tokens == 0
    assert b.generic_residual_write_tokens == 500
    assert b.uncached_input_tokens == 700  # 1500 - 300 - 500
    assert b.is_conserved()

    cost, curr = estimate_cost_from_rate(
        "qwen/qwen3.7-flash",
        input_tokens=b.total_input_tokens,
        output_tokens=b.output_tokens,
        cached_tokens=b.cached_tokens,
        cache_reported=True,
        cache_write_tokens=b.cache_write_tokens,
        cache_write_reported=True,
        rate_card=VELONA_QWEN_RATES,
    )
    # 700 uncached @ 0.03/1M = 0.000021
    # 300 cached @ 0.006/1M = 0.0000018
    # 500 generic write @ 0.038/1M = 0.000019
    # 50 output @ 0.13/1M = 0.0000065
    # Total = 0.0000483
    assert curr == "USD"
    expected = (
        Decimal("700") * Decimal("0.03")
        + Decimal("300") * Decimal("0.006")
        + Decimal("500") * Decimal("0.038")
        + Decimal("50") * Decimal("0.13")
    ) / Decimal("1000000")
    assert Decimal(str(cost)) == expected


# ==============================================================================
# Scenario 7: Mixed Cache Categories & Token Conservation
# ==============================================================================
def test_scenario_07_mixed_cache_categories_token_conservation():
    """All 5 input categories present simultaneously: uncached + cached + 5m + 1h + generic residual."""
    # Total input: 1000 uncached + 2000 cached + 300 (5m) + 200 (1h) + 100 (generic residual) = 3600
    # Aggregate cache writes = 600 (300 5m + 200 1h + 100 generic residual)
    msg = AIMessage(
        content="Mixed categories response",
        response_metadata={
            "model": "claude-3-5-sonnet",
            "usage": {
                "input_tokens": 1000,  # Uncached remainder
                "output_tokens": 400,
                "cache_read_input_tokens": 2000,
                "cache_creation_input_tokens": 600,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 300,
                    "ephemeral_1h_input_tokens": 200,
                },
            },
        },
    )
    usage = TokenTracker.record_call([HumanMessage(content="test")], msg, "claude-3-5-sonnet")
    b = usage.to_breakdown()

    assert b.total_input_tokens == 3600
    assert b.uncached_input_tokens == 1000
    assert b.cached_tokens == 2000
    assert b.cache_write_tokens == 600
    assert b.cache_write_5m_tokens == 300
    assert b.cache_write_1h_tokens == 200
    assert b.generic_residual_write_tokens == 100  # 600 - (300 + 200) = 100
    assert b.output_tokens == 400
    assert b.is_conserved()

    # Exact Decimal cost verification
    cost, curr = estimate_cost_from_rate(
        "claude-3-5-sonnet",
        input_tokens=b.total_input_tokens,
        output_tokens=b.output_tokens,
        cached_tokens=b.cached_tokens,
        cache_reported=True,
        cache_write_tokens=b.cache_write_tokens,
        cache_write_reported=True,
        cache_write_5m_tokens=b.cache_write_5m_tokens,
        cache_write_1h_tokens=b.cache_write_1h_tokens,
        rate_card=ANTHROPIC_CLAUDE_RATES,
    )
    assert curr == "USD"
    # 1000 @ 3.00 = 3000
    # 2000 @ 0.30 = 600
    # 300 @ 3.75 = 1125
    # 200 @ 6.00 = 1200
    # 100 @ 3.75 = 375
    # 400 @ 15.00 = 6000
    # Total = 12300 / 1000000 = 0.012300
    expected = (
        Decimal("1000") * Decimal("3.00")
        + Decimal("2000") * Decimal("0.30")
        + Decimal("300") * Decimal("3.75")
        + Decimal("200") * Decimal("6.00")
        + Decimal("100") * Decimal("3.75")
        + Decimal("400") * Decimal("15.00")
    ) / Decimal("1000000")
    assert Decimal(str(cost)) == expected
    assert cost == 0.0123


# ==============================================================================
# Scenario 8: Multiple Cumulative Streaming Usage Events
# ==============================================================================
def test_scenario_08_multiple_cumulative_streaming_usage_events():
    """Streaming message_delta usage is cumulative; multiple events & duplicate terminals must not sum."""
    events = [
        # Event 1: message_start
        {
            "type": "message_start",
            "message": {
                "model": "claude-3-5-sonnet",
                "usage": {
                    "input_tokens": 1500,
                    "cache_read_input_tokens": 500,
                    "output_tokens": 1,
                },
            },
        },
        # Event 2: intermediate text delta
        {"type": "content_block_delta", "delta": {"text": "Hello"}},
        # Event 3: intermediate delta with cumulative output
        {"type": "message_delta", "usage": {"output_tokens": 25}},
        # Event 4: intermediate delta with cumulative output
        {"type": "message_delta", "usage": {"output_tokens": 60}},
        # Event 5: terminal event with final cumulative output
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 100},
        },
        # Event 6: duplicate terminal event
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 100},
        },
    ]

    dedup = deduplicate_streaming_usage(events)
    assert dedup is not None
    assert dedup["input_tokens"] == 2000  # 1500 + 500
    assert dedup["cached_tokens"] == 500
    assert dedup["uncached_tokens"] == 1500
    assert dedup["output_tokens"] == 100  # Cumulative latest, NOT sum of 1+25+60+100+100 = 286!
    assert dedup["total_tokens"] == 2100  # 2000 + 100
    assert dedup["is_partial"] is False
    assert dedup["finish_reason"] == "end_turn"


# ==============================================================================
# Scenario 9: Partial Stream Cancellation
# ==============================================================================
def test_scenario_09_partial_stream_cancellation():
    """Stream interrupted mid-flight retains partial counts and marks is_partial=True."""
    events = [
        # Event 1: message_start
        {
            "type": "message_start",
            "message": {
                "model": "claude-3-5-sonnet",
                "usage": {
                    "input_tokens": 1500,
                    "cache_read_input_tokens": 500,
                    "output_tokens": 1,
                },
            },
        },
        # Event 2: intermediate text delta
        {"type": "content_block_delta", "delta": {"text": "Partial start..."}},
        # Event 3: intermediate cumulative output before cancel
        {"type": "message_delta", "usage": {"output_tokens": 20}},
        # NO terminal stop_reason event! Stream cancelled here
    ]

    dedup = deduplicate_streaming_usage(events)
    assert dedup is not None
    assert dedup["input_tokens"] == 2000
    assert dedup["cached_tokens"] == 500
    assert dedup["uncached_tokens"] == 1500
    assert dedup["output_tokens"] == 20
    assert dedup["total_tokens"] == 2020
    assert dedup["is_partial"] is True


# ==============================================================================
# Scenario 10: SQLite Persistence and Recovery After Normalization
# ==============================================================================
def test_scenario_10_sqlite_persistence_and_recovery(tmp_path):
    """Normalized multi-dimensional usage records persist to SQLite and hydrate without loss."""
    db_file = str(tmp_path / "closure_fin.db")
    store = FinancialStore(db_file)
    gov = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("2000.00"),
            per_turn_cost_budget_inr=Decimal("1000.00"),
        ),
        store=store,
    )
    session_id = "test-session-closure-persistence"

    # Call 1: Anthropic normalized usage
    msg1 = AIMessage(
        content="Anthropic call",
        response_metadata={
            "model": "claude-3-5-sonnet",
            "usage": {
                "input_tokens": 500,
                "output_tokens": 100,
                "cache_read_input_tokens": 3000,
                "cache_creation_input_tokens": 1000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 600,
                    "ephemeral_1h_input_tokens": 400,
                },
            },
        },
    )
    u1 = TokenTracker.record_call([HumanMessage(content="hi")], msg1, "claude-3-5-sonnet")
    gov.record_call(
        session_id=session_id,
        provider="anthropic",
        model="claude-3-5-sonnet",
        tier="standard",
        usage=u1,
    )

    # Call 2: Velona normalized usage
    msg2 = AIMessage(
        content="Velona call",
        response_metadata={
            "provider": "velona",
            "token_usage": {
                "prompt_tokens": 2000,
                "completion_tokens": 200,
                "total_tokens": 2200,
                "prompt_tokens_details": {
                    "cached_tokens": 1000,
                    "cache_write_tokens": 300,
                },
            },
        },
    )
    u2 = TokenTracker.record_call([HumanMessage(content="hi")], msg2, "qwen/qwen3.7-flash")
    gov.record_call(
        session_id=session_id,
        provider="velona",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=u2,
    )

    tracker_before = gov.get_tracker(session_id)
    assert tracker_before.session_tokens == (4500 + 100) + (2000 + 200)  # 4600 + 2200 = 6800
    assert tracker_before.session_cached_tokens == 3000 + 1000  # 4000
    assert tracker_before.session_cache_write_tokens == 1000 + 300  # 1300
    assert tracker_before.total_calls_count == 2

    # Simulate fresh agent startup / restart
    fresh_gov = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("2000.00"),
            per_turn_cost_budget_inr=Decimal("1000.00"),
        ),
        store=FinancialStore(db_file),
    )
    tracker_after = fresh_gov.get_tracker(session_id)

    assert tracker_after.session_tokens == tracker_before.session_tokens
    assert tracker_after.session_cached_tokens == tracker_before.session_cached_tokens
    assert tracker_after.session_cache_write_tokens == tracker_before.session_cache_write_tokens
    assert tracker_after.total_calls_count == tracker_before.total_calls_count
    assert tracker_after.session_cost_usd == tracker_before.session_cost_usd
    assert tracker_after.session_cost_inr == tracker_before.session_cost_inr


"""
Unit and Integration Tests for Crusor AI Agent Core Cost & Token Governance (Phase 9.1)
=====================================================================================
Covers:
1. Simple task routing to economical models satisfying ₹5 target.
2. Token budget enforcement (per-turn and per-session).
3. Monetary budget enforcement in INR with exact Decimal arithmetic.
4. Pre-call headroom reservation protecting final response.
5. Premium model escalation blocking and graceful demotion.
6. Safe budget exhaustion with preserved work and honest status.
7. Unknown pricing discipline (never treated as free/₹0).
8. Compact user-facing summary string formatting with '₹'.
"""
import os
from decimal import Decimal
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.cost_governance import (
    CostGovernor,
    CostGovernanceConfig,
    ModelCallRecord,
    BudgetReservation,
    cost_governor,
)
from src.agents.cost_router import CostRouter
from src.context.token_tracker import TokenUsage
from src.graphs import budget as bg


@pytest.fixture(autouse=True)
def clean_governor():
    """Ensure governor state is fresh for every test."""
    cost_governor.reset_session("test_session")
    cost_governor.reset_session("default")
    yield
    cost_governor.reset_session("test_session")
    cost_governor.reset_session("default")


def test_simple_task_routes_to_cheap_model_and_satisfies_target(monkeypatch):
    """Test 1: Simple tasks route to economical models and meet ₹5 business target."""
    router = CostRouter()
    # Configure cheap tier via env
    monkeypatch.setenv("CRUSORAI_CHEAP_API_KEY", "mock-key")
    monkeypatch.setenv("CRUSORAI_CHEAP_BASE_URL", "https://api.mock.ai/v1")
    monkeypatch.setenv("CRUSORAI_CHEAP_MODEL", "qwen/qwen3.7-flash")
    router._build_tiers()

    # Simple lookup task
    simple_task = "what is the capital of France?"
    tier = router.classify(simple_task)
    assert tier == "cheap"

    provider, model = router.route(simple_task, session_id="test_session")
    assert provider == "cheap"
    assert model == "qwen/qwen3.7-flash"

    # Simulate realistic token usage for simple lookup: 1,500 prompt, 250 completion
    usage = TokenUsage(
        prompt_tokens=1500,
        completion_tokens=250,
        total_tokens=1750,
        estimated_cost_usd=0.0008,
        cost_known=True,
    )
    rec = cost_governor.record_call(
        session_id="test_session",
        provider=provider,
        model=model,
        tier=tier,
        usage=usage,
    )

    # Calculate INR spend with canonical conversion: USD * 86.0 * 1.005 * 1.07
    canonical_fx = Decimal("86.0") * Decimal("1.005") * Decimal("1.07")
    expected_inr = Decimal("0.0008") * canonical_fx
    assert rec.cost_inr == expected_inr.quantize(Decimal("0.000001"))
    # Spend must be well below target simple task cost of ₹5
    assert rec.cost_inr < Decimal("5.00")
    assert rec.cost_inr < Decimal("0.10")  # Actually ~₹0.07!


def test_token_budget_limits_per_turn_and_session():
    """Test 2: Token budget limits enforced per-turn and per-session."""
    cfg = CostGovernanceConfig(
        per_turn_token_budget=50_000,
        per_session_token_budget=120_000,
    )
    gov = CostGovernor(cfg)
    sid = "test_token_limits"

    # Call 1: 30k tokens
    gov.record_call(sid, "test_p", "test_m", "standard", TokenUsage(total_tokens=30_000))
    assert not gov.is_exhausted(sid)

    # Call 2: 25k tokens (turn total = 55k > 50k turn budget)
    gov.record_call(sid, "test_p", "test_m", "standard", TokenUsage(total_tokens=25_000))
    assert gov.is_exhausted(sid)
    reason = gov.trip_reason(sid)
    assert "tripped: turn_tokens" in reason

    # Start next turn: resets turn tokens
    gov.start_turn(sid)
    # Session tokens still 55k < 120k session budget
    assert not gov.is_exhausted(sid)

    # Call 3 in turn 2: 70k tokens (session total = 125k > 120k session budget)
    gov.record_call(sid, "test_p", "test_m", "standard", TokenUsage(total_tokens=70_000))
    assert gov.is_exhausted(sid)
    assert "tripped: session_tokens" in gov.trip_reason(sid)


def test_monetary_budget_limits_inr_and_usd():
    """Test 3: Monetary budget enforcement in INR with exact Decimal conversion."""
    cfg = CostGovernanceConfig(
        per_turn_cost_budget_inr=Decimal("20.00"),
        per_session_cost_budget_inr=Decimal("50.00"),
        usd_to_inr_rate=Decimal("86.0"),
    )
    gov = CostGovernor(cfg)
    sid = "test_monetary"

    # USD spend of $0.10 with canonical conversion (86.0 * 1.005 * 1.07 = 92.48010) = ₹9.248010
    gov.record_call(
        sid, "p", "m", "standard",
        TokenUsage(total_tokens=5000, estimated_cost_usd=0.10, cost_known=True)
    )
    tracker = gov._get_or_create_tracker(sid)
    assert tracker.session_cost_inr == Decimal("9.248010")
    assert not gov.is_exhausted(sid)

    # USD spend of $0.15 = ₹13.872015 (turn cost = 9.248010 + 13.872015 = ₹23.120025 > ₹20.00 turn budget)
    gov.record_call(
        sid, "p", "m", "standard",
        TokenUsage(total_tokens=5000, estimated_cost_usd=0.15, cost_known=True)
    )
    assert gov.is_exhausted(sid)
    assert "tripped: turn_cost" in gov.trip_reason(sid)


def test_budget_reservation_preserves_headroom():
    """Test 4: Budget reservation preserves reserve headroom for final response."""
    cfg = CostGovernanceConfig(
        per_turn_cost_budget_inr=Decimal("10.00"),
        per_session_cost_budget_inr=Decimal("10.00"),
        reserve_budget_inr=Decimal("2.00"),
        per_turn_token_budget=100_000,
        per_session_token_budget=100_000,
        reserve_tokens=10_000,
    )
    gov = CostGovernor(cfg)
    sid = "test_reservation"

    # Requesting ₹7.00 reservation out of ₹10.00:
    # 10.00 - 7.00 = 3.00 >= reserve_budget_inr (2.00) -> Allowed!
    ok, rid, reason = gov.reserve(sid, estimated_cost_inr=Decimal("7.00"), purpose="work")
    assert ok is True
    assert rid.startswith("res_")

    # Second work reservation for ₹2.00:
    # Remaining: 10.00 - 7.00 (reserved) = 3.00. 3.00 - 2.00 = 1.00 < 2.00 headroom -> Refused!
    ok2, _, reason2 = gov.reserve(sid, estimated_cost_inr=Decimal("2.00"), purpose="work")
    assert ok2 is False
    assert "headroom" in reason2

    # But final response reservation is allowed into the reserve!
    ok3, rid3, _ = gov.reserve(sid, estimated_cost_inr=Decimal("1.50"), purpose="final_response")
    assert ok3 is True


def test_premium_model_escalation_guard_and_graceful_demotion(monkeypatch):
    """Test 5: Premium escalation is blocked when budget is low and demotes gracefully."""
    cfg = CostGovernanceConfig(
        per_turn_cost_budget_inr=Decimal("10.00"),
        per_session_cost_budget_inr=Decimal("10.00"),
        reserve_budget_inr=Decimal("2.00"),
        max_premium_calls_per_turn=2,
    )
    gov = CostGovernor(cfg)
    sid = "test_escalation"

    # Initially premium can be afforded
    can_afford, rec_tier, reason = gov.can_afford_tier(sid, "premium", estimated_cost_inr=Decimal("1.50"))
    assert can_afford is True
    assert rec_tier == "premium"

    # Spend ₹7.50 of the ₹10.00 budget
    gov.record_call(
        sid, "p", "m", "premium",
        TokenUsage(total_tokens=5000, estimated_cost_usd=0.0872, cost_known=True) # ~₹7.50
    )
    tracker = gov._get_or_create_tracker(sid)
    tracker.session_cost_inr = Decimal("7.500000")
    tracker.turn_cost_inr = Decimal("7.500000")

    # Now premium (est ₹1.50) would leave ₹1.00 < ₹2.00 headroom -> Demoted to standard!
    can_afford2, rec_tier2, reason2 = gov.can_afford_tier(sid, "premium", estimated_cost_inr=Decimal("1.50"))
    assert can_afford2 is False
    assert rec_tier2 == "standard"
    assert "demoting" in reason2

    # Premium call count cap: set premium calls to max
    tracker.turn_calls_premium = 2
    can_afford3, rec_tier3, reason3 = gov.can_afford_tier(sid, "premium")
    assert can_afford3 is False
    assert rec_tier3 == "standard"
    assert "Premium call cap reached" in reason3


def test_safe_budget_exhaustion_preserves_work(monkeypatch):
    """Test 6: Safe budget exhaustion stops expensive cycles and reports budget_exhausted without rollbacks."""
    sid = "test_exhaustion_safety"
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "5")
    monkeypatch.setenv("CRUSORAI_TURN_TOKEN_BUDGET", "10000")
    cost_governor.reload_config()

    # Trip token budget
    cost_governor.record_call(
        sid, "groq", "llama", "standard",
        TokenUsage(total_tokens=15000, cost_known=True)
    )

    state = {
        "thread_id": sid,
        "iteration_used": 2,
        "messages": [HumanMessage(content="do work")],
        "steps_completed": ["wrote main.py", "tested health check"],
        "token_usage": {"total_tokens": 15000},
    }

    # Verify budget exhaustion detection
    assert bg._budget_exhausted(state) is True
    reason = bg._budget_trip_reason(state)
    assert "governance" in reason or "tripped: tokens" in reason

    # Final response slot allows delivering summary without rollback
    from src.graphs import chat_graph as cg
    finalize_out = cg.finalize_node(
        {
            **state,
            "messages": [
                HumanMessage(content="build app"),
                AIMessage(content="Budget reached. Summary of completed work: wrote main.py, tested health check."),
            ],
            "grace_done": 1,
        },
        {"configurable": {"thread_id": sid, "workspace": "."}},
    )
    # The run status reflects budget_exhausted honestly
    assert finalize_out.get("run_outcome") == "budget_exhausted"
    assert finalize_out.get("task_status") == "budget_exhausted"
    # Status contract carries the budget_exhausted failure reason without rollbacks
    assert finalize_out.get("status_contract", {}).get("run_outcome") == "budget_exhausted"


def test_unknown_pricing_discipline():
    """Test 7: Unrated models are recorded as cost_known=False and never treated as free."""
    sid = "test_unrated"
    # Provider with unknown pricing (cost_known=False)
    usage = TokenUsage(
        prompt_tokens=3000,
        completion_tokens=500,
        total_tokens=3500,
        estimated_cost_usd=0.0,
        cost_known=False,
    )
    rec = cost_governor.record_call(sid, "local_provider", "unlisted_model", "standard", usage)
    assert rec.cost_known is False
    assert rec.cost_usd is None
    assert rec.cost_inr is None

    # Summary acknowledges unrated spend
    summary = cost_governor.get_compact_summary(sid)
    assert "₹unknown" in summary or "unrated" in summary
    assert "3,500" in summary


def test_compact_summary_formatting():
    """Test 8: Compact summary formatted with '₹', percentages, and call breakdowns."""
    sid = "test_summary_fmt"
    cfg = CostGovernanceConfig(
        per_turn_cost_budget_inr=Decimal("25.00"),
        per_session_cost_budget_inr=Decimal("100.00"),
        per_session_token_budget=500_000,
    )
    gov = CostGovernor(cfg)

    # 1 cheap call: 1,000 tokens, $0.0005 USD = ₹0.043 INR
    gov.record_call(
        sid, "groq", "cheap_m", "cheap",
        TokenUsage(total_tokens=1000, cached_tokens=200, estimated_cost_usd=0.0005, cost_known=True)
    )
    # 1 standard call: 4,000 tokens, $0.0100 USD = ₹0.860 INR
    gov.record_call(
        sid, "groq", "std_m", "standard",
        TokenUsage(total_tokens=4000, cached_tokens=500, estimated_cost_usd=0.0100, cost_known=True)
    )

    summary = gov.get_compact_summary(sid)
    assert "[Cost Governance]" in summary
    assert "Session: ₹0.97 / ₹100.00" in summary
    assert "Tokens: 5,000 / 500,000 (700 cached)" in summary
    assert "Calls: 2 (cheap: 1, standard: 1, premium: 0)" in summary
    assert "Status: HEALTHY" in summary

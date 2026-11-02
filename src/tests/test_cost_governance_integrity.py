"""
test_cost_governance_integrity.py -- Phase 9.1.2 Financial Integrity Verification.

Validates:
1. Root session budget inheritance (child/subagent debits root parent).
2. Concurrent subagents thread safety across shared root tracker.
3. Nested subagents hierarchy (grandchild -> child -> root).
4. Reservation deterministic lifecycle (reconciliation & auto-release).
5. Auxiliary LLM accounting (classifier, planner, compaction, titling).
6. Unknown pricing policies (deny, token_limited, explicit_allow).
7. Canonical currency conversion (USD * fx * 1.005 * 1.07) & double-fee avoidance.
8. Pricing cache freshness status (fresh, stale, unavailable).
9. Configuration hygiene and premium / unrated settings.
"""

from __future__ import annotations

import concurrent.futures
from decimal import Decimal
import os
import time
from typing import Any
import pytest

from src.agents.cost_governance import (
    CostGovernanceConfig,
    CostGovernor,
    ReservationContext,
    cost_governor,
)
from src.context.token_tracker import TokenUsage
from src.telemetry import pricing


# -----------------------------------------------------------------------------
# 1. Root Session Budget Inheritance
# -----------------------------------------------------------------------------

def test_root_session_budget_inheritance_child_debits_root():
    """Child subagent session must debit the root parent session budget."""
    cfg = CostGovernanceConfig(
        per_turn_cost_budget_inr=Decimal("25.00"),
        per_session_cost_budget_inr=Decimal("50.00"),
        per_session_token_budget=100_000,
        per_turn_token_budget=40_000,
    )
    gov = CostGovernor(cfg)
    root_id = "parent-root-100"
    child_id = "sub-child-101"

    gov.register_parent_session(child_id, root_id)
    assert gov.get_root_session_id(child_id) == root_id

    # Record call under child session
    gov.record_call(
        session_id=child_id,
        provider="custom",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=TokenUsage(total_tokens=25_000, estimated_cost_usd=0.10, cost_known=True),
    )

    # Root tracker must have accumulated the spend and tokens
    root_tracker = gov._get_or_create_tracker(root_id)
    child_tracker = gov._get_or_create_tracker(child_id)

    assert root_tracker.session_tokens == 25_000
    assert root_tracker.session_cost_inr > Decimal("0")
    # Child tracker keeps local diagnostics
    assert child_tracker.session_tokens == 25_000

    # Record second call from child that trips root session budget (50k more tokens, total 75k + 30k = 105k > 100k)
    gov.record_call(
        session_id=child_id,
        provider="custom",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=TokenUsage(total_tokens=80_000, estimated_cost_usd=0.10, cost_known=True),
    )

    # Root session budget is exhausted, and query via child session reflects it
    assert gov.is_exhausted(child_id)
    assert gov.is_exhausted(root_id)
    assert "tripped: session_tokens" in gov.trip_reason(child_id)


# -----------------------------------------------------------------------------
# 2. Concurrent Subagents Thread Safety
# -----------------------------------------------------------------------------

def test_concurrent_subagents_thread_safety():
    """Multiple concurrent subagents debiting the shared root tracker without races."""
    cfg = CostGovernanceConfig(
        per_session_cost_budget_inr=Decimal("1000.00"),
        per_session_token_budget=1_000_000,
    )
    gov = CostGovernor(cfg)
    root_id = "concurrent-root"
    num_children = 8
    calls_per_child = 10

    child_ids = [f"sub-worker-{i}" for i in range(num_children)]
    for cid in child_ids:
        gov.register_parent_session(cid, root_id)

    def worker_task(cid: str):
        for _ in range(calls_per_child):
            gov.record_call(
                session_id=cid,
                provider="test_prov",
                model="test_model",
                tier="standard",
                usage=TokenUsage(total_tokens=500, estimated_cost_usd=0.001, cost_known=True),
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_children) as executor:
        futures = [executor.submit(worker_task, cid) for cid in child_ids]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    root_tracker = gov._get_or_create_tracker(root_id)
    expected_total_tokens = num_children * calls_per_child * 500
    assert root_tracker.session_tokens == expected_total_tokens
    assert len(root_tracker.call_history) == num_children * calls_per_child


# -----------------------------------------------------------------------------
# 3. Nested Subagents Hierarchy
# -----------------------------------------------------------------------------

def test_nested_subagents_hierarchy():
    """Grandchild -> child -> parent resolution correctly discovers root."""
    gov = CostGovernor(CostGovernanceConfig())
    root_id = "session-grandparent"
    child_id = "sub-parent"
    grandchild_id = "sub-grandchild"

    gov.register_parent_session(child_id, root_id)
    gov.register_parent_session(grandchild_id, child_id)

    assert gov.get_root_session_id(grandchild_id) == root_id
    assert gov.get_root_session_id(child_id) == root_id
    assert gov.get_root_session_id(root_id) == root_id

    # Grandchild call debits grandparent
    gov.record_call(
        session_id=grandchild_id,
        provider="p",
        model="m",
        tier="cheap",
        usage=TokenUsage(total_tokens=1234),
    )
    assert gov._get_or_create_tracker(root_id).session_tokens == 1234


# -----------------------------------------------------------------------------
# 4. Reservation Deterministic Lifecycle
# -----------------------------------------------------------------------------

def test_reservation_deterministic_lifecycle():
    """Reservations must be reconciled on success and released on exception/cancellation."""
    cfg = CostGovernanceConfig(
        per_turn_cost_budget_inr=Decimal("20.00"),
        per_session_cost_budget_inr=Decimal("50.00"),
    )
    gov = CostGovernor(cfg)
    sid = "res-test-session"

    # Case A: Successful reservation and reconciliation via record_call
    ok, res_id, _ = gov.reserve(sid, estimated_cost_inr=Decimal("5.00"), estimated_tokens=1000)
    assert ok and res_id is not None
    assert gov.get_active_reservations_inr(sid) == Decimal("5.00")

    gov.record_call(
        sid, "p", "m", "standard",
        TokenUsage(total_tokens=1000, estimated_cost_usd=0.01),
        reservation_id=res_id,
    )
    # Reservation must be gone
    assert gov.get_active_reservations_inr(sid) == Decimal("0.00")

    # Case B: Context manager auto-release on exception
    try:
        with gov.reservation(sid, estimated_cost_inr=Decimal("8.00"), estimated_tokens=2000) as ctx:
            assert ctx.reserved
            assert gov.get_active_reservations_inr(sid) == Decimal("8.00")
            raise RuntimeError("LLM simulation failure")
    except RuntimeError:
        pass

    # Reservation must have been auto-released without leaking
    assert gov.get_active_reservations_inr(sid) == Decimal("0.00")

    # Case C: Context manager reconciled in-body via record_call
    with gov.reservation(sid, estimated_cost_inr=Decimal("4.00")) as ctx:
        assert ctx.reserved
        gov.record_call(
            sid, "p", "m", "standard",
            TokenUsage(total_tokens=1000, estimated_cost_usd=0.01),
            reservation_id=ctx.reservation_id,
        )
        ctx.reconcile()
    assert gov.get_active_reservations_inr(sid) == Decimal("0.00")


# -----------------------------------------------------------------------------
# 5. Auxiliary LLM Accounting
# -----------------------------------------------------------------------------

def test_auxiliary_llm_accounting():
    """Auxiliary LLM calls (planner, classifier, titling, compaction) must be accounted."""
    gov = CostGovernor(CostGovernanceConfig())
    sid = "aux-test-session"

    class MockResponse:
        def __init__(self, content: str):
            self.content = content
            self.usage_metadata = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}

    # Track classifier call
    gov.track_auxiliary_call(
        session_id=sid,
        provider="custom",
        model="classifier-model",
        messages_or_prompt="task classification prompt",
        response=MockResponse("action: continue"),
        purpose="task_classifier",
    )

    # Track compaction call
    gov.track_auxiliary_call(
        session_id=sid,
        provider="custom",
        model="summarizer-model",
        messages_or_prompt="summarization prompt",
        response=MockResponse("summary result"),
        purpose="compaction_summary",
    )

    tracker = gov._get_or_create_tracker(sid)
    assert len(tracker.call_history) == 2
    purposes = [c.purpose for c in tracker.call_history]
    assert "task_classifier" in purposes
    assert "compaction_summary" in purposes
    assert tracker.session_tokens > 0


# -----------------------------------------------------------------------------
# 6. Unknown Pricing Policy (deny, token_limited, explicit_allow)
# -----------------------------------------------------------------------------

def test_unknown_pricing_policy_deny():
    """Policy 'deny' halts unrated model invocations immediately."""
    cfg = CostGovernanceConfig(unknown_pricing_policy="deny")
    gov = CostGovernor(cfg)
    sid = "deny-session"

    gov.record_call(
        sid, "mystery_provider", "mystery_model", "cheap",
        TokenUsage(total_tokens=500, cost_known=False),
    )
    assert gov.is_exhausted(sid)
    assert "unrated_denied" in gov.trip_reason(sid)


def test_unknown_pricing_policy_token_limited():
    """Policy 'token_limited' caps unrated calls and tokens strictly."""
    cfg = CostGovernanceConfig(
        unknown_pricing_policy="token_limited",
        max_unrated_calls_per_turn=3,
        max_unrated_tokens_per_turn=10_000,
    )
    gov = CostGovernor(cfg)
    sid = "unrated-session"

    # Call 1 & 2: within limits
    for _ in range(2):
        gov.record_call(
            sid, "prov", "unrated", "standard",
            TokenUsage(total_tokens=2000, cost_known=False),
        )
        assert not gov.is_exhausted(sid)

    # Call 3: hits max_unrated_calls_per_turn (3)
    gov.record_call(
        sid, "prov", "unrated", "standard",
        TokenUsage(total_tokens=2000, cost_known=False),
    )
    assert gov.is_exhausted(sid)
    assert "unrated_limits" in gov.trip_reason(sid)


def test_unknown_pricing_policy_explicit_allow():
    """Policy 'explicit_allow' allows unrated calls to continue."""
    cfg = CostGovernanceConfig(unknown_pricing_policy="explicit_allow")
    gov = CostGovernor(cfg)
    sid = "allow-session"

    for _ in range(10):
        gov.record_call(
            sid, "prov", "unrated", "standard",
            TokenUsage(total_tokens=1000, cost_known=False),
        )
    # Does not trip unrated limits
    assert not gov.is_exhausted(sid)


# -----------------------------------------------------------------------------
# 7. Currency Conversion Consistency & Double-Fee Avoidance
# -----------------------------------------------------------------------------

def test_currency_conversion_canonical_formula():
    """Verify canonical conversion formula USD -> INR with forex spread and gateway fee."""
    gov = CostGovernor(CostGovernanceConfig(usd_to_inr_rate=Decimal("86.0")))

    # Expected: 1.00 USD * 86.0 * 1.005 * 1.07 = 92.48010 INR
    inr = gov.usd_to_inr(Decimal("1.00"), apply_forex_fees=True)
    expected = (Decimal("1.00") * Decimal("86.0") * Decimal("1.005") * Decimal("1.07")).quantize(Decimal("0.000001"))
    assert inr == expected
    assert inr == Decimal("92.480100")

    # When fees already applied (apply_forex_fees=False), no double fee
    inr_no_fees = gov.usd_to_inr(Decimal("1.00"), apply_forex_fees=False)
    assert inr_no_fees == Decimal("86.000000")


# -----------------------------------------------------------------------------
# 8. Pricing Cache Freshness
# -----------------------------------------------------------------------------

def test_pricing_cache_freshness(tmp_path):
    """Verify pricing_status returns fresh, stale, and unavailable accurately."""
    test_dir = str(tmp_path)

    # Case 1: No cache exists -> unavailable
    status, age = pricing.pricing_status(directory=test_dir)
    assert status == "unavailable"
    assert age is None

    # Case 2: Fresh cache
    pricing.save_cache({"model-x": {"input_per_1m": 1.0, "currency": "USD"}}, "test_prov", directory=test_dir)
    status, age = pricing.pricing_status(directory=test_dir)
    assert status == "fresh"
    assert age is not None and age < 60

    # Case 3: Stale cache (mock mtime back by 48 hours)
    cache_f = pricing.cache_path(test_dir)
    old_time = time.time() - (48 * 3600)
    os.utime(cache_f, (old_time, old_time))

    status, age = pricing.pricing_status(directory=test_dir)
    assert status == "stale"
    assert age is not None and age >= (48 * 3600 - 5)

    # load_cached_rates_with_status reports stale status honestly
    rates, cache_status = pricing.load_cached_rates_with_status(directory=test_dir)
    assert "model-x" in rates
    assert cache_status == "stale"


# -----------------------------------------------------------------------------
# 9. Configuration Hygiene
# -----------------------------------------------------------------------------

def test_configuration_hygiene():
    """Verify settings.py supplies centralized governance limits."""
    from src.config import settings

    assert hasattr(settings, "CRUSORAI_MAX_PREMIUM_CALLS_PER_TURN")
    assert hasattr(settings, "CRUSORAI_MAX_PREMIUM_CALLS_PER_SESSION")
    assert hasattr(settings, "CRUSORAI_UNKNOWN_PRICING_POLICY")
    assert hasattr(settings, "CRUSORAI_MAX_UNRATED_CALLS_PER_TURN")
    assert hasattr(settings, "CRUSORAI_MAX_UNRATED_CALLS_PER_SESSION")

    # CostGovernor default config picks up settings values
    cfg = CostGovernanceConfig()
    assert cfg.max_premium_calls_per_turn == settings.CRUSORAI_MAX_PREMIUM_CALLS_PER_TURN
    assert cfg.max_premium_calls_per_session == settings.CRUSORAI_MAX_PREMIUM_CALLS_PER_SESSION
    assert cfg.unknown_pricing_policy == settings.CRUSORAI_UNKNOWN_PRICING_POLICY

"""
test_agent_financial_stress.py -- Crusor Phase 9.1.3 Adversarial Financial Stress Testing.

Stress-tests:
1. Concurrent Subagents Stress (10, 20 children, nested trees, race conditions, overspend bounds)
2. Reservation Stress & Zero Leakage (429, 500, timeouts, cancellation, retry backoff, partial reconciliation)
3. Auxiliary LLM Accounting & Boundaries (classifier, planner, compaction, titling, summarizer)
4. Unknown Pricing Attacks & Discipline (deny, token_limited, explicit_allow, malformed metadata)
5. Multi-Turn & Persistence Analysis (turn transitions, concurrency, application restart persistence)
"""

from __future__ import annotations

import concurrent.futures
from decimal import Decimal
import os
import threading
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


# =============================================================================
# 1. CONCURRENT SUBAGENT STRESS TESTING
# =============================================================================

class TestConcurrentSubagentsStress:
    """Stress tests concurrent subagent workloads against root budget."""

    def test_concurrent_10_children_debit_root_budget_atomically(self):
        """10 concurrent children making simultaneous calls debit the root budget atomically."""
        cfg = CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("500.00"),
            per_session_token_budget=500_000,
            usd_to_inr_rate=Decimal("86.0"),
        )
        gov = CostGovernor(cfg)
        root_id = "root-session-10-workers"
        num_children = 10
        calls_per_child = 15

        child_ids = [f"sub-child-10-{i}" for i in range(num_children)]
        for cid in child_ids:
            gov.register_parent_session(cid, root_id)

        def worker_task(cid: str):
            for _ in range(calls_per_child):
                # 1000 tokens, $0.001 USD
                gov.record_call(
                    session_id=cid,
                    provider="custom",
                    model="qwen/qwen3.7-flash",
                    tier="cheap",
                    usage=TokenUsage(total_tokens=1000, estimated_cost_usd=0.001, cost_known=True),
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_children) as executor:
            futures = [executor.submit(worker_task, cid) for cid in child_ids]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        root_tracker = gov._get_or_create_tracker(root_id)
        expected_total_tokens = num_children * calls_per_child * 1000
        assert root_tracker.session_tokens == expected_total_tokens
        assert len(root_tracker.call_history) == num_children * calls_per_child
        # Total cost check: 150 calls * 0.001 USD * 92.48010 = 13.872015 INR
        expected_cost_inr = Decimal(str(num_children * calls_per_child)) * gov.usd_to_inr(Decimal("0.001"))
        assert root_tracker.session_cost_inr == expected_cost_inr

    def test_concurrent_20_children_high_contention(self):
        """20 concurrent children bombarding the governor simultaneously."""
        cfg = CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("1000.00"),
            per_session_token_budget=1_000_000,
        )
        gov = CostGovernor(cfg)
        root_id = "root-session-20-workers"
        num_children = 20
        calls_per_child = 20

        child_ids = [f"sub-child-20-{i}" for i in range(num_children)]
        for cid in child_ids:
            gov.register_parent_session(cid, root_id)

        def worker_task(cid: str):
            for _ in range(calls_per_child):
                gov.record_call(
                    session_id=cid,
                    provider="custom",
                    model="qwen/qwen3.7-flash",
                    tier="cheap",
                    usage=TokenUsage(total_tokens=500, estimated_cost_usd=0.0005, cost_known=True),
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_children) as executor:
            futures = [executor.submit(worker_task, cid) for cid in child_ids]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        root_tracker = gov._get_or_create_tracker(root_id)
        assert root_tracker.session_tokens == num_children * calls_per_child * 500
        assert len(root_tracker.call_history) == num_children * calls_per_child

    def test_overbooking_prevention_two_agents_cannot_reserve_same_balance(self):
        """Two concurrent agents competing for remaining balance cannot double-reserve."""
        cfg = CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("20.00"),
            reserve_budget_inr=Decimal("5.00"),
        )
        gov = CostGovernor(cfg)
        root_id = "root-overbooking"
        c1 = "sub-agent-1"
        c2 = "sub-agent-2"
        gov.register_parent_session(c1, root_id)
        gov.register_parent_session(c2, root_id)

        # Available headroom: 20.00 - 5.00 (reserve) = 15.00 INR
        # Both agents concurrently attempt to reserve 10.00 INR (total 20.00 > 15.00 headroom)
        results = []
        barrier = threading.Barrier(2)

        def try_reserve(cid: str):
            barrier.wait()
            ok, rid, reason = gov.reserve(cid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=1000)
            results.append((ok, rid, reason))

        t1 = threading.Thread(target=try_reserve, args=(c1,))
        t2 = threading.Thread(target=try_reserve, args=(c2,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        successes = [r for r in results if r[0] is True]
        failures = [r for r in results if r[0] is False]

        # Exactly ONE agent succeeded, and ONE was denied
        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
        assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
        assert "Insufficient root session monetary budget" in failures[0][2]

    def test_concurrent_subagents_race_condition_overspend_measurement(self):
        """
        Adversarial race-condition stress: 50 concurrent child agents attempting
        to spend past the budget simultaneously. Measures maximum observed overspend.
        """
        cap = Decimal("50.00")
        reserve_headroom = Decimal("5.00")
        cfg = CostGovernanceConfig(
            per_session_cost_budget_inr=cap,
            reserve_budget_inr=reserve_headroom,
        )
        gov = CostGovernor(cfg)
        root_id = "root-race-overspend"
        num_threads = 50
        cost_per_call = Decimal("5.00")  # If all 50 succeeded, spend would be 250.00 INR (5x budget)

        child_ids = [f"sub-race-{i}" for i in range(num_threads)]
        for cid in child_ids:
            gov.register_parent_session(cid, root_id)

        barrier = threading.Barrier(num_threads)
        admitted = []

        def race_worker(cid: str):
            barrier.wait()
            ok, rid, reason = gov.reserve(cid, estimated_cost_inr=cost_per_call, estimated_tokens=1000)
            if ok:
                admitted.append(cid)
                # Reconcile with actual spend
                gov.record_call(
                    session_id=cid,
                    provider="p",
                    model="m",
                    tier="standard",
                    usage=TokenUsage(total_tokens=1000, estimated_cost_usd=0.0540656, cost_known=True), # ~5.00 INR
                    reservation_id=rid,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(race_worker, cid) for cid in child_ids]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        root_tracker = gov._get_or_create_tracker(root_id)
        final_spend = root_tracker.session_cost_inr
        active_reservations = root_tracker.total_reserved_inr()
        total_committed = final_spend + active_reservations

        # Calculate overspend: total_committed - cap
        overspend = max(Decimal("0.00"), total_committed - cap)

        # In a sound financial governor, maximum observed overspend must be strictly ZERO.
        assert overspend == Decimal("0.00"), f"Financial leak! Overspend observed: ₹{overspend}"
        # Admitted calls must be at most (cap - reserve_headroom) // cost_per_call = (50 - 5) // 5 = 9
        assert len(admitted) <= 9, f"Too many calls admitted: {len(admitted)}"

    def test_failed_child_agents_release_unused_reservations(self):
        """Children that crash or encounter exceptions release their reservations."""
        cfg = CostGovernanceConfig(per_session_cost_budget_inr=Decimal("50.00"))
        gov = CostGovernor(cfg)
        root_id = "root-fail-cleanup"
        num_failing_children = 5

        for i in range(num_failing_children):
            cid = f"sub-fail-{i}"
            gov.register_parent_session(cid, root_id)
            try:
                with gov.reservation_context(cid, estimated_cost_inr=Decimal("8.00")):
                    raise RuntimeError("Crash inside child task")
            except RuntimeError:
                pass

        # All reservations must be completely released
        root_tracker = gov._get_or_create_tracker(root_id)
        assert root_tracker.total_reserved_inr() == Decimal("0.00")
        assert len(root_tracker.reservations) == 0

    def test_child_completion_does_not_reset_parent_spending(self):
        """When a child finishes, its spend remains durable on the parent."""
        gov = CostGovernor(CostGovernanceConfig())
        root_id = "root-durable"
        child_id = "sub-ephemeral"
        gov.register_parent_session(child_id, root_id)

        gov.record_call(
            child_id, "p", "m", "standard",
            TokenUsage(total_tokens=5000, estimated_cost_usd=0.05, cost_known=True),
        )
        assert gov._get_or_create_tracker(root_id).session_tokens == 5000

        # Reset or discard child session tracker
        gov.reset_session(child_id)
        # Parent session tracker must NOT be reset!
        assert gov._get_or_create_tracker(root_id).session_tokens == 5000
        assert gov._get_or_create_tracker(root_id).session_cost_inr > Decimal("0")


# =============================================================================
# 2. RESERVATION STRESS TESTING & ZERO LEAKAGE
# =============================================================================

class TestReservationStressAndZeroLeakage:
    """Stress tests reservation lifecycle under network, provider, and abort failures."""

    def test_http_429_rate_limit_auto_release(self):
        """HTTP 429 rate limit exception releases reservation."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "res-http-429"

        try:
            with gov.reservation_context(sid, estimated_cost_inr=Decimal("6.00")) as ctx:
                assert ctx.ok
                raise Exception("HTTP 429 Too Many Requests: Rate limit exceeded")
        except Exception:
            pass

        tracker = gov._get_or_create_tracker(sid)
        assert tracker.total_reserved_inr() == Decimal("0.00")

    def test_http_500_internal_error_auto_release(self):
        """HTTP 500 provider internal error releases reservation."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "res-http-500"

        try:
            with gov.reservation_context(sid, estimated_cost_inr=Decimal("7.50")) as ctx:
                raise Exception("HTTP 500 Internal Server Error")
        except Exception:
            pass

        tracker = gov._get_or_create_tracker(sid)
        assert tracker.total_reserved_inr() == Decimal("0.00")

    def test_network_timeout_auto_release(self):
        """Network timeout releases reservation."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "res-timeout"

        try:
            with gov.reservation_context(sid, estimated_cost_inr=Decimal("5.00")) as ctx:
                raise TimeoutError("Read timed out after 30.0s")
        except TimeoutError:
            pass

        tracker = gov._get_or_create_tracker(sid)
        assert tracker.total_reserved_inr() == Decimal("0.00")

    def test_user_cancellation_auto_release(self):
        """User cancellation during request releases reservation without leaking."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "res-cancel"

        try:
            with gov.reservation_context(sid, estimated_cost_inr=Decimal("12.00")) as ctx:
                from src.graphs.turn_controls import TurnCancelledError
                raise TurnCancelledError("Operation cancelled by the user.")
        except Exception:
            pass

        tracker = gov._get_or_create_tracker(sid)
        assert tracker.total_reserved_inr() == Decimal("0.00")

    def test_retry_after_failure_maintains_consistent_reservations(self):
        """First attempt fails and releases; second attempt succeeds and reconciles."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "res-retry-seq"

        # Attempt 1 fails
        try:
            with gov.reservation_context(sid, estimated_cost_inr=Decimal("5.00")) as ctx:
                raise ConnectionResetError("Connection lost")
        except ConnectionResetError:
            pass

        tracker = gov._get_or_create_tracker(sid)
        assert tracker.total_reserved_inr() == Decimal("0.00")

        # Attempt 2 succeeds
        with gov.reservation_context(sid, estimated_cost_inr=Decimal("5.00")) as ctx:
            gov.record_call(
                sid, "prov", "model", "standard",
                TokenUsage(total_tokens=2500, estimated_cost_usd=0.02, cost_known=True),
                reservation_id=ctx.reservation_id,
            )
            ctx.mark_reconciled()

        assert tracker.total_reserved_inr() == Decimal("0.00")
        assert tracker.session_tokens == 2500

    def test_reconciliation_after_partial_usage(self):
        """Reconciliation with lower-than-estimated usage releases full reservation."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "res-partial-usage"

        tracker = gov._get_or_create_tracker(sid)
        # Estimate was 10.00 INR and 5000 tokens
        with gov.reservation_context(sid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=5000) as ctx:
            assert tracker.total_reserved_inr() == Decimal("10.00")
            # Actual usage was only 500 tokens ($0.002 = ~₹0.18 INR)
            gov.record_call(
                sid, "prov", "model", "cheap",
                TokenUsage(total_tokens=500, estimated_cost_usd=0.002, cost_known=True),
                reservation_id=ctx.reservation_id,
            )
            ctx.mark_reconciled()

        # Reservation is completely cleared; tracker recorded actual usage
        assert tracker.total_reserved_inr() == Decimal("0.00")
        assert tracker.session_tokens == 500


# =============================================================================
# 3. AUXILIARY LLM STRESS TESTING
# =============================================================================

class TestAuxiliaryLLMStress:
    """Stress tests auxiliary LLM invocation pathways for exact accounting and non-bypass."""

    def test_all_auxiliary_invocation_points_are_accounted_exactly_once(self):
        """Verify task classification, plan revision, compaction, and session titling accounting."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "session-aux-audit"

        class DummyMsg:
            def __init__(self, content): self.content = content

        # 1. Task classification
        gov.track_auxiliary_call(
            sid, "aux_prov", "classifier-m",
            messages_or_prompt="task classification input",
            response=DummyMsg("action: continue"),
            purpose="task_classifier",
        )

        # 2. Plan revision
        gov.track_auxiliary_call(
            sid, "aux_prov", "planner-m",
            messages_or_prompt="plan revision prompt",
            response=DummyMsg("revised plan step"),
            purpose="planner",
        )

        # 3. Context compaction digest
        gov.track_auxiliary_call(
            sid, "aux_prov", "digest-m",
            messages_or_prompt="segment digest",
            response=DummyMsg("digest summary text"),
            purpose="compaction_digest",
        )

        # 4. Context compaction summary
        gov.track_auxiliary_call(
            sid, "aux_prov", "compactor-m",
            messages_or_prompt="compaction summary",
            response=DummyMsg("compacted turns"),
            purpose="compaction_summary",
        )

        # 5. Session titling
        gov.track_auxiliary_call(
            sid, "aux_prov", "titling-m",
            messages_or_prompt="titling prompt",
            response=DummyMsg("Fix financial stress"),
            purpose="session_titling",
        )

        # 6. Tool result summarization
        gov.track_auxiliary_call(
            sid, "aux_prov", "tool-summarizer-m",
            messages_or_prompt="huge stdout to summarize",
            response=DummyMsg("brief error observation"),
            purpose="tool_summarizer",
        )

        tracker = gov._get_or_create_tracker(sid)
        assert len(tracker.call_history) == 6
        purposes = [c.purpose for c in tracker.call_history]
        assert purposes == [
            "task_classifier",
            "planner",
            "compaction_digest",
            "compaction_summary",
            "session_titling",
            "tool_summarizer",
        ]
        assert tracker.session_tokens > 0

    def test_auxiliary_calls_respect_session_limits(self):
        """Auxiliary calls trip exhaustion if session token cap is breached."""
        cfg = CostGovernanceConfig(per_session_token_budget=1000)
        gov = CostGovernor(cfg)
        sid = "aux-limit-test"

        class HeavyResponse:
            def __init__(self):
                self.content = "long summary " * 500

        gov.track_auxiliary_call(
            sid, "aux_prov", "heavy-m",
            messages_or_prompt="very long input history " * 500,
            response=HeavyResponse(),
            purpose="compaction_summary",
        )

        assert gov.is_exhausted(sid)
        assert "tripped: session_tokens" in gov.trip_reason(sid)

    def test_failed_auxiliary_calls_handled_safely(self):
        """Malformed response objects in auxiliary calls never crash execution."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "aux-safe-test"

        # Pass invalid response object
        gov.track_auxiliary_call(
            sid, "aux_prov", "err-m",
            messages_or_prompt=None,
            response=None,
            purpose="failed_call",
        )
        # Should record safely without throwing
        assert len(gov._get_or_create_tracker(sid).call_history) == 1


# =============================================================================
# 4. UNKNOWN PRICING ATTACK SCENARIOS
# =============================================================================

class TestUnknownPricingAttacks:
    """Stress tests unknown / unpriced model policies and unrated ceilings."""

    def test_attack_policy_deny_blocks_unrated_immediately(self):
        """Under policy 'deny', unrated provider calls immediately halt."""
        cfg = CostGovernanceConfig(unknown_pricing_policy="deny")
        gov = CostGovernor(cfg)
        sid = "deny-attack"

        gov.record_call(
            sid, "unknown_cloud_llm", "secret-v1", "cheap",
            TokenUsage(total_tokens=100, cost_known=False),
        )

        assert gov.is_exhausted(sid)
        assert "unrated_denied" in gov.trip_reason(sid)

    def test_attack_policy_token_limited_caps_calls_and_tokens(self):
        """Under policy 'token_limited', unrated models cannot run infinitely."""
        cfg = CostGovernanceConfig(
            unknown_pricing_policy="token_limited",
            max_unrated_calls_per_turn=4,
            max_unrated_tokens_per_turn=5000,
        )
        gov = CostGovernor(cfg)
        sid = "token-limited-attack"

        # 4 calls of 1000 tokens (4000 tokens <= 5000 cap, 4 calls == 4 cap)
        for _ in range(4):
            gov.record_call(
                sid, "local_ollama", "mistral-local", "standard",
                TokenUsage(total_tokens=1000, cost_known=False),
            )

        assert gov.is_exhausted(sid)
        assert "unrated_limits" in gov.trip_reason(sid)

    def test_unknown_costs_never_become_zero(self):
        """Unknown spend flag is set so unknown spend is never masked as ₹0."""
        gov = CostGovernor(CostGovernanceConfig())
        sid = "unrated-flag-check"

        gov.record_call(
            sid, "unknown_prov", "m", "standard",
            TokenUsage(total_tokens=2500, cost_known=False),
        )

        tracker = gov._get_or_create_tracker(sid)
        assert tracker.session_has_unknown_spend is True
        assert tracker.turn_has_unknown_spend is True
        summary = gov.get_compact_summary(sid)
        assert "₹unknown" in summary or "(+1 unrated)" in summary


# =============================================================================
# 5. MULTI-TURN & PERSISTENCE ANALYSIS
# =============================================================================

class TestMultiTurnAndPersistenceAnalysis:
    """Stress tests multi-turn lifecycles, final response reservations, and persistence."""

    def test_multi_turn_budget_accumulation(self):
        """Turn budget resets on next_turn but session spend accumulates monotonically."""
        cfg = CostGovernanceConfig(
            per_turn_cost_budget_inr=Decimal("15.00"),
            per_session_cost_budget_inr=Decimal("40.00"),
        )
        gov = CostGovernor(cfg)
        sid = "multi-turn-session"

        # Turn 1: Spend ~₹10.00
        gov.record_call(
            sid, "p", "m", "standard",
            TokenUsage(total_tokens=2000, estimated_cost_usd=0.10, cost_known=True),
        )
        assert not gov.is_exhausted(sid)

        # Turn 2: Advance turn
        gov.start_turn(sid)
        tracker = gov._get_or_create_tracker(sid)
        assert tracker.current_turn_id == 2
        assert tracker.turn_cost_inr == Decimal("0.000000")
        assert tracker.session_cost_inr > Decimal("9.00")

        # Turn 2: Spend ~₹10.00 more
        gov.record_call(
            sid, "p", "m", "standard",
            TokenUsage(total_tokens=2000, estimated_cost_usd=0.10, cost_known=True),
        )
        assert not gov.is_exhausted(sid)

        # Turn 3: Advance turn and spend ~₹25.00 more (session total ~₹45.00 > ₹40.00 session cap)
        gov.start_turn(sid)
        gov.record_call(
            sid, "p", "m", "standard",
            TokenUsage(total_tokens=5000, estimated_cost_usd=0.25, cost_known=True),
        )
        assert gov.is_exhausted(sid)
        assert "tripped: session_cost" in gov.trip_reason(sid)

    def test_final_response_can_be_reserved_even_at_headroom_boundary(self):
        """Final response purpose is granted reservation when general calls are denied."""
        cfg = CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("20.00"),
            reserve_budget_inr=Decimal("5.00"),  # Headroom reserve
        )
        gov = CostGovernor(cfg)
        sid = "final-reserve-test"

        # Record spend of ~13.87 INR
        gov.record_call(
            sid, "p", "m", "standard",
            TokenUsage(total_tokens=1000, estimated_cost_usd=0.15, cost_known=True),
        )
        # Remaining is ~6.13 INR.
        # General work call of 3.00 INR would leave ~3.13 < 5.00 headroom:
        ok_work, _, reason_work = gov.reserve(sid, estimated_cost_inr=Decimal("3.00"), purpose="work")
        assert not ok_work
        assert "Insufficient root session monetary budget" in reason_work

        # BUT final_response call with 3.00 INR bypasses the 5.00 headroom requirement:
        ok_final, rid_final, _ = gov.reserve(sid, estimated_cost_inr=Decimal("3.00"), purpose="final_response")
        assert ok_final
        assert rid_final is not None

    def test_persistence_investigation_in_memory_only(self):
        """
        ARCHITECTURAL FINDING: CostGovernor is strictly in-memory.
        Simulating process restart demonstrates that in-memory spend trackers
        do not survive process restart unless persisted to disk/DB.
        """
        cfg = CostGovernanceConfig()
        gov_instance_1 = CostGovernor(cfg)
        sid = "persistent-session-candidate"

        gov_instance_1.record_call(
            sid, "p", "m", "standard",
            TokenUsage(total_tokens=50_000, estimated_cost_usd=1.00, cost_known=True),
        )
        assert gov_instance_1._get_or_create_tracker(sid).session_tokens == 50_000

        # Simulate fresh process restart by initializing a new CostGovernor instance
        gov_instance_2 = CostGovernor(cfg)
        tracker_after_restart = gov_instance_2._get_or_create_tracker(sid)

        # Verification: In-memory tracker resets to 0 upon process restart
        assert tracker_after_restart.session_tokens == 0
        assert tracker_after_restart.session_cost_inr == Decimal("0.000000")

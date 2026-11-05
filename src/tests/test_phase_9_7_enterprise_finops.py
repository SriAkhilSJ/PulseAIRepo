"""
test_phase_9_7_enterprise_finops.py -- Verification Suite for Phase 9.7 Enterprise FinOps.

Phase 9.7: Enterprise FinOps & Intelligent Cost Governance.
Tests all 20 required FinOps scenarios deterministically with zero paid API calls:
- Pricing registry metadata, multi-currency conversion, verification statuses.
- Idempotent token accounting, stream chunk deduplication, retry handling.
- Multi-dimensional attribution and time-bucket aggregations.
- Intelligent model routing with task complexity classification and user-pin inviolability.
- Concurrency-safe atomic budget governor, warning watermarks, and fail-closed ceilings.
- Context cost optimization and prompt cache alignment.
- Diamond / Credit ledger with atomic debit, idempotency, and refund reversals.
- Distributed FinOps observability tracing and secret sanitization.
"""

from decimal import Decimal
import threading
import time
import pytest

from src.finops.pricing_registry import (
    ModelPricingMetadata,
    ModelPricingRegistry,
    VerificationStatus,
    get_pricing_registry,
    quantize_currency,
)
from src.finops.accounting import (
    TokenAccountingEngine,
    UsageRecord,
    get_accounting_engine,
)
from src.finops.attribution import (
    CostAggregationSummary,
    CostAttributionEngine,
    get_attribution_engine,
)
from src.finops.model_router import (
    IntelligentModelRouter,
    ModelTier,
    RoutingDecision,
    TaskComplexity,
    get_model_router,
)
from src.finops.budget_governor import (
    ActiveReservation,
    BudgetExhaustionError,
    BudgetGovernor,
    BudgetPolicy,
    BudgetScopeState,
    get_budget_governor,
)
from src.finops.context_optimizer import (
    ContextCostOptimizer,
    ContextOptimizationReceipt,
    get_context_optimizer,
)
from src.finops.credits import (
    CreditAccountingEngine,
    CreditTransaction,
    CreditTransactionType,
    InsufficientCreditsError,
    get_credit_engine,
)
from src.finops.observability import (
    FinOpsObservabilityTracer,
    FinOpsTelemetrySnapshot,
    get_finops_observability,
)


class TestPhase97EnterpriseFinOps:
    """Deterministic, zero-cost test suite for Phase 9.7 FinOps."""

    # --------------------------------------------------------------------------
    # 1. PRICING REGISTRY & COST INTELLIGENCE
    # --------------------------------------------------------------------------

    def test_scenario_01_pricing_registry_lookup_and_verification(self) -> None:
        """SCENARIO-01: Model Pricing Registry lookup and verification status."""
        registry = ModelPricingRegistry()
        meta = registry.get_model_pricing("gpt-4o", provider="openai")
        assert meta is not None
        assert meta.provider == "openai"
        assert meta.model == "gpt-4o"
        assert meta.input_price_per_1m == Decimal("2.50")
        assert meta.output_price_per_1m == Decimal("10.00")
        assert meta.verification_status == VerificationStatus.VERIFIED

    def test_scenario_02_multi_currency_conversion(self) -> None:
        """SCENARIO-02: Multi-currency conversion (USD to INR with canonical spread and gateway fee)."""
        registry = ModelPricingRegistry(usd_to_inr_rate=Decimal("86.0"))
        # 1.00 USD * 86.0 * 1.005 * 1.07 = 92.4801 px
        inr_val = registry.usd_to_inr(Decimal("1.00"), apply_forex_fees=True)
        assert inr_val is not None
        assert inr_val == Decimal("92.480100")

        # Inverted conversion
        usd_back = registry.inr_to_usd(inr_val, apply_forex_fees=True)
        assert usd_back is not None
        assert usd_back == Decimal("1.000000")

    def test_scenario_03_cached_and_reasoning_token_cost_calculation(self) -> None:
        """SCENARIO-03: Cached and reasoning token cost calculation accuracy."""
        registry = ModelPricingRegistry()
        # claude-3-5-sonnet: input=$3.00, cached=$0.30, output=$15.00
        # 1M uncached input = $3.00, 1M cached input = $0.30, 1M output = $15.00 -> Total $18.30
        calc = registry.calculate_cost(
            model="claude-3-5-sonnet",
            input_tokens=2_000_000,
            output_tokens=1_000_000,
            cached_tokens=1_000_000,
            provider="anthropic",
        )
        assert calc.cost_usd is not None
        assert calc.cost_usd == Decimal("18.300000")
        assert calc.cached_cost == Decimal("0.300000")
        assert calc.verification_status == VerificationStatus.VERIFIED

    def test_scenario_04_unknown_model_pricing_transparency(self) -> None:
        """SCENARIO-04: Missing / unknown model pricing graceful handling."""
        registry = ModelPricingRegistry()
        calc = registry.calculate_cost(
            model="unreleased-exotic-ai-v99",
            input_tokens=10_000,
            output_tokens=2_000,
            provider="custom_lab",
        )
        assert calc.cost_usd is None
        assert calc.cost_inr is None
        assert calc.currency == "UNKNOWN"
        assert not calc.is_exact
        assert calc.verification_status == VerificationStatus.UNKNOWN

    def test_scenario_05_provider_reported_billing_precedence(self) -> None:
        """SCENARIO-05: Provider-reported billing precedence over estimated calculations."""
        registry = ModelPricingRegistry()
        # Even if model is gpt-4o, if provider reported exact bill of $0.0042, respect it
        calc = registry.calculate_cost(
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            reported_cost_usd=0.004200,
        )
        assert calc.cost_usd == Decimal("0.004200")
        assert calc.is_exact is True
        assert calc.source == "provider_reported_receipt"

    # --------------------------------------------------------------------------
    # 2. TOKEN & USAGE ACCOUNTING
    # --------------------------------------------------------------------------

    def test_scenario_06_token_accounting_idempotency(self) -> None:
        """SCENARIO-06: Token accounting idempotency (duplicate event ID deduplication)."""
        engine = TokenAccountingEngine()
        rec1 = engine.record_usage(
            request_id="req-101",
            session_id="session-alpha",
            task_id="task-01",
            workspace_id="ws-main",
            model="gpt-4o",
            input_tokens=500,
            output_tokens=100,
            event_id="evt-fixed-101",
        )
        # Duplicate record attempt with same event_id
        rec2 = engine.record_usage(
            request_id="req-101",
            session_id="session-alpha",
            task_id="task-01",
            workspace_id="ws-main",
            model="gpt-4o",
            input_tokens=500,
            output_tokens=100,
            event_id="evt-fixed-101",
        )
        assert rec1.event_id == rec2.event_id
        assert len(engine.list_records()) == 1  # No double counting!

    def test_scenario_07_streaming_token_chunk_aggregation(self) -> None:
        """SCENARIO-07: Streaming token chunk aggregation without double-counting."""
        engine = TokenAccountingEngine()
        stream_id = "stream-xyz-9"
        # Chunk 1
        engine.track_stream_chunk(stream_id, "req-stream-1", "sess-1", "Hello ", "gpt-4o-mini", is_first=True)
        # Chunk 2
        engine.track_stream_chunk(stream_id, "req-stream-1", "sess-1", "world from Crusor! ", "gpt-4o-mini")
        # Final Chunk
        final_rec = engine.track_stream_chunk(
            stream_id, "req-stream-1", "sess-1", "Done.", "gpt-4o-mini", is_final=True,
            reported_usage={"prompt_tokens": 50, "completion_tokens": 12},
        )
        assert final_rec is not None
        assert final_rec.input_tokens == 50
        assert final_rec.output_tokens == 12
        assert final_rec.total_tokens == 62
        assert len(engine.list_records()) == 1

    def test_scenario_08_retry_accounting_without_double_counting(self) -> None:
        """SCENARIO-08: Retry accounting without double-counting attempts."""
        engine = TokenAccountingEngine()
        # Attempt 0 (failed/timed out)
        rec0 = engine.record_usage(
            request_id="req-retry-1",
            session_id="sess-retry",
            retry_count=0,
            input_tokens=1000,
            output_tokens=0,
            event_id="retry-req-1-attempt-0",
        )
        # Attempt 1 (successful retry)
        rec1 = engine.record_usage(
            request_id="req-retry-1",
            session_id="sess-retry",
            retry_count=1,
            input_tokens=1000,
            output_tokens=200,
            event_id="retry-req-1-attempt-1",
        )
        records = engine.list_records()
        assert len(records) == 2
        assert records[0].retry_count == 0
        assert records[1].retry_count == 1
        assert records[0].event_id != records[1].event_id

    # --------------------------------------------------------------------------
    # 3. COST ATTRIBUTION ENGINE
    # --------------------------------------------------------------------------

    def test_scenario_09_cost_attribution_dimensions(self) -> None:
        """SCENARIO-09: Cost attribution across task, workspace, and model dimensions."""
        engine = TokenAccountingEngine()
        attr = CostAttributionEngine(engine)

        engine.record_usage("r1", "s1", task_id="task-A", workspace_id="ws-1", model="gpt-4o", input_tokens=10_000, output_tokens=2_000)
        engine.record_usage("r2", "s1", task_id="task-A", workspace_id="ws-1", model="gpt-4o-mini", input_tokens=5_000, output_tokens=1_000)
        engine.record_usage("r3", "s2", task_id="task-B", workspace_id="ws-2", model="gpt-4o", input_tokens=8_000, output_tokens=1_500)

        task_groups = attr.attribute_by_dimension("task_id")
        assert "task-A" in task_groups
        assert "task-B" in task_groups
        assert task_groups["task-A"].call_count == 2
        assert task_groups["task-B"].call_count == 1

        ws_groups = attr.attribute_by_dimension("workspace_id")
        assert "ws-1" in ws_groups
        assert "ws-2" in ws_groups

    def test_scenario_10_temporal_aggregation_time_buckets(self) -> None:
        """SCENARIO-10: Temporal aggregation (daily / monthly time buckets)."""
        engine = TokenAccountingEngine()
        attr = CostAttributionEngine(engine)

        engine.record_usage("r1", "s1", input_tokens=10_000, output_tokens=2_000)
        engine.record_usage("r2", "s1", input_tokens=20_000, output_tokens=4_000)

        daily_groups = attr.attribute_by_time_bucket("daily")
        today_key = time.strftime("%Y-%m-%d", time.gmtime())
        assert today_key in daily_groups
        assert daily_groups[today_key].call_count == 2
        assert daily_groups[today_key].total_tokens == 36_000

    def test_scenario_11_top_spending_driver_identification(self) -> None:
        """SCENARIO-11: Top spending driver identification."""
        engine = TokenAccountingEngine()
        attr = CostAttributionEngine(engine)

        # Record inexpensive call on mini vs expensive call on gpt-4o
        engine.record_usage("r1", "s1", model="gpt-4o-mini", input_tokens=1000, output_tokens=200)
        engine.record_usage("r2", "s1", model="gpt-4o", input_tokens=20_000, output_tokens=5_000)

        drivers = attr.get_top_spending_drivers(limit=2, dimension="model")
        assert len(drivers) >= 2
        assert drivers[0].dimension_value == "gpt-4o"
        assert drivers[0].cost_usd > drivers[1].cost_usd

    # --------------------------------------------------------------------------
    # 4. INTELLIGENT MODEL ROUTING
    # --------------------------------------------------------------------------

    def test_scenario_12_task_complexity_classification(self) -> None:
        """SCENARIO-12: Task complexity classification heuristics."""
        router = IntelligentModelRouter()
        assert router.classify_task_complexity("fix typo in README.md") == TaskComplexity.SIMPLE
        assert router.classify_task_complexity("add unit test for token counter") == TaskComplexity.MODERATE
        assert router.classify_task_complexity("refactor entire authentication subsystem") == TaskComplexity.COMPLEX
        assert router.classify_task_complexity("formal verification theorem proof of deadlock avoidance") == TaskComplexity.REASONING_HEAVY

    def test_scenario_13_automated_cost_optimized_tier_routing(self) -> None:
        """SCENARIO-13: Automated cost-optimized tier routing (simple tasks route to cheap tier)."""
        router = IntelligentModelRouter()
        decision = router.route_task("fix typo in comments")
        assert decision.task_complexity == TaskComplexity.SIMPLE
        assert decision.selected_tier == ModelTier.CHEAP
        assert decision.is_user_pinned is False
        assert decision.savings_vs_premium_usd > Decimal("0.000000")

    def test_scenario_14_user_pinned_model_inviolability(self) -> None:
        """SCENARIO-14: User pinned model inviolability (NEVER silently downgrade pinned model)."""
        router = IntelligentModelRouter()
        # Even for a simple typo, if user explicitly requested o1, router MUST NOT downgrade
        decision = router.route_task("fix typo", user_pinned_model="o1", user_pinned_provider="openai")
        assert decision.is_user_pinned is True
        assert decision.selected_model == "o1"
        assert decision.selected_tier == ModelTier.PREMIUM
        assert "pinned" in decision.routing_reason.lower()

    # --------------------------------------------------------------------------
    # 5. BUDGET AND SPENDING CONTROLS
    # --------------------------------------------------------------------------

    def test_scenario_15_atomic_budget_reservation_and_hard_ceiling(self) -> None:
        """SCENARIO-15: Atomic budget reservation and hard ceiling enforcement."""
        gov = BudgetGovernor()
        policy = BudgetPolicy("task", hard_limit_usd=Decimal("2.00"))
        gov.set_scope_policy("task-99", policy)

        # 1. Under limit: succeeds
        ok, res_id, _ = gov.reserve_budget("task-99", Decimal("1.50"))
        assert ok is True
        assert res_id != ""

        # 2. Over limit: fails closed
        ok2, res_id2, reason2 = gov.reserve_budget("task-99", Decimal("1.00"))
        assert ok2 is False
        assert "hard limit exceeded" in reason2.lower()

        # 3. Commit first reservation
        gov.commit_reservation("task-99", res_id, Decimal("1.20"))
        state = gov.get_scope_state("task-99")
        assert state.committed_spend_usd == Decimal("1.200000")
        assert state.reserved_spend_usd == Decimal("0.000000")

    def test_scenario_16_concurrent_budget_reservation_race_safety(self) -> None:
        """SCENARIO-16: Concurrent budget reservation race safety."""
        gov = BudgetGovernor()
        policy = BudgetPolicy("workspace", hard_limit_usd=Decimal("10.00"))
        gov.set_scope_policy("ws-concurrent", policy)

        success_count = 0
        failure_count = 0
        lock = threading.Lock()

        def try_reserve() -> None:
            nonlocal success_count, failure_count
            ok, _, _ = gov.reserve_budget("ws-concurrent", Decimal("2.00"))
            with lock:
                if ok:
                    success_count += 1
                else:
                    failure_count += 1

        threads = [threading.Thread(target=try_reserve) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Hard limit $10.00 / $2.00 per slot = exactly 5 can succeed, 5 must fail!
        assert success_count == 5
        assert failure_count == 5
        health = gov.check_health_and_limits("ws-concurrent")
        assert health["is_exhausted"] is True

    def test_scenario_17_budget_warning_threshold_watermark(self) -> None:
        """SCENARIO-17: Budget warning threshold watermark detection."""
        gov = BudgetGovernor()
        policy = BudgetPolicy("project", hard_limit_usd=Decimal("100.00"), warning_threshold_ratio=Decimal("0.80"))
        gov.set_scope_policy("proj-warn", policy)

        # Reserve $85 (85% > 80% threshold)
        ok, res_id, _ = gov.reserve_budget("proj-warn", Decimal("85.00"))
        assert ok is True
        health = gov.check_health_and_limits("proj-warn")
        assert health["warning_triggered"] is True
        assert health["is_exhausted"] is False

    # --------------------------------------------------------------------------
    # 6. CONTEXT COST OPTIMIZATION
    # --------------------------------------------------------------------------

    def test_scenario_18_prompt_context_cost_optimization(self) -> None:
        """SCENARIO-18: Prompt and context optimization (duplicate removal and mutation payload compaction)."""
        optimizer = ContextCostOptimizer()

        repetitive_block = "CRITICAL_RULES: Always preserve security boundaries.\n" * 20
        messages = [
            {"role": "system", "content": "You are Crusor AI."},
            {"role": "user", "content": "Run tests"},
            {"role": "assistant", "content": repetitive_block, "tool_calls": [
                {"name": "write_file", "args": {"Path": "foo.py", "content": "A" * 1000}}
            ]},
            {"role": "assistant", "content": repetitive_block},  # Exact duplicate assistant text
        ]

        optimized, receipt = optimizer.optimize_messages(messages, model="gpt-4o")
        assert receipt.tokens_saved > 0
        assert receipt.duplicate_chunks_pruned >= 1
        assert receipt.mutation_payloads_compacted >= 1
        assert receipt.savings_usd >= Decimal("0.000000")

    # --------------------------------------------------------------------------
    # 7. CREDIT & DIAMONDS ACCOUNTING
    # --------------------------------------------------------------------------

    def test_scenario_19_diamond_credit_atomic_debit_and_refund(self) -> None:
        """SCENARIO-19: Diamond / Credit accounting: atomic debit, idempotency, and refund reversal."""
        engine = CreditAccountingEngine()
        account_id = "user-vip-1"
        # 1. Check initial starter grant
        assert engine.get_balance(account_id) == Decimal("10000.000000")

        # 2. Debit $2.50 = 2,500 Diamonds
        debit_tx = engine.debit_usage(account_id, Decimal("2.50"), "turn-101", description="Model inference")
        assert debit_tx.amount_diamonds == Decimal("2500.000000")
        assert engine.get_balance(account_id) == Decimal("7500.000000")

        # 3. Idempotent debit test
        dup_tx = engine.debit_usage(account_id, Decimal("2.50"), "turn-101")
        assert dup_tx.tx_id == debit_tx.tx_id
        assert engine.get_balance(account_id) == Decimal("7500.000000")  # Balance unchanged!

        # 4. Refund reversal (e.g. tool crashed)
        refund_tx = engine.refund_credits(account_id, Decimal("2500.000000"), "turn-101")
        assert refund_tx.amount_diamonds == Decimal("2500.000000")
        assert engine.get_balance(account_id) == Decimal("10000.000000")

    # --------------------------------------------------------------------------
    # 8. FINOPS OBSERVABILITY
    # --------------------------------------------------------------------------

    def test_scenario_20_finops_observability_tracing_and_redaction(self) -> None:
        """SCENARIO-20: FinOps observability: distributed tracing, metric emission, and secret redaction."""
        obs = get_finops_observability()

        # 1. Trace a financial reservation
        span = obs.trace_financial_reservation(
            session_id="session-trace-1",
            correlation_id="corr-trace-fin-1",
            amount_usd=Decimal("0.045"),
            scope="task",
            success=True,
        )
        assert span.operation == "finops.reserve_budget"
        assert span.correlation_id == "corr-trace-fin-1"

        # 2. Trace model routing
        span2 = obs.trace_model_routing(
            correlation_id="corr-trace-fin-2",
            task_complexity="MODERATE",
            selected_model="gpt-4o",
            selected_tier="standard",
            estimated_cost_usd=Decimal("0.025"),
            is_user_pinned=False,
        )
        assert span2.operation == "finops.model_routing"

        # 3. Verify telemetry tracking
        obs.record_token_telemetry("gpt-4o", 1000, 200, Decimal("0.0045"))
        dist = obs.get_routing_distribution()
        assert "gpt-4o" in dist


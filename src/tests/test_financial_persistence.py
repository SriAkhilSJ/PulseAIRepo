"""
test_financial_persistence.py -- Test suite for Phase 9.1.4: Persistent Financial Accounting & Session Recovery.

Covers all 17 requirements:
1. Session persistence across simulated application restarts.
2. Token restoration (input, output, cached, total).
3. Cost restoration (USD and INR exact Decimal precision).
4. Unknown-priced usage restoration (flag, unrated calls, unrated tokens).
5. Premium call count restoration (cheap, standard, premium tier counts).
6. Parent-child relationship restoration across restarts.
7. Nested subagent hierarchy restoration across restarts.
8. Duplicate event prevention (idempotent ledger writes, no double debit).
9. Interrupted reservation recovery (in_flight -> uncertain on crash).
10. Crash after provider call (ledger event exists -> reconciled).
11. Concurrent accounting writes under WAL mode.
12. SQLite transaction interruption and rollback.
13. Schema versioning and migration check.
14. Changed budget configuration (tighter budget binds; increased budget does not grant extra money).
15. Persistence failure fail-closed policy.
16. Existing session compatibility (legacy session store co-existence).
17. Performance measurements (hydration latency < 5ms, write latency < 5ms).
"""

import concurrent.futures
from decimal import Decimal
import os
import sqlite3
import tempfile
import time
import pytest

from src.agents.cost_governance import (
    CostGovernor,
    CostGovernanceConfig,
    BudgetReservation,
    SessionSpendTracker,
)
from src.agents.financial_store import FinancialStore, get_financial_store, reset_financial_store
from src.context.token_tracker import TokenUsage


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a dedicated clean temporary SQLite DB file."""
    db_file = tmp_path / "test_financial.db"
    return str(db_file)


@pytest.fixture
def financial_store(temp_db_path):
    """Provide a clean FinancialStore instance."""
    store = FinancialStore(temp_db_path)
    yield store
    store.close()


def test_01_session_persistence_across_restarts(temp_db_path):
    """Requirement 1: Verify token & cost accumulation preserved across simulated application restarts."""
    cfg = CostGovernanceConfig(
        per_session_cost_budget_inr=Decimal("100.00"),
        per_session_token_budget=200_000,
    )
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(cfg, store=store1)
    sid = "session-restart-01"

    # Turn 1
    gov1.record_call(
        session_id=sid,
        provider="openrouter",
        model="anthropic/claude-3.5-sonnet",
        tier="standard",
        usage=TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500, estimated_cost_usd=0.015, cost_known=True),
    )
    gov1.advance_turn(sid)

    # Turn 2
    gov1.record_call(
        session_id=sid,
        provider="custom",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=TokenUsage(prompt_tokens=800, completion_tokens=200, total_tokens=1000, estimated_cost_usd=0.001, cost_known=True),
    )
    t1 = gov1.get_tracker(sid)
    expected_tokens = t1.session_tokens
    expected_cost_usd = t1.session_cost_usd
    expected_cost_inr = t1.session_cost_inr

    # Simulate restart: new store connection and new CostGovernor
    store1.close()
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(cfg, store=store2)

    # Hydrate on access
    t2 = gov2.get_tracker(sid)
    assert t2.session_tokens == expected_tokens == 2500
    assert t2.session_cost_usd == expected_cost_usd
    assert t2.session_cost_inr == expected_cost_inr
    assert t2.current_turn_id == 2
    store2.close()


def test_02_token_restoration(temp_db_path):
    """Requirement 2: Token restoration: input tokens, output tokens, cached tokens, total tokens."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(CostGovernanceConfig(), store=store1)
    sid = "session-tokens-02"

    gov1.record_call(
        session_id=sid,
        provider="anthropic",
        model="claude-3-5-sonnet",
        tier="standard",
        usage=TokenUsage(
            prompt_tokens=4500,
            completion_tokens=1200,
            cached_tokens=800,
            total_tokens=5700,
            estimated_cost_usd=0.02,
            cost_known=True,
        ),
    )

    store1.close()
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(CostGovernanceConfig(), store=store2)

    t = gov2.get_tracker(sid)
    assert t.cumulative_input_tokens == 4500
    assert t.cumulative_output_tokens == 1200
    assert t.session_cached_tokens == 800
    assert t.session_tokens == 5700
    store2.close()


def test_03_cost_restoration_exact_decimal_precision(temp_db_path):
    """Requirement 3: Cost restoration: USD and INR exact Decimal precision across restart."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(CostGovernanceConfig(), store=store1)
    sid = "session-decimals-03"

    exact_usd = Decimal("0.123456")
    gov1.record_call(
        session_id=sid,
        provider="custom",
        model="high-precision-model",
        tier="standard",
        usage=TokenUsage(
            prompt_tokens=1000,
            completion_tokens=1000,
            total_tokens=2000,
            estimated_cost_usd=float(exact_usd),
            cost_known=True,
        ),
    )

    expected_usd = gov1.get_tracker(sid).session_cost_usd
    expected_inr = gov1.get_tracker(sid).session_cost_inr
    assert isinstance(expected_usd, Decimal)
    assert isinstance(expected_inr, Decimal)

    store1.close()
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(CostGovernanceConfig(), store=store2)

    t = gov2.get_tracker(sid)
    assert t.session_cost_usd == expected_usd
    assert t.session_cost_inr == expected_inr
    # Ensure exact string-decimal match with no float representation rounding issues
    assert str(t.session_cost_usd) == str(expected_usd)
    assert str(t.session_cost_inr) == str(expected_inr)
    store2.close()


def test_04_unknown_priced_usage_restoration(temp_db_path):
    """Requirement 4: Unknown-priced usage restoration: flag, unrated calls, unrated tokens."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(CostGovernanceConfig(), store=store1)
    sid = "session-unrated-04"

    # Record unrated call
    gov1.record_call(
        session_id=sid,
        provider="ollama",
        model="custom-local-model",
        tier="cheap",
        usage=TokenUsage(
            prompt_tokens=2000,
            completion_tokens=1000,
            total_tokens=3000,
            cost_known=False,
            estimated_cost_usd=None,
        ),
    )
    t1 = gov1.get_tracker(sid)
    assert t1.session_has_unknown_spend is True
    assert t1.unrated_calls_session == 1
    assert t1.unrated_tokens_session == 3000

    store1.close()
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(CostGovernanceConfig(), store=store2)

    t2 = gov2.get_tracker(sid)
    assert t2.session_has_unknown_spend is True
    assert t2.unrated_calls_session == 1
    assert t2.unrated_tokens_session == 3000
    store2.close()


def test_05_tier_call_counts_restoration(temp_db_path):
    """Requirement 5: Call count restoration across tiers: cheap, standard, premium."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(CostGovernanceConfig(), store=store1)
    sid = "session-tiers-05"

    for _ in range(3):
        gov1.record_call(sid, "p", "m", "cheap", TokenUsage(total_tokens=100, estimated_cost_usd=0.0001, cost_known=True))
    for _ in range(2):
        gov1.record_call(sid, "p", "m", "standard", TokenUsage(total_tokens=200, estimated_cost_usd=0.001, cost_known=True))
    for _ in range(1):
        gov1.record_call(sid, "p", "m", "premium", TokenUsage(total_tokens=500, estimated_cost_usd=0.01, cost_known=True))

    store1.close()
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(CostGovernanceConfig(), store=store2)

    t = gov2.get_tracker(sid)
    assert t.session_calls_cheap == 3
    assert t.session_calls_standard == 2
    assert t.session_calls_premium == 1
    assert t.total_calls_count == 6
    store2.close()


def test_06_parent_child_relationship_restoration(temp_db_path):
    """Requirement 6: Parent-child relationship restoration across restarts."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(CostGovernanceConfig(), store=store1)
    root_id = "root-session-06"
    child_id = "subagent-worker-06"

    gov1.register_parent_session(child_id, root_id)
    assert gov1.get_root_session_id(child_id) == root_id

    # Make a child call
    gov1.record_call(
        session_id=child_id,
        provider="custom",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=TokenUsage(total_tokens=1200, estimated_cost_usd=0.001, cost_known=True),
    )

    store1.close()
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(CostGovernanceConfig(), store=store2)

    # Verify relationship persisted in DB
    assert gov2.get_root_session_id(child_id) == root_id

    # Another call from child should continue debiting root in resumed session
    gov2.record_call(
        session_id=child_id,
        provider="custom",
        model="qwen/qwen3.7-flash",
        tier="cheap",
        usage=TokenUsage(total_tokens=800, estimated_cost_usd=0.001, cost_known=True),
    )

    root_t = gov2.get_tracker(root_id)
    assert root_t.session_tokens == 2000
    store2.close()


def test_07_nested_subagent_hierarchy_restoration(temp_db_path):
    """Requirement 7: Nested subagent hierarchy restoration across restarts."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(CostGovernanceConfig(), store=store1)

    root_id = "root-hier-07"
    child_id = "child-hier-07"
    grandchild_id = "grandchild-hier-07"

    gov1.register_parent_session(child_id, root_id)
    gov1.register_parent_session(grandchild_id, child_id)

    assert gov1.get_root_session_id(grandchild_id) == root_id

    store1.close()
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(CostGovernanceConfig(), store=store2)

    assert gov2.get_root_session_id(grandchild_id) == root_id
    assert gov2.get_root_session_id(child_id) == root_id

    # Grandchild call debits root
    gov2.record_call(
        session_id=grandchild_id,
        provider="custom",
        model="model-g",
        tier="cheap",
        usage=TokenUsage(total_tokens=3300, estimated_cost_usd=0.002, cost_known=True),
    )
    assert gov2.get_tracker(root_id).session_tokens == 3300
    store2.close()


def test_08_duplicate_event_prevention_idempotency(temp_db_path):
    """Requirement 8: Duplicate event prevention: replaying a call event does not increase tokens or cost."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "session-idempotency-08"

    evt_id = "evt_dedup_unique_08"
    usage = TokenUsage(total_tokens=5000, estimated_cost_usd=0.05, cost_known=True)

    # First record call
    rec1 = gov.record_call(
        session_id=sid,
        provider="openai",
        model="gpt-4o",
        tier="standard",
        usage=usage,
        event_id=evt_id,
    )
    t1 = gov.get_tracker(sid)
    assert t1.session_tokens == 5000
    assert t1.session_cost_usd == Decimal("0.050000")

    # Second record call with SAME event_id (simulating network retry replay)
    rec2 = gov.record_call(
        session_id=sid,
        provider="openai",
        model="gpt-4o",
        tier="standard",
        usage=usage,
        event_id=evt_id,
    )
    t2 = gov.get_tracker(sid)
    # Should NOT have increased tokens or cost
    assert t2.session_tokens == 5000
    assert t2.session_cost_usd == Decimal("0.050000")
    assert rec2.call_id == evt_id
    store.close()


def test_09_interrupted_reservation_recovery_marked_uncertain(temp_db_path):
    """Requirement 9: Interrupted reservation recovery: in_flight reservation becomes uncertain on crash."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("50.00"),
            reserve_budget_inr=Decimal("5.00"),
        ),
        store=store1,
    )
    sid = "session-crash-in-flight-09"

    # Reserve and enter in_flight
    ok, rid, _ = gov1.reserve(sid, estimated_cost_inr=Decimal("15.00"), estimated_tokens=10_000)
    assert ok
    store1.update_reservation_status(rid, "in_flight")

    # Simulate crash before provider responds or call records
    store1.close()

    # Restart application
    store2 = FinancialStore(temp_db_path)
    gov2 = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("50.00"),
            reserve_budget_inr=Decimal("5.00"),
        ),
        store=store2,
    )

    tracker = gov2.get_tracker(sid)
    assert rid in tracker.reservations
    res = tracker.reservations[rid]
    assert res.status == "uncertain"
    # Ensure reserved budget is NOT silently freed up to prevent runaway overspending
    assert tracker.total_reserved_inr() == Decimal("15.00")
    store2.close()


def test_10_crash_after_provider_call_reconciled_on_restart(temp_db_path):
    """Requirement 10: Crash after provider call: reservation in_flight with completed ledger event becomes reconciled."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(CostGovernanceConfig(), store=store1)
    sid = "session-crash-after-call-10"

    ok, rid, _ = gov1.reserve(sid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=5_000)
    assert ok
    store1.update_reservation_status(rid, "in_flight")

    # Record completed call event in ledger with the reservation_id
    evt_dict = {
        "event_id": "evt_post_call_crash_10",
        "root_session_id": sid,
        "child_session_id": None,
        "turn_id": 1,
        "provider": "openrouter",
        "model=" : "claude",
        "tier": "standard",
        "purpose": "work",
        "input_tokens": 1000,
        "output_tokens": 500,
        "cached_tokens": 0,
        "total_tokens": 1500,
        "estimated_cost_usd": "0.01",
        "estimated_cost_inr": "0.924801",
        "actual_cost_usd": "0.01",
        "actual_cost_inr": "0.924801",
        "cost_known": True,
        "pricing_status": "fresh",
        "reservation_id": rid,
        "call_outcome": "completed",
        "created_at": time.time(),
    }
    store1.record_call_event(evt_dict)

    # Crash simulated before reservation was explicitly marked reconciled in store
    store1.close()

    # Restart
    store2 = FinancialStore(temp_db_path)
    # The recovery function checks ledger events
    unresolved = store2.recover_interrupted_reservations_on_startup(sid)
    # Since a ledger event exists for this reservation, it transitions to reconciled and is not returned as unresolved
    assert len(unresolved) == 0

    res_row = store2.get_reservation(rid)
    assert res_row is not None
    assert res_row["status"] == "reconciled"
    store2.close()


def test_11_concurrent_accounting_writes_wal_mode(temp_db_path):
    """Requirement 11: Concurrent accounting writes under WAL mode verify database integrity."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("10000.00"),
            per_turn_cost_budget_inr=Decimal("10000.00"),
            per_session_token_budget=10_000_000,
            per_turn_token_budget=10_000_000,
        ),
        store=store,
    )
    root_id = "root-wal-stress-11"
    num_threads = 12
    calls_per_thread = 15

    for i in range(num_threads):
        gov.register_parent_session(f"child-worker-{i}", root_id)

    def worker(worker_idx: int):
        cid = f"child-worker-{worker_idx}"
        for c in range(calls_per_thread):
            ok, rid, reason = gov.reserve(cid, estimated_cost_inr=Decimal("0.10"), estimated_tokens=100)
            assert ok, f"Worker {worker_idx} reserve {c} failed: {reason}"
            gov.record_call(
                session_id=cid,
                provider="custom",
                model="model-fast",
                tier="cheap",
                usage=TokenUsage(total_tokens=100, estimated_cost_usd=0.0001, cost_known=True),
                reservation_id=rid,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # Verify SQLite integrity
    conn = sqlite3.connect(temp_db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check")
    check_result = cur.fetchone()[0]
    conn.close()
    assert check_result == "ok"

    root_t = gov.get_tracker(root_id)
    assert root_t.session_tokens == num_threads * calls_per_thread * 100
    store.close()


def test_12_sqlite_transaction_rollback_on_failure(temp_db_path):
    """Requirement 12: SQLite transaction interruption and rollback on simulated write failure."""
    store = FinancialStore(temp_db_path)

    # Test that failed transaction rolls back cleanly
    with pytest.raises(sqlite3.IntegrityError):
        with store._transaction() as conn:
            # Insert valid event
            conn.execute(
                """
                INSERT INTO financial_call_ledger (event_id, root_session_id, turn_id, provider, model, tier, total_tokens, cost_known, created_at)
                VALUES ('evt_rollback_1', 'root-12', 1, 'p', 'm', 'cheap', 100, 1, 12345.0)
                """
            )
            # Insert duplicate event_id to trigger primary key IntegrityError
            conn.execute(
                """
                INSERT INTO financial_call_ledger (event_id, root_session_id, turn_id, provider, model, tier, total_tokens, cost_known, created_at)
                VALUES ('evt_rollback_1', 'root-12', 1, 'p', 'm', 'cheap', 100, 1, 12345.0)
                """
            )

    # Verify that evt_rollback_1 was rolled back completely and does not exist
    assert not store.has_call_event("evt_rollback_1")
    store.close()


def test_13_schema_versioning_and_migration_check(temp_db_path):
    """Requirement 13: Schema versioning: verify schema version is recorded and tracked."""
    store = FinancialStore(temp_db_path)
    assert store.get_schema_version() == 2

    # Verify schema version table in DB
    conn = sqlite3.connect(temp_db_path)
    cur = conn.cursor()
    cur.execute("SELECT version FROM financial_schema_version ORDER BY version DESC LIMIT 1")
    ver = cur.fetchone()[0]
    conn.close()
    assert ver == 2
    store.close()


def test_14_changed_budget_configuration_on_restart(temp_db_path):
    """Requirement 14: Changed budget configuration: tighter binds immediately, increased does not grant extra money."""
    store1 = FinancialStore(temp_db_path)
    cfg1 = CostGovernanceConfig(per_session_cost_budget_inr=Decimal("100.00"))
    gov1 = CostGovernor(cfg1, store=store1)
    sid = "session-cfg-change-14"

    # Spend ~60 INR
    gov1.record_call(
        sid, "p", "m", "standard",
        TokenUsage(total_tokens=10_000, estimated_cost_usd=0.648788, cost_known=True),
    )
    t1 = gov1.get_tracker(sid)
    assert abs(t1.session_cost_inr - Decimal("60.00")) < Decimal("0.01")
    spent_inr = t1.session_cost_inr

    store1.close()

    # Case A: Startup with tighter budget (e.g. 50 INR). Since spent ~60 > 50, standard tier cannot be afforded.
    store2 = FinancialStore(temp_db_path)
    cfg_tight = CostGovernanceConfig(per_session_cost_budget_inr=Decimal("50.00"))
    gov2 = CostGovernor(cfg_tight, store=store2)

    afford_tight, demoted_tier, reason = gov2.can_afford_tier(sid, "standard")
    assert afford_tight is False
    assert "budget" in reason.lower()
    store2.close()

    # Case B: Startup with higher budget (e.g. 200 INR).
    # Resumed session must retain spent ₹60 and remaining is ₹140 (not reset to ₹200).
    store3 = FinancialStore(temp_db_path)
    cfg_loose = CostGovernanceConfig(per_session_cost_budget_inr=Decimal("200.00"))
    gov3 = CostGovernor(cfg_loose, store=store3)

    t3 = gov3.get_tracker(sid)
    assert t3.session_cost_inr == spent_inr
    afford_loose, _, _ = gov3.can_afford_tier(sid, "standard")
    assert afford_loose is True
    store3.close()


def test_15_persistence_failure_fail_closed_policy(temp_db_path):
    """Requirement 15: Persistence failure handling fails closed or flags persistence_failed."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "session-failure-15"

    tracker = gov.get_tracker(sid)
    # Simulate persistence failure
    tracker.persistence_failed = True

    # Check governor response to persistence failure
    can_afford, demoted_tier, reason = gov.can_afford_tier(sid, "cheap")
    assert can_afford is False
    assert "persistence" in reason.lower()
    store.close()


def test_16_existing_session_compatibility(temp_db_path):
    """Requirement 16: Existing session compatibility alongside existing sessions.db tables."""
    # Create tables of existing session_store
    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            state_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO sessions VALUES ('legacy-sess-1', 1234.0, 1234.0, '{\"key\": \"val\"}')"
    )
    conn.commit()
    conn.close()

    # Initialize FinancialStore on same DB
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)

    # Legacy session queried in CostGovernor should cleanly initialize empty tracker without crashing
    legacy_tracker = gov.get_tracker("legacy-sess-1")
    assert legacy_tracker.session_tokens == 0
    assert legacy_tracker.session_cost_inr == Decimal("0.000000")

    # Verify existing table remains completely intact
    conn = sqlite3.connect(temp_db_path)
    row = conn.execute("SELECT session_id, state_json FROM sessions WHERE session_id = 'legacy-sess-1'").fetchone()
    conn.close()
    assert row[0] == "legacy-sess-1"
    assert "key" in row[1]
    store.close()


def test_17_performance_benchmarks_hydration_and_write(temp_db_path):
    """Requirement 17: Performance measurements: hydration latency < 5ms, write latency < 5ms."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "session-perf-17"

    # Seed data
    gov.record_call(
        sid, "custom", "perf-model", "cheap",
        TokenUsage(total_tokens=1000, estimated_cost_usd=0.001, cost_known=True),
    )

    # Measure write latency (100 snapshot saves)
    write_latencies = []
    tracker = gov.get_tracker(sid)
    for _ in range(100):
        t0 = time.perf_counter()
        gov._persist_session_snapshot(tracker, sid, None)
        t1 = time.perf_counter()
        write_latencies.append((t1 - t0) * 1000.0)  # in ms

    mean_write_ms = sum(write_latencies) / len(write_latencies)

    # Measure hydration latency (100 cold hydrations from DB)
    hydration_latencies = []
    for i in range(100):
        gov_fresh = CostGovernor(CostGovernanceConfig(), store=store)
        t0 = time.perf_counter()
        _ = gov_fresh.get_tracker(sid)
        t1 = time.perf_counter()
        hydration_latencies.append((t1 - t0) * 1000.0)  # in ms

    mean_hydration_ms = sum(hydration_latencies) / len(hydration_latencies)

    print(f"\n[PERF] Mean write latency: {mean_write_ms:.3f} ms (Target < 5.0 ms)")
    print(f"[PERF] Mean hydration latency: {mean_hydration_ms:.3f} ms (Target < 5.0 ms)")

    store.close()
    assert mean_write_ms < 5.0, f"Write latency {mean_write_ms:.2f}ms exceeds 5ms target"
    assert mean_hydration_ms < 5.0, f"Hydration latency {mean_hydration_ms:.2f}ms exceeds 5ms target"

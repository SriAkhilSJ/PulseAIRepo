"""
test_financial_integrity_closure.py -- Phase 9.1.6 Financial Integrity Closure & Production Freeze Test Suite.

Covers:
1. Atomic financial accounting & crash-consistency failpoint testing (all-or-nothing rollback).
2. Idempotent crash recovery with zero double-counting.
3. Uncertain reservation lifecycle (Stage A recovery, Stage B eligibility, Stage C administrative resolution).
4. Safety rule: Timeouts NEVER automatically grant spend permission.
5. SQLite durability configuration: NORMAL vs FULL validation and SQL injection prevention.
6. Persistence failure fail-closed safety (completed work preserved, subsequent calls blocked).
7. Concurrency and idempotency across root and child agents.
8. Migration and backward compatibility from Schema v1 to v2.
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
from src.agents.financial_store import (
    FinancialStore,
    SimulatedCrashError,
    _SCHEMA_VERSION,
)
from src.context.token_tracker import TokenUsage


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a dedicated clean temporary SQLite DB file."""
    db_file = tmp_path / "test_closure.db"
    return str(db_file)


# ==============================================================================
# 1. ATOMIC TRANSACTIONS & CRASH FAILPOINTS
# ==============================================================================

def test_atomic_transaction_crash_before_ledger(temp_db_path):
    """Crash before ledger insert: entire transaction rolled back cleanly."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "sess-atomic-01"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=1000)
    assert ok

    # Attempt record_call with failpoint 'before_ledger'
    with pytest.raises(SimulatedCrashError):
        gov.record_call(
            session_id=sid,
            provider="custom",
            model="test-model",
            tier="cheap",
            usage=TokenUsage(total_tokens=1000, estimated_cost_usd=0.01, cost_known=True),
            reservation_id=rid,
            event_id="evt_fail_before_ledger",
            _failpoint="before_ledger",
        )

    # Verify rollback: ledger has no event, reservation NOT reconciled, snapshot empty
    assert not store.has_call_event("evt_fail_before_ledger")
    res = store.get_reservation(rid)
    assert res["status"] == "reserved"
    snap = store.load_session_snapshot(sid)
    assert snap is not None
    assert snap["total_calls_count"] == 0
    assert snap["cumulative_cost_inr"] == "0.000000"
    store.close()


def test_atomic_transaction_crash_after_ledger_before_reservation(temp_db_path):
    """Crash after ledger insert but before reservation update: rolls back completely."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "sess-atomic-02"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=1000)
    assert ok

    with pytest.raises(SimulatedCrashError):
        gov.record_call(
            session_id=sid,
            provider="custom",
            model="test-model",
            tier="cheap",
            usage=TokenUsage(total_tokens=1000, estimated_cost_usd=0.01, cost_known=True),
            reservation_id=rid,
            event_id="evt_fail_after_ledger",
            _failpoint="after_ledger",
        )

    # Transaction rolled back: ledger event must NOT exist
    assert not store.has_call_event("evt_fail_after_ledger")
    res = store.get_reservation(rid)
    assert res["status"] == "reserved"
    snap = store.load_session_snapshot(sid)
    assert snap is not None
    assert snap["total_calls_count"] == 0
    assert snap["cumulative_cost_inr"] == "0.000000"
    store.close()


def test_atomic_transaction_crash_after_reservation_before_snapshot(temp_db_path):
    """Crash after reservation update but before snapshot update: rolls back completely."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "sess-atomic-03"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=1000)
    assert ok

    with pytest.raises(SimulatedCrashError):
        gov.record_call(
            session_id=sid,
            provider="custom",
            model="test-model",
            tier="cheap",
            usage=TokenUsage(total_tokens=1000, estimated_cost_usd=0.01, cost_known=True),
            reservation_id=rid,
            event_id="evt_fail_after_res",
            _failpoint="after_reservation",
        )

    # Rollback verified across all tables
    assert not store.has_call_event("evt_fail_after_res")
    res = store.get_reservation(rid)
    assert res["status"] == "reserved"
    snap = store.load_session_snapshot(sid)
    assert snap is not None
    assert snap["total_calls_count"] == 0
    assert snap["cumulative_cost_inr"] == "0.000000"
    store.close()


def test_atomic_transaction_crash_immediately_before_commit(temp_db_path):
    """Crash immediately before commit: rolls back all tables."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "sess-atomic-04"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=1000)
    assert ok

    with pytest.raises(SimulatedCrashError):
        gov.record_call(
            session_id=sid,
            provider="custom",
            model="test-model",
            tier="cheap",
            usage=TokenUsage(total_tokens=1000, estimated_cost_usd=0.01, cost_known=True),
            reservation_id=rid,
            event_id="evt_fail_before_commit",
            _failpoint="before_commit",
        )

    assert not store.has_call_event("evt_fail_before_commit")
    res = store.get_reservation(rid)
    assert res["status"] == "reserved"
    snap = store.load_session_snapshot(sid)
    assert snap is not None
    assert snap["total_calls_count"] == 0
    assert snap["cumulative_cost_inr"] == "0.000000"
    store.close()


def test_atomic_transaction_successful_commit_all_or_nothing(temp_db_path):
    """Successful commit updates ledger, reservation, root snapshot, and child atomically."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    root_id = "root-atomic-05"
    child_id = "child-atomic-05"

    gov.register_parent_session(child_id, root_id)
    ok, rid, _ = gov.reserve(child_id, estimated_cost_inr=Decimal("5.00"), estimated_tokens=500)
    assert ok

    rec = gov.record_call(
        session_id=child_id,
        provider="openrouter",
        model="anthropic/claude-3.5-sonnet",
        tier="standard",
        usage=TokenUsage(prompt_tokens=400, completion_tokens=100, total_tokens=500, estimated_cost_usd=0.01, cost_known=True),
        reservation_id=rid,
        event_id="evt_atomic_success_05",
    )
    assert rec.call_id == "evt_atomic_success_05"

    # Verify all 4 changes committed in unison
    assert store.has_call_event("evt_atomic_success_05")
    res = store.get_reservation(rid)
    assert res["status"] == "reconciled"

    root_snap = store.load_session_snapshot(root_id)
    assert root_snap is not None
    assert root_snap["cumulative_total_tokens"] == 500

    child_snap = store.load_session_snapshot(child_id)
    assert child_snap is not None
    assert child_snap["cumulative_total_tokens"] == 500
    store.close()


# ==============================================================================
# 2. UNCERTAIN RESERVATION LIFECYCLE & ADMINISTRATIVE RESOLUTION
# ==============================================================================

def test_uncertain_reservation_stage_a_immediate_recovery(temp_db_path):
    """Stage A: in-flight reservation on restart marked uncertain, headroom retained."""
    store1 = FinancialStore(temp_db_path)
    gov1 = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("50.00"),
            reserve_budget_inr=Decimal("5.00"),
        ),
        store=store1,
    )
    sid = "sess-uncertain-stage-a"

    ok, rid, _ = gov1.reserve(sid, estimated_cost_inr=Decimal("20.00"), estimated_tokens=5000)
    assert ok
    store1.update_reservation_status(rid, "in_flight")
    store1.close()

    # Restart
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
    assert tracker.reservations[rid].status == "uncertain"
    # Headroom retained: available = 50 - 5 (reserve) - 20 (uncertain) = 25
    assert tracker.total_reserved_inr() == Decimal("20.00")
    store2.close()


def test_uncertain_reservation_stage_b_eligibility_and_no_silent_release(temp_db_path):
    """Stage B: Eligibility query returns aged reservations; verifies NO silent release."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "sess-uncertain-stage-b"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("15.00"), estimated_tokens=1000)
    assert ok
    store.update_reservation_status(rid, "uncertain")

    # Manually backdate updated_at to simulate 35 minutes ago
    thirty_five_mins_ago = time.time() - 2100.0
    conn = sqlite3.connect(temp_db_path)
    conn.execute("UPDATE financial_reservations SET updated_at = ? WHERE reservation_id = ?", (thirty_five_mins_ago, rid))
    conn.commit()
    conn.close()

    # Query eligibility for reconciliation review (> 30 mins = 1800s)
    eligible = gov.get_uncertain_reservations_for_review(min_age_seconds=1800.0)
    assert len(eligible) >= 1
    assert any(r["reservation_id"] == rid for r in eligible)

    # CRITICAL SAFETY TEST: Verify reservation is STILL uncertain and NOT released
    res = store.get_reservation(rid)
    assert res["status"] == "uncertain"
    tracker = gov.get_tracker(sid)
    # Headroom is STILL locked
    assert rid in tracker.reservations
    assert tracker.total_reserved_inr() == Decimal("15.00")
    store.close()


def test_uncertain_reservation_stage_c_release_resolution(temp_db_path):
    """Stage C: Explicit administrative release unlocks headroom and creates audit trail."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("100.00"),
            per_turn_cost_budget_inr=Decimal("50.00"),
            reserve_budget_inr=Decimal("5.00"),
        ),
        store=store,
    )
    sid = "sess-uncertain-release"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("25.00"), estimated_tokens=2000)
    assert ok
    store.update_reservation_status(rid, "uncertain")
    tracker = gov.get_tracker(sid)
    assert tracker.total_reserved_inr() == Decimal("25.00")

    # Admin verifies provider logs: request never reached provider -> release
    ok_res, msg = gov.resolve_uncertain_reservation(
        session_id=sid,
        reservation_id=rid,
        action="release",
        resolution_notes="Provider API gateway logs confirm TCP timeout before dispatch; 0 charge.",
        resolved_by="lead_infrastructure_engineer",
    )
    assert ok_res, f"Resolution failed: {msg}"

    # Verify headroom is unlocked in memory and store
    assert tracker.total_reserved_inr() == Decimal("0.00")
    assert rid not in tracker.reservations
    db_res = store.get_reservation(rid)
    assert db_res["status"] == "released"

    # Verify audit record
    audit = store.get_reservation_resolution(rid)
    assert audit is not None
    assert audit["action"] == "release"
    assert audit["resolved_by"] == "lead_infrastructure_engineer"
    assert "Provider API gateway logs" in audit["resolution_notes"]
    store.close()


def test_uncertain_reservation_stage_c_reconcile_resolution(temp_db_path):
    """Stage C: Explicit administrative reconcile debits actual cost and updates audit trail."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(
        CostGovernanceConfig(
            per_session_cost_budget_inr=Decimal("100.00"),
            per_turn_cost_budget_inr=Decimal("50.00"),
            reserve_budget_inr=Decimal("5.00"),
        ),
        store=store,
    )
    sid = "sess-uncertain-reconcile"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("30.00"), estimated_tokens=3000)
    assert ok
    store.update_reservation_status(rid, "uncertain")

    # Admin verifies provider billing: request succeeded, cost was 28.50 INR
    ok_res, msg = gov.resolve_uncertain_reservation(
        session_id=sid,
        reservation_id=rid,
        action="reconcile",
        actual_cost_inr=Decimal("28.500000"),
        resolution_notes="Provider billing dashboard confirms request completed.",
        resolved_by="finops_auditor",
    )
    assert ok_res, f"Resolution failed: {msg}"

    # Headroom unlocked, actual cost debited
    tracker = gov.get_tracker(sid)
    assert tracker.total_reserved_inr() == Decimal("0.00")
    assert tracker.session_cost_inr == Decimal("28.500000")

    db_res = store.get_reservation(rid)
    assert db_res["status"] == "reconciled"

    audit = store.get_reservation_resolution(rid)
    assert audit is not None
    assert audit["action"] == "reconcile"
    assert audit["actual_cost_inr"] == "28.500000"
    store.close()


def test_uncertain_reservation_duplicate_and_invalid_transitions_rejected(temp_db_path):
    """Prevent duplicate resolution and reject invalid state transitions."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "sess-uncertain-invalid"

    ok, rid, _ = gov.reserve(sid, estimated_cost_inr=Decimal("10.00"), estimated_tokens=1000)
    assert ok
    # Reservation is currently 'reserved' (not 'uncertain')

    # Attempt to resolve while still 'reserved' -> must be rejected
    ok_inv, reason = gov.resolve_uncertain_reservation(sid, rid, action="release")
    assert not ok_inv
    assert "must be 'uncertain'" in reason.lower()

    # Transition to uncertain
    store.update_reservation_status(rid, "uncertain")

    # Reject invalid action name
    ok_bad_action, reason_bad = gov.resolve_uncertain_reservation(sid, rid, action="delete_now")
    assert not ok_bad_action
    assert "invalid resolution action" in reason_bad.lower()

    # First valid resolution succeeds
    ok1, _ = gov.resolve_uncertain_reservation(sid, rid, action="release")
    assert ok1

    # Second resolution (duplicate) must be rejected
    ok2, reason_dup = gov.resolve_uncertain_reservation(sid, rid, action="release")
    assert not ok2
    assert "must be 'uncertain'" in reason_dup.lower()
    store.close()


# ==============================================================================
# 3. SQLITE DURABILITY CONFIGURATION (NORMAL vs FULL)
# ==============================================================================

def test_sqlite_durability_default_is_normal(temp_db_path, monkeypatch):
    """Default SQLite synchronous mode is NORMAL."""
    monkeypatch.delenv("CRUSORAI_SQLITE_SYNCHRONOUS", raising=False)
    store = FinancialStore(temp_db_path)
    assert store.get_synchronous_mode() == "NORMAL"
    store.close()


def test_sqlite_durability_explicit_full_configuration(temp_db_path, monkeypatch):
    """Setting CRUSORAI_SQLITE_SYNCHRONOUS=FULL applies PRAGMA synchronous=FULL."""
    monkeypatch.setenv("CRUSORAI_SQLITE_SYNCHRONOUS", "FULL")
    store = FinancialStore(temp_db_path)
    assert store.get_synchronous_mode() == "FULL"
    store.close()


def test_sqlite_durability_invalid_value_safe_fallback_no_sql_injection(temp_db_path, monkeypatch):
    """Invalid or malicious CRUSORAI_SQLITE_SYNCHRONOUS falls back safely to NORMAL."""
    malicious_input = "OFF; DROP TABLE financial_call_ledger;"
    monkeypatch.setenv("CRUSORAI_SQLITE_SYNCHRONOUS", malicious_input)
    store = FinancialStore(temp_db_path)
    # Must safely fall back to NORMAL without executing injection
    assert store.get_synchronous_mode() == "NORMAL"

    # Verify table was NOT dropped
    conn = sqlite3.connect(temp_db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='financial_call_ledger'")
    assert cur.fetchone() is not None
    conn.close()
    store.close()


# ==============================================================================
# 4. PERSISTENCE FAILURE SAFETY (FAIL-CLOSED)
# ==============================================================================

def test_persistence_failure_circuit_breaker(temp_db_path):
    """Storage failure trips circuit breaker; completed work preserved, subsequent calls blocked."""
    store = FinancialStore(temp_db_path)
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    sid = "sess-fail-closed"

    # Record first successful call
    gov.record_call(sid, "p", "m", "cheap", TokenUsage(total_tokens=100, estimated_cost_usd=0.001, cost_known=True))
    assert gov.can_afford_tier(sid, "cheap")[0] is True

    # Simulate catastrophic storage failure by closing DB connection underneath
    store.close()

    # Attempt call when database connection is closed: completed call object returned, persistence_failed tripped
    rec = gov.record_call(sid, "p", "m", "cheap", TokenUsage(total_tokens=200, estimated_cost_usd=0.002, cost_known=True))
    assert rec is not None
    assert rec.total_tokens == 200

    tracker = gov.get_tracker(sid)
    assert tracker.persistence_failed is True

    # Subsequent reserve and afford checks fail closed
    ok_res, _, reason_res = gov.reserve(sid, estimated_cost_inr=Decimal("1.00"), estimated_tokens=500)
    assert not ok_res
    assert "persistence_failure" in reason_res

    can_afford, _, reason_aff = gov.can_afford_tier(sid, "cheap")
    assert not can_afford
    assert "persistence_failure" in reason_aff


# ==============================================================================
# 5. CONCURRENCY & IDEMPOTENCY
# ==============================================================================

def test_concurrent_atomic_calls_and_deduplication(temp_db_path):
    """Concurrent child agents execute atomic transactions with zero lost updates and zero duplicate debits."""
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
    root_id = "root-atomic-concurrency"
    num_threads = 10
    calls_per_thread = 10

    for i in range(num_threads):
        gov.register_parent_session(f"worker-{i}", root_id)

    def worker(idx: int):
        cid = f"worker-{idx}"
        for c in range(calls_per_thread):
            ok, rid, _ = gov.reserve(cid, estimated_cost_inr=Decimal("0.10"), estimated_tokens=100)
            gov.record_call(
                session_id=cid,
                provider="custom",
                model="model-fast",
                tier="cheap",
                usage=TokenUsage(total_tokens=100, estimated_cost_usd=0.0001, cost_known=True),
                reservation_id=rid if ok else None,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    root_t = gov.get_tracker(root_id)
    assert root_t.session_tokens == num_threads * calls_per_thread * 100

    # Idempotency test: Replay the very first event in ledger
    first_evt = root_t.call_history[0].call_id
    tokens_before = root_t.session_tokens
    cost_before = root_t.session_cost_inr

    gov.record_call(
        session_id="worker-0",
        provider="custom",
        model="model-fast",
        tier="cheap",
        usage=TokenUsage(total_tokens=100, estimated_cost_usd=0.0001, cost_known=True),
        event_id=first_evt,
    )

    # Replayed event must NOT change tokens or cost
    assert root_t.session_tokens == tokens_before
    assert root_t.session_cost_inr == cost_before
    store.close()


# ==============================================================================
# 6. MIGRATION & BACKWARD COMPATIBILITY
# ==============================================================================

def test_backward_compatibility_v1_database_upgrades_cleanly(tmp_path):
    """Database created under Schema v1 opens cleanly, migrates to v2, and retains all history."""
    v1_db_path = tmp_path / "legacy_v1.db"
    conn = sqlite3.connect(str(v1_db_path))

    # Construct Schema v1 exactly as it was
    conn.execute(
        """
        CREATE TABLE financial_schema_version (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL,
            installed_at REAL NOT NULL
        )
        """
    )
    conn.execute("INSERT INTO financial_schema_version VALUES (1, 12345.0, 12345.0)")

    conn.execute(
        """
        CREATE TABLE financial_session_snapshots (
            session_id TEXT PRIMARY KEY,
            root_session_id TEXT NOT NULL,
            parent_session_id TEXT,
            cumulative_input_tokens INTEGER DEFAULT 0,
            cumulative_output_tokens INTEGER DEFAULT 0,
            cumulative_cached_tokens INTEGER DEFAULT 0,
            cumulative_total_tokens INTEGER DEFAULT 0,
            cumulative_cost_usd TEXT NOT NULL DEFAULT '0.000000',
            cumulative_cost_inr TEXT NOT NULL DEFAULT '0.000000',
            has_unknown_spend INTEGER DEFAULT 0,
            unrated_calls_count INTEGER DEFAULT 0,
            unrated_tokens_count INTEGER DEFAULT 0,
            cheap_calls_count INTEGER DEFAULT 0,
            standard_calls_count INTEGER DEFAULT 0,
            premium_calls_count INTEGER DEFAULT 0,
            total_calls_count INTEGER DEFAULT 0,
            current_turn_id INTEGER DEFAULT 1,
            turn_tokens INTEGER DEFAULT 0,
            turn_cached_tokens INTEGER DEFAULT 0,
            turn_cost_usd TEXT NOT NULL DEFAULT '0.000000',
            turn_cost_inr TEXT NOT NULL DEFAULT '0.000000',
            turn_calls_cheap INTEGER DEFAULT 0,
            turn_calls_standard INTEGER DEFAULT 0,
            turn_calls_premium INTEGER DEFAULT 0,
            budget_config_json TEXT NOT NULL DEFAULT '{}',
            schema_version INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO financial_session_snapshots (session_id, root_session_id, cumulative_total_tokens, cumulative_cost_usd, cumulative_cost_inr, created_at, updated_at)
        VALUES ('v1-historical-sess', 'v1-historical-sess', 42000, '0.420000', '38.841642', 12345.0, 12345.0)
        """
    )
    conn.commit()
    conn.close()

    # Open with new FinancialStore
    store = FinancialStore(str(v1_db_path))

    # Verify schema version migrated to 2
    assert store.get_schema_version() == 2

    # Verify resolution table exists
    conn = sqlite3.connect(str(v1_db_path))
    res_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='financial_reservation_resolutions'").fetchone()
    assert res_table is not None
    conn.close()

    # Verify historical session snapshot is recovered without data loss
    gov = CostGovernor(CostGovernanceConfig(), store=store)
    tracker = gov.get_tracker("v1-historical-sess")
    assert tracker.session_tokens == 42000
    assert tracker.session_cost_usd == Decimal("0.420000")
    assert tracker.session_cost_inr == Decimal("38.841642")
    store.close()

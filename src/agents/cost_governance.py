"""
cost_governance.py -- Central financial & token governance engine for Crusor AI Agent Core.

Phase 9.1.4: Persistent Financial Accounting & Session Recovery
- Root session budget inheritance (child/subagent debits root parent).
- Durable SQLite persistence in canonical `sessions.db` via FinancialStore.
- Startup hydration of cumulative tokens, costs, call counts, and unrated usage.
- Persistent reservation lifecycle: reserved -> in_flight -> reconciled | released | uncertain.
- Crash recovery: in-flight reservations marked uncertain, retaining reserved headroom.
- Idempotent call ledger event deduplication.
- Configuration change management: effective budget enforcement prevents silent allowance inflation on restart.
- Fail-closed safety on persistence errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import os
import random
import uuid
import threading
import time
from typing import Any, Literal, Optional

from src.config import settings
from src.context.token_tracker import TokenUsage

TierType = Literal["cheap", "standard", "premium"]
GovernanceStatus = Literal["healthy", "near_limit", "exhausted"]
UnknownPricingPolicy = Literal["deny", "token_limited", "explicit_allow"]

log = logging.getLogger("crusorai.cost_governance")

# House financial conversion constants (matching pricing.py exactly)
_DEFAULT_USD_TO_INR = Decimal("86.0")
_FOREX_SPREAD = Decimal("1.005")
_GATEWAY_FEE = Decimal("1.07")


def _quantize_currency(val: Decimal) -> Decimal:
    """Standardize monetary amounts to 6 decimal places (micro-currency precision)."""
    return val.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _to_decimal(val: Decimal | float | int | str | None) -> Decimal:
    if val is None:
        return Decimal("0.000000")
    if isinstance(val, Decimal):
        return _quantize_currency(val)
    return _quantize_currency(Decimal(str(val)))


@dataclass
class CostGovernanceConfig:
    """
    Central governance limits and financial policies.
    Enforces the ₹5 target simple task cost and bounds token/monetary consumption.
    """
    enabled: bool = True
    target_simple_task_cost_inr: Decimal = Decimal("5.00")
    per_turn_token_budget: int = 150_000
    per_session_token_budget: int = 600_000
    per_turn_cost_budget_inr: Decimal = Decimal("25.00")
    per_session_cost_budget_inr: Decimal = Decimal("86.00")  # ~$0.93 USD billing equiv
    reserve_budget_inr: Decimal = Decimal("2.00")
    reserve_tokens: int = 20_000
    usd_to_inr_rate: Decimal = _DEFAULT_USD_TO_INR
    max_premium_calls_per_turn: int = getattr(settings, "CRUSORAI_MAX_PREMIUM_CALLS_PER_TURN", 3)
    max_premium_calls_per_session: int = getattr(settings, "CRUSORAI_MAX_PREMIUM_CALLS_PER_SESSION", 10)
    unknown_pricing_policy: UnknownPricingPolicy = getattr(settings, "CRUSORAI_UNKNOWN_PRICING_POLICY", "token_limited")  # type: ignore
    max_unrated_calls_per_turn: int = getattr(settings, "CRUSORAI_MAX_UNRATED_CALLS_PER_TURN", 5)
    max_unrated_calls_per_session: int = getattr(settings, "CRUSORAI_MAX_UNRATED_CALLS_PER_SESSION", 15)
    max_unrated_tokens_per_turn: int = getattr(settings, "CRUSORAI_MAX_UNRATED_TOKENS_PER_TURN", 50_000)
    max_unrated_tokens_per_session: int = getattr(settings, "CRUSORAI_MAX_UNRATED_TOKENS_PER_SESSION", 150_000)

    @classmethod
    def from_env(cls) -> "CostGovernanceConfig":
        enabled_str = os.environ.get("CRUSORAI_COST_GOVERNANCE", "on").strip().lower()
        enabled = enabled_str not in {"off", "0", "false", "no"}

        def _env_dec(name: str, default: str) -> Decimal:
            val = os.environ.get(name, default).strip()
            try:
                return _quantize_currency(Decimal(val))
            except Exception:
                return _quantize_currency(Decimal(default))

        def _env_int(name: str, default: int) -> int:
            val = os.environ.get(name, str(default)).strip()
            try:
                return int(val)
            except Exception:
                return default

        fx = _env_dec("CRUSORAI_USD_INR", str(_DEFAULT_USD_TO_INR))

        agent_cost_usd_raw = os.environ.get("AGENT_COST_BUDGET")
        if agent_cost_usd_raw:
            try:
                multiplier = fx * _FOREX_SPREAD * _GATEWAY_FEE
                session_inr = _quantize_currency(Decimal(agent_cost_usd_raw) * multiplier)
            except Exception:
                session_inr = Decimal("86.00")
        else:
            session_inr = _env_dec("CRUSORAI_SESSION_COST_BUDGET_INR", "86.00")

        session_tokens = _env_int("CRUSORAI_SESSION_TOKEN_BUDGET", _env_int("AGENT_TOKEN_BUDGET", 600_000))

        raw_policy = os.environ.get("CRUSORAI_UNKNOWN_PRICING_POLICY", "token_limited").strip().lower()
        policy: UnknownPricingPolicy = (
            raw_policy if raw_policy in {"deny", "token_limited", "explicit_allow"} else "token_limited"  # type: ignore
        )

        return cls(
            enabled=enabled,
            target_simple_task_cost_inr=_env_dec("CRUSORAI_TARGET_SIMPLE_COST_INR", "5.00"),
            per_turn_token_budget=_env_int("CRUSORAI_TURN_TOKEN_BUDGET", 150_000),
            per_session_token_budget=session_tokens,
            per_turn_cost_budget_inr=_env_dec("CRUSORAI_TURN_COST_BUDGET_INR", "25.00"),
            per_session_cost_budget_inr=session_inr,
            reserve_budget_inr=_env_dec("CRUSORAI_RESERVE_BUDGET_INR", "2.00"),
            reserve_tokens=_env_int("CRUSORAI_RESERVE_TOKENS", 20_000),
            usd_to_inr_rate=fx,
            max_premium_calls_per_turn=_env_int("CRUSORAI_MAX_PREMIUM_CALLS_PER_TURN", 3),
            max_premium_calls_per_session=_env_int("CRUSORAI_MAX_PREMIUM_CALLS_PER_SESSION", 10),
            unknown_pricing_policy=policy,
            max_unrated_calls_per_turn=_env_int("CRUSORAI_MAX_UNRATED_CALLS_PER_TURN", 5),
            max_unrated_calls_per_session=_env_int("CRUSORAI_MAX_UNRATED_CALLS_PER_SESSION", 15),
            max_unrated_tokens_per_turn=_env_int("CRUSORAI_MAX_UNRATED_TOKENS_PER_TURN", 50_000),
            max_unrated_tokens_per_session=_env_int("CRUSORAI_MAX_UNRATED_TOKENS_PER_SESSION", 150_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "target_simple_task_cost_inr": str(self.target_simple_task_cost_inr),
            "per_turn_token_budget": self.per_turn_token_budget,
            "per_session_token_budget": self.per_session_token_budget,
            "per_turn_cost_budget_inr": str(self.per_turn_cost_budget_inr),
            "per_session_cost_budget_inr": str(self.per_session_cost_budget_inr),
            "reserve_budget_inr": str(self.reserve_budget_inr),
            "reserve_tokens": self.reserve_tokens,
            "usd_to_inr_rate": str(self.usd_to_inr_rate),
            "max_premium_calls_per_turn": self.max_premium_calls_per_turn,
            "max_premium_calls_per_session": self.max_premium_calls_per_session,
            "unknown_pricing_policy": self.unknown_pricing_policy,
            "max_unrated_calls_per_turn": self.max_unrated_calls_per_turn,
            "max_unrated_calls_per_session": self.max_unrated_calls_per_session,
            "max_unrated_tokens_per_turn": self.max_unrated_tokens_per_turn,
            "max_unrated_tokens_per_session": self.max_unrated_tokens_per_session,
        }


@dataclass
class ModelCallRecord:
    """Structured accounting record for a single model call."""
    call_id: str
    session_id: str
    turn_id: int
    timestamp: float
    provider: str
    model: str
    tier: TierType
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    total_tokens: int
    cost_usd: Decimal | None
    cost_inr: Decimal | None
    cost_known: bool
    cache_write_tokens: int = 0
    duration_s: float = 0.0
    purpose: str = "work"

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": float(self.cost_usd) if self.cost_usd is not None else None,
            "cost_inr": float(self.cost_inr) if self.cost_inr is not None else None,
            "cost_known": self.cost_known,
            "duration_s": self.duration_s,
            "purpose": self.purpose,
        }


@dataclass
class BudgetReservation:
    """A reserved slice of budget protecting turn execution and final response."""
    reservation_id: str
    session_id: str
    estimated_cost_inr: Decimal
    estimated_tokens: int
    purpose: str
    active: bool = True
    status: str = "reserved"  # 'reserved', 'in_flight', 'reconciled', 'released', 'uncertain'
    created_at: float = field(default_factory=time.time)


@dataclass
class SessionSpendTracker:
    """Thread-safe accounting tracker for a session and its turns."""
    session_id: str
    current_turn_id: int = 1

    # Session cumulative
    session_tokens: int = 0
    session_cached_tokens: int = 0
    session_cache_write_tokens: int = 0
    session_cost_inr: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    session_cost_usd: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    session_has_unknown_spend: bool = False
    session_calls_cheap: int = 0
    session_calls_standard: int = 0
    session_calls_premium: int = 0

    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    total_calls_count: int = 0

    # Current turn cumulative
    turn_tokens: int = 0
    turn_cached_tokens: int = 0
    turn_cache_write_tokens: int = 0
    turn_cost_inr: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    turn_cost_usd: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    turn_has_unknown_spend: bool = False
    turn_calls_cheap: int = 0
    turn_calls_standard: int = 0
    turn_calls_premium: int = 0

    # Unrated models governance
    unrated_calls_session: int = 0
    unrated_calls_turn: int = 0
    unrated_tokens_session: int = 0
    unrated_tokens_turn: int = 0

    # Snapshot configuration & reliability
    budget_config_snapshot: dict[str, Any] | None = None
    persistence_failed: bool = False

    # Active reservations & call history
    reservations: dict[str, BudgetReservation] = field(default_factory=dict)
    call_history: list[ModelCallRecord] = field(default_factory=list)

    def total_reserved_inr(self) -> Decimal:
        return sum(
            (r.estimated_cost_inr for r in self.reservations.values() if r.active),
            Decimal("0.000000"),
        )

    def total_reserved_tokens(self) -> int:
        return sum(
            (r.estimated_tokens for r in self.reservations.values() if r.active),
            0,
        )

    def next_turn(self) -> None:
        self.current_turn_id += 1
        self.turn_tokens = 0
        self.turn_cached_tokens = 0
        self.turn_cache_write_tokens = 0
        self.turn_cost_inr = Decimal("0.000000")
        self.turn_cost_usd = Decimal("0.000000")
        self.turn_has_unknown_spend = False
        self.turn_calls_cheap = 0
        self.turn_calls_standard = 0
        self.turn_calls_premium = 0
        self.unrated_calls_turn = 0
        self.unrated_tokens_turn = 0
        self.reservations.clear()


class ReservationContext:
    """Deterministic context manager for budget reservations. Releases automatically on error."""
    def __init__(
        self,
        governor: "CostGovernor",
        session_id: str,
        estimated_cost_inr: Decimal | float,
        estimated_tokens: int = 4000,
        purpose: str = "work",
    ):
        self.governor = governor
        self.session_id = session_id
        self.estimated_cost_inr = estimated_cost_inr
        self.estimated_tokens = estimated_tokens
        self.purpose = purpose
        self.reservation_id: str | None = None
        self.ok: bool = False
        self.reason: str = ""
        self.is_reconciled: bool = False

    @property
    def reserved(self) -> bool:
        return self.ok

    def __enter__(self) -> "ReservationContext":
        self.ok, self.reservation_id, self.reason = self.governor.reserve(
            session_id=self.session_id,
            estimated_cost_inr=self.estimated_cost_inr,
            estimated_tokens=self.estimated_tokens,
            purpose=self.purpose,
        )
        if self.ok and self.reservation_id:
            store = self.governor._get_store()
            if store:
                try:
                    store.update_reservation_status(self.reservation_id, "in_flight")
                except Exception:
                    pass
        return self

    def mark_reconciled(self) -> None:
        self.is_reconciled = True

    def reconcile(self) -> None:
        self.mark_reconciled()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.reservation_id and not self.is_reconciled:
            self.governor.release_reservation(self.session_id, self.reservation_id)


class CostGovernor:
    """
    Central financial and token governor for Crusor AI Agent Core.
    Guarantees root session budget inheritance, financial predictability,
    headroom preservation, zero arithmetic drift, and persistent session recovery.
    """

    def __init__(
        self,
        config: CostGovernanceConfig | None = None,
        store: Any | None = None,
    ):
        self._config = config or CostGovernanceConfig.from_env()
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionSpendTracker] = {}
        self._parent_sessions: dict[str, str] = {}
        self._store = store

    def _get_store(self) -> Any:
        if self._store is None:
            persistence_env = os.environ.get("CRUSORAI_FINANCIAL_PERSISTENCE", "on").strip().lower()
            if persistence_env in {"off", "0", "false", "no"}:
                self._store = False
                return None
            try:
                from src.agents.financial_store import get_financial_store
                self._store = get_financial_store()
            except Exception as exc:
                log.warning("Could not initialize financial store: %s", exc)
                self._store = False
        return self._store if self._store is not False else None

    def get_config(self) -> CostGovernanceConfig:
        return self._config

    def reload_config(self) -> None:
        with self._lock:
            self._config = CostGovernanceConfig.from_env()

    def is_enabled(self) -> bool:
        return self._config.enabled

    # --------------------------------------------------------------------------
    # CONFIGURATION EVOLUTION & EFFECTIVE BUDGET
    # --------------------------------------------------------------------------

    def get_effective_config(self, session_id: str) -> CostGovernanceConfig:
        """
        Derive effective budget configuration for a session.
        Rule: An application restart must never silently grant an existing session extra budget.
        Tighter limits between persisted snapshot and current configuration always bind.
        """
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
        snap = tracker.budget_config_snapshot
        current = self._config
        if not snap:
            return current

        snap_session_cost = _to_decimal(snap.get("per_session_cost_budget_inr", current.per_session_cost_budget_inr))
        snap_session_tokens = int(snap.get("per_session_token_budget", current.per_session_token_budget))
        snap_turn_cost = _to_decimal(snap.get("per_turn_cost_budget_inr", current.per_turn_cost_budget_inr))
        snap_turn_tokens = int(snap.get("per_turn_token_budget", current.per_turn_token_budget))

        effective_session_cost = min(snap_session_cost, current.per_session_cost_budget_inr)
        effective_session_tokens = min(snap_session_tokens, current.per_session_token_budget)
        effective_turn_cost = min(snap_turn_cost, current.per_turn_cost_budget_inr)
        effective_turn_tokens = min(snap_turn_tokens, current.per_turn_token_budget)

        policy_rank = {"deny": 0, "token_limited": 1, "explicit_allow": 2}
        snap_policy = snap.get("unknown_pricing_policy", current.unknown_pricing_policy)
        curr_policy = current.unknown_pricing_policy
        effective_policy = snap_policy if policy_rank.get(snap_policy, 1) < policy_rank.get(curr_policy, 1) else curr_policy

        return CostGovernanceConfig(
            enabled=current.enabled,
            target_simple_task_cost_inr=current.target_simple_task_cost_inr,
            per_session_cost_budget_inr=effective_session_cost,
            per_turn_cost_budget_inr=effective_turn_cost,
            per_session_token_budget=effective_session_tokens,
            per_turn_token_budget=effective_turn_tokens,
            reserve_budget_inr=current.reserve_budget_inr,
            reserve_tokens=current.reserve_tokens,
            usd_to_inr_rate=current.usd_to_inr_rate,
            max_premium_calls_per_turn=min(int(snap.get("max_premium_calls_per_turn", current.max_premium_calls_per_turn)), current.max_premium_calls_per_turn),
            max_premium_calls_per_session=min(int(snap.get("max_premium_calls_per_session", current.max_premium_calls_per_session)), current.max_premium_calls_per_session),
            unknown_pricing_policy=effective_policy,
            max_unrated_calls_per_turn=min(int(snap.get("max_unrated_calls_per_turn", current.max_unrated_calls_per_turn)), current.max_unrated_calls_per_turn),
            max_unrated_calls_per_session=min(int(snap.get("max_unrated_calls_per_session", current.max_unrated_calls_per_session)), current.max_unrated_calls_per_session),
            max_unrated_tokens_per_turn=min(int(snap.get("max_unrated_tokens_per_turn", current.max_unrated_tokens_per_turn)), current.max_unrated_tokens_per_turn),
            max_unrated_tokens_per_session=min(int(snap.get("max_unrated_tokens_per_session", current.max_unrated_tokens_per_session)), current.max_unrated_tokens_per_session),
        )

    # --------------------------------------------------------------------------
    # ROOT SESSION HIERARCHY
    # --------------------------------------------------------------------------

    def register_parent_session(self, child_session_id: str, parent_session_id: str) -> None:
        """Register parent linkage for a delegated subagent session."""
        if not child_session_id or not parent_session_id or child_session_id == parent_session_id:
            return
        with self._lock:
            self._parent_sessions[str(child_session_id)] = str(parent_session_id)
            store = self._get_store()
            if store:
                try:
                    store.save_parent_session(str(child_session_id), str(parent_session_id))
                except Exception as exc:
                    log.error("Failed to persist parent session: %s", exc)

    def get_root_session_id(self, session_id: str) -> str:
        """Resolve the top-level parent session ID across arbitrarily nested delegations."""
        current = str(session_id or "default")
        visited = set()
        with self._lock:
            while current:
                if current in visited:
                    break
                visited.add(current)
                parent = self._parent_sessions.get(current)
                if not parent:
                    # Check persistent store
                    store = self._get_store()
                    if store:
                        try:
                            parent = store.get_parent_session(current)
                            if parent:
                                self._parent_sessions[current] = parent
                        except Exception:
                            pass
                if not parent and current.startswith("sub-"):
                    # Dynamic discovery from subagent_store
                    try:
                        from src.runtime.subagent_store import get_store
                        row = get_store().get_by_child(current)
                        if row and row.parent_session_id:
                            parent = row.parent_session_id
                            self._parent_sessions[current] = parent
                    except Exception:
                        pass
                if not parent:
                    break
                current = parent
        return current

    # --------------------------------------------------------------------------
    # HYDRATION & SNAPSHOT PERSISTENCE
    # --------------------------------------------------------------------------

    def _hydrate_tracker_from_snapshot(self, session_id: str, snapshot: dict[str, Any]) -> SessionSpendTracker:
        """Hydrate a SessionSpendTracker from persisted database snapshot."""
        cfg_snapshot = None
        cfg_json = snapshot.get("budget_config_json")
        if cfg_json:
            try:
                cfg_snapshot = json.loads(cfg_json)
            except Exception:
                pass

        tracker = SessionSpendTracker(
            session_id=session_id,
            current_turn_id=int(snapshot.get("current_turn_id", 1)),
            session_tokens=int(snapshot.get("cumulative_total_tokens", 0)),
            session_cached_tokens=int(snapshot.get("cumulative_cached_tokens", 0)),
            session_cache_write_tokens=int(snapshot.get("cumulative_cache_write_tokens", 0)),
            session_cost_inr=Decimal(str(snapshot.get("cumulative_cost_inr", "0.000000"))),
            session_cost_usd=Decimal(str(snapshot.get("cumulative_cost_usd", "0.000000"))),
            session_has_unknown_spend=bool(snapshot.get("has_unknown_spend", 0)),
            session_calls_cheap=int(snapshot.get("cheap_calls_count", 0)),
            session_calls_standard=int(snapshot.get("standard_calls_count", 0)),
            session_calls_premium=int(snapshot.get("premium_calls_count", 0)),
            cumulative_input_tokens=int(snapshot.get("cumulative_input_tokens", 0)),
            cumulative_output_tokens=int(snapshot.get("cumulative_output_tokens", 0)),
            total_calls_count=int(snapshot.get("total_calls_count", 0)),
            turn_tokens=int(snapshot.get("turn_tokens", 0)),
            turn_cached_tokens=int(snapshot.get("turn_cached_tokens", 0)),
            turn_cache_write_tokens=int(snapshot.get("turn_cache_write_tokens", 0)),
            turn_cost_inr=Decimal(str(snapshot.get("turn_cost_inr", "0.000000"))),
            turn_cost_usd=Decimal(str(snapshot.get("turn_cost_usd", "0.000000"))),
            turn_has_unknown_spend=bool(snapshot.get("has_unknown_spend", 0)),
            turn_calls_cheap=int(snapshot.get("turn_calls_cheap", 0)),
            turn_calls_standard=int(snapshot.get("turn_calls_standard", 0)),
            turn_calls_premium=int(snapshot.get("turn_calls_premium", 0)),
            unrated_calls_session=int(snapshot.get("unrated_calls_count", 0)),
            unrated_tokens_session=int(snapshot.get("unrated_tokens_count", 0)),
            budget_config_snapshot=cfg_snapshot,
        )

        parent_sid = snapshot.get("parent_session_id")
        if parent_sid:
            self._parent_sessions[session_id] = str(parent_sid)

        # Recover unresolved reservations
        store = self._get_store()
        if store:
            root_id = str(snapshot.get("root_session_id") or session_id)
            unresolved = store.recover_interrupted_reservations_on_startup(root_id)
            for res in unresolved:
                if res.get("session_id") == session_id or session_id == root_id:
                    rid = res["reservation_id"]
                    tracker.reservations[rid] = BudgetReservation(
                        reservation_id=rid,
                        session_id=res["session_id"],
                        estimated_cost_inr=Decimal(str(res["estimated_cost_inr"])),
                        estimated_tokens=int(res["estimated_tokens"]),
                        purpose=res.get("purpose", "work"),
                        active=True,
                        status=res.get("status", "uncertain"),
                    )
        return tracker

    def _extract_tracker_snapshot_dict(self, tracker: SessionSpendTracker) -> dict[str, Any]:
        """Extract tracker metrics into snapshot data dictionary."""
        return {
            "cumulative_input_tokens": tracker.cumulative_input_tokens,
            "cumulative_output_tokens": tracker.cumulative_output_tokens,
            "session_cached_tokens": tracker.session_cached_tokens,
            "session_cache_write_tokens": tracker.session_cache_write_tokens,
            "turn_cache_write_tokens": tracker.turn_cache_write_tokens,
            "session_tokens": tracker.session_tokens,
            "session_cost_usd": tracker.session_cost_usd,
            "session_cost_inr": tracker.session_cost_inr,
            "session_has_unknown_spend": tracker.session_has_unknown_spend,
            "unrated_calls_session": tracker.unrated_calls_session,
            "unrated_tokens_session": tracker.unrated_tokens_session,
            "session_calls_cheap": tracker.session_calls_cheap,
            "session_calls_standard": tracker.session_calls_standard,
            "session_calls_premium": tracker.session_calls_premium,
            "total_calls_count": len(tracker.call_history) or tracker.total_calls_count,
            "current_turn_id": tracker.current_turn_id,
            "turn_tokens": tracker.turn_tokens,
            "turn_cached_tokens": tracker.turn_cached_tokens,
            "turn_cost_usd": tracker.turn_cost_usd,
            "turn_cost_inr": tracker.turn_cost_inr,
            "turn_calls_cheap": tracker.turn_calls_cheap,
            "turn_calls_standard": tracker.turn_calls_standard,
            "turn_calls_premium": tracker.turn_calls_premium,
        }

    def _persist_session_snapshot(
        self,
        tracker: SessionSpendTracker,
        root_session_id: str,
        parent_session_id: str | None,
    ) -> None:
        """Save a snapshot of the tracker to durable storage."""
        store = self._get_store()
        if not store:
            return
        data = self._extract_tracker_snapshot_dict(tracker)
        cfg_json = json.dumps(self._config.to_dict(), ensure_ascii=False)
        ok = store.save_session_snapshot(
            session_id=tracker.session_id,
            root_session_id=root_session_id,
            parent_session_id=parent_session_id,
            tracker_data=data,
            budget_config_json=cfg_json,
        )
        if not ok:
            tracker.persistence_failed = True

    def _get_or_create_tracker(self, session_id: str) -> SessionSpendTracker:
        with self._lock:
            sid = session_id or "default"
            if sid in self._sessions:
                return self._sessions[sid]

            store = self._get_store()
            tracker = None
            if store:
                try:
                    snapshot = store.load_session_snapshot(sid)
                    if snapshot:
                        tracker = self._hydrate_tracker_from_snapshot(sid, snapshot)
                except Exception as exc:
                    log.error("Failed hydrating session %s: %s", sid, exc)

            if tracker is None:
                tracker = SessionSpendTracker(session_id=sid)
                if store:
                    try:
                        stored_parent = store.get_parent_session(sid)
                        if stored_parent:
                            self._parent_sessions[sid] = stored_parent
                        root_id = self.get_root_session_id(sid)
                        unresolved = store.recover_interrupted_reservations_on_startup(root_id)
                        for res in unresolved:
                            if res.get("session_id") == sid or sid == root_id:
                                rid = res["reservation_id"]
                                tracker.reservations[rid] = BudgetReservation(
                                    reservation_id=rid,
                                    session_id=res["session_id"],
                                    estimated_cost_inr=Decimal(str(res["estimated_cost_inr"])),
                                    estimated_tokens=int(res["estimated_tokens"]),
                                    purpose=res.get("purpose", "work"),
                                    active=True,
                                    status=res.get("status", "uncertain"),
                                )
                    except Exception as exc:
                        log.error("Failed loading unresolved reservations on fresh tracker: %s", exc)

            self._sessions[sid] = tracker
            return tracker

    def reset_session(self, session_id: str) -> None:
        with self._lock:
            sid = session_id or "default"
            if sid in self._sessions:
                del self._sessions[sid]
            self._parent_sessions = {c: p for c, p in self._parent_sessions.items() if c != sid and p != sid}

    def start_turn(self, session_id: str) -> None:
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            tracker.next_turn()
            root_id = self.get_root_session_id(session_id)
            self._persist_session_snapshot(tracker, root_id, self._parent_sessions.get(session_id))

    def get_tracker(self, session_id: str) -> SessionSpendTracker:
        """Public accessor to get or hydrate the tracker for a session."""
        return self._get_or_create_tracker(session_id)

    def advance_turn(self, session_id: str) -> None:
        """Advance to the next turn for a session."""
        self.start_turn(session_id)

    # --------------------------------------------------------------------------
    # CANONICAL CURRENCY CONVERSION (Matching pricing.py)
    # --------------------------------------------------------------------------

    def usd_to_inr(self, usd_val: float | Decimal | None, apply_forex_fees: bool = True) -> Decimal | None:
        """Convert USD to INR using canonical exchange rate and gateway fees."""
        if usd_val is None:
            return None
        dec_usd = _to_decimal(usd_val)
        rate = self._config.usd_to_inr_rate
        if apply_forex_fees:
            effective_rate = rate * _FOREX_SPREAD * _GATEWAY_FEE
        else:
            effective_rate = rate
        return _quantize_currency(dec_usd * effective_rate)

    def inr_to_usd(self, inr_val: float | Decimal | None, apply_forex_fees: bool = False) -> Decimal | None:
        """Convert INR to USD using canonical rate without double fee deductions."""
        if inr_val is None:
            return None
        dec_inr = _to_decimal(inr_val)
        rate = self._config.usd_to_inr_rate
        if rate <= Decimal("0"):
            return Decimal("0.000000")
        if apply_forex_fees:
            divisor = rate * _FOREX_SPREAD * _GATEWAY_FEE
        else:
            divisor = rate
        return _quantize_currency(dec_inr / divisor)

    def estimate_tokens_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        cache_write_tokens: int = 0,
        rate_card: dict | None = None,
    ) -> tuple[Decimal | None, Decimal | None, str, bool]:
        """
        Estimate USD and INR cost for given token counts using telemetry rate card.
        Returns: (cost_usd, cost_inr, currency, cost_known)
        """
        try:
            from src.telemetry.call_ledger import estimate_cost_from_rate
            cost, currency = estimate_cost_from_rate(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                cache_reported=cached_tokens > 0,
                cache_write_tokens=cache_write_tokens,
                cache_write_reported=cache_write_tokens > 0,
                rate_card=rate_card,
            )
            if cost is None:
                return None, None, currency or "", False

            dec_cost = _to_decimal(cost)
            curr = str(currency or "USD").upper()
            if curr == "INR":
                cost_inr = _quantize_currency(dec_cost)
                cost_usd = self.inr_to_usd(cost_inr, apply_forex_fees=False)
                return cost_usd, cost_inr, "INR", True
            else:
                cost_usd = _quantize_currency(dec_cost)
                cost_inr = self.usd_to_inr(cost_usd, apply_forex_fees=True)
                return cost_usd, cost_inr, "USD", True
        except Exception:
            return None, None, "", False

    # --------------------------------------------------------------------------
    # BUDGET RESERVATION & HEADROOM (Root Session Enforced)
    # --------------------------------------------------------------------------

    def reserve(
        self,
        session_id: str,
        estimated_cost_inr: Decimal | float,
        estimated_tokens: int = 4000,
        purpose: str = "work",
        reservation_id: str | None = None,
    ) -> tuple[bool, str, str]:
        """Attempt to reserve budget for a planned model call or tool cycle."""
        cfg = self.get_effective_config(session_id)
        if not cfg.enabled:
            rid = reservation_id or f"res_{int(time.time()*1000)}"
            return True, rid, "governance_disabled"

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            if root_tracker.persistence_failed:
                return False, "", "persistence_failure"

            dec_cost = _to_decimal(estimated_cost_inr)
            rid = reservation_id or f"res_{int(time.time()*1000)}_{uuid.uuid4().hex[:12]}"

            is_final = purpose in {"final_response", "reserve", "summary"}

            rem_session_cost = cfg.per_session_cost_budget_inr - root_tracker.session_cost_inr - root_tracker.total_reserved_inr()
            rem_turn_cost = cfg.per_turn_cost_budget_inr - root_tracker.turn_cost_inr - root_tracker.total_reserved_inr()
            rem_session_tokens = cfg.per_session_token_budget - root_tracker.session_tokens - root_tracker.total_reserved_tokens()
            rem_turn_tokens = cfg.per_turn_token_budget - root_tracker.turn_tokens - root_tracker.total_reserved_tokens()

            headroom_cost = Decimal("0.000000") if is_final else cfg.reserve_budget_inr
            headroom_tokens = 0 if is_final else cfg.reserve_tokens

            if (rem_session_cost - dec_cost) < headroom_cost:
                return False, "", f"Insufficient root session monetary budget (needed ₹{dec_cost}, headroom ₹{headroom_cost})"

            if (rem_turn_cost - dec_cost) < headroom_cost:
                return False, "", f"Insufficient turn monetary budget (needed ₹{dec_cost}, headroom ₹{headroom_cost})"

            if (rem_session_tokens - estimated_tokens) < headroom_tokens:
                return False, "", f"Insufficient root session token budget (needed {estimated_tokens}, headroom {headroom_tokens})"

            if (rem_turn_tokens - estimated_tokens) < headroom_tokens:
                return False, "", f"Insufficient turn token budget (needed {estimated_tokens}, headroom {headroom_tokens})"

            res = BudgetReservation(
                reservation_id=rid,
                session_id=root_id,
                estimated_cost_inr=dec_cost,
                estimated_tokens=estimated_tokens,
                purpose=purpose,
                active=True,
                status="reserved",
            )
            root_tracker.reservations[rid] = res

            store = self._get_store()
            if store:
                store.save_reservation(
                    reservation_id=rid,
                    root_session_id=root_id,
                    session_id=session_id,
                    turn_id=root_tracker.current_turn_id,
                    estimated_cost_inr=dec_cost,
                    estimated_tokens=estimated_tokens,
                    purpose=purpose,
                    status="reserved",
                )
                self._persist_session_snapshot(root_tracker, root_id, None)
            return True, rid, "ok"

    def release_reservation(self, session_id: str, reservation_id: str) -> None:
        """Release an unused reservation from the root tracker."""
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            if reservation_id in root_tracker.reservations:
                del root_tracker.reservations[reservation_id]
            store = self._get_store()
            if store:
                store.update_reservation_status(reservation_id, "released")

    def reservation_context(
        self,
        session_id: str,
        estimated_cost_inr: Decimal | float,
        estimated_tokens: int = 4000,
        purpose: str = "work",
    ) -> ReservationContext:
        """Context manager for leak-proof reservation lifecycle."""
        return ReservationContext(
            governor=self,
            session_id=session_id,
            estimated_cost_inr=estimated_cost_inr,
            estimated_tokens=estimated_tokens,
            purpose=purpose,
        )

    def reservation(
        self,
        session_id: str,
        estimated_cost_inr: Decimal | float,
        estimated_tokens: int = 4000,
        purpose: str = "work",
    ) -> ReservationContext:
        """Alias for reservation_context."""
        return self.reservation_context(session_id, estimated_cost_inr, estimated_tokens, purpose)

    def get_active_reservations_inr(self, session_id: str) -> Decimal:
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            return tracker.total_reserved_inr()

    # --------------------------------------------------------------------------
    # MODEL CALL ACCOUNTING (Root Session Debited)
    # --------------------------------------------------------------------------

    def record_call(
        self,
        session_id: str,
        provider: str,
        model: str,
        tier: TierType,
        usage: TokenUsage | dict[str, Any],
        duration_s: float = 0.0,
        purpose: str = "work",
        reservation_id: str | None = None,
        event_id: str | None = None,
        _failpoint: str | None = None,
    ) -> ModelCallRecord:
        """
        Record a completed model call, update root session and child accumulators,
        and reconcile any active reservation. Idempotent across restarts.
        """
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            local_tracker = self._get_or_create_tracker(session_id) if root_id != session_id else root_tracker

            if isinstance(usage, dict):
                u = TokenUsage.from_dict(usage)
            else:
                u = usage

            # Idempotency check against durable store
            store = self._get_store()
            call_evt_id = event_id or getattr(u, "event_id", None) or f"evt_{session_id}_{local_tracker.current_turn_id}_{int(time.time()*1000)}_{uuid.uuid4().hex[:12]}"
            if store and store.has_call_event(call_evt_id):
                log.info("Duplicate event %s detected; skipping double debit", call_evt_id)
                # Return existing record from history if found
                for rec in root_tracker.call_history:
                    if rec.call_id == call_evt_id:
                        return rec
                return ModelCallRecord(
                    call_id=call_evt_id, session_id=session_id, turn_id=local_tracker.current_turn_id,
                    timestamp=time.time(), provider=provider, model=model, tier=tier,
                    input_tokens=u.prompt_tokens, output_tokens=u.completion_tokens,
                    cached_tokens=u.cached_tokens, total_tokens=u.total_tokens,
                    cache_write_tokens=getattr(u, "cache_write_tokens", 0),
                    cost_usd=None, cost_inr=None, cost_known=True,
                )

            # Reconcile reservation in-memory on ROOT tracker (durable update is performed atomically below)
            if reservation_id and reservation_id in root_tracker.reservations:
                del root_tracker.reservations[reservation_id]

            cost_known = bool(u.cost_known)
            if cost_known and u.estimated_cost_usd is not None:
                dec_usd = _to_decimal(u.estimated_cost_usd)
                dec_inr = self.usd_to_inr(dec_usd, apply_forex_fees=True)
            else:
                dec_usd = None
                dec_inr = None

            record = ModelCallRecord(
                call_id=call_evt_id,
                session_id=session_id,
                turn_id=local_tracker.current_turn_id,
                timestamp=time.time(),
                provider=provider,
                model=model,
                tier=tier,
                input_tokens=u.prompt_tokens,
                output_tokens=u.completion_tokens,
                cached_tokens=u.cached_tokens,
                cache_write_tokens=getattr(u, "cache_write_tokens", 0),
                total_tokens=u.total_tokens,
                cost_usd=dec_usd,
                cost_inr=dec_inr,
                cost_known=cost_known,
                duration_s=duration_s,
                purpose=purpose,
            )

            def _apply_spend(tracker: SessionSpendTracker):
                tracker.session_tokens += u.total_tokens
                tracker.session_cached_tokens += u.cached_tokens
                tracker.session_cache_write_tokens += getattr(u, "cache_write_tokens", 0)
                tracker.turn_tokens += u.total_tokens
                tracker.turn_cached_tokens += u.cached_tokens
                tracker.turn_cache_write_tokens += getattr(u, "cache_write_tokens", 0)
                tracker.cumulative_input_tokens += u.prompt_tokens
                tracker.cumulative_output_tokens += u.completion_tokens
                tracker.total_calls_count += 1

                if dec_usd is not None and dec_inr is not None:
                    tracker.session_cost_usd += dec_usd
                    tracker.session_cost_inr += dec_inr
                    tracker.turn_cost_usd += dec_usd
                    tracker.turn_cost_inr += dec_inr
                else:
                    tracker.session_has_unknown_spend = True
                    tracker.turn_has_unknown_spend = True
                    tracker.unrated_calls_session += 1
                    tracker.unrated_calls_turn += 1
                    tracker.unrated_tokens_session += u.total_tokens
                    tracker.unrated_tokens_turn += u.total_tokens

                if tier == "cheap":
                    tracker.session_calls_cheap += 1
                    tracker.turn_calls_cheap += 1
                elif tier == "standard":
                    tracker.session_calls_standard += 1
                    tracker.turn_calls_standard += 1
                elif tier == "premium":
                    tracker.session_calls_premium += 1
                    tracker.turn_calls_premium += 1

                tracker.call_history.append(record)

            _apply_spend(root_tracker)
            if local_tracker is not root_tracker:
                _apply_spend(local_tracker)

            # Persist event, reservation update, and session snapshots ATOMICALLY in a single SQLite transaction
            if store:
                event_dict = {
                    "event_id": call_evt_id,
                    "root_session_id": root_id,
                    "child_session_id": session_id if session_id != root_id else None,
                    "turn_id": local_tracker.current_turn_id,
                    "provider": provider,
                    "model": model,
                    "tier": tier,
                    "purpose": purpose,
                    "input_tokens": u.prompt_tokens,
                    "output_tokens": u.completion_tokens,
                    "cached_tokens": u.cached_tokens,
                    "cache_write_tokens": getattr(u, "cache_write_tokens", 0),
                    "total_tokens": u.total_tokens,
                    "estimated_cost_usd": str(dec_usd) if dec_usd is not None else None,
                    "estimated_cost_inr": str(dec_inr) if dec_inr is not None else None,
                    "actual_cost_usd": str(dec_usd) if dec_usd is not None else None,
                    "actual_cost_inr": str(dec_inr) if dec_inr is not None else None,
                    "cost_known": cost_known,
                    "pricing_status": "fresh",
                    "reservation_id": reservation_id,
                    "call_outcome": "completed",
                    "created_at": time.time(),
                }
                cfg_json = json.dumps(self._config.to_dict(), ensure_ascii=False)
                root_snap = {
                    "session_id": root_id,
                    "root_session_id": root_id,
                    "parent_session_id": None,
                    "tracker_data": self._extract_tracker_snapshot_dict(root_tracker),
                    "budget_config_json": cfg_json,
                }
                child_snap = (
                    {
                        "session_id": session_id,
                        "root_session_id": root_id,
                        "parent_session_id": self._parent_sessions.get(session_id),
                        "tracker_data": self._extract_tracker_snapshot_dict(local_tracker),
                        "budget_config_json": cfg_json,
                    }
                    if local_tracker is not root_tracker
                    else None
                )
                parent_link = (
                    (session_id, self._parent_sessions.get(session_id))
                    if (session_id != root_id and self._parent_sessions.get(session_id))
                    else None
                )
                ok = store.record_call_and_snapshot(
                    event_dict=event_dict,
                    root_snapshot=root_snap,
                    child_snapshot=child_snap,
                    reservation_id=reservation_id,
                    parent_link=parent_link,
                    _failpoint=_failpoint,
                )
                if not ok:
                    root_tracker.persistence_failed = True
                    if local_tracker is not root_tracker:
                        local_tracker.persistence_failed = True

            return record

    def track_auxiliary_call(
        self,
        session_id: str,
        provider: str,
        model: str,
        messages_or_prompt: Any,
        response: Any,
        purpose: str = "auxiliary",
    ) -> Optional[ModelCallRecord]:
        """Track auxiliary / background LLM invocations safely."""
        try:
            from langchain_core.messages import HumanMessage
            from src.context.token_tracker import TokenTracker

            if isinstance(messages_or_prompt, str):
                msgs = [HumanMessage(content=messages_or_prompt)]
            elif isinstance(messages_or_prompt, list):
                msgs = messages_or_prompt
            else:
                msgs = [HumanMessage(content=str(messages_or_prompt))]

            usage = TokenTracker.record_call(msgs, response, model)
            return self.record_call(
                session_id=session_id or "default",
                provider=provider or "aux",
                model=model or "unknown",
                tier="cheap",
                usage=usage,
                purpose=purpose,
            )
        except Exception:
            return None

    # --------------------------------------------------------------------------
    # TIER AFFORDABILITY & ESCALATION GUARD (Root Session Enforced)
    # --------------------------------------------------------------------------

    def can_afford_tier(
        self,
        session_id: str,
        tier: TierType,
        estimated_cost_inr: Decimal | float | None = None,
        estimated_tokens: int = 4000,
        model_name: str | None = None,
    ) -> tuple[bool, TierType, str]:
        """Check if the requested tier can be afforded given root budget, headroom, and call caps."""
        cfg = self.get_effective_config(session_id)
        if not cfg.enabled:
            return True, tier, "ok"

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            if root_tracker.persistence_failed:
                return False, "cheap", "persistence_failure: storage unwritable"

            if tier == "cheap":
                return True, tier, "ok"

            if model_name and cfg.unknown_pricing_policy == "deny":
                _, _, _, cost_known = self.estimate_tokens_cost(model_name, estimated_tokens, 1000)
                if not cost_known:
                    return False, "cheap", "Unrated model blocked under deny unknown_pricing_policy"

            if tier == "premium":
                if root_tracker.turn_calls_premium >= cfg.max_premium_calls_per_turn:
                    return False, "standard", f"Premium call cap reached for this turn ({root_tracker.turn_calls_premium}/{cfg.max_premium_calls_per_turn})"
                if root_tracker.session_calls_premium >= cfg.max_premium_calls_per_session:
                    return False, "standard", f"Premium call cap reached for this session ({root_tracker.session_calls_premium}/{cfg.max_premium_calls_per_session})"

            if estimated_cost_inr is None:
                dec_est = Decimal("1.50") if tier == "premium" else Decimal("0.30")
            else:
                dec_est = _to_decimal(estimated_cost_inr)

            rem_cost = cfg.per_session_cost_budget_inr - root_tracker.session_cost_inr - root_tracker.total_reserved_inr()
            rem_tokens = cfg.per_session_token_budget - root_tracker.session_tokens - root_tracker.total_reserved_tokens()

            if (rem_cost - dec_est) < cfg.reserve_budget_inr or (rem_tokens - estimated_tokens) < cfg.reserve_tokens:
                if tier == "premium":
                    dec_std = Decimal("0.30")
                    if (rem_cost - dec_std) >= cfg.reserve_budget_inr:
                        return False, "standard", "demoting from premium to standard to preserve budget reserve"
                return False, "cheap", "demoting to cheap tier to preserve budget reserve"

            return True, tier, "ok"

    # --------------------------------------------------------------------------
    # BUDGET EXHAUSTION & STATUS INSPECTION (Root Session Enforced)
    # --------------------------------------------------------------------------

    def is_exhausted(self, session_id: str) -> bool:
        """Whether any budget leg on the root tracker or local turn has tripped."""
        cfg = self.get_effective_config(session_id)
        if not cfg.enabled:
            return False

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            if root_tracker.persistence_failed:
                return True

            if cfg.unknown_pricing_policy == "deny" and root_tracker.session_has_unknown_spend:
                return True
            if cfg.unknown_pricing_policy == "token_limited":
                if root_tracker.unrated_calls_turn >= cfg.max_unrated_calls_per_turn:
                    return True
                if root_tracker.unrated_calls_session >= cfg.max_unrated_calls_per_session:
                    return True
                if root_tracker.unrated_tokens_turn >= cfg.max_unrated_tokens_per_turn:
                    return True
                if root_tracker.unrated_tokens_session >= cfg.max_unrated_tokens_per_session:
                    return True

            if root_tracker.session_tokens >= cfg.per_session_token_budget:
                return True
            if root_tracker.turn_tokens >= cfg.per_turn_token_budget:
                return True
            if root_tracker.session_cost_inr >= cfg.per_session_cost_budget_inr:
                return True
            if root_tracker.turn_cost_inr >= cfg.per_turn_cost_budget_inr:
                return True

            if root_id != session_id:
                local_tracker = self._get_or_create_tracker(session_id)
                if local_tracker.turn_tokens >= cfg.per_turn_token_budget:
                    return True
                if local_tracker.turn_cost_inr >= cfg.per_turn_cost_budget_inr:
                    return True

            return False

    def trip_reason(self, session_id: str) -> str:
        """Detailed diagnostic explanation of trip reason."""
        cfg = self.get_effective_config(session_id)
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            parts = []

            if tracker.persistence_failed:
                parts.append("tripped: persistence_failure")

            s_tok = tracker.session_tokens
            s_cap = cfg.per_session_token_budget
            s_cached = tracker.session_cached_tokens
            cached_str = f" ({s_cached:,} cached)" if s_cached else ""
            parts.append(f"root session tokens {s_tok:,}/{s_cap:,}{cached_str}")

            t_tok = tracker.turn_tokens
            t_cap = cfg.per_turn_token_budget
            parts.append(f"turn tokens {t_tok:,}/{t_cap:,}")

            if tracker.session_has_unknown_spend and tracker.session_cost_inr == Decimal("0.000000"):
                parts.append(f"session cost ₹unknown/{cfg.per_session_cost_budget_inr:.2f}")
            else:
                unkn = f" + unrated({tracker.unrated_calls_session} calls)" if tracker.session_has_unknown_spend else ""
                parts.append(f"session cost ₹{tracker.session_cost_inr:.2f}/{cfg.per_session_cost_budget_inr:.2f}{unkn}")

            if tracker.turn_has_unknown_spend and tracker.turn_cost_inr == Decimal("0.000000"):
                parts.append(f"turn cost ₹unknown/{cfg.per_turn_cost_budget_inr:.2f}")
            else:
                unkn = f" + unrated({tracker.unrated_calls_turn} calls)" if tracker.turn_has_unknown_spend else ""
                parts.append(f"turn cost ₹{tracker.turn_cost_inr:.2f}/{cfg.per_turn_cost_budget_inr:.2f}{unkn}")

            if cfg.unknown_pricing_policy == "deny" and tracker.session_has_unknown_spend:
                parts.append("tripped: unrated_denied")
            elif cfg.unknown_pricing_policy == "token_limited" and (
                tracker.unrated_calls_turn >= cfg.max_unrated_calls_per_turn
                or tracker.unrated_calls_session >= cfg.max_unrated_calls_per_session
                or tracker.unrated_tokens_turn >= cfg.max_unrated_tokens_per_turn
                or tracker.unrated_tokens_session >= cfg.max_unrated_tokens_per_session
            ):
                parts.append("tripped: unrated_limits")
            elif s_tok >= s_cap:
                parts.append("tripped: session_tokens")
            elif t_tok >= t_cap:
                parts.append("tripped: turn_tokens")
            elif tracker.session_cost_inr >= cfg.per_session_cost_budget_inr:
                parts.append("tripped: session_cost")
            elif tracker.turn_cost_inr >= cfg.per_turn_cost_budget_inr:
                parts.append("tripped: turn_cost")
            elif tracker.persistence_failed:
                pass
            else:
                parts.append("tripped: none")

            return ", ".join(parts)

    def get_status(self, session_id: str) -> GovernanceStatus:
        if self.is_exhausted(session_id):
            return "exhausted"

        cfg = self.get_effective_config(session_id)
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            near_cost = (tracker.session_cost_inr >= cfg.per_session_cost_budget_inr * Decimal("0.85")
                         or tracker.turn_cost_inr >= cfg.per_turn_cost_budget_inr * Decimal("0.85"))
            near_tokens = (tracker.session_tokens >= cfg.per_session_token_budget * 0.85
                           or tracker.turn_tokens >= cfg.per_turn_token_budget * 0.85)
            if near_cost or near_tokens:
                return "near_limit"
            return "healthy"

    # --------------------------------------------------------------------------
    # UNCERTAIN RESERVATION RESOLUTION & RECONCILIATION (Phase 9.1.6)
    # --------------------------------------------------------------------------

    def get_uncertain_reservations_for_review(
        self,
        root_session_id: str | None = None,
        min_age_seconds: float = 1800.0,
    ) -> list[dict[str, Any]]:
        """
        Query uncertain reservations that are eligible for review (> 30 mins).
        Safety principle: These reservations retain headroom and are NEVER automatically released.
        """
        store = self._get_store()
        if not store:
            return []
        return store.get_reservations_eligible_for_reconciliation(min_age_seconds=min_age_seconds)

    def resolve_uncertain_reservation(
        self,
        session_id: str,
        reservation_id: str,
        action: str,
        actual_cost_inr: Decimal | float | None = None,
        resolution_notes: str = "",
        resolved_by: str = "admin",
    ) -> tuple[bool, str]:
        """
        Stage C resolution: explicitly resolve an uncertain reservation.
        Supported actions:
        - 'release': Verified non-execution. Headroom is safely unlocked.
        - 'reconcile': Verified execution. Debit actual cost and clear reservation.

        Safety: Never allows duplicate resolution; rejects invalid state transitions.
        """
        action_clean = str(action).strip().lower()
        if action_clean not in {"release", "reconcile"}:
            return False, f"Invalid resolution action '{action}'. Must be 'release' or 'reconcile'."

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)

            store = self._get_store()
            if store:
                ok, msg = store.resolve_uncertain_reservation(
                    reservation_id=reservation_id,
                    action=action_clean,
                    actual_cost_inr=actual_cost_inr,
                    resolution_notes=resolution_notes,
                    resolved_by=resolved_by,
                )
                if not ok:
                    return False, msg

            # Update in-memory tracker
            if reservation_id in root_tracker.reservations:
                del root_tracker.reservations[reservation_id]

            if action_clean == "reconcile" and actual_cost_inr is not None:
                dec_cost = _to_decimal(actual_cost_inr)
                root_tracker.session_cost_inr += dec_cost
                root_tracker.turn_cost_inr += dec_cost

            if store:
                self._persist_session_snapshot(root_tracker, root_id, None)

            log.info(
                "Uncertain reservation %s resolved via %s in session %s",
                reservation_id, action_clean, root_id
            )
            return True, f"Reservation '{reservation_id}' resolved via {action_clean}."

    def get_compact_summary(self, session_id: str) -> str:
        """Generate a compact user-facing summary string with '₹' and token breakdown."""
        cfg = self.get_effective_config(session_id)
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            status = self.get_status(root_id).upper()

            if tracker.session_has_unknown_spend and tracker.session_cost_inr == Decimal("0.000000"):
                cost_str = f"₹unknown / ₹{cfg.per_session_cost_budget_inr:.2f}"
            else:
                pct = int((tracker.session_cost_inr / cfg.per_session_cost_budget_inr) * 100) if cfg.per_session_cost_budget_inr > 0 else 0
                unkn = f" (+{tracker.unrated_calls_session} unrated)" if tracker.session_has_unknown_spend else ""
                cost_str = f"₹{tracker.session_cost_inr:.2f} / ₹{cfg.per_session_cost_budget_inr:.2f} ({pct}%){unkn}"

            if tracker.turn_has_unknown_spend and tracker.turn_cost_inr == Decimal("0.000000"):
                turn_str = f"₹unknown / ₹{cfg.per_turn_cost_budget_inr:.2f}"
            else:
                turn_str = f"₹{tracker.turn_cost_inr:.2f} / ₹{cfg.per_turn_cost_budget_inr:.2f}"

            tok_str = f"{tracker.session_tokens:,} / {cfg.per_session_token_budget:,}"
            if tracker.session_cached_tokens:
                tok_str += f" ({tracker.session_cached_tokens:,} cached)"

            tot_calls = len(tracker.call_history) or tracker.total_calls_count
            calls_str = f"{tot_calls} (cheap: {tracker.session_calls_cheap}, standard: {tracker.session_calls_standard}, premium: {tracker.session_calls_premium})"

            root_prefix = f"Root [{root_id[:12]}] " if root_id != session_id else ""
            return (
                f"[Cost Governance] {root_prefix}Session: {cost_str} | Turn: {turn_str} | "
                f"Tokens: {tok_str} | Calls: {calls_str} | Status: {status}"
            )

    def get_call_history(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            if tracker.call_history:
                return [r.to_dict() for r in tracker.call_history]
            store = self._get_store()
            if store:
                return store.get_session_call_history(root_id)
            return []


# Global singleton instance
cost_governor = CostGovernor()

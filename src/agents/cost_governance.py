"""
Cost & Token Governance for Crusor AI Agent Core (Remediated Phase 9.1.2)
========================================================================
Central governance engine providing financial predictability, token discipline,
model tier escalation controls, headroom reservation, root-session inheritance,
and strict accounting for all agent and auxiliary model calls.

Guarantees:
- Root Session Inheritance: Every child/subagent inherits and debits the root parent session budget.
- Deterministic Reservation Lifecycle: Automatic release on error/abort; zero reservation leakage.
- Unknown Pricing Enforcement: Configurable policies (deny, token_limited, explicit_allow).
- Currency Consistency: Canonical Decimal conversion matching pricing.py (forex spread 1.005, gateway fee 1.07).
- Zero Drift Arithmetic: All accounting in exact Decimal (0.000001 precision).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from src.context.token_tracker import TokenUsage

TierType = Literal["cheap", "standard", "premium"]
GovernanceStatus = Literal["healthy", "near_limit", "exhausted"]
UnknownPricingPolicy = Literal["deny", "token_limited", "explicit_allow"]

# Default exchange rate and constants (matching src/telemetry/pricing.py)
_DEFAULT_USD_TO_INR = 86.0
_FOREX_SPREAD = 1.005
_GATEWAY_FEE = 1.07


def _quantize_currency(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _to_decimal(val: float | int | str | Decimal | None) -> Decimal:
    if val is None:
        return Decimal("0.000000")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0.000000")


@dataclass
class CostGovernanceConfig:
    """Configuration for cost and token governance."""
    enabled: bool = True
    target_simple_task_cost_inr: Decimal = field(default_factory=lambda: Decimal("5.00"))
    per_turn_token_budget: int = 150_000
    per_session_token_budget: int = 600_000
    per_turn_cost_budget_inr: Decimal = field(default_factory=lambda: Decimal("25.00"))
    per_session_cost_budget_inr: Decimal = field(default_factory=lambda: Decimal("86.00"))
    reserve_budget_inr: Decimal = field(default_factory=lambda: Decimal("2.00"))
    reserve_tokens: int = 20_000
    usd_to_inr_rate: Decimal = field(default_factory=lambda: Decimal(str(_DEFAULT_USD_TO_INR)))
    max_premium_calls_per_turn: int = 3
    max_premium_calls_per_session: int = 10

    # Unknown pricing governance
    unknown_pricing_policy: UnknownPricingPolicy = "token_limited"
    max_unrated_calls_per_turn: int = 5
    max_unrated_calls_per_session: int = 15
    max_unrated_tokens_per_turn: int = 50_000
    max_unrated_tokens_per_session: int = 150_000

    @classmethod
    def from_env(cls) -> "CostGovernanceConfig":
        raw_enabled = os.environ.get("CRUSORAI_COST_GOVERNANCE", "on").strip().lower()
        enabled = raw_enabled not in {"off", "0", "false", "no"}

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

        # USD to INR conversion rate
        fx = _env_dec("CRUSORAI_USD_INR", str(_DEFAULT_USD_TO_INR))

        # Check if session cost budget is in USD (AGENT_COST_BUDGET)
        agent_cost_usd_raw = os.environ.get("AGENT_COST_BUDGET")
        if agent_cost_usd_raw:
            try:
                # Billing multiplier includes forex spread and gateway fee
                multiplier = fx * Decimal(str(_FOREX_SPREAD)) * Decimal(str(_GATEWAY_FEE))
                session_inr = _quantize_currency(Decimal(agent_cost_usd_raw) * multiplier)
            except Exception:
                session_inr = Decimal("86.00")
        else:
            session_inr = _env_dec("CRUSORAI_SESSION_COST_BUDGET_INR", "86.00")

        # Session token budget
        session_tokens = _env_int("CRUSORAI_SESSION_TOKEN_BUDGET",
                                  _env_int("AGENT_TOKEN_BUDGET", 600_000))

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
    duration_s: float
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
    created_at: float = field(default_factory=time.time)


@dataclass
class SessionSpendTracker:
    """Thread-safe accounting tracker for a session and its turns."""
    session_id: str
    current_turn_id: int = 1

    # Session cumulative
    session_tokens: int = 0
    session_cached_tokens: int = 0
    session_cost_inr: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    session_cost_usd: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    session_has_unknown_spend: bool = False
    session_calls_cheap: int = 0
    session_calls_standard: int = 0
    session_calls_premium: int = 0

    # Current turn cumulative
    turn_tokens: int = 0
    turn_cached_tokens: int = 0
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

    def __enter__(self) -> "ReservationContext":
        self.ok, self.reservation_id, self.reason = self.governor.reserve(
            session_id=self.session_id,
            estimated_cost_inr=self.estimated_cost_inr,
            estimated_tokens=self.estimated_tokens,
            purpose=self.purpose,
        )
        return self

    def mark_reconciled(self) -> None:
        self.is_reconciled = True

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.reservation_id and not self.is_reconciled:
            self.governor.release_reservation(self.session_id, self.reservation_id)


class CostGovernor:
    """
    Central financial and token governor for Crusor AI Agent Core.
    Guarantees root session budget inheritance, financial predictability,
    headroom preservation, and zero arithmetic drift.
    """

    def __init__(self, config: CostGovernanceConfig | None = None):
        self._config = config or CostGovernanceConfig.from_env()
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionSpendTracker] = {}
        self._parent_sessions: dict[str, str] = {}

    def get_config(self) -> CostGovernanceConfig:
        return self._config

    def reload_config(self) -> None:
        with self._lock:
            self._config = CostGovernanceConfig.from_env()

    def is_enabled(self) -> bool:
        return self._config.enabled

    # --------------------------------------------------------------------------
    # ROOT SESSION HIERARCHY
    # --------------------------------------------------------------------------

    def register_parent_session(self, child_session_id: str, parent_session_id: str) -> None:
        """Register parent linkage for a delegated subagent session."""
        if not child_session_id or not parent_session_id or child_session_id == parent_session_id:
            return
        with self._lock:
            self._parent_sessions[str(child_session_id)] = str(parent_session_id)

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
                if not parent and current.startswith("sub-"):
                    # Dynamic discovery from persistent store
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

    def _get_or_create_tracker(self, session_id: str) -> SessionSpendTracker:
        sid = session_id or "default"
        if sid not in self._sessions:
            self._sessions[sid] = SessionSpendTracker(session_id=sid)
        return self._sessions[sid]

    def reset_session(self, session_id: str) -> None:
        with self._lock:
            sid = session_id or "default"
            if sid in self._sessions:
                del self._sessions[sid]
            # Remove any parent links referencing sid
            self._parent_sessions = {c: p for c, p in self._parent_sessions.items() if c != sid and p != sid}

    def start_turn(self, session_id: str) -> None:
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            tracker.next_turn()

    # --------------------------------------------------------------------------
    # CANONICAL CURRENCY CONVERSION (Matching pricing.py)
    # --------------------------------------------------------------------------

    def usd_to_inr(self, usd_val: float | Decimal | None, apply_forex_fees: bool = True) -> Decimal | None:
        """Convert USD to INR using canonical exchange rate and gateway fees."""
        if usd_val is None:
            return None
        dec_usd = _to_decimal(usd_val)
        fx = self._config.usd_to_inr_rate
        if apply_forex_fees:
            multiplier = fx * Decimal(str(_FOREX_SPREAD)) * Decimal(str(_GATEWAY_FEE))
        else:
            multiplier = fx
        return _quantize_currency(dec_usd * multiplier)

    def inr_to_usd(self, inr_val: float | Decimal | None, apply_forex_fees: bool = True) -> Decimal | None:
        """Convert INR to USD using canonical exchange rate and gateway fees."""
        if inr_val is None:
            return None
        dec_inr = _to_decimal(inr_val)
        fx = self._config.usd_to_inr_rate
        if fx <= Decimal("0"):
            return Decimal("0.000000")
        if apply_forex_fees:
            multiplier = fx * Decimal(str(_FOREX_SPREAD)) * Decimal(str(_GATEWAY_FEE))
        else:
            multiplier = fx
        return _quantize_currency(dec_inr / multiplier)

    def estimate_tokens_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
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
                rate_card=rate_card,
            )
            if cost is None:
                return None, None, currency or "", False

            dec_cost = _to_decimal(cost)
            curr = str(currency or "USD").upper()
            if curr == "INR":
                # Catalog already converted with forex fees: use INR directly
                cost_inr = _quantize_currency(dec_cost)
                cost_usd = self.inr_to_usd(cost_inr, apply_forex_fees=False)
                return cost_usd, cost_inr, "INR", True
            else:
                cost_usd = _quantize_currency(dec_cost)
                # Apply canonical billing multiplier to USD cost
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
        """
        Attempt to reserve budget for a planned model call or tool cycle.
        Always debits and enforces against the ROOT session tracker!
        """
        if not self._config.enabled:
            rid = reservation_id or f"res_{int(time.time()*1000)}"
            return True, rid, "governance_disabled"

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            dec_cost = _to_decimal(estimated_cost_inr)
            rid = reservation_id or f"res_{int(time.time()*1000)}"

            # Final response always gets reserved if headroom remains
            is_final = purpose in {"final_response", "reserve", "summary"}

            # Calculate remaining against ROOT tracker
            rem_session_cost = self._config.per_session_cost_budget_inr - root_tracker.session_cost_inr - root_tracker.total_reserved_inr()
            rem_turn_cost = self._config.per_turn_cost_budget_inr - root_tracker.turn_cost_inr - root_tracker.total_reserved_inr()
            rem_session_tokens = self._config.per_session_token_budget - root_tracker.session_tokens - root_tracker.total_reserved_tokens()
            rem_turn_tokens = self._config.per_turn_token_budget - root_tracker.turn_tokens - root_tracker.total_reserved_tokens()

            headroom_cost = Decimal("0.000000") if is_final else self._config.reserve_budget_inr
            headroom_tokens = 0 if is_final else self._config.reserve_tokens

            if (rem_session_cost - dec_cost) < headroom_cost:
                return False, "", f"Insufficient root session monetary budget (needed ₹{dec_cost}, headroom ₹{headroom_cost})"

            if (rem_turn_cost - dec_cost) < headroom_cost:
                return False, "", f"Insufficient turn monetary budget (needed ₹{dec_cost}, headroom ₹{headroom_cost})"

            if (rem_session_tokens - estimated_tokens) < headroom_tokens:
                return False, "", f"Insufficient root session token budget (needed {estimated_tokens}, headroom {headroom_tokens})"

            if (rem_turn_tokens - estimated_tokens) < headroom_tokens:
                return False, "", f"Insufficient turn token budget (needed {estimated_tokens}, headroom {headroom_tokens})"

            # Store reservation on ROOT tracker
            res = BudgetReservation(
                reservation_id=rid,
                session_id=root_id,
                estimated_cost_inr=dec_cost,
                estimated_tokens=estimated_tokens,
                purpose=purpose,
            )
            root_tracker.reservations[rid] = res
            return True, rid, "ok"

    def release_reservation(self, session_id: str, reservation_id: str) -> None:
        """Release an unused reservation from the root tracker."""
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            if reservation_id in root_tracker.reservations:
                del root_tracker.reservations[reservation_id]

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

    # --------------------------------------------------------------------------
    # RECORD CALL & RECONCILIATION
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
    ) -> ModelCallRecord:
        """
        Record a completed model call, update root session and child accumulators,
        and reconcile any active reservation.
        """
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)
            local_tracker = self._get_or_create_tracker(session_id) if root_id != session_id else root_tracker

            # Release reservation on ROOT tracker
            if reservation_id and reservation_id in root_tracker.reservations:
                del root_tracker.reservations[reservation_id]

            if isinstance(usage, dict):
                u = TokenUsage.from_dict(usage)
            else:
                u = usage

            # Extract costs
            cost_known = bool(u.cost_known)
            if cost_known and u.estimated_cost_usd is not None:
                dec_usd = _to_decimal(u.estimated_cost_usd)
                dec_inr = self.usd_to_inr(dec_usd, apply_forex_fees=True)
            else:
                dec_usd = None
                dec_inr = None

            call_id = f"call_{len(root_tracker.call_history)+1}_{int(time.time()*1000)}"
            record = ModelCallRecord(
                call_id=call_id,
                session_id=session_id,
                turn_id=local_tracker.current_turn_id,
                timestamp=time.time(),
                provider=provider,
                model=model,
                tier=tier,
                input_tokens=u.prompt_tokens,
                output_tokens=u.completion_tokens,
                cached_tokens=u.cached_tokens,
                total_tokens=u.total_tokens,
                cost_usd=dec_usd,
                cost_inr=dec_inr,
                cost_known=cost_known,
                duration_s=duration_s,
                purpose=purpose,
            )

            # Update helper for a tracker
            def _apply_spend(tracker: SessionSpendTracker):
                tracker.session_tokens += u.total_tokens
                tracker.session_cached_tokens += u.cached_tokens
                tracker.turn_tokens += u.total_tokens
                tracker.turn_cached_tokens += u.cached_tokens

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

            # Always apply to ROOT tracker
            _apply_spend(root_tracker)
            # If child session, also track locally for child diagnostics
            if local_tracker is not root_tracker:
                _apply_spend(local_tracker)

            return record

    def track_auxiliary_call(
        self,
        session_id: str,
        provider: str,
        model: str,
        messages_or_prompt: Any,
        response: Any,
        purpose: str = "auxiliary",
    ) -> ModelCallRecord | None:
        """
        Reusable tracking helper for auxiliary / housekeeping LLM calls.
        Safe: never raises, never breaks the caller.
        """
        if not self._config.enabled:
            return None
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
        """
        Check if the requested tier can be afforded given root budget, headroom, and call caps.
        """
        if not self._config.enabled or tier == "cheap":
            return True, tier, "ok"

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)

            # Check unknown pricing policy if model is specified
            if model_name and self._config.unknown_pricing_policy == "deny":
                _, _, _, cost_known = self.estimate_tokens_cost(model_name, estimated_tokens, 1000)
                if not cost_known:
                    return False, "cheap", "Unrated model blocked under deny unknown_pricing_policy"

            # Check premium call count limits against ROOT tracker
            if tier == "premium":
                if root_tracker.turn_calls_premium >= self._config.max_premium_calls_per_turn:
                    return False, "standard", f"Premium call cap reached for this turn ({root_tracker.turn_calls_premium}/{self._config.max_premium_calls_per_turn})"
                if root_tracker.session_calls_premium >= self._config.max_premium_calls_per_session:
                    return False, "standard", f"Premium call cap reached for this session ({root_tracker.session_calls_premium}/{self._config.max_premium_calls_per_session})"

            # Estimate cost if not provided
            if estimated_cost_inr is None:
                dec_est = Decimal("1.50") if tier == "premium" else Decimal("0.30")
            else:
                dec_est = _to_decimal(estimated_cost_inr)

            # Check remaining against ROOT tracker
            avail_session = self._config.per_session_cost_budget_inr - root_tracker.session_cost_inr - root_tracker.total_reserved_inr()
            avail_turn = self._config.per_turn_cost_budget_inr - root_tracker.turn_cost_inr - root_tracker.total_reserved_inr()

            if (avail_session - dec_est) < self._config.reserve_budget_inr or (avail_turn - dec_est) < self._config.reserve_budget_inr:
                demoted: TierType = "standard" if tier == "premium" else "cheap"
                return False, demoted, f"Tier {tier} exceeds budget headroom; demoting to {demoted}"

            # Token check against ROOT tracker
            avail_tokens_session = self._config.per_session_token_budget - root_tracker.session_tokens - root_tracker.total_reserved_tokens()
            if (avail_tokens_session - estimated_tokens) < self._config.reserve_tokens:
                demoted = "standard" if tier == "premium" else "cheap"
                return False, demoted, f"Tier {tier} exceeds token headroom; demoting to {demoted}"

            return True, tier, "ok"

    # --------------------------------------------------------------------------
    # BUDGET EXHAUSTION & STATUS INSPECTION (Root Session Enforced)
    # --------------------------------------------------------------------------

    def is_exhausted(self, session_id: str) -> bool:
        """Whether any budget leg on the root tracker or local turn has tripped."""
        if not self._config.enabled:
            return False

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            root_tracker = self._get_or_create_tracker(root_id)

            # Unknown pricing policy checks
            if self._config.unknown_pricing_policy == "deny" and root_tracker.session_has_unknown_spend:
                return True
            if self._config.unknown_pricing_policy == "token_limited":
                if root_tracker.unrated_calls_turn >= self._config.max_unrated_calls_per_turn:
                    return True
                if root_tracker.unrated_calls_session >= self._config.max_unrated_calls_per_session:
                    return True
                if root_tracker.unrated_tokens_turn >= self._config.max_unrated_tokens_per_turn:
                    return True
                if root_tracker.unrated_tokens_session >= self._config.max_unrated_tokens_per_session:
                    return True

            # General token and cost ceilings
            if root_tracker.session_tokens >= self._config.per_session_token_budget:
                return True
            if root_tracker.turn_tokens >= self._config.per_turn_token_budget:
                return True
            if root_tracker.session_cost_inr >= self._config.per_session_cost_budget_inr:
                return True
            if root_tracker.turn_cost_inr >= self._config.per_turn_cost_budget_inr:
                return True

            # If child session exists, also enforce local turn caps
            if root_id != session_id:
                local_tracker = self._get_or_create_tracker(session_id)
                if local_tracker.turn_tokens >= self._config.per_turn_token_budget:
                    return True
                if local_tracker.turn_cost_inr >= self._config.per_turn_cost_budget_inr:
                    return True

            return False

    def trip_reason(self, session_id: str) -> str:
        """Detailed diagnostic explanation of trip reason."""
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            parts = []

            # Session tokens
            s_tok = tracker.session_tokens
            s_cap = self._config.per_session_token_budget
            s_cached = tracker.session_cached_tokens
            cached_str = f" ({s_cached:,} cached)" if s_cached else ""
            parts.append(f"root session tokens {s_tok:,}/{s_cap:,}{cached_str}")

            # Turn tokens
            t_tok = tracker.turn_tokens
            t_cap = self._config.per_turn_token_budget
            parts.append(f"turn tokens {t_tok:,}/{t_cap:,}")

            # Session cost
            if tracker.session_has_unknown_spend and tracker.session_cost_inr == Decimal("0.000000"):
                parts.append(f"session cost ₹unknown/{self._config.per_session_cost_budget_inr:.2f}")
            else:
                unkn = f" + unrated({tracker.unrated_calls_session} calls)" if tracker.session_has_unknown_spend else ""
                parts.append(f"session cost ₹{tracker.session_cost_inr:.2f}/{self._config.per_session_cost_budget_inr:.2f}{unkn}")

            # Turn cost
            if tracker.turn_has_unknown_spend and tracker.turn_cost_inr == Decimal("0.000000"):
                parts.append(f"turn cost ₹unknown/{self._config.per_turn_cost_budget_inr:.2f}")
            else:
                unkn = f" + unrated({tracker.unrated_calls_turn} calls)" if tracker.turn_has_unknown_spend else ""
                parts.append(f"turn cost ₹{tracker.turn_cost_inr:.2f}/{self._config.per_turn_cost_budget_inr:.2f}{unkn}")

            # Unrated policy check
            if self._config.unknown_pricing_policy == "deny" and tracker.session_has_unknown_spend:
                parts.append("tripped: unrated_denied")
            elif self._config.unknown_pricing_policy == "token_limited" and (
                tracker.unrated_calls_turn >= self._config.max_unrated_calls_per_turn
                or tracker.unrated_calls_session >= self._config.max_unrated_calls_per_session
                or tracker.unrated_tokens_turn >= self._config.max_unrated_tokens_per_turn
                or tracker.unrated_tokens_session >= self._config.max_unrated_tokens_per_session
            ):
                parts.append("tripped: unrated_limits")
            elif s_tok >= s_cap:
                parts.append("tripped: session_tokens")
            elif t_tok >= t_cap:
                parts.append("tripped: turn_tokens")
            elif tracker.session_cost_inr >= self._config.per_session_cost_budget_inr:
                parts.append("tripped: session_cost")
            elif tracker.turn_cost_inr >= self._config.per_turn_cost_budget_inr:
                parts.append("tripped: turn_cost")
            else:
                parts.append("tripped: none")

            return ", ".join(parts)

    def get_status(self, session_id: str) -> GovernanceStatus:
        if self.is_exhausted(session_id):
            return "exhausted"

        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            near_cost = (tracker.session_cost_inr >= self._config.per_session_cost_budget_inr * Decimal("0.85")
                         or tracker.turn_cost_inr >= self._config.per_turn_cost_budget_inr * Decimal("0.85"))
            near_tokens = (tracker.session_tokens >= self._config.per_session_token_budget * 0.85
                           or tracker.turn_tokens >= self._config.per_turn_token_budget * 0.85)
            if near_cost or near_tokens:
                return "near_limit"
            return "healthy"

    def get_compact_summary(self, session_id: str) -> str:
        """Generate a compact user-facing summary string with '₹' and token breakdown."""
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            status = self.get_status(root_id).upper()

            # Session cost string
            if tracker.session_has_unknown_spend and tracker.session_cost_inr == Decimal("0.000000"):
                cost_str = f"₹unknown / ₹{self._config.per_session_cost_budget_inr:.2f}"
            else:
                pct = int((tracker.session_cost_inr / self._config.per_session_cost_budget_inr) * 100) if self._config.per_session_cost_budget_inr > 0 else 0
                unkn = f" (+{tracker.unrated_calls_session} unrated)" if tracker.session_has_unknown_spend else ""
                cost_str = f"₹{tracker.session_cost_inr:.2f} / ₹{self._config.per_session_cost_budget_inr:.2f} ({pct}%){unkn}"

            # Turn cost string
            if tracker.turn_has_unknown_spend and tracker.turn_cost_inr == Decimal("0.000000"):
                turn_str = f"₹unknown / ₹{self._config.per_turn_cost_budget_inr:.2f}"
            else:
                turn_str = f"₹{tracker.turn_cost_inr:.2f} / ₹{self._config.per_turn_cost_budget_inr:.2f}"

            # Tokens string
            tok_str = f"{tracker.session_tokens:,} / {self._config.per_session_token_budget:,}"
            if tracker.session_cached_tokens:
                tok_str += f" ({tracker.session_cached_tokens:,} cached)"

            # Calls string
            tot_calls = len(tracker.call_history)
            calls_str = f"{tot_calls} (cheap: {tracker.session_calls_cheap}, standard: {tracker.session_calls_standard}, premium: {tracker.session_calls_premium})"

            root_prefix = f"Root [{root_id[:12]}] " if root_id != session_id else ""
            return (
                f"[Cost Governance] {root_prefix}Session: {cost_str} | Turn: {turn_str} | "
                f"Tokens: {tok_str} | Calls: {calls_str} | Status: {status}"
            )

    def get_audit_records(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            root_id = self.get_root_session_id(session_id)
            tracker = self._get_or_create_tracker(root_id)
            return [r.to_dict() for r in tracker.call_history]


# Global singleton instance
cost_governor = CostGovernor()

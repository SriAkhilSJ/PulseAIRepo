"""
Cost & Token Governance for Crusor AI Agent Core
=================================================
Central governance engine providing financial predictability, token discipline,
model tier escalation controls, and headroom reservation for agent turns and sessions.

Primary business targets:
- Predictable spend with simple task target of ₹5 (measured using provider rate metadata, not hardcoded).
- Enforce per-turn and per-session budgets for tokens and monetary spend (INR/USD).
- Prevent uncontrolled premium model escalation with automatic graceful demotion.
- Reserve sufficient headroom for final response so agent turns always conclude cleanly.
- Absolute precision: Decimal-backed accounting to eliminate floating-point drift.
- Transparent reporting: unknown provider pricing marked as 'unknown', never treated as free ($0).
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

# Default exchange rate and constants
_DEFAULT_USD_TO_INR = 86.0
_FOREX_SPREAD = 1.005
_GATEWAY_FEE = 1.07

# Rounding helper for Decimal
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
                session_inr = _quantize_currency(Decimal(agent_cost_usd_raw) * fx)
            except Exception:
                session_inr = Decimal("86.00")
        else:
            session_inr = _env_dec("CRUSORAI_SESSION_COST_BUDGET_INR", "86.00")

        # Session token budget
        session_tokens = _env_int("CRUSORAI_SESSION_TOKEN_BUDGET",
                                  _env_int("AGENT_TOKEN_BUDGET", 600_000))

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

    # Active reservations
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
        self.reservations.clear()


class CostGovernor:
    """
    Central financial and token governor for Crusor AI Agent Core.
    Guarantees financial predictability, headroom preservation, and zero arithmetic drift.
    """

    def __init__(self, config: CostGovernanceConfig | None = None):
        self._config = config or CostGovernanceConfig.from_env()
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionSpendTracker] = {}

    def get_config(self) -> CostGovernanceConfig:
        return self._config

    def reload_config(self) -> None:
        with self._lock:
            self._config = CostGovernanceConfig.from_env()

    def is_enabled(self) -> bool:
        return self._config.enabled

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

    def start_turn(self, session_id: str) -> None:
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            tracker.next_turn()

    # --------------------------------------------------------------------------
    # CURRENCY & CONVERSION HELPERS
    # --------------------------------------------------------------------------

    def usd_to_inr(self, usd_val: float | Decimal | None) -> Decimal | None:
        if usd_val is None:
            return None
        dec_usd = _to_decimal(usd_val)
        return _quantize_currency(dec_usd * self._config.usd_to_inr_rate)

    def inr_to_usd(self, inr_val: float | Decimal | None) -> Decimal | None:
        if inr_val is None:
            return None
        dec_inr = _to_decimal(inr_val)
        if self._config.usd_to_inr_rate <= Decimal("0"):
            return Decimal("0.000000")
        return _quantize_currency(dec_inr / self._config.usd_to_inr_rate)

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
                cost_inr = _quantize_currency(dec_cost)
                cost_usd = self.inr_to_usd(cost_inr)
                return cost_usd, cost_inr, "INR", True
            else:
                cost_usd = _quantize_currency(dec_cost)
                cost_inr = self.usd_to_inr(cost_usd)
                return cost_usd, cost_inr, "USD", True
        except Exception:
            return None, None, "", False

    # --------------------------------------------------------------------------
    # BUDGET RESERVATION & HEADROOM
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
        Returns: (success, reservation_id, reason)
        Ensures reserve headroom (₹2.00 / 20k tokens) is protected unless purpose is 'final_response'.
        """
        if not self._config.enabled:
            rid = reservation_id or f"res_{int(time.time()*1000)}"
            return True, rid, "governance_disabled"

        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            dec_cost = _to_decimal(estimated_cost_inr)
            rid = reservation_id or f"res_{int(time.time()*1000)}"

            # Final response always gets reserved if headroom remains
            is_final = purpose in {"final_response", "reserve", "summary"}

            # Calculate remaining before this reservation
            rem_session_cost = self._config.per_session_cost_budget_inr - tracker.session_cost_inr - tracker.total_reserved_inr()
            rem_turn_cost = self._config.per_turn_cost_budget_inr - tracker.turn_cost_inr - tracker.total_reserved_inr()
            rem_session_tokens = self._config.per_session_token_budget - tracker.session_tokens - tracker.total_reserved_tokens()
            rem_turn_tokens = self._config.per_turn_token_budget - tracker.turn_tokens - tracker.total_reserved_tokens()

            headroom_cost = Decimal("0.000000") if is_final else self._config.reserve_budget_inr
            headroom_tokens = 0 if is_final else self._config.reserve_tokens

            if (rem_session_cost - dec_cost) < headroom_cost:
                return False, "", f"Insufficient session monetary budget (needed ₹{dec_cost}, headroom ₹{headroom_cost})"

            if (rem_turn_cost - dec_cost) < headroom_cost:
                return False, "", f"Insufficient turn monetary budget (needed ₹{dec_cost}, headroom ₹{headroom_cost})"

            if (rem_session_tokens - estimated_tokens) < headroom_tokens:
                return False, "", f"Insufficient session token budget (needed {estimated_tokens}, headroom {headroom_tokens})"

            if (rem_turn_tokens - estimated_tokens) < headroom_tokens:
                return False, "", f"Insufficient turn token budget (needed {estimated_tokens}, headroom {headroom_tokens})"

            # Store reservation
            res = BudgetReservation(
                reservation_id=rid,
                session_id=session_id,
                estimated_cost_inr=dec_cost,
                estimated_tokens=estimated_tokens,
                purpose=purpose,
            )
            tracker.reservations[rid] = res
            return True, rid, "ok"

    def release_reservation(self, session_id: str, reservation_id: str) -> None:
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            if reservation_id in tracker.reservations:
                del tracker.reservations[reservation_id]

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
        Record a completed model call, update session and turn accumulators,
        and reconcile any active reservation.
        """
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)

            # Release reservation if provided
            if reservation_id and reservation_id in tracker.reservations:
                del tracker.reservations[reservation_id]

            if isinstance(usage, dict):
                u = TokenUsage.from_dict(usage)
            else:
                u = usage

            # Extract costs
            cost_known = bool(u.cost_known)
            if cost_known and u.estimated_cost_usd is not None:
                dec_usd = _to_decimal(u.estimated_cost_usd)
                dec_inr = self.usd_to_inr(dec_usd)
            else:
                dec_usd = None
                dec_inr = None

            call_id = f"call_{len(tracker.call_history)+1}_{int(time.time()*1000)}"
            record = ModelCallRecord(
                call_id=call_id,
                session_id=session_id,
                turn_id=tracker.current_turn_id,
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

            # Update session accumulators
            tracker.session_tokens += u.total_tokens
            tracker.session_cached_tokens += u.cached_tokens
            if dec_usd is not None and dec_inr is not None:
                tracker.session_cost_usd += dec_usd
                tracker.session_cost_inr += dec_inr
            else:
                tracker.session_has_unknown_spend = True

            # Update turn accumulators
            tracker.turn_tokens += u.total_tokens
            tracker.turn_cached_tokens += u.cached_tokens
            if dec_usd is not None and dec_inr is not None:
                tracker.turn_cost_usd += dec_usd
                tracker.turn_cost_inr += dec_inr
            else:
                tracker.turn_has_unknown_spend = True

            # Update tier counts
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
            return record

    # --------------------------------------------------------------------------
    # TIER AFFORDABILITY & ESCALATION GUARD
    # --------------------------------------------------------------------------

    def can_afford_tier(
        self,
        session_id: str,
        tier: TierType,
        estimated_cost_inr: Decimal | float | None = None,
        estimated_tokens: int = 4000,
    ) -> tuple[bool, TierType, str]:
        """
        Check if the requested tier can be afforded given current budget, headroom, and call caps.
        If unaffordable, provides graceful demotion (e.g. premium -> standard -> cheap).
        Returns: (can_afford, recommended_tier, reason)
        """
        if not self._config.enabled or tier == "cheap":
            return True, tier, "ok"

        with self._lock:
            tracker = self._get_or_create_tracker(session_id)

            # Check premium call count limits
            if tier == "premium":
                if tracker.turn_calls_premium >= self._config.max_premium_calls_per_turn:
                    return False, "standard", f"Premium call cap reached for this turn ({tracker.turn_calls_premium}/{self._config.max_premium_calls_per_turn})"
                if tracker.session_calls_premium >= self._config.max_premium_calls_per_session:
                    return False, "standard", f"Premium call cap reached for this session ({tracker.session_calls_premium}/{self._config.max_premium_calls_per_session})"

            # Estimate cost if not provided
            if estimated_cost_inr is None:
                # Typical cost estimate per tier
                if tier == "premium":
                    dec_est = Decimal("1.50")
                elif tier == "standard":
                    dec_est = Decimal("0.30")
                else:
                    dec_est = Decimal("0.05")
            else:
                dec_est = _to_decimal(estimated_cost_inr)

            # Check if remaining budget after this call maintains headroom
            avail_session = self._config.per_session_cost_budget_inr - tracker.session_cost_inr - tracker.total_reserved_inr()
            avail_turn = self._config.per_turn_cost_budget_inr - tracker.turn_cost_inr - tracker.total_reserved_inr()

            if (avail_session - dec_est) < self._config.reserve_budget_inr or (avail_turn - dec_est) < self._config.reserve_budget_inr:
                demoted: TierType = "standard" if tier == "premium" else "cheap"
                return False, demoted, f"Tier {tier} exceeds budget headroom; demoting to {demoted}"

            # Token check
            avail_tokens_session = self._config.per_session_token_budget - tracker.session_tokens - tracker.total_reserved_tokens()
            if (avail_tokens_session - estimated_tokens) < self._config.reserve_tokens:
                demoted = "standard" if tier == "premium" else "cheap"
                return False, demoted, f"Tier {tier} exceeds token headroom; demoting to {demoted}"

            return True, tier, "ok"

    # --------------------------------------------------------------------------
    # BUDGET EXHAUSTION & STATUS INSPECTION
    # --------------------------------------------------------------------------

    def is_exhausted(self, session_id: str) -> bool:
        """Whether any hard budget leg (session tokens, session cost, turn tokens, turn cost) has tripped."""
        if not self._config.enabled:
            return False

        with self._lock:
            tracker = self._get_or_create_tracker(session_id)

            if tracker.session_tokens >= self._config.per_session_token_budget:
                return True
            if tracker.turn_tokens >= self._config.per_turn_token_budget:
                return True
            if tracker.session_cost_inr >= self._config.per_session_cost_budget_inr:
                return True
            if tracker.turn_cost_inr >= self._config.per_turn_cost_budget_inr:
                return True
            return False

    def trip_reason(self, session_id: str) -> str:
        """Detailed diagnostic explanation of trip reason."""
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            parts = []

            # Session tokens
            s_tok = tracker.session_tokens
            s_cap = self._config.per_session_token_budget
            s_cached = tracker.session_cached_tokens
            cached_str = f" ({s_cached:,} cached)" if s_cached else ""
            parts.append(f"session tokens {s_tok:,}/{s_cap:,}{cached_str}")

            # Turn tokens
            t_tok = tracker.turn_tokens
            t_cap = self._config.per_turn_token_budget
            parts.append(f"turn tokens {t_tok:,}/{t_cap:,}")

            # Session cost
            if tracker.session_has_unknown_spend and tracker.session_cost_inr == Decimal("0.000000"):
                parts.append(f"session cost ₹unknown/{self._config.per_session_cost_budget_inr:.2f}")
            else:
                unkn = " + unrated" if tracker.session_has_unknown_spend else ""
                parts.append(f"session cost ₹{tracker.session_cost_inr:.2f}/{self._config.per_session_cost_budget_inr:.2f}{unkn}")

            # Turn cost
            if tracker.turn_has_unknown_spend and tracker.turn_cost_inr == Decimal("0.000000"):
                parts.append(f"turn cost ₹unknown/{self._config.per_turn_cost_budget_inr:.2f}")
            else:
                unkn = " + unrated" if tracker.turn_has_unknown_spend else ""
                parts.append(f"turn cost ₹{tracker.turn_cost_inr:.2f}/{self._config.per_turn_cost_budget_inr:.2f}{unkn}")

            # Identify tripped leg
            if s_tok >= s_cap:
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
            tracker = self._get_or_create_tracker(session_id)
            near_cost = (tracker.session_cost_inr >= self._config.per_session_cost_budget_inr * Decimal("0.85")
                         or tracker.turn_cost_inr >= self._config.per_turn_cost_budget_inr * Decimal("0.85"))
            near_tokens = (tracker.session_tokens >= self._config.per_session_token_budget * 0.85
                           or tracker.turn_tokens >= self._config.per_turn_token_budget * 0.85)
            if near_cost or near_tokens:
                return "near_limit"
            return "healthy"

    def get_compact_summary(self, session_id: str) -> str:
        """
        Generate a compact, user-facing summary string formatted with '₹'.
        """
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            status = self.get_status(session_id).upper()

            # Session cost string
            if tracker.session_has_unknown_spend and tracker.session_cost_inr == Decimal("0.000000"):
                cost_str = f"₹unknown / ₹{self._config.per_session_cost_budget_inr:.2f}"
            else:
                pct = int((tracker.session_cost_inr / self._config.per_session_cost_budget_inr) * 100) if self._config.per_session_cost_budget_inr > 0 else 0
                unkn = " (+unrated)" if tracker.session_has_unknown_spend else ""
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

            return (
                f"[Cost Governance] Session: {cost_str} | Turn: {turn_str} | "
                f"Tokens: {tok_str} | Calls: {calls_str} | Status: {status}"
            )

    def get_audit_records(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            tracker = self._get_or_create_tracker(session_id)
            return [r.to_dict() for r in tracker.call_history]


# Global singleton instance
cost_governor = CostGovernor()


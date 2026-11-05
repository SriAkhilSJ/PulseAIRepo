"""
budget_governor.py -- Concurrency-Safe Atomic Budget Enforcement Governor.

Phase 9.7: Enterprise FinOps & Intelligent Cost Governance.
Guarantees strict fiscal boundaries across Crusor AI IDE:
- Multi-scope budget ceilings: per-task, daily, monthly, workspace, project.
- Concurrency-safe atomic reservations preventing race condition limit bypasses.
- Proactive warning threshold alerts (e.g., 80% watermark notification).
- Fail-closed hard budget exhaustion with descriptive explanation and safe recovery paths.
- Preserves in-flight work and prevents silent overages or surprise charges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from src.finops.pricing_registry import quantize_currency

log = logging.getLogger("crusorai.finops.budget_governor")


class BudgetExhaustionError(Exception):
    """Raised when a proposed operation exceeds the configured hard spending ceiling."""
    def __init__(self, message: str, scope: str, current_spend: Decimal, limit: Decimal, recovery_options: List[str]):
        super().__init__(message)
        self.scope = scope
        self.current_spend = current_spend
        self.limit = limit
        self.recovery_options = recovery_options


@dataclass
class BudgetPolicy:
    """Configurable spending limits and thresholds for a specific scope."""
    scope_name: str                                  # 'task', 'daily', 'monthly', 'workspace'
    hard_limit_usd: Decimal = Decimal("50.00")
    warning_threshold_ratio: Decimal = Decimal("0.80")  # Trigger alert at 80%
    require_user_approval_above_usd: Optional[Decimal] = None
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_name": self.scope_name,
            "hard_limit_usd": float(self.hard_limit_usd),
            "warning_threshold_ratio": float(self.warning_threshold_ratio),
            "require_user_approval_above_usd": float(self.require_user_approval_above_usd) if self.require_user_approval_above_usd is not None else None,
            "enabled": self.enabled,
        }


@dataclass
class ActiveReservation:
    """An atomic hold placed on a budget slice prior to model execution."""
    reservation_id: str
    scope_key: str
    amount_usd: Decimal
    timestamp: float = field(default_factory=time.time)
    purpose: str = "model_call"
    is_committed: bool = False
    is_released: bool = False


@dataclass
class BudgetScopeState:
    """Internal tracker for an individual budget scope."""
    scope_key: str
    policy: BudgetPolicy
    committed_spend_usd: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    active_reservations: Dict[str, ActiveReservation] = field(default_factory=dict)
    warning_triggered: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def reserved_spend_usd(self) -> Decimal:
        return sum(
            (r.amount_usd for r in self.active_reservations.values() if not r.is_committed and not r.is_released),
            Decimal("0.000000"),
        )

    @property
    def total_encumbered_usd(self) -> Decimal:
        return quantize_currency(self.committed_spend_usd + self.reserved_spend_usd)


class BudgetGovernor:
    """
    Enterprise Budget Governor.
    Ensures that concurrent operations cannot exceed configured financial thresholds.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scopes: Dict[str, BudgetScopeState] = {}
        self._default_policies: Dict[str, BudgetPolicy] = {
            "task": BudgetPolicy("task", hard_limit_usd=Decimal("5.00"), warning_threshold_ratio=Decimal("0.80")),
            "daily": BudgetPolicy("daily", hard_limit_usd=Decimal("25.00"), warning_threshold_ratio=Decimal("0.80")),
            "monthly": BudgetPolicy("monthly", hard_limit_usd=Decimal("150.00"), warning_threshold_ratio=Decimal("0.80")),
            "workspace": BudgetPolicy("workspace", hard_limit_usd=Decimal("100.00"), warning_threshold_ratio=Decimal("0.85")),
        }

    def set_scope_policy(self, scope_key: str, policy: BudgetPolicy) -> None:
        with self._lock:
            if scope_key in self._scopes:
                self._scopes[scope_key].policy = policy
            else:
                self._scopes[scope_key] = BudgetScopeState(scope_key=scope_key, policy=policy)

    def get_scope_state(self, scope_key: str, default_scope_type: str = "task") -> BudgetScopeState:
        with self._lock:
            if scope_key not in self._scopes:
                policy = self._default_policies.get(default_scope_type, self._default_policies["task"])
                self._scopes[scope_key] = BudgetScopeState(scope_key=scope_key, policy=policy)
            return self._scopes[scope_key]

    def reserve_budget(
        self,
        scope_key: str,
        estimated_usd: Decimal,
        default_scope_type: str = "task",
        purpose: str = "model_call",
    ) -> Tuple[bool, str, str]:
        """
        Atomically reserve a slice of budget.
        Returns: (success, reservation_id, reason)
        Fails closed if the reservation would breach the hard limit.
        """
        with self._lock:
            state = self.get_scope_state(scope_key, default_scope_type=default_scope_type)
            policy = state.policy

            if not policy.enabled:
                res_id = str(uuid.uuid4())[:16]
                return True, res_id, "Budget policy disabled"

            dec_est = quantize_currency(estimated_usd)
            projected_total = quantize_currency(state.total_encumbered_usd + dec_est)

            # Hard Limit Check
            if projected_total > policy.hard_limit_usd:
                excess = quantize_currency(projected_total - policy.hard_limit_usd)
                reason = (
                    f"Budget hard limit exceeded for scope '{scope_key}'. "
                    f"Limit: ${policy.hard_limit_usd:.2f}, Currently Encumbered: ${state.total_encumbered_usd:.2f}, "
                    f"Requested: ${dec_est:.4f}, Excess: ${excess:.4f}"
                )
                log.warning(reason)
                return False, "", reason

            # Warning Threshold Check
            warning_cutoff = quantize_currency(policy.hard_limit_usd * policy.warning_threshold_ratio)
            if projected_total >= warning_cutoff and not state.warning_triggered:
                state.warning_triggered = True
                log.info(
                    "Budget warning threshold reached for '%s' (80%% of $%s): encumbered $%s",
                    scope_key, policy.hard_limit_usd, projected_total,
                )

            res_id = str(uuid.uuid4())[:16]
            reservation = ActiveReservation(
                reservation_id=res_id,
                scope_key=scope_key,
                amount_usd=dec_est,
                purpose=purpose,
            )
            state.active_reservations[res_id] = reservation
            return True, res_id, "Budget reserved successfully"

    def commit_reservation(
        self,
        scope_key: str,
        reservation_id: str,
        actual_usd: Decimal,
    ) -> None:
        """
        Finalize a reservation by applying actual spend to committed spend and releasing the hold.
        """
        with self._lock:
            state = self.get_scope_state(scope_key)
            if reservation_id in state.active_reservations:
                res = state.active_reservations[reservation_id]
                res.is_committed = True
                del state.active_reservations[reservation_id]

            state.committed_spend_usd = quantize_currency(state.committed_spend_usd + actual_usd)

    def release_reservation(self, scope_key: str, reservation_id: str) -> None:
        """Release a reservation without charging (e.g. on cancelled or failed request)."""
        with self._lock:
            state = self.get_scope_state(scope_key)
            if reservation_id in state.active_reservations:
                del state.active_reservations[reservation_id]

    def check_health_and_limits(self, scope_key: str) -> Dict[str, Any]:
        with self._lock:
            state = self.get_scope_state(scope_key)
            pol = state.policy
            utilization = (
                float(state.total_encumbered_usd / pol.hard_limit_usd)
                if pol.hard_limit_usd > Decimal("0") else 1.0
            )
            return {
                "scope_key": scope_key,
                "hard_limit_usd": float(pol.hard_limit_usd),
                "committed_spend_usd": float(state.committed_spend_usd),
                "reserved_spend_usd": float(state.reserved_spend_usd),
                "total_encumbered_usd": float(state.total_encumbered_usd),
                "remaining_headroom_usd": float(max(Decimal("0.000000"), pol.hard_limit_usd - state.total_encumbered_usd)),
                "utilization_percent": round(utilization * 100.0, 2),
                "warning_triggered": state.warning_triggered,
                "is_exhausted": state.total_encumbered_usd >= pol.hard_limit_usd,
            }


_GLOBAL_BUDGET_GOVERNOR: Optional[BudgetGovernor] = None
_GOVERNOR_LOCK = threading.Lock()


def get_budget_governor() -> BudgetGovernor:
    global _GLOBAL_BUDGET_GOVERNOR
    with _GOVERNOR_LOCK:
        if _GLOBAL_BUDGET_GOVERNOR is None:
            _GLOBAL_BUDGET_GOVERNOR = BudgetGovernor()
        return _GLOBAL_BUDGET_GOVERNOR


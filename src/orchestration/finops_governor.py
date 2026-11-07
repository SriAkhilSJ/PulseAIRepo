"""
src/orchestration/finops_governor.py - Phase 9.7 FinOps Cost & Token Governance.

Phase 11.6: Autonomous Engineering Execution & P0.4 Budget Overrun Prevention.
Integrates directly with canonical Phase 9.7 FinOps:
- Tracks tokens, cached tokens, model tiers, and monetary costs.
- Enforces atomic reserve-before-call and post-execution settlement.
- Concurrency-safe atomic reservations preventing race-condition overages.
- Explicit budget breach detection and subsequent execution lockout.
- State persistence and restart recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

log = logging.getLogger("crusor.orchestration.finops")


class BudgetExhaustedError(RuntimeError):
    """Raised when an operation would exceed allocated task or workspace budgets."""
    pass


@dataclass
class FinOpsReservation:
    """An atomic hold placed on a task budget slice prior to model execution."""
    reservation_id: str
    task_id: str
    amount_inr: float
    amount_usd: float
    tokens: int
    purpose: str = "model_call"
    created_at: float = field(default_factory=time.time)
    is_committed: bool = False
    is_released: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "task_id": self.task_id,
            "amount_inr": self.amount_inr,
            "amount_usd": self.amount_usd,
            "tokens": self.tokens,
            "purpose": self.purpose,
            "created_at": self.created_at,
            "is_committed": self.is_committed,
            "is_released": self.is_released,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FinOpsReservation:
        return cls(
            reservation_id=data["reservation_id"],
            task_id=data["task_id"],
            amount_inr=float(data.get("amount_inr", 0.0)),
            amount_usd=float(data.get("amount_usd", 0.0)),
            tokens=int(data.get("tokens", 0)),
            purpose=data.get("purpose", "model_call"),
            created_at=float(data.get("created_at", time.time())),
            is_committed=bool(data.get("is_committed", False)),
            is_released=bool(data.get("is_released", False)),
        )


@dataclass
class TaskFinOpsExpenditure:
    """Detailed financial and token accounting for an engineering task."""
    task_id: str
    budget_inr: float = 0.00
    spent_inr: float = 0.00
    spent_usd: float = 0.00
    reserved_inr: float = 0.00
    reserved_usd: float = 0.00
    token_budget: int = 150000
    tokens_consumed: int = 0
    reserved_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    tool_execution_seconds: float = 0.0
    test_execution_seconds: float = 0.0
    calls_count: int = 0
    is_breached: bool = False
    breach_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "budget_inr": self.budget_inr,
            "spent_inr": self.spent_inr,
            "spent_usd": self.spent_usd,
            "reserved_inr": self.reserved_inr,
            "reserved_usd": self.reserved_usd,
            "token_budget": self.token_budget,
            "tokens_consumed": self.tokens_consumed,
            "reserved_tokens": self.reserved_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "tool_execution_seconds": round(self.tool_execution_seconds, 2),
            "test_execution_seconds": round(self.test_execution_seconds, 2),
            "calls_count": self.calls_count,
            "is_breached": self.is_breached,
            "breach_reason": self.breach_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskFinOpsExpenditure:
        return cls(
            task_id=data["task_id"],
            budget_inr=float(data.get("budget_inr", 0.0)),
            spent_inr=float(data.get("spent_inr", 0.0)),
            spent_usd=float(data.get("spent_usd", 0.0)),
            reserved_inr=float(data.get("reserved_inr", 0.0)),
            reserved_usd=float(data.get("reserved_usd", 0.0)),
            token_budget=int(data.get("token_budget", 150000)),
            tokens_consumed=int(data.get("tokens_consumed", 0)),
            reserved_tokens=int(data.get("reserved_tokens", 0)),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            cached_tokens=int(data.get("cached_tokens", 0)),
            tool_execution_seconds=float(data.get("tool_execution_seconds", 0.0)),
            test_execution_seconds=float(data.get("test_execution_seconds", 0.0)),
            calls_count=int(data.get("calls_count", 0)),
            is_breached=bool(data.get("is_breached", False)),
            breach_reason=data.get("breach_reason"),
        )


class OrchestrationFinOpsGovernor:
    """
    Guarantees that autonomous execution stays strictly within allocated FinOps boundaries.
    Enforces atomic reserve-before-call and post-execution settlement with concurrency safety.
    """

    def __init__(
        self,
        task_id: str,
        budget_inr: float = 0.00,
        token_budget: int = 150000,
        storage_dir: Optional[str] = None,
        workspace_root: Optional[str] = None,
    ) -> None:
        self._lock = threading.RLock()
        self.task_id = task_id
        self.storage_dir = Path(storage_dir).resolve() if storage_dir else None
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None

        self.accounting = TaskFinOpsExpenditure(
            task_id=task_id,
            budget_inr=budget_inr,
            token_budget=token_budget,
        )
        self._active_reservations: Dict[str, FinOpsReservation] = {}
        self._settled_reservations: Dict[str, FinOpsReservation] = {}

        # Restore from persistent state if available
        self._load_state()

        # Connect with canonical BudgetGovernor
        self._sync_with_canonical_budget_governor()

    def _sync_with_canonical_budget_governor(self) -> None:
        """Register task scope with canonical Phase 9.7 BudgetGovernor."""
        try:
            from src.finops.budget_governor import BudgetPolicy, get_budget_governor
            from src.finops.pricing_registry import get_pricing_registry
            pricing_reg = get_pricing_registry()
            usd_limit = pricing_reg.inr_to_usd(Decimal(str(self.accounting.budget_inr))) or Decimal("0.00")
            policy = BudgetPolicy(
                scope_name=self.task_id,
                hard_limit_usd=usd_limit,
                warning_threshold_ratio=Decimal("0.80"),
            )
            gov = get_budget_governor()
            gov.set_scope_policy(self.task_id, policy)
        except Exception as exc:
            log.debug("Canonical budget governor sync optional: %s", exc)

    def _get_state_file(self) -> Optional[Path]:
        if self.storage_dir:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in self.task_id)
            return self.storage_dir / f"{safe_id}_finops.json"
        if self.workspace_root:
            p = self.workspace_root / ".crusorai" / "finops"
            p.mkdir(parents=True, exist_ok=True)
            safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in self.task_id)
            return p / f"{safe_id}_finops.json"
        return None

    def _persist_state(self) -> None:
        sf = self._get_state_file()
        if not sf:
            return
        try:
            payload = {
                "accounting": self.accounting.to_dict(),
                "active_reservations": {k: v.to_dict() for k, v in self._active_reservations.items()},
                "settled_reservations": {k: v.to_dict() for k, v in self._settled_reservations.items()},
            }
            tmp_sf = sf.with_suffix(".tmp")
            tmp_sf.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp_sf, sf)
        except Exception as exc:
            log.warning("FinOps governor persistence failed for %s: %s", self.task_id, exc)

    def _load_state(self) -> None:
        sf = self._get_state_file()
        if not sf or not sf.exists():
            return
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if "accounting" in data:
                persisted = TaskFinOpsExpenditure.from_dict(data["accounting"])
                # Preserve the newly requested budget if greater or explicitly configured
                configured_budget = self.accounting.budget_inr
                configured_tokens = self.accounting.token_budget
                self.accounting = persisted
                if configured_budget > 0:
                    self.accounting.budget_inr = configured_budget
                if configured_tokens > 0:
                    self.accounting.token_budget = configured_tokens
            if "active_reservations" in data:
                self._active_reservations = {
                    k: FinOpsReservation.from_dict(v) for k, v in data["active_reservations"].items()
                }
            if "settled_reservations" in data:
                self._settled_reservations = {
                    k: FinOpsReservation.from_dict(v) for k, v in data["settled_reservations"].items()
                }
        except Exception as exc:
            log.warning("Failed to recover FinOps state for %s: %s", self.task_id, exc)

    def save_state(self, filepath: Optional[str] = None) -> None:
        with self._lock:
            if filepath:
                p = Path(filepath).resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "accounting": self.accounting.to_dict(),
                    "active_reservations": {k: v.to_dict() for k, v in self._active_reservations.items()},
                    "settled_reservations": {k: v.to_dict() for k, v in self._settled_reservations.items()},
                }
                tmp_p = p.with_suffix(".tmp")
                tmp_p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                os.replace(tmp_p, p)
            else:
                self._persist_state()

    def load_state(self, filepath: Optional[str] = None) -> None:
        with self._lock:
            if filepath:
                p = Path(filepath).resolve()
                if not p.exists():
                    return
                data = json.loads(p.read_text(encoding="utf-8"))
                if "accounting" in data:
                    self.accounting = TaskFinOpsExpenditure.from_dict(data["accounting"])
                if "active_reservations" in data:
                    self._active_reservations = {
                        k: FinOpsReservation.from_dict(v) for k, v in data["active_reservations"].items()
                    }
                if "settled_reservations" in data:
                    self._settled_reservations = {
                        k: FinOpsReservation.from_dict(v) for k, v in data["settled_reservations"].items()
                    }
            else:
                self._load_state()

    def authorize_operation(self, estimated_tokens: int = 0, estimated_cost_inr: float = 0.00) -> None:
        """Checks if operation can proceed without exceeding budget or breaching limits."""
        with self._lock:
            if self.accounting.is_breached:
                raise BudgetExhaustedError(
                    f"Operation rejected: task budget was breached ({self.accounting.breach_reason}). "
                    f"Subsequent execution is strictly blocked."
                )
            if self.accounting.spent_inr + self.accounting.reserved_inr + estimated_cost_inr > self.accounting.budget_inr:
                remaining = max(0.0, self.accounting.budget_inr - (self.accounting.spent_inr + self.accounting.reserved_inr))
                raise BudgetExhaustedError(
                    f"Operation rejected: estimated cost INR {estimated_cost_inr:.2f} exceeds "
                    f"remaining budget INR {remaining:.2f}"
                )
            if self.accounting.tokens_consumed + self.accounting.reserved_tokens + estimated_tokens > self.accounting.token_budget:
                remaining_tokens = max(0, self.accounting.token_budget - (self.accounting.tokens_consumed + self.accounting.reserved_tokens))
                raise BudgetExhaustedError(
                    f"Operation rejected: estimated tokens {estimated_tokens} exceeds "
                    f"remaining budget {remaining_tokens}"
                )

    def reserve(
        self,
        estimated_tokens: int,
        estimated_cost_inr: float,
        estimated_cost_usd: float = 0.0,
        purpose: str = "model_call",
        reservation_id: Optional[str] = None,
    ) -> str:
        """
        Atomically reserve funds and tokens prior to model invocation.
        Rejects immediately with BudgetExhaustedError if the request cannot fit
        within remaining unreserved budget or if the task budget was previously breached.
        """
        with self._lock:
            if self.accounting.is_breached:
                raise BudgetExhaustedError(
                    f"Operation rejected: task budget was breached ({self.accounting.breach_reason}). "
                    f"Subsequent execution is strictly blocked."
                )

            # Check monetary budget
            projected_cost = round(self.accounting.spent_inr + self.accounting.reserved_inr + estimated_cost_inr, 6)
            if projected_cost > self.accounting.budget_inr:
                remaining = max(0.0, self.accounting.budget_inr - (self.accounting.spent_inr + self.accounting.reserved_inr))
                raise BudgetExhaustedError(
                    f"Operation rejected: estimated cost INR {estimated_cost_inr:.4f} exceeds "
                    f"remaining budget INR {remaining:.4f} "
                    f"(budget: INR {self.accounting.budget_inr:.4f}, spent: INR {self.accounting.spent_inr:.4f}, "
                    f"reserved: INR {self.accounting.reserved_inr:.4f})"
                )

            # Check token budget
            projected_tokens = self.accounting.tokens_consumed + self.accounting.reserved_tokens + estimated_tokens
            if projected_tokens > self.accounting.token_budget:
                remaining_tokens = max(0, self.accounting.token_budget - (self.accounting.tokens_consumed + self.accounting.reserved_tokens))
                raise BudgetExhaustedError(
                    f"Operation rejected: estimated tokens {estimated_tokens} exceeds "
                    f"remaining budget {remaining_tokens} "
                    f"(budget: {self.accounting.token_budget}, consumed: {self.accounting.tokens_consumed}, "
                    f"reserved: {self.accounting.reserved_tokens})"
                )

            res_id = reservation_id or f"res_{uuid.uuid4().hex[:12]}"
            res = FinOpsReservation(
                reservation_id=res_id,
                task_id=self.task_id,
                amount_inr=estimated_cost_inr,
                amount_usd=estimated_cost_usd,
                tokens=estimated_tokens,
                purpose=purpose,
            )
            self._active_reservations[res_id] = res
            self.accounting.reserved_inr = round(self.accounting.reserved_inr + estimated_cost_inr, 6)
            self.accounting.reserved_usd = round(self.accounting.reserved_usd + estimated_cost_usd, 6)
            self.accounting.reserved_tokens += estimated_tokens

            # Canonical BudgetGovernor reservation
            try:
                from src.finops.budget_governor import get_budget_governor
                get_budget_governor().reserve_budget(
                    scope_key=self.task_id,
                    estimated_usd=Decimal(str(round(estimated_cost_usd, 6))),
                    purpose=purpose,
                )
            except Exception as exc:
                log.debug("Canonical budget governor reserve optional: %s", exc)

            self._persist_state()
            return res_id

    def commit_reservation(
        self,
        reservation_id: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
        actual_cached_tokens: int,
        actual_cost_inr: float,
        actual_cost_usd: float,
        tool_seconds: float = 0.0,
        test_seconds: float = 0.0,
    ) -> None:
        """
        Finalizes a reservation by committing actual expenditure and releasing unspent funds.
        Detects and records budget breaches if actual expenditure exceeds reserved maximum.
        """
        with self._lock:
            if reservation_id not in self._active_reservations:
                if reservation_id in self._settled_reservations:
                    log.warning("Reservation %s was already settled, ignoring duplicate commit", reservation_id)
                    return
                raise KeyError(f"Active reservation '{reservation_id}' not found")

            res = self._active_reservations.pop(reservation_id)
            res.is_committed = True
            self._settled_reservations[reservation_id] = res

            # Release the reservation hold
            self.accounting.reserved_inr = max(0.0, round(self.accounting.reserved_inr - res.amount_inr, 6))
            self.accounting.reserved_usd = max(0.0, round(self.accounting.reserved_usd - res.amount_usd, 6))
            self.accounting.reserved_tokens = max(0, self.accounting.reserved_tokens - res.tokens)

            # Record actual usage into spent accounting
            self.record_usage(
                input_tokens=actual_input_tokens,
                output_tokens=actual_output_tokens,
                cached_tokens=actual_cached_tokens,
                cost_inr=actual_cost_inr,
                cost_usd=actual_cost_usd,
                tool_seconds=tool_seconds,
                test_seconds=test_seconds,
            )

            # Breach Detection: check if actual cost exceeded reserved maximum
            if actual_cost_inr > res.amount_inr:
                breach_msg = (
                    f"Actual cost INR {actual_cost_inr:.4f} exceeded reserved maximum INR {res.amount_inr:.4f} "
                    f"for reservation '{reservation_id}'."
                )
                log.error("FinOps budget breach: %s", breach_msg)
                self.accounting.is_breached = True
                self.accounting.breach_reason = breach_msg

            # Breach Detection: check if total spent exceeded total budget
            if self.accounting.spent_inr > self.accounting.budget_inr:
                breach_msg = (
                    f"Total spent INR {self.accounting.spent_inr:.4f} exceeded budget INR {self.accounting.budget_inr:.4f}."
                )
                log.error("FinOps total budget breach: %s", breach_msg)
                self.accounting.is_breached = True
                self.accounting.breach_reason = breach_msg

            # Canonical BudgetGovernor commit
            try:
                from src.finops.budget_governor import get_budget_governor
                get_budget_governor().commit_reservation(
                    scope_key=self.task_id,
                    reservation_id=reservation_id,
                    actual_usd=Decimal(str(round(actual_cost_usd, 6))),
                )
            except Exception as exc:
                log.debug("Canonical budget governor commit optional: %s", exc)

            self._persist_state()

    def release_reservation(self, reservation_id: str, reason: str = "cancelled_or_failed") -> None:
        """
        Releases an active reservation without committing spend (e.g. on provider error, timeout, or cancellation).
        Guarantees idempotent duplicate release prevention.
        """
        with self._lock:
            if reservation_id not in self._active_reservations:
                if reservation_id in self._settled_reservations:
                    log.warning("Reservation %s was already settled, ignoring duplicate release", reservation_id)
                    return
                log.warning("Reservation %s not found for release", reservation_id)
                return

            res = self._active_reservations.pop(reservation_id)
            res.is_released = True
            self._settled_reservations[reservation_id] = res

            # Release the hold
            self.accounting.reserved_inr = max(0.0, round(self.accounting.reserved_inr - res.amount_inr, 6))
            self.accounting.reserved_usd = max(0.0, round(self.accounting.reserved_usd - res.amount_usd, 6))
            self.accounting.reserved_tokens = max(0, self.accounting.reserved_tokens - res.tokens)

            # Canonical BudgetGovernor release
            try:
                from src.finops.budget_governor import get_budget_governor
                get_budget_governor().release_reservation(
                    scope_key=self.task_id,
                    reservation_id=reservation_id,
                )
            except Exception as exc:
                log.debug("Canonical budget governor release optional: %s", exc)

            self._persist_state()

    def record_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cost_inr: float = 0.00,
        cost_usd: float = 0.00,
        tool_seconds: float = 0.0,
        test_seconds: float = 0.0,
    ) -> None:
        """Records actual consumed resources and verifies limits."""
        with self._lock:
            total_tok = input_tokens + output_tokens
            self.accounting.input_tokens += input_tokens
            self.accounting.output_tokens += output_tokens
            self.accounting.cached_tokens += cached_tokens
            self.accounting.tokens_consumed += total_tok
            self.accounting.spent_inr = round(self.accounting.spent_inr + cost_inr, 6)
            self.accounting.spent_usd = round(self.accounting.spent_usd + cost_usd, 6)
            self.accounting.tool_execution_seconds += tool_seconds
            self.accounting.test_execution_seconds += test_seconds
            self.accounting.calls_count += 1

            if self.accounting.spent_inr > self.accounting.budget_inr:
                breach_msg = (
                    f"Task {self.accounting.task_id} exhausted monetary budget: "
                    f"INR {self.accounting.spent_inr:.4f} > INR {self.accounting.budget_inr:.4f}"
                )
                log.warning(breach_msg)
                self.accounting.is_breached = True
                self.accounting.breach_reason = breach_msg

            self._persist_state()

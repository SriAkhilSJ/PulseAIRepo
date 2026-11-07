"""
src/orchestration/finops_governor.py - Phase 9.7 FinOps Cost & Token Governance.

Phase 11.6: Autonomous Engineering Execution & P0.4 / P0.4.1 Budget Overrun Prevention.
Integrates directly with canonical Phase 9.7 FinOps:
- Tracks tokens, cached tokens, model tiers, and monetary costs.
- Enforces atomic reserve-before-call and post-execution settlement.
- Concurrency-safe atomic reservations preventing race-condition overages.
- Explicit budget breach detection and subsequent execution lockout.
- Canonical BudgetGovernor two-phase commit with exact reservation ID propagation.
- Fail-closed durable persistence before model dispatch.
- Resilient uncertain reservation state holding funds on post-dispatch timeout/cancellation.
- State persistence and restart recovery across process boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
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


class FinancialPersistenceError(RuntimeError):
    """Raised when a reservation or settlement cannot be durably recorded."""


class FinancialStateCorruptionError(FinancialPersistenceError):
    """Raised when persisted financial state exists but cannot be recovered safely."""


class FinancialIntegrityError(RuntimeError):
    """Raised when a canonical reservation ID is missing or a ledger invariant is broken."""


class CanonicalReservationError(RuntimeError):
    """Raised when the canonical BudgetGovernor fails to reserve/commit/release."""


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
    canonical_reservation_id: Optional[str] = None
    canonical_amount_usd: float = 0.0
    status: str = "reserved"  # 'reserved', 'in_flight', 'reconciled', 'released', 'uncertain'

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
            "canonical_reservation_id": self.canonical_reservation_id,
            "canonical_amount_usd": self.canonical_amount_usd,
            "status": self.status,
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
            canonical_reservation_id=data.get("canonical_reservation_id"),
            canonical_amount_usd=float(data.get("canonical_amount_usd", 0.0)),
            status=data.get("status", "reserved"),
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
        self._uncertain_reservations: Dict[str, FinOpsReservation] = {}
        self._settled_reservations: Dict[str, FinOpsReservation] = {}

        # Restore from persistent state if available. A corrupt state file must
        # never silently reset accounting to zero (that would free uncertain
        # holds), so _load_state raises FinancialStateCorruptionError.
        self._load_state()

        # Connect with canonical BudgetGovernor (fail closed: a governor that
        # cannot register its scope must not dispense budget).
        self._sync_with_canonical_budget_governor()

        # Re-hold recovered reservations and spend in the process-local
        # canonical governor. Cross-process atomicity is NOT claimed: this is
        # best-effort reconstruction from the durable task state written by
        # reserve()/commit().
        self._restore_canonical_holds()

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
            raise FinancialIntegrityError(
                f"Cannot register task scope '{self.task_id}' with the canonical BudgetGovernor: {exc}"
            ) from exc

    def _canonical_usd_amount(self, estimated_cost_inr: float, estimated_cost_usd: float) -> Decimal:
        """
        Derive the canonical USD hold from the task's authoritative INR budget.

        The canonical governor is USD-denominated while task budgets are INR.
        Dividing by the canonical FX rate and flooring directly at micro-currency
        precision (no intermediate half-up rounding) guarantees that N holds can
        never sum above the converted limit: e.g. 5 x floor6(2.00/86) = 0.116275,
        which stays under floor6(10.00/86) = 0.116279.
        """
        from src.finops.pricing_registry import get_pricing_registry
        if estimated_cost_inr > 0:
            rate = get_pricing_registry().get_fx_rate()
            if rate and rate > 0:
                usd = Decimal(str(estimated_cost_inr)) / rate
                return usd.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
            return Decimal("0.000000")
        return Decimal(str(estimated_cost_usd)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

    def _restore_canonical_holds(self) -> None:
        """Re-establish canonical holds/spend in this process after a restart."""
        from src.finops.budget_governor import get_budget_governor
        gov = get_budget_governor()
        gov.restore_committed_spend(self.task_id, Decimal(str(self.accounting.spent_usd)))

        recovered = list(self._active_reservations.values()) + list(self._uncertain_reservations.values())
        for res in recovered:
            canonical_id = res.canonical_reservation_id
            if not canonical_id:
                # Legacy/hand-written state without a canonical ID cannot be
                # settled safely. Keep the funds held as uncertain rather than
                # letting them silently return to the available budget.
                log.error(
                    "Reservation %s recovered without a canonical reservation ID; "
                    "holding funds as uncertain.",
                    res.reservation_id,
                )
                self._active_reservations.pop(res.reservation_id, None)
                res.status = "uncertain"
                self._uncertain_reservations[res.reservation_id] = res
                continue
            amount = (
                Decimal(str(res.canonical_amount_usd))
                if res.canonical_amount_usd > 0
                else self._canonical_usd_amount(res.amount_inr, res.amount_usd)
            )
            gov.restore_reservation(
                scope_key=self.task_id,
                reservation_id=canonical_id,
                amount_usd=amount,
                purpose=res.purpose,
            )

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
        """
        Durable state persistence.
        Raises on failure to enforce fail-closed semantics across financial boundaries.
        """
        sf = self._get_state_file()
        if not sf:
            return
        payload = {
            "accounting": self.accounting.to_dict(),
            "active_reservations": {k: v.to_dict() for k, v in self._active_reservations.items()},
            "uncertain_reservations": {k: v.to_dict() for k, v in self._uncertain_reservations.items()},
            "settled_reservations": {k: v.to_dict() for k, v in self._settled_reservations.items()},
        }
        tmp_sf = sf.with_suffix(".tmp")
        tmp_sf.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_sf, sf)

    def _load_state(self) -> None:
        sf = self._get_state_file()
        if not sf or not sf.exists():
            return
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if "accounting" in data:
                persisted = TaskFinOpsExpenditure.from_dict(data["accounting"])
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
            if "uncertain_reservations" in data:
                self._uncertain_reservations = {
                    k: FinOpsReservation.from_dict(v) for k, v in data["uncertain_reservations"].items()
                }
            if "settled_reservations" in data:
                self._settled_reservations = {
                    k: FinOpsReservation.from_dict(v) for k, v in data["settled_reservations"].items()
                }

            # Recalculate encumbered funds including both active and uncertain holds
            total_reserved_inr = sum(r.amount_inr for r in self._active_reservations.values()) + sum(r.amount_inr for r in self._uncertain_reservations.values())
            total_reserved_usd = sum(r.amount_usd for r in self._active_reservations.values()) + sum(r.amount_usd for r in self._uncertain_reservations.values())
            total_reserved_tok = sum(r.tokens for r in self._active_reservations.values()) + sum(r.tokens for r in self._uncertain_reservations.values())
            self.accounting.reserved_inr = round(total_reserved_inr, 6)
            self.accounting.reserved_usd = round(total_reserved_usd, 6)
            self.accounting.reserved_tokens = total_reserved_tok
        except Exception as exc:
            # Fail closed: a state file that exists but cannot be parsed must
            # not be treated as "no reservations" (which would free holds).
            raise FinancialStateCorruptionError(
                f"Persisted FinOps state for task '{self.task_id}' at {sf} is unreadable: {exc}"
            ) from exc

    def _sync_reservation_to_store(self, res: FinOpsReservation) -> None:
        """
        Durably record a reservation transition in the canonical SQLite store.

        Fail-closed: a reservation that is not durably recorded must never be
        followed by a paid provider call. When no workspace/storage directory
        is configured, the FinancialStore's canonical default database is used,
        so there is no "persistence skipped" code path.
        """
        from src.agents.financial_store import FinancialStore
        db_path = None
        if self.workspace_root:
            db_path = self.workspace_root / ".crusorai" / "sessions.db"
        elif self.storage_dir:
            db_path = self.storage_dir / "sessions.db"
        store = None
        try:
            store = FinancialStore(db_path=db_path)
            ok = store.save_reservation(
                reservation_id=res.reservation_id,
                root_session_id=self.task_id,
                session_id=self.task_id,
                turn_id=1,
                estimated_cost_inr=Decimal(str(round(res.amount_inr, 6))),
                estimated_tokens=res.tokens,
                purpose=res.purpose,
                status=res.status,
                canonical_reservation_id=res.canonical_reservation_id,
            )
            if not ok:
                raise FinancialPersistenceError(
                    f"FinancialStore rejected reservation '{res.reservation_id}'."
                )
        except FinancialPersistenceError:
            raise
        except Exception as exc:
            raise FinancialPersistenceError(
                f"Failed to durably persist reservation '{res.reservation_id}': {exc}"
            ) from exc
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

    def save_state(self, filepath: Optional[str] = None) -> None:
        with self._lock:
            if filepath:
                p = Path(filepath).resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "accounting": self.accounting.to_dict(),
                    "active_reservations": {k: v.to_dict() for k, v in self._active_reservations.items()},
                    "uncertain_reservations": {k: v.to_dict() for k, v in self._uncertain_reservations.items()},
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
                if "uncertain_reservations" in data:
                    self._uncertain_reservations = {
                        k: FinOpsReservation.from_dict(v) for k, v in data["uncertain_reservations"].items()
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
        Enforces canonical BudgetGovernor two-phase reservation and fail-closed persistence.
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

            # 1. Local provisional hold
            res_id = reservation_id or f"res_{uuid.uuid4().hex[:12]}"
            res = FinOpsReservation(
                reservation_id=res_id,
                task_id=self.task_id,
                amount_inr=estimated_cost_inr,
                amount_usd=estimated_cost_usd,
                tokens=estimated_tokens,
                purpose=purpose,
                status="reserved",
            )
            self._active_reservations[res_id] = res
            self.accounting.reserved_inr = round(self.accounting.reserved_inr + estimated_cost_inr, 6)
            self.accounting.reserved_usd = round(self.accounting.reserved_usd + estimated_cost_usd, 6)
            self.accounting.reserved_tokens += estimated_tokens

            # 2. Canonical BudgetGovernor reservation. The result is mandatory:
            # a denied or failed canonical hold rolls the local provisional hold
            # back and aborts execution before any provider dispatch.
            canon_gov = None
            canon_res_id: Optional[str] = None
            canon_usd = self._canonical_usd_amount(estimated_cost_inr, estimated_cost_usd)
            try:
                from src.finops.budget_governor import get_budget_governor
                canon_gov = get_budget_governor()
                success, canon_res_id, reason = canon_gov.reserve_budget(
                    scope_key=self.task_id,
                    estimated_usd=canon_usd,
                    purpose=purpose,
                )
                if not success or not canon_res_id:
                    self._discard_local_reservation(res_id)
                    raise BudgetExhaustedError(
                        f"Canonical budget governor denied reservation for scope '{self.task_id}': {reason}"
                    )
            except BudgetExhaustedError:
                raise
            except Exception as exc:
                self._discard_local_reservation(res_id)
                raise CanonicalReservationError(
                    f"Canonical budget governor failed to reserve for scope '{self.task_id}': {exc}"
                ) from exc

            res.canonical_reservation_id = canon_res_id
            res.canonical_amount_usd = float(canon_usd)

            # 3. Fail-closed durable persistence BEFORE returning a usable
            # reservation. Both the task-state journal and the canonical
            # SQLite store must accept the record.
            try:
                self._persist_state()
                self._sync_reservation_to_store(res)
            except Exception as exc:
                self._discard_local_reservation(res_id)
                if canon_gov is not None and canon_res_id:
                    try:
                        canon_gov.release_reservation(self.task_id, canon_res_id)
                    except Exception:
                        log.exception(
                            "Failed to release canonical hold %s after local persistence failure",
                            canon_res_id,
                        )
                # Best effort: remove the stale local record so a restart does
                # not resurrect a phantom hold.
                try:
                    self._persist_state()
                except Exception:
                    log.exception("Failed to clean up state after reservation persistence failure")
                raise FinancialPersistenceError(
                    f"Durable reservation persistence failed for task '{self.task_id}': {exc}"
                ) from exc

            return res_id

    def _discard_local_reservation(self, reservation_id: str) -> None:
        """Remove a provisional local hold and its accounting encumbrance."""
        res = self._active_reservations.pop(reservation_id, None)
        if res is None:
            return
        self.accounting.reserved_inr = max(0.0, round(self.accounting.reserved_inr - res.amount_inr, 6))
        self.accounting.reserved_usd = max(0.0, round(self.accounting.reserved_usd - res.amount_usd, 6))
        self.accounting.reserved_tokens = max(0, self.accounting.reserved_tokens - res.tokens)

    def mark_in_flight(self, reservation_id: str) -> None:
        """Mark reservation as actively in-flight during provider execution."""
        with self._lock:
            res = self._active_reservations.get(reservation_id)
            if not res:
                raise FinancialIntegrityError(
                    f"Cannot mark unknown reservation '{reservation_id}' in-flight; dispatch must be blocked."
                )
            if res.status != "in_flight":
                res.status = "in_flight"
                self._sync_reservation_to_store(res)
                self._persist_state()

    def mark_uncertain(self, reservation_id: str, reason: str = "") -> None:
        """
        Transition an in-flight reservation to 'uncertain' state when post-dispatch outcome is unknown
        (e.g. timeout, connection reset, cancellation).
        CRITICAL: Retains the financial hold (reserved_inr, reserved_usd, reserved_tokens)
        so that funds cannot be double-spent.
        """
        with self._lock:
            res = self._active_reservations.pop(reservation_id, None)
            if not res:
                if reservation_id in self._uncertain_reservations:
                    return
                raise FinancialIntegrityError(
                    f"Cannot mark unknown reservation '{reservation_id}' uncertain; "
                    f"post-dispatch billing state would be lost."
                )

            res.status = "uncertain"
            self._uncertain_reservations[reservation_id] = res
            log.warning(
                "Reservation '%s' marked UNCERTAIN (%s). Financial hold of INR %.4f / USD %.4f retained.",
                reservation_id, reason, res.amount_inr, res.amount_usd,
            )
            self._sync_reservation_to_store(res)
            self._persist_state()

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
        Propagates canonical reservation ID for canonical settlement.
        """
        with self._lock:
            res = self._active_reservations.get(reservation_id)
            if res is None:
                res = self._uncertain_reservations.get(reservation_id)

            if res is None:
                if reservation_id in self._settled_reservations:
                    log.warning("Reservation %s was already settled, ignoring duplicate commit", reservation_id)
                    return
                raise KeyError(f"Reservation '{reservation_id}' not found for commit")

            if not res.canonical_reservation_id:
                # A local-only hold cannot be settled against the canonical
                # ledger. Keep the funds held and fail closed rather than
                # charging an unrelated/unknown canonical reservation.
                raise FinancialIntegrityError(
                    f"Reservation '{reservation_id}' has no canonical reservation ID; settlement refused."
                )

            # Canonical settlement FIRST using the EXACT canonical ID. The
            # canonical governor is idempotent, so a retried commit cannot
            # double-charge. If it fails the local hold remains active.
            try:
                from src.finops.budget_governor import get_budget_governor
                get_budget_governor().commit_reservation(
                    scope_key=self.task_id,
                    reservation_id=res.canonical_reservation_id,
                    actual_usd=Decimal(str(round(actual_cost_usd, 6))),
                )
            except Exception as exc:
                raise CanonicalReservationError(
                    f"Canonical settlement failed for reservation '{reservation_id}' "
                    f"(canonical '{res.canonical_reservation_id}'): {exc}"
                ) from exc

            self._active_reservations.pop(reservation_id, None)
            self._uncertain_reservations.pop(reservation_id, None)

            res.is_committed = True
            res.status = "reconciled"
            self._settled_reservations[reservation_id] = res

            # Release the local reservation hold
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

            self._sync_reservation_to_store(res)
            self._persist_state()

    def release_reservation(self, reservation_id: str, reason: str = "cancelled_or_failed") -> None:
        """
        Releases an active reservation without committing spend (e.g. on pre-dispatch error).
        Guarantees idempotent duplicate release prevention.
        Propagates canonical reservation ID for canonical release.
        """
        with self._lock:
            res = self._active_reservations.get(reservation_id)
            if res is None:
                res = self._uncertain_reservations.get(reservation_id)

            if res is None:
                if reservation_id in self._settled_reservations:
                    log.warning("Reservation %s was already settled, ignoring duplicate release", reservation_id)
                    return
                log.warning("Reservation %s not found for release", reservation_id)
                return

            if not res.canonical_reservation_id:
                raise FinancialIntegrityError(
                    f"Reservation '{reservation_id}' has no canonical reservation ID; release refused."
                )

            # Canonical release FIRST using the EXACT canonical ID. Idempotent;
            # a failure keeps the local hold so funds are never silently freed.
            try:
                from src.finops.budget_governor import get_budget_governor
                get_budget_governor().release_reservation(
                    scope_key=self.task_id,
                    reservation_id=res.canonical_reservation_id,
                )
            except Exception as exc:
                raise CanonicalReservationError(
                    f"Canonical release failed for reservation '{reservation_id}' "
                    f"(canonical '{res.canonical_reservation_id}'): {exc}"
                ) from exc

            self._active_reservations.pop(reservation_id, None)
            self._uncertain_reservations.pop(reservation_id, None)

            res.is_released = True
            res.status = "released"
            self._settled_reservations[reservation_id] = res

            # Release the local hold
            self.accounting.reserved_inr = max(0.0, round(self.accounting.reserved_inr - res.amount_inr, 6))
            self.accounting.reserved_usd = max(0.0, round(self.accounting.reserved_usd - res.amount_usd, 6))
            self.accounting.reserved_tokens = max(0, self.accounting.reserved_tokens - res.tokens)

            self._sync_reservation_to_store(res)
            self._persist_state()

    def reconcile_uncertain_reservation(
        self,
        reservation_id: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
        actual_cached_tokens: int,
        actual_cost_inr: float,
        actual_cost_usd: float,
    ) -> None:
        """Administrative reconciliation of an uncertain reservation once verified."""
        self.commit_reservation(
            reservation_id=reservation_id,
            actual_input_tokens=actual_input_tokens,
            actual_output_tokens=actual_output_tokens,
            actual_cached_tokens=actual_cached_tokens,
            actual_cost_inr=actual_cost_inr,
            actual_cost_usd=actual_cost_usd,
        )

    def release_uncertain_reservation(self, reservation_id: str, reason: str = "administrative_release") -> None:
        """Administrative release of an uncertain reservation once confirmed uncharged."""
        self.release_reservation(reservation_id=reservation_id, reason=reason)

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

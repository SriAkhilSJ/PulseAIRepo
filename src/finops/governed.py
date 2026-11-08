"""Governed provider invocation gateway.

P0.6.8 live finding: the session auto-titler invoked the auxiliary model through
``RetryLLMProxy`` (so the acceptance guard counted it) but no FinOps reservation
existed. This gateway is the shared accounting boundary for auxiliary and
background calls: unpriced, unauthorized or un-settleable invocations never
reach the provider.

The orchestrator keeps its existing task-governed path; both write the same
``provider_invocations.jsonl`` ledger so a session report and the acceptance
guard can reconcile one source of attribution without duplicating cost truth
(the FinOps governor/SQLite remains authoritative for money).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.finops.invocation_context import (
    new_invocation_id,
    invocation_scope,
    record_invocation,
)
from src.finops.pricing_registry import PricingRegistry, VerificationStatus
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor
from src.orchestration.model_adapter import (
    UnknownModelPricingError,
    build_output_token_kwargs,
    calculate_max_request_cost,
    can_enforce_token_limit,
    estimate_prompt_token_upper_bound,
    extract_provider_token_usage,
    is_uncertain_post_dispatch_error,
)


class AuxiliaryAccountingError(RuntimeError):
    """The auxiliary call could not be financially authorized; do not dispatch."""


@dataclass
class GovernedResult:
    text: str
    invocation_id: str
    reservation_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    actual_cost_inr: float
    actual_cost_usd: float
    status: str
    started_at: float
    completed_at: float


def _response_text(response: Any) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(getattr(item, "text", "") or ""))
        return "".join(parts)
    return str(content or "")


class GovernedProviderGateway:
    """Reserve → invoke → usage → cost → settle, with full attribution."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        subsystem: str,
        operation_type: str = "auxiliary",
        session_id: str = "",
        run_id: str = "",
        turn_id: str = "",
        workspace_id: str = "",
        task_id: str = "",
        budget_inr: float = 0.50,
        token_budget: int = 4000,
        storage_dir: Optional[str] = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.subsystem = subsystem
        self.operation_type = operation_type
        self.session_id = session_id or os.environ.get("CRUSORAI_SESSION_ID", "")
        self.run_id = run_id or os.environ.get("CRUSORAI_ACCEPTANCE_RUN_ID", "")
        self.turn_id = turn_id or os.environ.get("CRUSORAI_TURN_ID", "")
        self.workspace_id = workspace_id or os.environ.get("CRUSORAI_WORKSPACE_ID", "")
        self.task_id = task_id or f"aux_{subsystem}_{self.session_id or 'session'}"
        self.budget_inr = float(budget_inr)
        self.token_budget = int(token_budget)
        self.storage_dir = storage_dir
        self._governor: Optional[OrchestrationFinOpsGovernor] = None

    def _resolve_governor(self) -> OrchestrationFinOpsGovernor:
        if self._governor is None:
            self._governor = OrchestrationFinOpsGovernor(
                self.task_id,
                budget_inr=self.budget_inr,
                token_budget=self.token_budget,
                storage_dir=self.storage_dir,
                workspace_root=str(self.workspace),
            )
        return self._governor

    def _record(
        self,
        *,
        invocation_id: str,
        reservation_id: str,
        provider: str,
        model: str,
        status: str,
        started: float,
        purpose: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cost_inr: float = 0.0,
        cost_usd: float = 0.0,
        error: str = "",
        mode: str = "provider",
    ) -> None:
        record_invocation(self.workspace, {
            "invocation_id": invocation_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "subsystem": self.subsystem,
            "operation_type": self.operation_type,
            "provider": provider,
            "model": model,
            "attempt_number": 1,
            "reservation_id": reservation_id,
            "usage_record_id": (
                f"{reservation_id}:usage" if input_tokens or output_tokens else ""
            ),
            "settlement_id": reservation_id if status == "settled" else "",
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "actual_cost_inr": cost_inr,
            "actual_cost_usd": cost_usd,
            "started_at": started,
            "completed_at": time.time(),
            "purpose": purpose,
            "mode": mode,
            "error": error[:1000],
        })

    def invoke(
        self,
        *,
        prompt: str,
        provider: str,
        model: str,
        max_output_tokens: int,
        purpose: str,
        client: Any = None,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> GovernedResult:
        """One physically accounted provider request (exactly one attempt)."""
        invocation_id = new_invocation_id()
        started = time.time()

        def _refuse(message: str) -> None:
            self._record(
                invocation_id=invocation_id, reservation_id="", provider=provider,
                model=model, status="blocked", started=started, purpose=purpose,
                error=message,
            )
            raise AuxiliaryAccountingError(message)

        if self.budget_inr <= 0:
            _refuse("auxiliary budget is zero; refusing provider call")
        pricing_reg = PricingRegistry.get_pricing_registry()
        pricing = pricing_reg.get_model_pricing(model, provider=provider)
        if not pricing or pricing.verification_status == VerificationStatus.UNKNOWN:
            _refuse(f"no verified pricing for {provider}/{model}; refusing unmetered call")
        bound = estimate_prompt_token_upper_bound(prompt, provider=provider, model=model)
        max_output = int(max_output_tokens)
        max_total = bound.upper_bound_tokens + max_output
        max_cost = calculate_max_request_cost(
            pricing_reg, model=model, provider=provider,
            input_tokens=bound.upper_bound_tokens, max_output_tokens=max_output,
        )
        if max_cost.cost_inr is None or max_cost.cost_usd is None:
            _refuse(f"pricing calculation failed for {provider}/{model}; refusing call")
        governor = self._resolve_governor()
        try:
            governor.authorize_operation(
                estimated_tokens=max_total, estimated_cost_inr=float(max_cost.cost_inr),
            )
            res_id = governor.reserve(
                estimated_tokens=max_total,
                estimated_cost_inr=float(max_cost.cost_inr),
                estimated_cost_usd=float(max_cost.cost_usd),
                purpose=f"{self.subsystem}:{purpose}",
            )
        except Exception as exc:
            self._record(
                invocation_id=invocation_id, reservation_id="", provider=provider,
                model=model, status="blocked", started=started, purpose=purpose,
                error=f"reservation refused: {type(exc).__name__}: {exc}",
            )
            raise AuxiliaryAccountingError(f"reservation refused: {exc}") from exc

        try:
            if client is None:
                if client_factory is None:
                    from src.llm.factory import get_llm

                    client = get_llm(provider=provider, model=model, max_attempts=1)
                else:
                    client = client_factory()
            if hasattr(client, "_max_attempts"):
                try:
                    client._max_attempts = 1
                except Exception:
                    pass
        except Exception as exc:
            governor.release_reservation(res_id, reason="aux_client_construction_failed")
            self._record(
                invocation_id=invocation_id, reservation_id=res_id, provider=provider,
                model=model, status="released", started=started, purpose=purpose,
                error=f"client construction failed: {type(exc).__name__}: {exc}",
            )
            raise AuxiliaryAccountingError(f"client construction failed: {exc}") from exc

        kwargs = build_output_token_kwargs(provider, max_output)
        if not kwargs or not can_enforce_token_limit(
            client, provider=provider, max_output_tokens=max_output,
        ):
            governor.release_reservation(res_id, reason="aux_provider_cannot_enforce_ceiling")
            self._record(
                invocation_id=invocation_id, reservation_id=res_id, provider=provider,
                model=model, status="released", started=started, purpose=purpose,
                error="provider cannot enforce the output token ceiling",
            )
            raise AuxiliaryAccountingError(
                f"provider {provider!r} cannot enforce the output ceiling"
            )

        governor.mark_in_flight(res_id)
        try:
            with invocation_scope(
                subsystem=self.subsystem,
                reservation_id=res_id,
                operation_type=self.operation_type,
                task_id=self.task_id,
                provider=provider,
                model=model,
                purpose=purpose,
            ):
                response = client.invoke(prompt, **kwargs)
        except Exception as exc:
            if is_uncertain_post_dispatch_error(exc):
                governor.mark_uncertain(
                    res_id, reason=f"aux_post_dispatch_error: {type(exc).__name__}",
                )
                self._record(
                    invocation_id=invocation_id, reservation_id=res_id, provider=provider,
                    model=model, status="uncertain", started=started, purpose=purpose,
                    error=f"{type(exc).__name__}: {exc}",
                )
            else:
                governor.release_reservation(res_id, reason="aux_dispatch_rejected")
                self._record(
                    invocation_id=invocation_id, reservation_id=res_id, provider=provider,
                    model=model, status="released", started=started, purpose=purpose,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise

        try:
            in_tok, out_tok, cached_tok = extract_provider_token_usage(response)
        except Exception as exc:
            governor.mark_uncertain(res_id, reason="aux_missing_usage_receipts")
            self._record(
                invocation_id=invocation_id, reservation_id=res_id, provider=provider,
                model=model, status="uncertain", started=started, purpose=purpose,
                error=f"missing usage receipts: {type(exc).__name__}",
            )
            raise

        calc = pricing_reg.calculate_cost(
            model=model, input_tokens=in_tok, output_tokens=out_tok,
            cached_tokens=cached_tok, provider=provider,
        )
        if calc.cost_inr is None or calc.cost_usd is None:
            governor.mark_uncertain(res_id, reason="aux_unverifiable_actual_cost")
            self._record(
                invocation_id=invocation_id, reservation_id=res_id, provider=provider,
                model=model, status="uncertain", started=started, purpose=purpose,
                input_tokens=in_tok, output_tokens=out_tok, cached_tokens=cached_tok,
                error="actual cost could not be calculated",
            )
            raise AuxiliaryAccountingError("actual cost could not be calculated")

        cost_inr = float(calc.cost_inr)
        cost_usd = float(calc.cost_usd)
        governor.commit_reservation(
            reservation_id=res_id,
            actual_input_tokens=in_tok,
            actual_output_tokens=out_tok,
            actual_cached_tokens=cached_tok,
            actual_cost_inr=cost_inr,
            actual_cost_usd=cost_usd,
        )
        self._record(
            invocation_id=invocation_id, reservation_id=res_id, provider=provider,
            model=model, status="settled", started=started, purpose=purpose,
            input_tokens=in_tok, output_tokens=out_tok, cached_tokens=cached_tok,
            cost_inr=cost_inr, cost_usd=cost_usd,
        )
        return GovernedResult(
            text=_response_text(response),
            invocation_id=invocation_id,
            reservation_id=res_id,
            provider=provider,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=cached_tok,
            actual_cost_inr=cost_inr,
            actual_cost_usd=cost_usd,
            status="settled",
            started_at=started,
            completed_at=time.time(),
        )

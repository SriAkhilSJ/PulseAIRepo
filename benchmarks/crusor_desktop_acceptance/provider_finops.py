"""Read-only provider and financial observability seams.

Nothing here changes the accounting algorithm or fabricates a receipt. Each
function either reads state that the real components already hold, or records
a boundary event whose mandatory fields are the real identifiers (provider
request id, reservation id, mutation id). A boundary call without identifiers
raises — a nameless "cost" record is not evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from benchmarks.crusor_desktop_acceptance.correlation import RunContext


class EvidenceIncomplete(RuntimeError):
    """A provider/financial record was attempted without real identifiers."""


@dataclass(frozen=True)
class DispatchObservation:
    provider: str
    model: str
    provider_request_id: str
    output_token_ceiling: int
    reservation_id: str
    turn_id: str
    session_id: str


def record_dispatch(
    ctx: RunContext,
    observation: DispatchObservation,
    *,
    attempt: int = 1,
    task_id: str = "",
) -> None:
    if not observation.provider_request_id:
        raise EvidenceIncomplete("provider dispatch record requires a provider_request_id")
    if not observation.reservation_id:
        raise EvidenceIncomplete("provider dispatch record requires a reservation_id")
    if not observation.turn_id:
        raise EvidenceIncomplete("provider dispatch record requires the desktop turn_id it belongs to")
    ctx.record(
        "provider",
        "provider.dispatch",
        {
            "provider": observation.provider,
            "model": observation.model,
            "output_token_ceiling": observation.output_token_ceiling,
            "attempt": attempt,
        },
        session_id=observation.session_id,
        turn_id=observation.turn_id,
        task_id=task_id,
        provider_request_id=observation.provider_request_id,
        reservation_id=observation.reservation_id,
    )


def record_usage_receipt(
    ctx: RunContext,
    *,
    provider_request_id: str,
    reservation_id: str,
    turn_id: str,
    session_id: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    finish_reason: str,
    raw_finish_reason: str,
) -> None:
    if not provider_request_id or not reservation_id or not turn_id:
        raise EvidenceIncomplete("usage receipt requires provider request, reservation and turn ids")
    ctx.record(
        "provider",
        "provider.usage_receipt",
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "finish_reason": finish_reason,
            "raw_finish_reason": raw_finish_reason,
        },
        session_id=session_id,
        turn_id=turn_id,
        provider_request_id=provider_request_id,
        reservation_id=reservation_id,
    )


def snapshot_finops(finops: Any) -> dict[str, Any]:
    """Read the governor's live state without touching it."""
    accounting = getattr(finops, "accounting", None)
    accounting_dict: dict[str, Any] = {}
    if accounting is not None and hasattr(accounting, "to_dict"):
        try:
            accounting_dict = accounting.to_dict()
        except Exception as exc:  # pragma: no cover - defensive
            accounting_dict = {"error": str(exc)}

    def _reservations(attr: str) -> list[dict[str, Any]]:
        store: Mapping[str, Any] = getattr(finops, attr, {}) or {}
        out = []
        for key, reservation in store.items():
            if hasattr(reservation, "to_dict"):
                out.append(reservation.to_dict())
            else:  # pragma: no cover - unusual object
                out.append({"id": str(key)})
        return out

    return {
        "task_id": getattr(finops, "task_id", ""),
        "accounting": accounting_dict,
        "active_reservations": _reservations("_active_reservations"),
        "uncertain_reservations": _reservations("_uncertain_reservations"),
        "settled_reservations": _reservations("_settled_reservations"),
        "unresolved_count": len(getattr(finops, "_active_reservations", {}) or {})
        + len(getattr(finops, "_uncertain_reservations", {}) or {}),
    }


def record_finops_snapshot(ctx: RunContext, finops: Any, *, session_id: str = "", turn_id: str = "") -> dict[str, Any]:
    snapshot = snapshot_finops(finops)
    ctx.record(
        "finops",
        "finops.snapshot",
        snapshot,
        session_id=session_id,
        turn_id=turn_id,
        task_id=str(snapshot.get("task_id") or ""),
    )
    return snapshot


def preflight_estimate(
    *,
    prompt: str,
    provider: str,
    model: str,
    max_output_tokens: int,
    budget_inr: float = 5.00,
) -> dict[str, Any]:
    """Offline budget arithmetic using the production helpers (no dispatch)."""
    from src.finops.pricing_registry import PricingRegistry, VerificationStatus
    from src.orchestration.model_adapter import (
        calculate_max_request_cost,
        estimate_prompt_token_upper_bound,
    )

    registry = PricingRegistry.get_pricing_registry()
    pricing = registry.get_model_pricing(model, provider=provider)
    bound = estimate_prompt_token_upper_bound(prompt, provider=provider, model=model)
    cost = calculate_max_request_cost(
        registry,
        model=model,
        provider=provider,
        input_tokens=bound.upper_bound_tokens,
        max_output_tokens=max_output_tokens,
    )
    return {
        "provider": provider,
        "model": model,
        "pricing_verified": bool(pricing and pricing.verification_status == VerificationStatus.VERIFIED),
        "input_price_per_1m_usd": getattr(pricing, "input_price_per_1m", None),
        "output_price_per_1m_usd": getattr(pricing, "output_price_per_1m", None),
        "prompt_upper_bound_tokens": bound.upper_bound_tokens,
        "bound_method": bound.method,
        "max_output_tokens": max_output_tokens,
        "max_cost_usd": float(cost.cost_usd) if cost.cost_usd is not None else None,
        "max_cost_inr": float(cost.cost_inr) if cost.cost_inr is not None else None,
        "budget_inr": budget_inr,
        "fits_budget": bool(
            cost.cost_inr is not None and float(cost.cost_inr) <= float(budget_inr)
        ),
    }


def provider_retry_configuration() -> dict[str, Any]:
    """Report the retry/failover posture the run would inherit (read-only)."""
    info: dict[str, Any] = {}
    try:
        from src.config.settings import LLM_MODEL, LLM_PROVIDER
        from src.llm import factory

        info["provider"] = LLM_PROVIDER
        info["model"] = LLM_MODEL
        proxy_cls = getattr(factory, "RetryLLMProxy", None)
        info["retry_proxy_class"] = getattr(proxy_cls, "__name__", None)
        client = factory.get_llm(LLM_PROVIDER, LLM_MODEL)
        info["max_attempts"] = getattr(client, "_max_attempts", None)
        inner = getattr(client, "_llm", None) or getattr(client, "llm", None)
        info["inner_client_class"] = type(inner).__name__ if inner is not None else None
        info["max_retries"] = getattr(inner, "max_retries", None)
        info["failover"] = bool(getattr(client, "_failover", False))
    except Exception as exc:  # pragma: no cover - environment dependent
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info

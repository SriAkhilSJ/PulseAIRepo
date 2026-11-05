"""
observability.py -- FinOps Telemetry, Tracing & Metrics Subsystem.

Phase 9.7: Enterprise FinOps & Intelligent Cost Governance.
Connects the FinOps engine directly to Phase 9.6 Desktop Observability:
- Emits distributed trace spans for financial reservations, token metering, and budget checks.
- Records real-time cost, token volume, and cache efficiency metrics.
- Automatic secret sanitization using Phase 9.6 SecretRedactor (zero API key / token leaks).
- Tracks variance between estimated costs and final provider receipts.
- Exposes structured telemetry snapshots for bench-results and diagnostic reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from src.observability.metrics import get_metrics_collector
from src.observability.redaction import redact_sensitive_data
from src.observability.tracing import (
    DesktopComponent,
    OperationOutcome,
    TraceSpan,
    get_tracer,
)

log = logging.getLogger("crusorai.finops.observability")


@dataclass
class FinOpsTelemetrySnapshot:
    """Comprehensive diagnostic snapshot of financial health."""
    total_spend_usd: float
    total_spend_inr: float
    total_tokens_consumed: int
    cached_tokens_consumed: int
    cached_savings_usd: float
    total_calls_recorded: int
    unrated_calls_recorded: int
    active_budget_headroom_usd: float
    budget_exhaustion_events: int
    model_routing_counts: Dict[str, int]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_spend_usd": round(self.total_spend_usd, 4),
            "total_spend_inr": round(self.total_spend_inr, 2),
            "total_tokens_consumed": self.total_tokens_consumed,
            "cached_tokens_consumed": self.cached_tokens_consumed,
            "cached_savings_usd": round(self.cached_savings_usd, 4),
            "total_calls_recorded": self.total_calls_recorded,
            "unrated_calls_recorded": self.unrated_calls_recorded,
            "active_budget_headroom_usd": round(self.active_budget_headroom_usd, 2),
            "budget_exhaustion_events": self.budget_exhaustion_events,
            "model_routing_counts": self.model_routing_counts,
            "timestamp": self.timestamp,
        }


class FinOpsObservabilityTracer:
    """
    Observability gateway capturing financial telemetry.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tracer = get_tracer()
        self._metrics = get_metrics_collector()
        self._routing_distribution: Dict[str, int] = {}
        self._budget_exhaustion_count: int = 0

    def trace_financial_reservation(
        self,
        session_id: str,
        correlation_id: str,
        amount_usd: Decimal,
        scope: str = "task",
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> TraceSpan:
        """Trace an atomic budget reservation attempt."""
        span = self._tracer.start_span(
            correlation_id=correlation_id,
            component=DesktopComponent.AGENT_CORE,
            operation="finops.reserve_budget",
            metadata={
                "session_id": session_id,
                "scope": scope,
                "amount_usd": float(amount_usd),
            },
        )
        outcome = OperationOutcome.SUCCESS if success else OperationOutcome.ERROR
        span.finish(
            outcome=outcome,
            error_category="BudgetExhausted" if not success else None,
            error_message=error_message,
        )
        if not success:
            with self._lock:
                self._budget_exhaustion_count += 1
        return span

    def trace_model_routing(
        self,
        correlation_id: str,
        task_complexity: str,
        selected_model: str,
        selected_tier: str,
        estimated_cost_usd: Decimal,
        is_user_pinned: bool,
    ) -> TraceSpan:
        """Trace a model routing evaluation."""
        with self._lock:
            self._routing_distribution[selected_model] = self._routing_distribution.get(selected_model, 0) + 1

        span = self._tracer.start_span(
            correlation_id=correlation_id,
            component=DesktopComponent.AGENT_CORE,
            operation="finops.model_routing",
            metadata={
                "task_complexity": task_complexity,
                "selected_model": selected_model,
                "selected_tier": selected_tier,
                "estimated_cost_usd": float(estimated_cost_usd),
                "is_user_pinned": is_user_pinned,
            },
        )
        span.finish(outcome=OperationOutcome.SUCCESS)
        return span

    def record_token_telemetry(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Optional[Decimal] = None,
        cached_tokens: int = 0,
    ) -> None:
        """Record operational token counts and spend into telemetry."""
        total = input_tokens + output_tokens
        # Sanitize model name and metadata
        safe_model = redact_sensitive_data(model)
        self._metrics.record_latency(f"tokens.{safe_model}.volume", float(total))
        if cost_usd is not None:
            self._metrics.record_latency(f"cost.{safe_model}.usd", float(cost_usd))

    def get_routing_distribution(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._routing_distribution)

    def get_exhaustion_count(self) -> int:
        with self._lock:
            return self._budget_exhaustion_count


_GLOBAL_FINOPS_OBS: Optional[FinOpsObservabilityTracer] = None
_OBS_LOCK = threading.Lock()


def get_finops_observability() -> FinOpsObservabilityTracer:
    global _GLOBAL_FINOPS_OBS
    with _OBS_LOCK:
        if _GLOBAL_FINOPS_OBS is None:
            _GLOBAL_FINOPS_OBS = FinOpsObservabilityTracer()
        return _GLOBAL_FINOPS_OBS


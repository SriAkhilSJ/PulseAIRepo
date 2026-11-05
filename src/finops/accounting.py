"""
accounting.py -- Reliable, Idempotent Token & Usage Accounting Engine.

Phase 9.7: Enterprise FinOps & Intelligent Cost Governance.
Provides immutable, idempotent event accounting for model operations:
- Fine-grained token metrics: prompt, completion, cached, reasoning tokens.
- Multi-dimensional attribution: request_id, task_id, workspace_id, session_id.
- Exact vs Estimated distinction to protect billing transparency.
- Streaming chunk aggregation and deduplication preventing double-counting.
- Thread-safe in-memory cache with durable persistence integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set

from src.finops.pricing_registry import (
    CalculatedCost,
    ModelPricingRegistry,
    VerificationStatus,
    get_pricing_registry,
    quantize_currency,
)

log = logging.getLogger("crusorai.finops.accounting")


@dataclass
class UsageRecord:
    """Immutable audit record for a single model operation."""
    event_id: str                      # Unique idempotency key
    request_id: str
    task_id: str
    session_id: str
    workspace_id: str
    provider: str
    model: str
    operation_type: str                # e.g., 'completion', 'embedding', 'planner', 'tool_turn'
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Optional[Decimal] = None
    cost_inr: Optional[Decimal] = None
    currency: str = "USD"
    is_reported_by_provider: bool = False
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    retry_count: int = 0
    timestamp: float = field(default_factory=time.time)
    duration_s: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "provider": self.provider,
            "model": self.model,
            "operation_type": self.operation_type,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": float(self.cost_usd) if self.cost_usd is not None else None,
            "cost_inr": float(self.cost_inr) if self.cost_inr is not None else None,
            "currency": self.currency,
            "is_reported_by_provider": self.is_reported_by_provider,
            "verification_status": self.verification_status.value,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp,
            "duration_s": round(self.duration_s, 3),
            "metadata": self.metadata,
        }


class TokenAccountingEngine:
    """
    Idempotent token and cost accounting ledger.
    Guarantees no double-counting during retries, streaming, or re-executions.
    """

    def __init__(self, registry: Optional[ModelPricingRegistry] = None) -> None:
        self._lock = threading.RLock()
        self._registry = registry or get_pricing_registry()
        # In-memory storage for rapid lookup and deduplication
        self._records_by_event: Dict[str, UsageRecord] = {}
        self._request_seen_ids: Set[str] = set()
        self._active_streams: Dict[str, Dict[str, Any]] = {}

    def generate_idempotency_key(
        self,
        request_id: str,
        session_id: str,
        retry_count: int = 0,
        extra_salt: str = "",
    ) -> str:
        """Derive deterministic idempotency key for an operation."""
        raw = f"{session_id}:{request_id}:{retry_count}:{extra_salt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def record_usage(
        self,
        request_id: str,
        session_id: str,
        task_id: str = "default_task",
        workspace_id: str = "default_workspace",
        provider: str = "openai",
        model: str = "gpt-4o",
        operation_type: str = "chat",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
        reported_cost_usd: Optional[float] = None,
        reported_cost_inr: Optional[float] = None,
        retry_count: int = 0,
        duration_s: float = 0.0,
        event_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UsageRecord:
        """
        Record token consumption for an operation.
        Idempotent: Duplicate calls with the same event_id / request_id + retry_count return existing record.
        """
        resolved_event_id = event_id or self.generate_idempotency_key(request_id, session_id, retry_count)

        with self._lock:
            # Idempotency check: if already recorded, return pristine existing record without re-accumulating
            if resolved_event_id in self._records_by_event:
                log.info("Idempotent deduplication triggered for event %s", resolved_event_id)
                return self._records_by_event[resolved_event_id]

            total_tokens = input_tokens + output_tokens

            # Calculate cost breakdown through pricing registry
            calc = self._registry.calculate_cost(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                reasoning_tokens=reasoning_tokens,
                provider=provider,
                reported_cost_usd=reported_cost_usd,
                reported_cost_inr=reported_cost_inr,
            )

            is_reported = reported_cost_usd is not None or reported_cost_inr is not None

            record = UsageRecord(
                event_id=resolved_event_id,
                request_id=request_id,
                task_id=task_id,
                session_id=session_id,
                workspace_id=workspace_id,
                provider=provider,
                model=model,
                operation_type=operation_type,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                reasoning_tokens=reasoning_tokens,
                total_tokens=total_tokens,
                cost_usd=calc.cost_usd,
                cost_inr=calc.cost_inr,
                currency=calc.currency,
                is_reported_by_provider=is_reported,
                verification_status=calc.verification_status,
                retry_count=retry_count,
                duration_s=duration_s,
                metadata=metadata or {},
            )

            self._records_by_event[resolved_event_id] = record
            self._request_seen_ids.add(request_id)

            # Persist to durable SQLite session store if available
            self._sync_to_financial_store(record)

            return record

    def track_stream_chunk(
        self,
        stream_id: str,
        request_id: str,
        session_id: str,
        chunk_text: str,
        model: str,
        provider: str = "openai",
        is_first: bool = False,
        is_final: bool = False,
        reported_usage: Optional[Dict[str, int]] = None,
    ) -> Optional[UsageRecord]:
        """
        Safely accumulate streaming chunks.
        Emits one final usage record only upon stream completion, preventing double-counting of chunks.
        """
        with self._lock:
            if is_first or stream_id not in self._active_streams:
                self._active_streams[stream_id] = {
                    "request_id": request_id,
                    "session_id": session_id,
                    "model": model,
                    "provider": provider,
                    "char_count": 0,
                    "start_time": time.time(),
                }

            stream_data = self._active_streams[stream_id]
            stream_data["char_count"] += len(chunk_text or "")

            if is_final:
                duration_s = time.time() - stream_data["start_time"]
                # If usage reported by provider in final stream frame, use exact numbers
                if reported_usage:
                    in_tok = reported_usage.get("prompt_tokens", 0)
                    out_tok = reported_usage.get("completion_tokens", 0)
                    cached_tok = reported_usage.get("cached_tokens", 0)
                    reason_tok = reported_usage.get("reasoning_tokens", 0)
                else:
                    # Deterministic fallback estimation: ~4 chars per token
                    out_tok = max(1, stream_data["char_count"] // 4)
                    in_tok = 0
                    cached_tok = 0
                    reason_tok = 0

                del self._active_streams[stream_id]

                return self.record_usage(
                    request_id=request_id,
                    session_id=session_id,
                    provider=provider,
                    model=model,
                    operation_type="stream_completion",
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cached_tokens=cached_tok,
                    reasoning_tokens=reason_tok,
                    duration_s=duration_s,
                    event_id=f"stream-{stream_id}",
                )

            return None

    def _sync_to_financial_store(self, record: UsageRecord) -> None:
        """Best-effort persistence bridge into existing canonical financial_store."""
        try:
            from src.agents.financial_store import get_financial_store
            store = get_financial_store()
            if store:
                store.record_call_event(
                    event_id=record.event_id,
                    root_session_id=record.session_id,
                    child_session_id=record.metadata.get("child_session_id"),
                    turn_id=record.metadata.get("turn_id", 1),
                    provider=record.provider,
                    model=record.model,
                    tier=record.metadata.get("tier", "standard"),
                    purpose=record.operation_type,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    cached_tokens=record.cached_tokens,
                    total_tokens=record.total_tokens,
                    estimated_cost_usd=record.cost_usd,
                    estimated_cost_inr=record.cost_inr,
                    actual_cost_usd=record.cost_usd if record.is_reported_by_provider else None,
                    actual_cost_inr=record.cost_inr if record.is_reported_by_provider else None,
                    cost_known=record.verification_status != VerificationStatus.UNKNOWN,
                    pricing_status=record.verification_status.value,
                    call_outcome="completed",
                )
        except Exception as exc:
            log.debug("Durable store sync skipped: %s", exc)

    def get_record(self, event_id: str) -> Optional[UsageRecord]:
        with self._lock:
            return self._records_by_event.get(event_id)

    def list_records(self) -> List[UsageRecord]:
        with self._lock:
            return list(self._records_by_event.values())

    def clear(self) -> None:
        with self._lock:
            self._records_by_event.clear()
            self._request_seen_ids.clear()
            self._active_streams.clear()


_GLOBAL_ACCOUNTING: Optional[TokenAccountingEngine] = None
_ACCOUNTING_LOCK = threading.Lock()


def get_accounting_engine() -> TokenAccountingEngine:
    global _GLOBAL_ACCOUNTING
    with _ACCOUNTING_LOCK:
        if _GLOBAL_ACCOUNTING is None:
            _GLOBAL_ACCOUNTING = TokenAccountingEngine()
        return _GLOBAL_ACCOUNTING


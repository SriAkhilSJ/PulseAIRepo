"""
tracing.py - Cross-Component Distributed Correlation Tracing for Crusor Desktop.

Phase 9.6: Desktop Performance & Observability.
Tracks requests across:
Electron Main -> Renderer -> Utility Process -> Python Sidecar -> Agent Core -> MCP/Browser.
"""

from __future__ import annotations

import collections
import enum
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.observability.redaction import redact_sensitive_data


class DesktopComponent(str, enum.Enum):
    ELECTRON_MAIN = "electron_main"
    RENDERER = "renderer"
    UTILITY_PROCESS = "utility_process"
    PYTHON_SIDECAR = "python_sidecar"
    AGENT_CORE = "agent_core"
    MCP_GATEWAY = "mcp_gateway"
    BROWSER_AGENT = "browser_agent"


class OperationOutcome(str, enum.Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    correlation_id: str
    component: DesktopComponent
    operation: str
    start_time: float = field(default_factory=time.time)
    parent_span_id: Optional[str] = None
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    outcome: OperationOutcome = OperationOutcome.SUCCESS
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def finish(
        self,
        outcome: OperationOutcome = OperationOutcome.SUCCESS,
        error_category: Optional[str] = None,
        error_message: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 3)
        self.outcome = outcome
        self.error_category = error_category
        if error_message:
            self.error_message = redact_sensitive_data(error_message)
        if extra_metadata:
            self.metadata.update(redact_sensitive_data(extra_metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "correlation_id": self.correlation_id,
            "component": self.component.value if isinstance(self.component, DesktopComponent) else str(self.component),
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "outcome": self.outcome.value if isinstance(self.outcome, OperationOutcome) else str(self.outcome),
            "error_category": self.error_category,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "metadata": self.metadata,
        }


class DesktopObservabilityTracer:
    """
    Thread-safe, bounded memory correlation tracer for desktop operations.
    """

    def __init__(self, max_retained_spans: int = 2000) -> None:
        self.max_retained_spans = max_retained_spans
        # Ring buffer prevents unbounded memory growth during extended sessions
        self._spans: collections.deque[TraceSpan] = collections.deque(maxlen=max_retained_spans)
        self._active_spans: Dict[str, TraceSpan] = {}

    @classmethod
    def generate_correlation_id(cls, prefix: str = "crusor") -> str:
        """Generate high-entropy unique correlation ID."""
        ts_ms = int(time.time() * 1000)
        rand_token = uuid.uuid4().hex[:10]
        return f"{prefix}_{ts_ms}_{rand_token}"

    def start_span(
        self,
        component: DesktopComponent,
        operation: str,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TraceSpan:
        corr_id = correlation_id or self.generate_correlation_id()
        tr_id = trace_id or f"tr_{uuid.uuid4().hex[:12]}"
        sp_id = f"sp_{uuid.uuid4().hex[:8]}"

        safe_meta = redact_sensitive_data(metadata or {})
        span = TraceSpan(
            trace_id=tr_id,
            span_id=sp_id,
            parent_span_id=parent_span_id,
            correlation_id=corr_id,
            component=component,
            operation=operation,
            metadata=safe_meta,
        )
        self._active_spans[sp_id] = span
        return span

    def end_span(
        self,
        span: TraceSpan,
        outcome: OperationOutcome = OperationOutcome.SUCCESS,
        error_category: Optional[str] = None,
        error_message: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        span.finish(outcome=outcome, error_category=error_category, error_message=error_message, extra_metadata=extra_metadata)
        self._active_spans.pop(span.span_id, None)
        self._spans.append(span)

    def get_spans_by_correlation_id(self, correlation_id: str) -> List[TraceSpan]:
        """Query span timeline across components for an exact correlation ID."""
        return [s for s in self._spans if s.correlation_id == correlation_id]

    def get_recent_spans(self, limit: int = 50) -> List[Dict[str, Any]]:
        recent = list(self._spans)[-limit:]
        return [s.to_dict() for s in recent]

    def clear(self) -> None:
        self._spans.clear()
        self._active_spans.clear()


_GLOBAL_TRACER: Optional[DesktopObservabilityTracer] = None


def get_tracer() -> DesktopObservabilityTracer:
    global _GLOBAL_TRACER
    if _GLOBAL_TRACER is None:
        _GLOBAL_TRACER = DesktopObservabilityTracer()
    return _GLOBAL_TRACER


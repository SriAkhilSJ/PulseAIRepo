"""
src/observability - Unified Desktop Observability, Performance Monitoring & Tracing Subsystem.

Phase 9.6: Desktop Performance & Observability.
"""

from src.observability.redaction import (
    SecretRedactor,
    redact_sensitive_data,
)
from src.observability.tracing import (
    DesktopComponent,
    DesktopObservabilityTracer,
    OperationOutcome,
    TraceSpan,
    get_tracer,
)
from src.observability.metrics import (
    LatencyHistogram,
    LatencySummary,
    PerformanceMetricsCollector,
    get_metrics_collector,
)
from src.observability.bridge_governor import (
    BridgeBackpressureError,
    BridgeError,
    BridgeGovernor,
    BridgePayloadSizeError,
    BridgeTimeoutError,
    PendingBridgeRequest,
)
from src.observability.monitor import (
    BASELINE_TARGETS,
    DesktopHealthStatus,
    DesktopPerformanceMonitor,
    get_performance_monitor,
)

__all__ = [
    "SecretRedactor",
    "redact_sensitive_data",
    "DesktopComponent",
    "DesktopObservabilityTracer",
    "OperationOutcome",
    "TraceSpan",
    "get_tracer",
    "LatencyHistogram",
    "LatencySummary",
    "PerformanceMetricsCollector",
    "get_metrics_collector",
    "BridgeGovernor",
    "BridgeError",
    "BridgeBackpressureError",
    "BridgeTimeoutError",
    "BridgePayloadSizeError",
    "PendingBridgeRequest",
    "DesktopHealthStatus",
    "DesktopPerformanceMonitor",
    "BASELINE_TARGETS",
    "get_performance_monitor",
]


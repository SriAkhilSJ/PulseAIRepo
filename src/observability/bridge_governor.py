"""
bridge_governor.py - IPC & JSONL Bridge Reliability, Backpressure & Timeout Governor.

Phase 9.6: Desktop Performance & Observability.
Manages communication reliability between:
- Electron Main / Utility Process
- Python Sidecar (`src.bridge`)
- Agent Core

Guarantees:
1. End-to-end request correlation (`request_id` / `correlation_id`).
2. Bounded queue depth with proactive backpressure management.
3. Message frame size enforcement (`MAX_LINE_BYTES = 1048576`).
4. Timed execution and cancel propagation.
5. Crash detection and connection health tracking.
"""

from __future__ import annotations

import collections
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.observability.metrics import get_metrics_collector
from src.observability.redaction import redact_sensitive_data
from src.observability.tracing import (
    DesktopComponent,
    OperationOutcome,
    get_tracer,
)

# Standard protocol bounds
DEFAULT_MAX_QUEUE_DEPTH = 1000
DEFAULT_MAX_FRAME_BYTES = 1 << 20  # 1 MB
DEFAULT_REQUEST_TIMEOUT_S = 30.0


class BridgeError(Exception):
    pass


class BridgeBackpressureError(BridgeError):
    """Raised when queue depth exceeds safety limits."""
    pass


class BridgeTimeoutError(BridgeError):
    """Raised when a request exceeds bounded timeout."""
    pass


class BridgePayloadSizeError(BridgeError):
    """Raised when a frame exceeds maximum line bytes."""
    pass


@dataclass
class PendingBridgeRequest:
    request_id: str
    correlation_id: str
    method: str
    payload: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S
    callback: Optional[Callable[[Dict[str, Any]], None]] = None
    is_cancelled: bool = False
    completed: bool = False
    response_payload: Optional[Dict[str, Any]] = None

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.timeout_s


class BridgeGovernor:
    """
    Manages bounded queues, request-response correlation, and timeouts for the desktop bridge.
    """

    def __init__(
        self,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        default_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    ) -> None:
        self.max_queue_depth = max_queue_depth
        self.max_frame_bytes = max_frame_bytes
        self.default_timeout_s = default_timeout_s

        self._inbound_queue: collections.deque[Dict[str, Any]] = collections.deque(maxlen=max_queue_depth)
        self._outbound_queue: collections.deque[bytes] = collections.deque(maxlen=max_queue_depth)
        self._pending_requests: Dict[str, PendingBridgeRequest] = {}
        self._lock = threading.Lock()

        self._sidecar_connected = False
        self._sidecar_crashes = 0
        self._total_requests_dispatched = 0
        self._total_responses_received = 0
        self._total_timeouts = 0
        self._total_cancellations = 0
        self._total_backpressure_rejections = 0

        self._metrics = get_metrics_collector()
        self._tracer = get_tracer()

    def set_sidecar_state(self, connected: bool) -> None:
        with self._lock:
            self._sidecar_connected = connected

    def record_sidecar_crash(self) -> None:
        with self._lock:
            self._sidecar_crashes += 1
            self._sidecar_connected = False
            # Fail all currently pending requests
            for req in list(self._pending_requests.values()):
                req.completed = True
            self._pending_requests.clear()
        self._metrics.record_error("python_sidecar", "SIDECAR_CRASH")

    def enqueue_inbound_frame(self, raw_line: bytes) -> Dict[str, Any]:
        """
        Validate and enqueue an incoming frame from the sidecar.
        Enforces frame size limits and validates JSON format.
        """
        if len(raw_line) > self.max_frame_bytes:
            self._metrics.record_error("ipc_bridge", "FRAME_SIZE_EXCEEDED")
            raise BridgePayloadSizeError(
                f"Frame size ({len(raw_line)} bytes) exceeds limit ({self.max_frame_bytes} bytes)."
            )

        with self._lock:
            if len(self._inbound_queue) >= self.max_queue_depth:
                self._total_backpressure_rejections += 1
                self._metrics.record_error("ipc_bridge", "INBOUND_QUEUE_OVERFLOW")
                raise BridgeBackpressureError("Inbound bridge queue capacity saturated (backpressure rejection).")

        try:
            frame = json.loads(raw_line.decode("utf-8"))
        except Exception as exc:
            self._metrics.record_error("ipc_bridge", "MALFORMED_JSON_FRAME")
            raise BridgeError(f"Malformed JSON frame received: {exc}") from exc

        if not isinstance(frame, dict) or "type" not in frame:
            raise BridgeError("Frame must be a JSON object containing a 'type' property.")

        req_id = frame.get("request_id") or frame.get("id")
        if req_id and req_id in self._pending_requests:
            with self._lock:
                pending = self._pending_requests.pop(req_id, None)
            if pending:
                duration_ms = (time.time() - pending.created_at) * 1000.0
                pending.completed = True
                pending.response_payload = frame
                self._metrics.record_latency(f"bridge.method.{pending.method}", duration_ms)
                if pending.callback:
                    try:
                        pending.callback(frame)
                    except Exception:
                        pass

        with self._lock:
            self._inbound_queue.append(frame)
            self._total_responses_received += 1
            self._metrics.record_queue_depth("bridge_inbound", len(self._inbound_queue))

        return frame

    def dispatch_request(
        self,
        method: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout_s: Optional[float] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        correlation_id: Optional[str] = None,
    ) -> PendingBridgeRequest:
        """
        Dispatch a request across the bridge with correlated request ID and timeout tracking.
        """
        with self._lock:
            if len(self._outbound_queue) >= self.max_queue_depth:
                self._total_backpressure_rejections += 1
                self._metrics.record_error("ipc_bridge", "OUTBOUND_QUEUE_OVERFLOW")
                raise BridgeBackpressureError("Outbound bridge queue capacity saturated (backpressure rejection).")

        req_id = f"req_{uuid.uuid4().hex[:12]}"
        corr_id = correlation_id or self._tracer.generate_correlation_id()
        t_limit = timeout_s or self.default_timeout_s

        body = payload or {}
        frame_obj = {
            "type": method,
            "request_id": req_id,
            "correlation_id": corr_id,
            **body,
        }

        encoded = (json.dumps(frame_obj, ensure_ascii=False) + "\n").encode("utf-8")
        if len(encoded) > self.max_frame_bytes:
            raise BridgePayloadSizeError(
                f"Outbound frame size ({len(encoded)} bytes) exceeds limit ({self.max_frame_bytes} bytes)."
            )

        req = PendingBridgeRequest(
            request_id=req_id,
            correlation_id=corr_id,
            method=method,
            payload=body,
            timeout_s=t_limit,
            callback=callback,
        )

        with self._lock:
            self._pending_requests[req_id] = req
            self._outbound_queue.append(encoded)
            self._total_requests_dispatched += 1
            self._metrics.record_queue_depth("bridge_outbound", len(self._outbound_queue))

        return req

    def cancel_request(self, request_id: str) -> bool:
        """
        Mark a pending request as cancelled and propagate cancellation event.
        """
        with self._lock:
            req = self._pending_requests.pop(request_id, None)
            if req:
                req.is_cancelled = True
                req.completed = True
                self._total_cancellations += 1
                cancel_frame = {
                    "type": "cancel",
                    "request_id": request_id,
                    "correlation_id": req.correlation_id,
                }
                encoded = (json.dumps(cancel_frame) + "\n").encode("utf-8")
                self._outbound_queue.append(encoded)
                return True
        return False

    def sweep_expired_requests(self) -> List[PendingBridgeRequest]:
        """
        Sweep and fail expired requests exceeding their bounded timeouts.
        """
        expired: List[PendingBridgeRequest] = []
        now = time.time()
        with self._lock:
            for req_id, req in list(self._pending_requests.items()):
                if (now - req.created_at) > req.timeout_s:
                    self._pending_requests.pop(req_id, None)
                    req.completed = True
                    expired.append(req)
                    self._total_timeouts += 1

        for ex in expired:
            self._metrics.record_error("ipc_bridge", f"TIMEOUT_{ex.method.upper()}")
            span = self._tracer.start_span(
                component=DesktopComponent.UTILITY_PROCESS,
                operation=f"bridge.timeout.{ex.method}",
                correlation_id=ex.correlation_id,
            )
            self._tracer.end_span(
                span,
                outcome=OperationOutcome.TIMEOUT,
                error_category="BRIDGE_TIMEOUT",
                error_message=f"Request {ex.request_id} ({ex.method}) exceeded timeout of {ex.timeout_s}s",
            )
        return expired

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "sidecar_connected": self._sidecar_connected,
                "sidecar_crashes": self._sidecar_crashes,
                "pending_requests_count": len(self._pending_requests),
                "inbound_queue_depth": len(self._inbound_queue),
                "outbound_queue_depth": len(self._outbound_queue),
                "total_requests_dispatched": self._total_requests_dispatched,
                "total_responses_received": self._total_responses_received,
                "total_timeouts": self._total_timeouts,
                "total_cancellations": self._total_cancellations,
                "total_backpressure_rejections": self._total_backpressure_rejections,
            }

    def clear(self) -> None:
        with self._lock:
            self._inbound_queue.clear()
            self._outbound_queue.clear()
            self._pending_requests.clear()


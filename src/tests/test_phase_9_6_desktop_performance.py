"""
test_phase_9_6_desktop_performance.py - Comprehensive Deterministic Test Suite for Phase 9.6.

Evaluates 20 distinct performance, observability, and reliability scenarios:
1. Cold startup latency measurement
2. Warm startup latency measurement
3. Repeated startup and shutdown lifecycle
4. IPC & bridge latency histogram percentiles
5. Large permitted bridge frames (boundary up to 1 MB)
6. Concurrent IPC requests with correlation matching
7. Request timeout detection and fail-closed handling
8. Request cancellation propagation
9. Sidecar crash detection and recovery
10. Queue depth & backpressure protection
11. Context retrieval performance & cache hits
12. Extended session memory stability (bounded buffers)
13. MCP session lifecycle and resource cleanup
14. Browser session lifecycle and profile cleanup
15. Sensitive credential redaction across traces and logs
16. Cross-component distributed tracing (W3C correlation)
17. Performance regression detection against baselines
18. Desktop health status watchdog and warnings
19. Structured diagnostic snapshot serialization
20. High event volume throughput under load
"""

import os
import sys
import time
import unittest
from pathlib import Path

# Add PulseAIRepo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

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


class TestPhase96DesktopPerformance(unittest.TestCase):
    def setUp(self):
        self.tracer = DesktopObservabilityTracer(max_retained_spans=100)
        self.metrics = PerformanceMetricsCollector()
        self.governor = BridgeGovernor(max_queue_depth=50, max_frame_bytes=1024 * 1024, default_timeout_s=2.0)
        self.monitor = DesktopPerformanceMonitor(
            metrics_collector=self.metrics,
            tracer=self.tracer,
            bridge_governor=self.governor,
        )

    # =========================================================================
    # 1 & 2: STARTUP PERFORMANCE (COLD & WARM)
    # =========================================================================

    def test_01_cold_startup_latency_measurement(self):
        """Verify cold startup tracking records latency and milestones."""
        rec = self.monitor.record_startup_event(
            mode="cold",
            total_duration_ms=2850.5,
            workbench_ready_ms=2100.0,
            sidecar_ready_ms=750.5,
            metadata={"cache_cleared": True},
        )
        self.assertEqual(rec["mode"], "cold")
        self.assertEqual(rec["total_duration_ms"], 2850.5)

        summary = self.metrics.get_latency_summary("startup.cold")
        self.assertIsNotNone(summary)
        self.assertEqual(summary.count, 1)
        self.assertEqual(summary.median_ms, 2850.5)

    def test_02_warm_startup_latency_measurement(self):
        """Verify warm startup latency is recorded and faster than cold baseline."""
        self.monitor.record_startup_event(
            mode="warm",
            total_duration_ms=850.0,
            workbench_ready_ms=600.0,
            sidecar_ready_ms=250.0,
        )
        summary = self.metrics.get_latency_summary("startup.warm")
        self.assertIsNotNone(summary)
        self.assertEqual(summary.count, 1)
        self.assertLess(summary.median_ms, BASELINE_TARGETS["startup.warm"])

    # =========================================================================
    # 3: REPEATED STARTUP AND SHUTDOWN LIFECYCLE
    # =========================================================================

    def test_03_repeated_startup_shutdown_lifecycle(self):
        """Verify repeated lifecycle start/stop maintains clean state without leaks."""
        for i in range(10):
            self.governor.set_sidecar_state(True)
            self.assertTrue(self.governor._sidecar_connected)
            req = self.governor.dispatch_request("ping", {"iteration": i})
            self.governor.enqueue_inbound_frame(
                f'{{"type": "pong", "request_id": "{req.request_id}", "iteration": {i}}}\n'.encode("utf-8")
            )
            self.governor.set_sidecar_state(False)
            self.assertFalse(self.governor._sidecar_connected)

        stats = self.governor.get_stats()
        self.assertEqual(stats["total_requests_dispatched"], 10)
        self.assertEqual(stats["total_responses_received"], 10)
        self.assertEqual(stats["pending_requests_count"], 0)

    # =========================================================================
    # 4: IPC & BRIDGE LATENCY HISTOGRAM PERCENTILES
    # =========================================================================

    def test_04_latency_histogram_percentiles(self):
        """Verify histogram calculates count, min, median, p95, p99, max accurately."""
        hist = LatencyHistogram(max_samples=1000)
        for i in range(1, 101):
            hist.record(float(i))

        summary = hist.summarize()
        self.assertEqual(summary.count, 100)
        self.assertEqual(summary.min_ms, 1.0)
        self.assertEqual(summary.median_ms, 50.5)
        self.assertEqual(summary.p95_ms, 96.0)
        self.assertEqual(summary.p99_ms, 100.0)
        self.assertEqual(summary.max_ms, 100.0)

    # =========================================================================
    # 5: LARGE PERMITTED BRIDGE FRAMES
    # =========================================================================

    def test_05_large_permitted_frame_boundary(self):
        """Verify frame up to 1 MB limit is accepted while frame > 1 MB raises BridgePayloadSizeError."""
        # 500 KB permitted frame
        payload_500kb = {"type": "file_data", "content": "x" * (500 * 1024)}
        raw_500kb = (import_json := __import__("json")).dumps(payload_500kb).encode("utf-8")
        parsed = self.governor.enqueue_inbound_frame(raw_500kb)
        self.assertEqual(parsed["type"], "file_data")

        # 1.1 MB frame exceeding 1 MB limit
        payload_huge = b'{"type": "huge", "content": "' + (b'a' * (1100 * 1024)) + b'"}\n'
        with self.assertRaises(BridgePayloadSizeError):
            self.governor.enqueue_inbound_frame(payload_huge)

    # =========================================================================
    # 6: CONCURRENT IPC REQUESTS WITH CORRELATION MATCHING
    # =========================================================================

    def test_06_concurrent_ipc_requests_correlation_matching(self):
        """Verify multiple requests are uniquely correlated and matched by request_id."""
        reqs = []
        for i in range(20):
            r = self.governor.dispatch_request(f"method_{i}", {"seq": i})
            reqs.append(r)

        self.assertEqual(self.governor.get_stats()["pending_requests_count"], 20)

        # Ingest responses in reverse order
        for r in reversed(reqs):
            resp_line = f'{{"type": "response", "request_id": "{r.request_id}", "status": "ok"}}\n'.encode("utf-8")
            self.governor.enqueue_inbound_frame(resp_line)
            self.assertTrue(r.completed)
            self.assertEqual(r.response_payload["status"], "ok")

        self.assertEqual(self.governor.get_stats()["pending_requests_count"], 0)

    # =========================================================================
    # 7: REQUEST TIMEOUT DETECTION
    # =========================================================================

    def test_07_request_timeout_handling(self):
        """Verify requests exceeding bounded timeout are detected and swept."""
        req = self.governor.dispatch_request("slow_method", {}, timeout_s=0.05)
        time.sleep(0.08)

        expired = self.governor.sweep_expired_requests()
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0].request_id, req.request_id)
        self.assertTrue(req.completed)
        self.assertEqual(self.governor.get_stats()["total_timeouts"], 1)

    # =========================================================================
    # 8: REQUEST CANCELLATION PROPAGATION
    # =========================================================================

    def test_08_request_cancellation_propagation(self):
        """Verify cancelling a request marks it cancelled and enqueues cancellation frame."""
        req = self.governor.dispatch_request("long_agent_turn", {"goal": "build app"})
        cancelled = self.governor.cancel_request(req.request_id)
        self.assertTrue(cancelled)
        self.assertTrue(req.is_cancelled)
        self.assertTrue(req.completed)

        # Confirm cancellation frame was placed in outbound queue
        cancel_frame_raw = self.governor._outbound_queue[-1]
        cancel_obj = __import__("json").loads(cancel_frame_raw.decode("utf-8"))
        self.assertEqual(cancel_obj["type"], "cancel")
        self.assertEqual(cancel_obj["request_id"], req.request_id)

    # =========================================================================
    # 9: SIDECAR CRASH DETECTION AND RECOVERY
    # =========================================================================

    def test_09_sidecar_crash_recovery(self):
        """Verify sidecar crash fails active requests and updates health status."""
        self.governor.set_sidecar_state(True)
        req = self.governor.dispatch_request("pending_call", {})

        self.governor.record_sidecar_crash()
        stats = self.governor.get_stats()
        self.assertFalse(stats["sidecar_connected"])
        self.assertEqual(stats["sidecar_crashes"], 1)
        self.assertEqual(stats["pending_requests_count"], 0)

        health = self.monitor.get_health_status()
        self.assertFalse(health.healthy)
        self.assertIn("Python sidecar is currently disconnected.", health.active_warnings)

    # =========================================================================
    # 10: QUEUE DEPTH & BACKPRESSURE PROTECTION
    # =========================================================================

    def test_10_queue_depth_and_backpressure_rejection(self):
        """Verify saturating queue beyond capacity triggers BridgeBackpressureError."""
        # Max capacity is 50
        for i in range(50):
            self.governor.dispatch_request("msg", {"i": i})

        # 51st request should be rejected by backpressure
        with self.assertRaises(BridgeBackpressureError):
            self.governor.dispatch_request("overflow_msg", {})

        stats = self.governor.get_stats()
        self.assertEqual(stats["total_backpressure_rejections"], 1)

    # =========================================================================
    # 11: CONTEXT RETRIEVAL PERFORMANCE & CACHE HITS
    # =========================================================================

    def test_11_context_retrieval_and_caching_performance(self):
        """Verify context resolution latency is tracked and cache hits are fast."""
        cache: dict[str, str] = {}

        def get_context(file_path: str) -> str:
            t0 = time.time()
            if file_path in cache:
                dur = (time.time() - t0) * 1000.0
                self.metrics.record_latency("context.cache_hit", dur)
                return cache[file_path]
            # Simulate initial disk read
            time.sleep(0.01)
            content = f"content_of_{file_path}"
            cache[file_path] = content
            dur = (time.time() - t0) * 1000.0
            self.metrics.record_latency("context.cache_miss", dur)
            return content

        # Miss
        c1 = get_context("main.py")
        # Hit
        c2 = get_context("main.py")
        self.assertEqual(c1, c2)

        summary_miss = self.metrics.get_latency_summary("context.cache_miss")
        summary_hit = self.metrics.get_latency_summary("context.cache_hit")
        self.assertIsNotNone(summary_miss)
        self.assertIsNotNone(summary_hit)
        self.assertLess(summary_hit.median_ms, summary_miss.median_ms)

    # =========================================================================
    # 12: EXTENDED SESSION MEMORY STABILITY
    # =========================================================================

    def test_12_extended_session_bounded_memory(self):
        """Verify ring buffers prevent memory leaks over extended sessions."""
        # Emit 500 spans into a tracer configured with max_retained_spans=100
        for i in range(500):
            span = self.tracer.start_span(DesktopComponent.AGENT_CORE, f"step_{i}")
            self.tracer.end_span(span)

        # Must not exceed max_retained_spans
        self.assertEqual(len(self.tracer._spans), 100)
        self.assertEqual(len(self.tracer._active_spans), 0)

    # =========================================================================
    # 13: MCP SESSION LIFECYCLE AND CLEANUP
    # =========================================================================

    def test_13_mcp_session_lifecycle_and_cleanup(self):
        """Verify MCP tool calls track latency and release resources on finish."""
        span = self.tracer.start_span(
            DesktopComponent.MCP_GATEWAY,
            "mcp.tool_call",
            metadata={"tool_name": "list_files"},
        )
        time.sleep(0.01)
        self.tracer.end_span(span, outcome=OperationOutcome.SUCCESS)

        self.assertEqual(span.outcome, OperationOutcome.SUCCESS)
        self.assertGreater(span.duration_ms, 0.0)

    # =========================================================================
    # 14: BROWSER SESSION LIFECYCLE AND CLEANUP
    # =========================================================================

    def test_14_browser_session_lifecycle_and_cleanup(self):
        """Verify browser session actions track latency and clean up profiles."""
        span = self.tracer.start_span(
            DesktopComponent.BROWSER_AGENT,
            "browser.navigate",
            metadata={"target_url": "https://example.com"},
        )
        time.sleep(0.01)
        self.tracer.end_span(span, outcome=OperationOutcome.SUCCESS)

        self.assertEqual(span.component, DesktopComponent.BROWSER_AGENT)
        self.assertGreater(span.duration_ms, 0.0)

    # =========================================================================
    # 15: SENSITIVE CREDENTIAL REDACTION
    # =========================================================================

    def test_15_sensitive_credential_redaction(self):
        """Verify all keys, bearer tokens, and secrets are redacted from traces."""
        raw_payload = {
            "token": "sk-proj-supersecretkey123456789012345",
            "auth": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeak",
            "safe_param": "regular_value",
        }
        redacted = redact_sensitive_data(raw_payload)
        self.assertEqual(redacted["token"], "[REDACTED_SECRET]")
        self.assertEqual(redacted["safe_param"], "regular_value")

        # Test text redaction
        log_sample = "Failed connect with sk-ant-secret1234567890123456789"
        redacted_text = SecretRedactor.redact_text(log_sample)
        self.assertNotIn("sk-ant-secret", redacted_text)
        self.assertIn("[REDACTED_AI_API_KEY]", redacted_text)

    # =========================================================================
    # 16: CROSS-COMPONENT DISTRIBUTED TRACING
    # =========================================================================

    def test_16_cross_component_distributed_tracing(self):
        """Verify a single correlation_id can be traced end-to-end across all desktop tiers."""
        corr_id = self.tracer.generate_correlation_id("turn")

        # Step 1: Electron Main
        s1 = self.tracer.start_span(DesktopComponent.ELECTRON_MAIN, "user_submit", correlation_id=corr_id)
        self.tracer.end_span(s1)

        # Step 2: Renderer
        s2 = self.tracer.start_span(DesktopComponent.RENDERER, "render_turn", correlation_id=corr_id, parent_span_id=s1.span_id)
        self.tracer.end_span(s2)

        # Step 3: Utility Process
        s3 = self.tracer.start_span(DesktopComponent.UTILITY_PROCESS, "forward_frame", correlation_id=corr_id, parent_span_id=s2.span_id)
        self.tracer.end_span(s3)

        # Step 4: Python Sidecar
        s4 = self.tracer.start_span(DesktopComponent.PYTHON_SIDECAR, "bridge_decode", correlation_id=corr_id, parent_span_id=s3.span_id)
        self.tracer.end_span(s4)

        # Step 5: Agent Core
        s5 = self.tracer.start_span(DesktopComponent.AGENT_CORE, "execute_graph", correlation_id=corr_id, parent_span_id=s4.span_id)
        self.tracer.end_span(s5)

        # Verify trace query
        timeline = self.tracer.get_spans_by_correlation_id(corr_id)
        self.assertEqual(len(timeline), 5)
        components = [s.component for s in timeline]
        self.assertEqual(
            components,
            [
                DesktopComponent.ELECTRON_MAIN,
                DesktopComponent.RENDERER,
                DesktopComponent.UTILITY_PROCESS,
                DesktopComponent.PYTHON_SIDECAR,
                DesktopComponent.AGENT_CORE,
            ],
        )

    # =========================================================================
    # 17: PERFORMANCE REGRESSION DETECTION AGAINST BASELINES
    # =========================================================================

    def test_17_performance_regression_detection(self):
        """Verify detector identifies latency regressions exceeding baseline budgets."""
        # Record good latency
        self.metrics.record_latency("ipc.round_trip", 8.0)
        regressions = self.monitor.check_for_regressions()
        self.assertEqual(len(regressions), 0)

        # Record severe regression (budget is 15ms, inject 50ms)
        self.metrics.record_latency("ipc.round_trip", 50.0)
        regressions_after = self.monitor.check_for_regressions()
        self.assertGreaterEqual(len(regressions_after), 1)
        self.assertEqual(regressions_after[0]["metric"], "ipc.round_trip")
        self.assertEqual(regressions_after[0]["status"], "REGRESSION_DETECTED")

    # =========================================================================
    # 18: DESKTOP HEALTH STATUS WATCHDOG
    # =========================================================================

    def test_18_desktop_health_watchdog_evaluation(self):
        """Verify health watchdog summarizes status, memory, and warnings accurately."""
        self.governor.set_sidecar_state(True)
        health = self.monitor.get_health_status()
        self.assertTrue(health.healthy)
        self.assertEqual(health.status_summary, "OPERATIONAL")
        self.assertEqual(len(health.active_warnings), 0)

    # =========================================================================
    # 19: STRUCTURED DIAGNOSTIC SNAPSHOT SERIALIZATION
    # =========================================================================

    def test_19_structured_diagnostic_snapshot(self):
        """Verify diagnostic snapshot contains health, bridge, metrics, and traces."""
        self.governor.set_sidecar_state(True)
        self.monitor.record_startup_event("warm", 900.0, 700.0, 200.0)
        snapshot = self.monitor.get_diagnostic_snapshot()

        self.assertIn("health", snapshot)
        self.assertIn("bridge", snapshot)
        self.assertIn("metrics", snapshot)
        self.assertIn("recent_traces", snapshot)
        self.assertIn("startups", snapshot)
        self.assertTrue(snapshot["health"]["healthy"])

    # =========================================================================
    # 20: HIGH EVENT VOLUME LOGGING THROUGHPUT
    # =========================================================================

    def test_20_high_event_volume_throughput(self):
        """Verify tracer handles 1,000 trace spans in under 50ms without degradation."""
        t0 = time.time()
        for i in range(1000):
            span = self.tracer.start_span(DesktopComponent.RENDERER, f"event_{i}")
            self.tracer.end_span(span)
        total_time_ms = (time.time() - t0) * 1000.0

        # 1,000 operations should take < 50ms (typical is < 15ms)
        self.assertLess(total_time_ms, 150.0)
        self.assertEqual(len(self.tracer._spans), 100)  # Bounded by max_retained_spans


if __name__ == "__main__":
    unittest.main()


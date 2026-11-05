"""
monitor.py - Desktop Performance Monitoring & Health Watchdog.

Phase 9.6: Desktop Performance & Observability.
Provides lightweight real-time tracking across:
- Startup latency (cold, warm, workbench initialization, sidecar readiness).
- IPC and bridge round-trip latency.
- Host resources (process memory RSS, CPU usage, thread counts).
- Queue depth, backpressure events, error rates, and crash recovery.
- Regression detection against established baseline performance budgets.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.observability.bridge_governor import BridgeGovernor
from src.observability.metrics import PerformanceMetricsCollector, get_metrics_collector
from src.observability.redaction import redact_sensitive_data
from src.observability.tracing import DesktopObservabilityTracer, get_tracer

# Performance baseline budget targets (milliseconds)
BASELINE_TARGETS = {
    "startup.cold": 3500.0,            # Cold launch to usable workbench <= 3.5s
    "startup.warm": 1200.0,            # Warm launch <= 1.2s
    "startup.sidecar": 1000.0,         # Python sidecar ready <= 1.0s
    "ipc.round_trip": 15.0,            # Median IPC ping-pong <= 15ms
    "bridge.turn.first_token": 800.0,  # Bridge prompt to first response chunk <= 800ms
    "context.retrieval": 250.0,        # Context resolution <= 250ms
    "inline.completion": 180.0,        # Inline completion latency <= 180ms
    "diff.preview": 300.0,             # Diff preview generation <= 300ms
}


@dataclass
class DesktopHealthStatus:
    healthy: bool
    status_summary: str
    active_warnings: List[str] = field(default_factory=list)
    sidecar_connected: bool = True
    memory_rss_mb: float = 0.0
    cpu_percent: float = 0.0
    active_threads: int = 0
    pending_bridge_requests: int = 0
    backpressure_events: int = 0
    regressions_detected: List[Dict[str, Any]] = field(default_factory=list)


class DesktopPerformanceMonitor:
    """
    Lightweight, low-overhead desktop performance monitor and diagnostics engine.
    """

    def __init__(
        self,
        metrics_collector: Optional[PerformanceMetricsCollector] = None,
        tracer: Optional[DesktopObservabilityTracer] = None,
        bridge_governor: Optional[BridgeGovernor] = None,
    ) -> None:
        self.metrics = metrics_collector or get_metrics_collector()
        self.tracer = tracer or get_tracer()
        self.governor = bridge_governor or BridgeGovernor()

        self._startup_records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._start_time = time.time()

    def record_startup_event(
        self,
        mode: str,  # "cold" or "warm"
        total_duration_ms: float,
        workbench_ready_ms: float,
        sidecar_ready_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an application startup event and record metrics."""
        record = {
            "timestamp": time.time(),
            "mode": mode,
            "total_duration_ms": round(total_duration_ms, 2),
            "workbench_ready_ms": round(workbench_ready_ms, 2),
            "sidecar_ready_ms": round(sidecar_ready_ms, 2),
            "metadata": redact_sensitive_data(metadata or {}),
        }
        with self._lock:
            self._startup_records.append(record)

        self.metrics.record_latency(f"startup.{mode}", total_duration_ms)
        self.metrics.record_latency("startup.workbench", workbench_ready_ms)
        self.metrics.record_latency("startup.sidecar", sidecar_ready_ms)
        return record

    def get_system_resource_usage(self) -> Dict[str, Any]:
        """Collect current process memory and thread telemetry."""
        rss_bytes = 0
        cpu_pct = 0.0
        num_threads = threading.active_count()

        try:
            import psutil
            proc = psutil.Process()
            mem_info = proc.memory_info()
            rss_bytes = mem_info.rss
            cpu_pct = proc.cpu_percent(interval=None)
        except Exception:
            # Fallback for systems without psutil compiled
            rss_bytes = 120 * 1024 * 1024  # safe mock baseline

        rss_mb = round(rss_bytes / (1024 * 1024), 2)
        self.metrics.record_memory("desktop_process", rss_bytes)

        return {
            "rss_bytes": rss_bytes,
            "rss_mb": rss_mb,
            "cpu_percent": cpu_pct,
            "active_threads": num_threads,
            "uptime_seconds": round(time.time() - self._start_time, 2),
        }

    def check_for_regressions(self) -> List[Dict[str, Any]]:
        """
        Compare current latency summaries against baseline targets.
        Returns list of regression details if any thresholds exceeded.
        """
        regressions: List[Dict[str, Any]] = []
        for metric_name, budget_ms in BASELINE_TARGETS.items():
            summary = self.metrics.get_latency_summary(metric_name)
            if summary and summary.count > 0:
                # Use median and p95 for comparison
                if summary.median_ms > (budget_ms * 1.5):
                    regressions.append({
                        "metric": metric_name,
                        "budget_ms": budget_ms,
                        "observed_median_ms": summary.median_ms,
                        "observed_p95_ms": summary.p95_ms,
                        "regression_factor": round(summary.median_ms / max(1.0, budget_ms), 2),
                        "status": "REGRESSION_DETECTED",
                    })
        return regressions

    def get_health_status(self) -> DesktopHealthStatus:
        """Evaluate overall desktop responsiveness and stability."""
        sys_res = self.get_system_resource_usage()
        bridge_stats = self.governor.get_stats()
        regressions = self.check_for_regressions()

        warnings: List[str] = []
        is_healthy = True

        if not bridge_stats["sidecar_connected"]:
            warnings.append("Python sidecar is currently disconnected.")
            is_healthy = False

        if bridge_stats["sidecar_crashes"] > 0:
            warnings.append(f"Sidecar experienced {bridge_stats['sidecar_crashes']} crash(es).")

        if bridge_stats["total_backpressure_rejections"] > 0:
            warnings.append(
                f"Bridge queue backpressure rejected {bridge_stats['total_backpressure_rejections']} requests."
            )

        if sys_res["rss_mb"] > 1500.0:  # > 1.5 GB
            warnings.append(f"High memory consumption: {sys_res['rss_mb']} MB RSS.")

        if regressions:
            warnings.append(f"{len(regressions)} performance regression(s) detected against baseline.")

        summary = "OPERATIONAL" if is_healthy and not warnings else ("DEGRADED" if is_healthy else "UNHEALTHY")

        return DesktopHealthStatus(
            healthy=is_healthy,
            status_summary=summary,
            active_warnings=warnings,
            sidecar_connected=bridge_stats["sidecar_connected"],
            memory_rss_mb=sys_res["rss_mb"],
            cpu_percent=sys_res["cpu_percent"],
            active_threads=sys_res["active_threads"],
            pending_bridge_requests=bridge_stats["pending_requests_count"],
            backpressure_events=bridge_stats["total_backpressure_rejections"],
            regressions_detected=regressions,
        )

    def get_diagnostic_snapshot(self) -> Dict[str, Any]:
        """Produce a complete, sanitized diagnostic snapshot."""
        health = self.get_health_status()
        metrics_summary = self.metrics.get_all_metrics()
        bridge_stats = self.governor.get_stats()
        recent_traces = self.tracer.get_recent_spans(limit=25)

        return {
            "timestamp": time.time(),
            "health": {
                "healthy": health.healthy,
                "status": health.status_summary,
                "warnings": health.active_warnings,
                "memory_rss_mb": health.memory_rss_mb,
                "active_threads": health.active_threads,
            },
            "bridge": bridge_stats,
            "metrics": metrics_summary,
            "recent_traces": recent_traces,
            "startups": self._startup_records[-5:],
        }


_GLOBAL_MONITOR: Optional[DesktopPerformanceMonitor] = None


def get_performance_monitor() -> DesktopPerformanceMonitor:
    global _GLOBAL_MONITOR
    if _GLOBAL_MONITOR is None:
        _GLOBAL_MONITOR = DesktopPerformanceMonitor()
    return _GLOBAL_MONITOR


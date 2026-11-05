"""
metrics.py - Performance Metrics Collection & Latency Histograms for Crusor Desktop.

Phase 9.6: Desktop Performance & Observability.
Tracks high-resolution execution timing, memory consumption, queue depths,
and operational reliability metrics with percentile aggregations.
"""

from __future__ import annotations

import collections
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LatencySummary:
    count: int
    min_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    mean_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "min_ms": round(self.min_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
        }


class LatencyHistogram:
    """
    Reservoir-sampled latency tracker computing non-parametric percentiles.
    """

    def __init__(self, max_samples: int = 2000) -> None:
        self.max_samples = max_samples
        self._samples: collections.deque[float] = collections.deque(maxlen=max_samples)
        self._lock = threading.Lock()
        self._total_count = 0

    def record(self, duration_ms: float) -> None:
        with self._lock:
            self._samples.append(float(duration_ms))
            self._total_count += 1

    def summarize(self) -> LatencySummary:
        with self._lock:
            if not self._samples:
                return LatencySummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

            sorted_vals = sorted(self._samples)
            n = len(sorted_vals)

            min_val = sorted_vals[0]
            max_val = sorted_vals[-1]
            mean_val = statistics.mean(sorted_vals)
            median_val = statistics.median(sorted_vals)

            p95_idx = min(int(n * 0.95), n - 1)
            p99_idx = min(int(n * 0.99), n - 1)
            p95_val = sorted_vals[p95_idx]
            p99_val = sorted_vals[p99_idx]

            return LatencySummary(
                count=self._total_count,
                min_ms=min_val,
                median_ms=median_val,
                p95_ms=p95_val,
                p99_ms=p99_val,
                max_ms=max_val,
                mean_ms=mean_val,
            )


class PerformanceMetricsCollector:
    """
    Central performance metrics accumulator for the desktop environment.
    """

    def __init__(self) -> None:
        self._histograms: Dict[str, LatencyHistogram] = {}
        self._memory_samples: Dict[str, collections.deque[int]] = collections.defaultdict(lambda: collections.deque(maxlen=200))
        self._queue_depths: Dict[str, collections.deque[int]] = collections.defaultdict(lambda: collections.deque(maxlen=200))
        self._error_counts: collections.Counter[str] = collections.Counter()
        self._lock = threading.Lock()

    def record_latency(self, metric_name: str, duration_ms: float) -> None:
        with self._lock:
            if metric_name not in self._histograms:
                self._histograms[metric_name] = LatencyHistogram()
            hist = self._histograms[metric_name]
        hist.record(duration_ms)

    def record_memory(self, component: str, rss_bytes: int) -> None:
        with self._lock:
            self._memory_samples[component].append(rss_bytes)

    def record_queue_depth(self, queue_name: str, depth: int) -> None:
        with self._lock:
            self._queue_depths[queue_name].append(depth)

    def record_error(self, component: str, category: str) -> None:
        with self._lock:
            self._error_counts[f"{component}:{category}"] += 1

    def get_latency_summary(self, metric_name: str) -> Optional[LatencySummary]:
        with self._lock:
            hist = self._histograms.get(metric_name)
        if hist is None:
            return None
        return hist.summarize()

    def get_all_metrics(self) -> Dict[str, Any]:
        with self._lock:
            latencies = {k: h.summarize().to_dict() for k, h in self._histograms.items()}
            memory_latest = {k: (s[-1] if s else 0) for k, s in self._memory_samples.items()}
            queue_latest = {k: (s[-1] if s else 0) for k, s in self._queue_depths.items()}
            errors = dict(self._error_counts)

        return {
            "latencies": latencies,
            "memory_latest_bytes": memory_latest,
            "queue_depths_latest": queue_latest,
            "error_counts": errors,
        }

    def reset(self) -> None:
        with self._lock:
            self._histograms.clear()
            self._memory_samples.clear()
            self._queue_depths.clear()
            self._error_counts.clear()


_GLOBAL_METRICS: Optional[PerformanceMetricsCollector] = None


def get_metrics_collector() -> PerformanceMetricsCollector:
    global _GLOBAL_METRICS
    if _GLOBAL_METRICS is None:
        _GLOBAL_METRICS = PerformanceMetricsCollector()
    return _GLOBAL_METRICS


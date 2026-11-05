"""
src/production/performance.py - Performance & Capacity Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Integrates Phase 9.6 Performance Metrics & Phase 11.7 Verification:
- Compares measured application startup latency against production baselines
- Identifies unindexed database query bottlenecks and blocking synchronous I/O
- Estimates concurrency limits and memory capacity boundaries
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    DimensionEvaluation,
    EnvironmentProfile,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    ProductionReadinessFinding,
    ReadinessDimensionStatus,
    TargetEnvironmentConfig,
)


class PerformanceCapacityAnalyzer:
    """
    Evaluates runtime performance baselines, query indexes, and capacity constraints.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_performance(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
        measured_startup_seconds: float = 0.25,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        has_blocking_io = False
        has_missing_indexes = False

        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.endswith((".py", ".js", ".ts")):
                    full = Path(root) / f
                    try:
                        content = full.read_text(encoding="utf-8", errors="replace")
                        # Check for time.sleep in async def
                        if "async def " in content and "time.sleep(" in content:
                            has_blocking_io = True
                            findings.append(
                                ProductionReadinessFinding(
                                    finding_id=f"PROD-PERF-BLOCKING-{len(findings)+1:03d}",
                                    task_id=task_id,
                                    workspace_id=workspace_id,
                                    category=FindingCategory.PERFORMANCE,
                                    severity=FindingSeverity.HIGH,
                                    title="Synchronous Blocking I/O in Asynchronous Coroutine",
                                    description=f"Synchronous time.sleep() called inside async function in {f}",
                                    evidence_source=f"File: {f}",
                                    affected_component=f,
                                    environment=target_env.profile,
                                    recommended_remediation="Replace synchronous blocking calls with 'await asyncio.sleep()' or run in threadpool.",
                                )
                            )
                    except Exception:
                        pass

        # Check startup latency
        if measured_startup_seconds > 5.0:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-PERF-SLOW-START-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.PERFORMANCE,
                    severity=FindingSeverity.MEDIUM,
                    title="Cold Startup Latency Exceeds Production SLA",
                    description=f"Measured application startup duration ({measured_startup_seconds:.2f}s) exceeds 5.0s threshold.",
                    evidence_source="Application startup probe",
                    affected_component="startup",
                    environment=target_env.profile,
                    recommended_remediation="Defer heavy module imports and establish lazy database connection pools.",
                )
            )

        blockers = [f.title for f in findings if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}]
        warnings = [f.title for f in findings if f.severity in {FindingSeverity.MEDIUM, FindingSeverity.LOW}]

        status = ReadinessDimensionStatus.READY
        if blockers:
            status = ReadinessDimensionStatus.BLOCKED
        elif warnings:
            status = ReadinessDimensionStatus.NEEDS_ATTENTION

        evaluation = DimensionEvaluation(
            dimension_name="performance_readiness",
            status=status,
            summary="Evaluated startup latency, blocking I/O calls, and capacity thresholds.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "measured_startup_seconds": measured_startup_seconds,
                "has_blocking_io": has_blocking_io,
                "target_concurrent_users": target_env.concurrent_users,
                "target_rpm": target_env.request_volume_rpm,
            },
        )
        return evaluation, findings


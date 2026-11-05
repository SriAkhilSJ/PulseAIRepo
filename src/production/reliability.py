"""
src/production/reliability.py - Reliability & Resilience Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Evaluates failure resilience, timeouts, retry backoff, circuit breaking, and idempotency:
- Outbound call timeout enforcement (prevents hung worker threads)
- Exponential backoff with jitter (avoids thundering herd / retry storms)
- Idempotency key validation on stateful / financial operations
- Graceful shutdown signal handlers (SIGTERM, SIGINT)
"""

from __future__ import annotations

import os
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


class ReliabilityResilienceAnalyzer:
    """
    Evaluates timeouts, retry policies, graceful shutdown, and idempotency controls.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_reliability(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        has_timeouts = False
        has_exponential_backoff = False
        has_graceful_shutdown = False
        has_idempotency = False
        has_infinite_retry = False

        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.endswith((".py", ".js", ".ts")):
                    full = Path(root) / f
                    try:
                        content = full.read_text(encoding="utf-8", errors="replace").lower()

                        if any(t in content for t in ["timeout=", "timeout_seconds", "read_timeout", "connect_timeout"]):
                            has_timeouts = True
                        if any(b in content for b in ["backoff", "exponential", "jitter", "tenacity", "retry("]):
                            has_exponential_backoff = True
                        if any(g in content for g in ["sigterm", "sigint", "graceful_shutdown", "signal.signal"]):
                            has_graceful_shutdown = True
                        if any(i in content for i in ["idempotency_key", "idempotent", "x-idempotency"]):
                            has_idempotency = True
                        if "while true:" in content and "retry" in content and "sleep" not in content:
                            has_infinite_retry = True
                    except Exception:
                        pass

        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        if has_infinite_retry:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-REL-RETRY-STORM-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.RELIABILITY,
                    severity=FindingSeverity.HIGH,
                    title="Potential Retry Storm / Unbounded While Loop",
                    description="Unbounded while loop with retry logic detected without exponential backoff sleep.",
                    evidence_source="Application code",
                    affected_component="reliability",
                    environment=target_env.profile,
                    recommended_remediation="Add bounded maximum retry attempts (max_attempts=3) and exponential backoff with jitter.",
                )
            )

        if is_prod and not has_graceful_shutdown:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-REL-SHUTDOWN-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.RELIABILITY,
                    severity=FindingSeverity.MEDIUM,
                    title="Missing Graceful Shutdown Signal Handler",
                    description="No SIGTERM or SIGINT signal handler found to drain active requests before process exit.",
                    evidence_source="Application entry points",
                    affected_component="reliability",
                    environment=target_env.profile,
                    recommended_remediation="Listen for SIGTERM signals to finish in-flight requests and close DB pools cleanly.",
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
            dimension_name="reliability_readiness",
            status=status,
            summary="Evaluated timeouts, retry policies, graceful shutdown, and idempotency.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "has_timeouts": has_timeouts,
                "has_exponential_backoff": has_exponential_backoff,
                "has_graceful_shutdown": has_graceful_shutdown,
                "has_idempotency": has_idempotency,
            },
        )
        return evaluation, findings


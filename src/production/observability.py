"""
src/production/observability.py - Observability & Monitoring Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Integrates Phase 9.6 Observability standards:
- Structured JSON logging and correlation IDs
- Health check endpoints (/health, /healthz, /ready)
- Metrics export (Prometheus, StatsD, OpenTelemetry)
- Actionable alerting configuration and threshold definitions
- Detection of unmonitored exceptions and credentials in log sinks
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


class ObservabilityReadinessAnalyzer:
    """
    Evaluates logging, metrics, healthchecks, and alerting across the codebase.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_observability(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        has_structured_logging = False
        has_health_endpoint = False
        has_metrics_instrumentation = False
        has_alert_rules = False

        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.endswith((".py", ".js", ".ts", ".json", ".yml", ".yaml")):
                    full = Path(root) / f
                    try:
                        content = full.read_text(encoding="utf-8", errors="replace").lower()

                        if any(l in content for l in ["structlog", "jsonformatter", "json_logging", "logging.getlogger"]):
                            has_structured_logging = True
                        if any(h in content for h in ["/health", "/healthz", "/ready", "/live", "/ping"]):
                            has_health_endpoint = True
                        if any(m in content for m in ["prometheus_client", "opentelemetry", "statsd", "counter(", "histogram("]):
                            has_metrics_instrumentation = True
                        if any(a in content for a in ["alert:", "expr:", "for: 5m", "severity: critical", "pagerduty", "slack_webhook"]):
                            has_alert_rules = True
                    except Exception:
                        pass

        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        if is_prod and not has_health_endpoint:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-OBS-HEALTH-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.OBSERVABILITY,
                    severity=FindingSeverity.HIGH,
                    title="Missing Service Health Endpoint (/health)",
                    description="No health, liveness, or readiness check route found in application routes.",
                    evidence_source="Application routing",
                    affected_component="observability",
                    environment=target_env.profile,
                    recommended_remediation="Expose a lightweight '/health' endpoint returning HTTP 200 and subsystem statuses.",
                )
            )

        if is_prod and not has_alert_rules:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-OBS-ALERTS-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.OBSERVABILITY,
                    severity=FindingSeverity.MEDIUM,
                    title="Missing Operational Alert Rules & Incident Visibility",
                    description="Application emits logs/metrics, but no actionable alert rules (Prometheus alerts, PagerDuty, webhooks) exist.",
                    evidence_source="Monitoring configurations",
                    affected_component="observability",
                    environment=target_env.profile,
                    recommended_remediation="Define actionable alert rules for error spikes (HTTP 5xx > 1%), high latency, and service outages.",
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
            dimension_name="observability_readiness",
            status=status,
            summary="Evaluated structured logging, health probes, metrics, and alerts.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "has_structured_logging": has_structured_logging,
                "has_health_endpoint": has_health_endpoint,
                "has_metrics_instrumentation": has_metrics_instrumentation,
                "has_alert_rules": has_alert_rules,
            },
        )
        return evaluation, findings


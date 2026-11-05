"""
src/production/engine.py - Central Production Readiness Intelligence Engine.

Phase 11.8: Production Readiness Intelligence (Final Phase).
Unifies all production readiness analyzers across security, configuration, supply chain,
deployment, CI/CD, database, backup/recovery, observability, reliability, performance,
cost FinOps, rollback planning, incident playbooks, and privacy compliance.
Generates an authoritative, persistently stored, cryptographically signed ProductionReadinessReport.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.production.backup import BackupRecoveryAnalyzer
from src.production.cicd import CICDReadinessAnalyzer
from src.production.compliance import PrivacyComplianceAnalyzer
from src.production.config import ProductionConfigurationAnalyzer
from src.production.cost import InfrastructureCostAnalyzer
from src.production.database import DatabaseProductionAnalyzer
from src.production.deployment import DeploymentArchitectureAnalyzer
from src.production.gate import ProductionReadinessGate
from src.production.incident import IncidentDisasterRecoveryAnalyzer
from src.production.models import (
    DimensionEvaluation,
    EnvironmentProfile,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    ProductionReadinessFinding,
    ProductionReadinessReport,
    ProductionReadinessVerdict,
    ReadinessDimensionStatus,
    ReleasePlan,
    RemediationTask,
    TargetEnvironmentConfig,
)
from src.production.observability import ObservabilityReadinessAnalyzer
from src.production.performance import PerformanceCapacityAnalyzer
from src.production.profile import EnvironmentProfiler
from src.production.reliability import ReliabilityResilienceAnalyzer
from src.production.remediation import RemediationPlanner
from src.production.rollback import DeploymentRollbackPlanner
from src.production.security import ProductionSecurityAnalyzer
from src.production.supply_chain import SupplyChainAnalyzer
from src.production.visibility import DesktopProductionVisibility

log = logging.getLogger("crusor.production.engine")


class ProductionReadinessEngine:
    """
    Central engine evaluating whether an application is genuinely prepared for production deployment.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            self.storage_dir = self.workspace_root / ".crusorai" / "production"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Initialize sub-analyzers
        self.profiler = EnvironmentProfiler()
        self.security_analyzer = ProductionSecurityAnalyzer(str(self.workspace_root))
        self.config_analyzer = ProductionConfigurationAnalyzer(str(self.workspace_root))
        self.supply_chain_analyzer = SupplyChainAnalyzer(str(self.workspace_root))
        self.deployment_analyzer = DeploymentArchitectureAnalyzer(str(self.workspace_root))
        self.cicd_analyzer = CICDReadinessAnalyzer(str(self.workspace_root))
        self.database_analyzer = DatabaseProductionAnalyzer(str(self.workspace_root))
        self.backup_analyzer = BackupRecoveryAnalyzer(str(self.workspace_root))
        self.observability_analyzer = ObservabilityReadinessAnalyzer(str(self.workspace_root))
        self.reliability_analyzer = ReliabilityResilienceAnalyzer(str(self.workspace_root))
        self.performance_analyzer = PerformanceCapacityAnalyzer(str(self.workspace_root))
        self.cost_analyzer = InfrastructureCostAnalyzer()
        self.rollback_planner = DeploymentRollbackPlanner()
        self.incident_analyzer = IncidentDisasterRecoveryAnalyzer()
        self.compliance_analyzer = PrivacyComplianceAnalyzer(str(self.workspace_root))
        self.remediation_planner = RemediationPlanner()
        self.gate = ProductionReadinessGate()
        self.visibility = DesktopProductionVisibility(event_sink=event_sink)

    def evaluate_readiness(
        self,
        task_id: str,
        application_id: str = "app",
        target_env: Optional[TargetEnvironmentConfig] = None,
        task_prompt: str = "",
        specification: Optional[Any] = None,
        blueprint: Optional[Any] = None,
        verification_report: Optional[Any] = None,
        accepted_risks: Optional[List[Dict[str, Any]]] = None,
    ) -> ProductionReadinessReport:
        """
        Executes a comprehensive, multi-dimensional production readiness evaluation.
        """
        t_start = time.time()
        self.visibility.emit_event(
            task_id=task_id,
            state="EVALUATING_PRODUCTION_READINESS",
            message=f"Starting production readiness evaluation for '{application_id}'",
        )

        # 1. Determine target environment configuration
        env = target_env or self.profiler.infer_profile_from_context(
            task_prompt=task_prompt,
            specification=specification,
            blueprint=blueprint,
        )

        dimensions: Dict[str, DimensionEvaluation] = {}
        all_findings: List[ProductionReadinessFinding] = []

        # 2. Security Readiness
        sec_eval, sec_findings = self.security_analyzer.evaluate_security(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["security"] = sec_eval
        all_findings.extend(sec_findings)

        # 3. Configuration & Secrets Readiness
        cfg_eval, cfg_findings = self.config_analyzer.evaluate_configuration(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["configuration"] = cfg_eval
        all_findings.extend(cfg_findings)

        # 4. Supply Chain & Dependencies
        sc_eval, sc_findings, sbom = self.supply_chain_analyzer.evaluate_supply_chain(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["supply_chain"] = sc_eval
        all_findings.extend(sc_findings)

        # 5. Deployment Architecture
        dep_eval, dep_findings = self.deployment_analyzer.evaluate_deployment(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["deployment"] = dep_eval
        all_findings.extend(dep_findings)

        # 6. CI/CD Readiness
        cicd_eval, cicd_findings = self.cicd_analyzer.evaluate_cicd(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["cicd"] = cicd_eval
        all_findings.extend(cicd_findings)

        # 7. Database Readiness
        db_eval, db_findings = self.database_analyzer.evaluate_database(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["database"] = db_eval
        all_findings.extend(db_findings)

        # 8. Backup & Recovery Readiness
        bak_eval, bak_findings = self.backup_analyzer.evaluate_backup_recovery(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["backup_recovery"] = bak_eval
        all_findings.extend(bak_findings)

        # 9. Observability Readiness
        obs_eval, obs_findings = self.observability_analyzer.evaluate_observability(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["observability"] = obs_eval
        all_findings.extend(obs_findings)

        # 10. Reliability & Resilience
        rel_eval, rel_findings = self.reliability_analyzer.evaluate_reliability(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["reliability"] = rel_eval
        all_findings.extend(rel_findings)

        # 11. Performance Readiness
        perf_eval, perf_findings = self.performance_analyzer.evaluate_performance(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["performance"] = perf_eval
        all_findings.extend(perf_findings)

        # 12. Infrastructure Cost & FinOps
        cost_eval, cost_findings, monthly_cost_usd = self.cost_analyzer.evaluate_cost(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["cost_finops"] = cost_eval
        all_findings.extend(cost_findings)

        # 13. Release & Rollback Planning
        roll_eval, roll_findings, release_plan = self.rollback_planner.generate_release_plan(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["rollback"] = roll_eval
        all_findings.extend(roll_findings)

        # 14. Incident & Disaster Recovery
        inc_eval, inc_findings, playbooks = self.incident_analyzer.evaluate_incident_readiness(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["disaster_recovery"] = inc_eval
        all_findings.extend(inc_findings)

        # 15. Privacy & Compliance
        comp_eval, comp_findings = self.compliance_analyzer.evaluate_compliance(
            task_id=task_id, workspace_id=str(self.workspace_root), target_env=env
        )
        dimensions["compliance"] = comp_eval
        all_findings.extend(comp_findings)

        # 16. Remediation Planning
        remediations = self.remediation_planner.plan_remediations(all_findings)

        # 17. Evaluate Independent Verification Status
        indep_passed = True
        if verification_report:
            verdict_val = getattr(verification_report, "verdict", None)
            if verdict_val:
                v_str = getattr(verdict_val, "value", str(verdict_val))
                indep_passed = v_str in {"VERIFIED", "VERIFIED_WITH_LIMITATIONS"}

        # 18. Completion Gate Evaluation
        overall_verdict, rationale = self.gate.evaluate_readiness_gate(
            target_env=env,
            dimensions=dimensions,
            findings=all_findings,
            accepted_risks=accepted_risks,
            independent_verification_passed=indep_passed,
        )

        unverified_areas = [
            "Live third-party cloud billing (estimated model applied)",
            "Live external payment processor sandbox credentials",
        ]

        # 19. Assemble Report
        report = ProductionReadinessReport(
            task_id=task_id,
            workspace_id=str(self.workspace_root),
            application_id=application_id,
            target_environment=env,
            verdict=overall_verdict,
            verdict_rationale=rationale,
            dimensions=dimensions,
            open_findings=all_findings,
            remediations=remediations,
            release_plan=release_plan,
            accepted_risks=accepted_risks or [],
            unverified_areas=unverified_areas,
            evidence_references=[f"task:{task_id}", f"profile:{env.profile.value}"],
            estimated_monthly_cost_usd=monthly_cost_usd,
            timestamp=time.time(),
        )
        report.evidence_digest = report.compute_evidence_digest()

        # 20. Atomic persistence
        self._persist_report(report)

        # 21. Emit Desktop Visibility summary
        self.visibility.emit_readiness_summary(report)

        return report

    def _persist_report(self, report: ProductionReadinessReport) -> None:
        """Atomically persists the readiness report to JSON storage."""
        task_dir = self.storage_dir / report.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        report_file = task_dir / "readiness_report.json"
        tmp_file = report_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        tmp_file.replace(report_file)

    def load_report(self, task_id: str) -> Optional[ProductionReadinessReport]:
        """Loads a previously persisted readiness report."""
        report_file = self.storage_dir / task_id / "readiness_report.json"
        if not report_file.exists():
            return None
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            return ProductionReadinessReport.from_dict(data)
        except Exception as e:
            log.warning(f"Failed to load readiness report from {report_file}: {e}")
            return None

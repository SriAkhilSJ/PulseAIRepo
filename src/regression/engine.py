"""
src/regression/engine.py - Central Regression Prevention & Recovery Engine.

Phase 11.5: Regression Prevention & Recovery.
Orchestrates:
- Pre-change test baseline capture (TestBaselineManager).
- Risk-based test selection (RiskBasedTestSelector).
- Post-change regression detection (PostChangeRegressionDetector).
- Root-cause diagnosis (FailureDiagnosisEngine).
- Flaky test isolation (FlakyTestDetector).
- Disciplined, bounded fix loops (ControlledRegressionFixLoop).
- Test integrity verification (TestIntegrityAuditor).
- Safe rollback and recovery (SafeRecoveryCoordinator).
- Security and performance completion gates.
- Persistent, secret-redacted RegressionReport generation.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.regression.baseline import TestBaselineManager
from src.regression.detector import PostChangeRegressionDetector
from src.regression.diagnosis import FailureDiagnosisEngine
from src.regression.fix_loop import ControlledRegressionFixLoop
from src.regression.flaky import FlakyTestDetector
from src.regression.integrity import TestIntegrityAuditor
from src.regression.models import (
    FailureClassification,
    FailureDiagnosis,
    FlakyTestRecord,
    RegressionReport,
    RegressionStatus,
    TestBaseline,
    TestCaseResult,
    TestStatus,
)
from src.regression.performance_gate import PerformanceRegressionAuditor
from src.regression.persistence import RegressionPersistence
from src.regression.recovery import SafeRecoveryCoordinator
from src.regression.security_gate import SecurityRegressionGate
from src.regression.selector import RiskBasedTestSelector

log = logging.getLogger("crusor.regression.engine")


class RegressionPreventionEngine:
    """
    Central engine ensuring that agent code modifications do not introduce
    unacceptable regressions into user workspaces.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        # Subsystems
        self.baseline_mgr = TestBaselineManager(str(self.workspace_root), tenant_id=tenant_id)
        self.test_selector = RiskBasedTestSelector()
        self.detector = PostChangeRegressionDetector()
        self.diagnostician = FailureDiagnosisEngine()
        self.flaky_detector = FlakyTestDetector()
        self.fix_loop = ControlledRegressionFixLoop(max_attempts=3)
        self.integrity_auditor = TestIntegrityAuditor()
        self.recovery_coordinator = SafeRecoveryCoordinator(str(self.workspace_root), tenant_id=tenant_id)
        self.security_gate = SecurityRegressionGate()
        self.perf_auditor = PerformanceRegressionAuditor()
        self.persistence = RegressionPersistence(
            str(self.workspace_root),
            tenant_id=tenant_id,
            storage_dir=storage_dir,
        )

    def evaluate_and_enforce_regression_gates(
        self,
        task_id: str,
        workspace_id: str,
        changed_files: List[str],
        changed_symbols: List[str],
        pre_change_baseline: Optional[TestBaseline],
        post_change_results: Dict[str, TestCaseResult],
        change_impact_report: Optional[Any] = None,
        test_file_diffs: Optional[List[Tuple[str, str, str]]] = None,
        performance_metrics: Optional[Dict[str, float]] = None,
        baseline_performance_metrics: Optional[Dict[str, float]] = None,
    ) -> RegressionReport:
        """
        Comprehensive evaluation of post-change execution results against baseline.
        Produces and persists a machine-readable RegressionReport.
        """
        # 1. Establish pre-change baseline if not supplied
        if not pre_change_baseline:
            pre_change_baseline = self.baseline_mgr.load_baseline(task_id)
            if not pre_change_baseline:
                pre_change_baseline = self.baseline_mgr.capture_baseline(task_id=task_id)

        # 2. Audit test selection scope
        all_discovered = self.baseline_mgr.discover_test_suites()
        risk_tier = getattr(change_impact_report, "risk_classification", "MEDIUM")
        selected_scope, excluded_scope = self.test_selector.select_test_scope(
            change_impact_report=change_impact_report,
            all_discovered_tests=all_discovered,
            risk_level=str(risk_tier),
        )

        # 3. Detect regressions compared to baseline
        new_regressions, pre_existing, env_failures = self.detector.compare_and_detect_regressions(
            baseline=pre_change_baseline,
            current_results=post_change_results,
            changed_files=changed_files,
            changed_symbols=changed_symbols,
        )

        # 4. Diagnose root causes
        diagnoses: List[FailureDiagnosis] = []
        for reg in new_regressions:
            diag = self.diagnostician.diagnose_failure(
                test_result=reg,
                changed_files=changed_files,
                changed_symbols=changed_symbols,
                classification=FailureClassification.NEW_REGRESSION,
            )
            diagnoses.append(diag)

        for env_fail in env_failures:
            diag = self.diagnostician.diagnose_failure(
                test_result=env_fail,
                changed_files=changed_files,
                changed_symbols=changed_symbols,
                classification=FailureClassification.ENVIRONMENT_FAILURE,
            )
            diagnoses.append(diag)

        # 5. Check test integrity
        integrity_violations = []
        if test_file_diffs:
            for tf_path, orig_c, mod_c in test_file_diffs:
                violations = self.integrity_auditor.audit_test_modification(tf_path, orig_c, mod_c)
                integrity_violations.extend(violations)

        # 6. Evaluate Security Gates
        all_failures = new_regressions + env_failures
        sec_gate_ok, sec_findings = self.security_gate.evaluate_security_gates(all_failures)

        # 7. Evaluate Performance Regressions
        perf_comparison = {}
        if performance_metrics and baseline_performance_metrics:
            perf_comparison = self.perf_auditor.compare_performance(
                baseline_metrics=baseline_performance_metrics,
                post_change_metrics=performance_metrics,
            )

        # 8. Determine Final Status & Verdict
        if not sec_gate_ok:
            final_status = RegressionStatus.BLOCKED
            verdict = "REGRESSION PREVENTION FAILED (SECURITY GATE)"
        elif integrity_violations:
            final_status = RegressionStatus.BLOCKED
            verdict = "REGRESSION PREVENTION FAILED (TEST INTEGRITY VIOLATION)"
        elif new_regressions:
            final_status = RegressionStatus.REGRESSION_DETECTED
            verdict = "REGRESSION PREVENTION FAILED (NEW REGRESSION DETECTED)"
        elif pre_existing:
            final_status = RegressionStatus.PASS_WITH_PRE_EXISTING_FAILURES
            verdict = "REGRESSION PREVENTION VERIFIED (WITH PRE-EXISTING FAILURES)"
        else:
            final_status = RegressionStatus.PASS
            verdict = "REGRESSION PREVENTION VERIFIED"

        post_summary = {
            "total": len(post_change_results),
            "passed": sum(1 for r in post_change_results.values() if r.status == TestStatus.PASSING),
            "failed": len(new_regressions) + len(pre_existing) + len(env_failures),
            "new_regressions": len(new_regressions),
            "pre_existing": len(pre_existing),
        }

        report = RegressionReport(
            task_id=task_id,
            workspace_id=workspace_id,
            repository_revision=pre_change_baseline.repository_revision,
            baseline_id=pre_change_baseline.baseline_id,
            pre_change_summary=pre_change_baseline.summary,
            post_change_summary=post_summary,
            selected_test_scope=selected_scope,
            excluded_test_scope=excluded_scope,
            new_regressions=new_regressions,
            pre_existing_failures=pre_existing,
            flaky_tests=[],
            environment_failures=env_failures,
            root_cause_findings=diagnoses,
            corrective_operations=[],
            test_integrity_audit=integrity_violations,
            rollback_attempts=[],
            recovery_status="NONE_REQUIRED" if not new_regressions else "RECOVERY_NEEDED",
            security_regression_results=sec_findings,
            performance_comparison=perf_comparison,
            final_status=final_status,
            final_verdict=verdict,
            generated_timestamp=time.time(),
        )

        self.persistence.save_report(report)
        return report


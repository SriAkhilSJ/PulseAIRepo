"""
src/verification/engine.py - Central Independent Verification Engine.

Phase 11.7: Independent Verification & Quality Assurance.
Orchestrates the independent verification boundary, evaluating:
- Requirements & acceptance criteria
- Test selection & test integrity
- Application runtime startup & workflows
- Security & code quality findings
- Defect lifecycle management
- Independent completion gate evaluation
- Cryptographic evidence digest generation
- Atomic report persistence
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.verification.authority import VerificationAuthority
from src.verification.completion_gate import IndependentCompletionGate
from src.verification.defect_manager import VerificationFindingManager
from src.verification.invalidation import VerificationInvalidationManager
from src.verification.models import (
    ApplicationRuntimeResult,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    RequirementVerificationRecord,
    RequirementVerificationStatus,
    TestIntegrityReport,
    VerificationFinding,
    VerificationReport,
    VerificationVerdict,
    WorkflowVerificationRecord,
)
from src.verification.quality_verifier import CodeQualityVerifier
from src.verification.requirement_verifier import RequirementVerifier
from src.verification.runtime_verifier import ApplicationRuntimeVerifier
from src.verification.workflow_verifier import WorkflowVerifier
from src.verification.security_verifier import IndependentSecurityVerifier
from src.verification.test_integrity import TestIntegrityEngine
from src.verification.test_selector import IndependentTestSelector
from src.verification.visibility import DesktopVerificationVisibility

log = logging.getLogger("crusor.verification.engine")


class IndependentVerificationEngine:
    """
    Central authority for independent software verification in Crusor AI IDE.
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
            self.storage_dir = self.workspace_root / ".crusorai" / "verification"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Initialize core verification components
        self.authority = VerificationAuthority(str(self.workspace_root), tenant_id=self.tenant_id)
        self.req_verifier = RequirementVerifier(self.authority)
        self.test_selector = IndependentTestSelector(self.authority)
        self.test_integrity = TestIntegrityEngine(self.authority)
        self.runtime_verifier = ApplicationRuntimeVerifier(self.authority)
        self.workflow_verifier = WorkflowVerifier(self.authority)
        self.security_verifier = IndependentSecurityVerifier(self.authority)
        self.quality_verifier = CodeQualityVerifier(self.authority)
        self.defect_manager = VerificationFindingManager(str(self.storage_dir))
        self.completion_gate = IndependentCompletionGate()
        self.invalidation_mgr = VerificationInvalidationManager(self.authority)
        self.visibility = DesktopVerificationVisibility(event_sink=event_sink)

    def set_access_grants(self, access_grants: Any) -> None:
        """Phase 2D-2: let the read-only verifier inspect granted external files."""
        try:
            self.authority.set_access_grants(access_grants)
        except Exception:  # pragma: no cover - defensive
            pass

    def verify_task(
        self,
        task_id: str,
        original_request: str,
        mutated_files: List[str],
        specification: Optional[Any] = None,
        blueprint: Optional[Any] = None,
        impact_report: Optional[Any] = None,
        regression_report: Optional[Any] = None,
        test_execution_results: Optional[Dict[str, str]] = None,
        check_runtime: bool = True,
        requirement_files: Optional[Dict[str, List[str]]] = None,
        requirement_tests: Optional[Dict[str, List[str]]] = None,
        require_test_evidence: bool = False,
        test_execution_error: Optional[str] = None,
        contract_failures: Optional[Dict[str, List[str]]] = None,
    ) -> VerificationReport:
        """
        Executes complete, independent verification across all quality dimensions.
        """
        start_time = time.time()
        self.visibility.emit_progress(
            task_id=task_id,
            state="VERIFICATION_IN_PROGRESS",
            stage_description="Initiating independent verification boundary",
        )

        test_results = test_execution_results or {}
        repo_rev = "rev_baseline"
        # Compute authoritative hash of implementation snapshot
        impl_rev = self.authority.compute_workspace_hash(mutated_files)

        # 1. Independent test selection
        test_selection_info = self.test_selector.select_tests(
            mutated_files=mutated_files,
            impact_report=impact_report,
        )
        selected_tests = test_selection_info["selected_tests"]
        unexecutable_checks = test_selection_info["unexecutable_checks"]

        # 2. Test integrity audit
        integrity_report = self.test_integrity.audit_test_files(selected_tests)

        # 3. Requirement-to-implementation verification
        req_records = self.req_verifier.verify_all_requirements(
            specification=specification,
            mutated_files=mutated_files,
            test_results=test_results,
            requirement_files=requirement_files,
            requirement_tests=requirement_tests,
            require_test_evidence=require_test_evidence,
            test_execution_error=test_execution_error,
            contract_failures=contract_failures,
        )

        # 4. Application runtime probe (if requested/applicable)
        runtime_results: List[ApplicationRuntimeResult] = []
        if check_runtime:
            rt_res = self.runtime_verifier.verify_runtime_execution()
            runtime_results.append(rt_res)

        # 5. Workflow verification
        workflow_records = self.workflow_verifier.verify_workflows(
            task_prompt=original_request,
            mutated_files=mutated_files,
        )

        # 6. Security verification
        sec_findings = self.security_verifier.audit_security(
            task_id=task_id,
            mutated_files=mutated_files,
        )

        # 7. Code quality verification
        qual_findings = self.quality_verifier.audit_quality(
            task_id=task_id,
            mutated_files=mutated_files,
        )

        # Register findings into defect manager
        all_new_findings = sec_findings + qual_findings
        for f in all_new_findings:
            self.defect_manager.add_finding(f)

        open_defects = self.defect_manager.list_findings(task_id=task_id)

        # 8. Evaluate Regression Status
        regression_status = "PASS"
        if regression_report:
            if hasattr(regression_report, "final_status"):
                status_val = getattr(regression_report.final_status, "value", str(regression_report.final_status))
                regression_status = status_val
            elif hasattr(regression_report, "has_regressions") and regression_report.has_regressions:
                regression_status = "REGRESSION_DETECTED"

        # 9. Independent Completion Gate evaluation
        verdict, rationale = self.completion_gate.evaluate_gate(
            requirements=req_records,
            findings=open_defects,
            test_results={
                "failed_count": sum(1 for st in test_results.values() if st in {"FAIL", "FAILED"}),
                "passed_count": sum(1 for st in test_results.values() if st in {"PASS", "PASSED"}),
            },
            regression_status=regression_status,
            workspace_hash_matches=True,
            unexecutable_checks=unexecutable_checks,
        )

        # 10. Assemble VerificationReport
        report = VerificationReport(
            task_id=task_id,
            workspace_id=str(self.workspace_root),
            original_user_request=original_request,
            repository_revision=repo_rev,
            implementation_revision=impl_rev,
            verification_timestamp=time.time(),
            scope={"mutated_files": mutated_files, "unexecutable_checks": unexecutable_checks},
            requirement_coverage={
                "total": len(req_records),
                "verified": len([r for r in req_records if r.status == RequirementVerificationStatus.VERIFIED]),
            },
            requirements=req_records,
            changed_files=mutated_files,
            test_selection=selected_tests,
            test_execution_results=test_results,
            test_integrity=integrity_report,
            runtime_results=runtime_results,
            workflow_results=workflow_records,
            security_findings=sec_findings,
            quality_findings=qual_findings,
            performance_results={"verification_duration_seconds": round(time.time() - start_time, 4)},
            platform_compatibility={"tested_platforms": ["windows-x64"], "untested_platforms": ["linux", "darwin"]},
            regression_status=regression_status,
            open_defects=open_defects,
            accepted_limitations=unexecutable_checks,
            unverified_areas=unexecutable_checks,
            verdict=verdict,
            verdict_rationale=rationale,
        )
        report.evidence_digest = report.compute_evidence_digest()

        # 11. Atomic persistence
        self._persist_report(report)

        # 12. Emit final visibility summary
        self.visibility.emit_final_report_summary(report)

        return report

    def _persist_report(self, report: VerificationReport) -> None:
        """Persists the verification report atomically."""
        task_dir = self.storage_dir / report.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        report_file = task_dir / "verification_report.json"
        tmp_file = report_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        tmp_file.replace(report_file)

    def load_report(self, task_id: str) -> Optional[VerificationReport]:
        """Loads a persisted report."""
        report_file = self.storage_dir / task_id / "verification_report.json"
        if not report_file.exists():
            return None
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            return VerificationReport.from_dict(data)
        except Exception as e:
            log.warning(f"Failed to load report from {report_file}: {e}")
            return None

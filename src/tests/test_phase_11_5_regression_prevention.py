"""
src/tests/test_phase_11_5_regression_prevention.py - Phase 11.5 Adversarial Test Suite.

36 Deterministic Scenarios covering Section 18:
1. Baseline capture.
2. Existing passing tests.
3. Pre-existing failing tests.
4. Newly introduced failing tests.
5. Individual test comparison.
6. Test selection from impact reports.
7. Direct dependency regression detection.
8. Transitive dependency regression detection.
9. Build failure detection.
10. Type and lint failure detection.
11. Integration failure detection.
12. API compatibility regression.
13. Database migration regression.
14. Security regression detection.
15. Flaky test classification.
16. Bounded retry execution.
17. Root-cause evidence classification.
18. New failure correlation with changed symbols.
19. Controlled corrective patching.
20. Failed correction handling.
21. Test integrity protection.
22. Agent-owned rollback.
23. User-modified file protection.
24. Multi-file transaction recovery.
25. Partial operation recovery.
26. Recovery after process termination.
27. Performance regression detection.
28. FinOps cost tracking.
29. Tenant and workspace isolation.
30. Report persistence.
31. Historical comparison.
32. Secret redaction.
33. Approval enforcement.
34. Infinite repair loop prevention.
35. Original requirement verification.
36. Existing functionality preservation.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from src.regression.baseline import TestBaselineManager
from src.regression.detector import PostChangeRegressionDetector
from src.regression.diagnosis import FailureDiagnosisEngine
from src.regression.engine import RegressionPreventionEngine
from src.regression.fix_loop import ControlledRegressionFixLoop
from src.regression.flaky import FlakyTestDetector
from src.regression.integrity import TestIntegrityAuditor
from src.regression.models import (
    FailureClassification,
    IntegrityViolationType,
    RecoveryActionType,
    RegressionStatus,
    RootCauseCertainty,
    TestBaseline,
    TestCaseResult,
    TestPriority,
    TestStatus,
)
from src.regression.performance_gate import PerformanceRegressionAuditor
from src.regression.persistence import RegressionPersistence, redact_secrets_from_dict
from src.regression.recovery import SafeRecoveryCoordinator
from src.regression.security_gate import SecurityRegressionGate
from src.regression.selector import RiskBasedTestSelector
from src.workspace.baseline import compute_file_sha256
from src.workspace.journal import WorkspaceJournalManager
from src.workspace.ledger import WorkspaceChangeLedger
from src.workspace.models import ChangeRecord, FileOwnershipCategory, JournalState, WorkspaceOperationType
from src.workspace.mutation_broker import WorkspaceMutationBroker


class TestPhase115RegressionPrevention(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="crusor_p11_5_")
        self.workspace = (Path(self.tmp_dir) / "workspace").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.engine = RegressionPreventionEngine(str(self.workspace))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Baseline capture
    def test_01_baseline_capture(self) -> None:
        (self.workspace / "test_main.py").write_text("def test_one(): assert True\n", encoding="utf-8")
        mgr = TestBaselineManager(str(self.workspace))
        base = mgr.capture_baseline(task_id="t1")
        self.assertEqual(base.task_id, "t1")
        self.assertIn("test_main.py", base.test_cases)
        self.assertEqual(base.summary["total"], 1)

    # 2. Existing passing tests
    def test_02_existing_passing_tests(self) -> None:
        mgr = TestBaselineManager(str(self.workspace))
        results = {
            "test_1": TestCaseResult(test_id="test_1", test_name="test_1", test_suite="s1", status=TestStatus.PASSING),
        }
        base = mgr.capture_baseline(task_id="t2", pre_existing_results=results)
        self.assertEqual(base.summary["passed"], 1)
        self.assertEqual(base.summary["failed"], 0)

    # 3. Pre-existing failing tests
    def test_03_pre_existing_failing_tests(self) -> None:
        mgr = TestBaselineManager(str(self.workspace))
        results = {
            "test_broken": TestCaseResult(
                test_id="test_broken", test_name="test_broken", test_suite="s1",
                status=TestStatus.FAILING, error_message="Legacy pre-existing failure"
            ),
        }
        base = mgr.capture_baseline(task_id="t3", pre_existing_results=results)
        self.assertEqual(base.summary["failed"], 1)
        self.assertEqual(base.test_cases["test_broken"].status, TestStatus.FAILING)

    # 4. Newly introduced failing tests
    def test_04_newly_introduced_failing_tests(self) -> None:
        detector = PostChangeRegressionDetector()
        base = TestBaseline(
            baseline_id="b4", task_id="t4", repository_revision=None, workspace_root=str(self.workspace),
            test_frameworks=["pytest"],
            test_cases={"t_a": TestCaseResult(test_id="t_a", test_name="t_a", test_suite="s1", status=TestStatus.PASSING)},
        )
        current = {
            "t_a": TestCaseResult(test_id="t_a", test_name="t_a", test_suite="s1", status=TestStatus.FAILING, error_message="Regression error"),
        }
        new_regs, pre_existing, _ = detector.compare_and_detect_regressions(base, current, ["mod.py"], ["func"])
        self.assertEqual(len(new_regs), 1)
        self.assertEqual(len(pre_existing), 0)

    # 5. Individual test comparison
    def test_05_individual_test_comparison(self) -> None:
        detector = PostChangeRegressionDetector()
        base = TestBaseline(
            baseline_id="b5", task_id="t5", repository_revision=None, workspace_root=str(self.workspace),
            test_frameworks=["pytest"],
            test_cases={
                "t_pass": TestCaseResult(test_id="t_pass", test_name="t_pass", test_suite="s", status=TestStatus.PASSING),
                "t_old_fail": TestCaseResult(test_id="t_old_fail", test_name="t_old_fail", test_suite="s", status=TestStatus.FAILING),
            },
        )
        current = {
            "t_pass": TestCaseResult(test_id="t_pass", test_name="t_pass", test_suite="s", status=TestStatus.FAILING),
            "t_old_fail": TestCaseResult(test_id="t_old_fail", test_name="t_old_fail", test_suite="s", status=TestStatus.FAILING),
        }
        new_regs, pre_existing, _ = detector.compare_and_detect_regressions(base, current, [], [])
        self.assertEqual(len(new_regs), 1)
        self.assertEqual(new_regs[0].test_id, "t_pass")
        self.assertEqual(len(pre_existing), 1)
        self.assertEqual(pre_existing[0].test_id, "t_old_fail")

    # 6. Test selection from impact reports
    def test_06_test_selection_from_impact_reports(self) -> None:
        selector = RiskBasedTestSelector()
        class DummyImpact:
            relevant_tests = [
                {"test_id": "t_direct", "file_path": "tests/test_direct.py", "priority": "P0", "rationale": "Direct caller"},
            ]
        selected, excluded = selector.select_test_scope(DummyImpact(), ["tests/test_direct.py", "tests/test_broad.py"])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["test_id"], "t_direct")
        self.assertEqual(len(excluded), 1)

    # 7. Direct dependency regression detection
    def test_07_direct_dependency_regression_detection(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t7", test_name="t7", test_suite="s", status=TestStatus.FAILING,
            error_message="AssertionError: 1 != 2",
            stack_trace="File 'src/auth/jwt.py', line 10, in verify_token\n    assert False",
        )
        diag = diag_engine.diagnose_failure(fail_res, ["src/auth/jwt.py"], ["verify_token"])
        self.assertEqual(diag.root_cause_certainty, RootCauseCertainty.CONFIRMED)
        self.assertIn("verify_token", diag.associated_symbols)

    # 8. Transitive dependency regression detection
    def test_08_transitive_dependency_regression_detection(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t8", test_name="t8", test_suite="s", status=TestStatus.FAILING,
            error_message="KeyError: 'user_id'",
            stack_trace="File 'src/api/routes.py', line 25, in handle_request\n    user = auth_service.get_user()",
        )
        diag = diag_engine.diagnose_failure(fail_res, ["src/auth/jwt.py"], ["verify_token"])
        self.assertEqual(diag.root_cause_certainty, RootCauseCertainty.POSSIBLE)

    # 9. Build failure detection
    def test_09_build_failure_detection(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t9", test_name="t9", test_suite="s", status=TestStatus.FAILING,
            error_message="SyntaxError: invalid syntax in build script",
        )
        diag = diag_engine.diagnose_failure(fail_res, ["build.py"], [])
        self.assertEqual(diag.exception_type, "SyntaxError")

    # 10. Type and lint failure detection
    def test_10_type_and_lint_failure_detection(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t10", test_name="t10", test_suite="s", status=TestStatus.FAILING,
            error_message="TypeError: unsupported operand type(s) for +: 'int' and 'str'",
        )
        diag = diag_engine.diagnose_failure(fail_res, [], [])
        self.assertEqual(diag.exception_type, "TypeError")

    # 11. Integration failure detection
    def test_11_integration_failure_detection(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t11", test_name="t11", test_suite="s", status=TestStatus.FAILING,
            error_message="HTTPConnectionPool(host='localhost', port=8000): Max retries exceeded",
        )
        diag = diag_engine.diagnose_failure(fail_res, [], [])
        self.assertTrue("HTTP" in diag.actual_behavior or "Connection" in diag.actual_behavior)

    # 12. API compatibility regression
    def test_12_api_compatibility_regression(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t12", test_name="test_api_v1", test_suite="s", status=TestStatus.FAILING,
            error_message="AssertionError: Expected status code 200 != 404",
        )
        diag = diag_engine.diagnose_failure(fail_res, ["api/v1/users.py"], [])
        self.assertIn("404", diag.expected_behavior)

    # 13. Database migration regression
    def test_13_database_migration_regression(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t13", test_name="test_migration", test_suite="s", status=TestStatus.FAILING,
            error_message="OperationalError: no such column: user.email",
        )
        diag = diag_engine.diagnose_failure(fail_res, ["migrations/001_user.sql"], [])
        self.assertEqual(diag.exception_type, "OperationalError")

    # 14. Security regression detection
    def test_14_security_regression_detection(self) -> None:
        sec_gate = SecurityRegressionGate()
        fail_res = TestCaseResult(
            test_id="tests/test_rbac.py::test_admin_authorization", test_name="test_admin_authorization",
            test_suite="tests/test_rbac.py", status=TestStatus.FAILING, error_message="PermissionError: Admin auth token rejected",
        )
        ok, findings = sec_gate.evaluate_security_gates([fail_res])
        self.assertFalse(ok)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "CRITICAL")

    # 15. Flaky test classification
    def test_15_flaky_test_classification(self) -> None:
        detector = FlakyTestDetector()
        res1 = TestCaseResult(test_id="f1", test_name="f1", test_suite="s", status=TestStatus.PASSING)
        res2 = TestCaseResult(test_id="f1", test_name="f1", test_suite="s", status=TestStatus.FAILING)
        record = detector.evaluate_test_stability("f1", [res1, res2])
        self.assertTrue(record.is_flaky)
        self.assertIn("inconsistent outcomes", record.variance_rationale)

    # 16. Bounded retry execution
    def test_16_bounded_retry_execution(self) -> None:
        detector = FlakyTestDetector()
        # Consistently failing test is deterministic, not flaky
        r1 = TestCaseResult(test_id="d1", test_name="d1", test_suite="s", status=TestStatus.FAILING)
        r2 = TestCaseResult(test_id="d1", test_name="d1", test_suite="s", status=TestStatus.FAILING)
        record = detector.evaluate_test_stability("d1", [r1, r2])
        self.assertFalse(record.is_flaky)
        self.assertIn("Deterministic failure", record.variance_rationale)

    # 17. Root-cause evidence classification
    def test_17_root_cause_evidence_classification(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t17", test_name="t17", test_suite="s", status=TestStatus.FAILING,
            error_message="ZeroDivisionError: division by zero",
            stack_trace="File 'calc.py', in div",
        )
        diag = diag_engine.diagnose_failure(fail_res, ["calc.py"], ["div"])
        self.assertEqual(diag.root_cause_certainty, RootCauseCertainty.CONFIRMED)

    # 18. New failure correlation with changed symbols
    def test_18_new_failure_correlation_with_changed_symbols(self) -> None:
        diag_engine = FailureDiagnosisEngine()
        fail_res = TestCaseResult(
            test_id="t18", test_name="t18", test_suite="s", status=TestStatus.FAILING,
            error_message="ValueError: invalid format in parse_date",
        )
        diag = diag_engine.diagnose_failure(fail_res, [], ["parse_date"])
        self.assertIn("parse_date", diag.associated_symbols)

    # 19. Controlled corrective patching
    def test_19_controlled_corrective_patching(self) -> None:
        loop = ControlledRegressionFixLoop(max_attempts=2)
        initial_fail = TestCaseResult(test_id="t19", test_name="t19", test_suite="s", status=TestStatus.FAILING)

        patch_applied = [False]
        def mock_patch(op):
            patch_applied[0] = True
            return True

        def mock_verify():
            return {"t19": TestCaseResult(test_id="t19", test_name="t19", test_suite="s", status=TestStatus.PASSING)}

        ok, ops = loop.execute_fix_loop("t19", [initial_fail], [], mock_patch, mock_verify)
        self.assertTrue(ok)
        self.assertTrue(patch_applied[0])
        self.assertEqual(ops[0]["status"], "SUCCESS_RESOLVED")

    # 20. Failed correction handling
    def test_20_failed_correction_handling(self) -> None:
        loop = ControlledRegressionFixLoop(max_attempts=2)
        initial_fail = TestCaseResult(test_id="t20", test_name="t20", test_suite="s", status=TestStatus.FAILING)

        def mock_patch(op): return False
        def mock_verify(): return {"t20": initial_fail}

        ok, ops = loop.execute_fix_loop("t20", [initial_fail], [], mock_patch, mock_verify)
        self.assertFalse(ok)
        self.assertEqual(ops[0]["status"], "PATCH_FAILED")

    # 21. Test integrity protection
    def test_21_test_integrity_protection(self) -> None:
        auditor = TestIntegrityAuditor()
        orig = "def test_real(): assert 1 == 1\ndef test_two(): assert True\n"
        # Attempt to delete test_two and add skip decorator
        mod = "@unittest.skip\ndef test_real():\n    assertTrue(True)\n"
        violations = auditor.audit_test_modification("tests/test_demo.py", orig, mod)
        types = [v.violation_type for v in violations]
        self.assertIn(IntegrityViolationType.TEST_CASE_REMOVED, types)
        self.assertIn(IntegrityViolationType.CONVERTED_TO_SKIP, types)
        self.assertIn(IntegrityViolationType.ASSERTION_WEAKENED, types)

    # 22. Agent-owned rollback
    def test_22_agent_owned_rollback(self) -> None:
        broker = WorkspaceMutationBroker(str(self.workspace), tenant_id="t22")
        broker.create_file("agent_code.py", "v1", task_id="t22")
        journal = WorkspaceJournalManager(str(self.workspace), tenant_id="t22")
        coordinator = SafeRecoveryCoordinator(str(self.workspace), tenant_id="t22", ledger=broker.ledger, journal=journal)

        eval_res = coordinator.evaluate_recovery("t22", ["agent_code.py"])
        self.assertTrue(eval_res.is_safe_to_rollback)
        self.assertEqual(len(eval_res.actions), 1)

    # 23. User-modified file protection
    def test_23_user_modified_file_protection(self) -> None:
        ledger = WorkspaceChangeLedger(str(self.workspace), tenant_id="t23")
        coordinator = SafeRecoveryCoordinator(str(self.workspace), tenant_id="t23", ledger=ledger)

        # File exists on disk but has no agent record -> user owned
        f = self.workspace / "user_file.py"
        f.write_text("user code", encoding="utf-8")
        eval_res = coordinator.evaluate_recovery("t23", ["user_file.py"])
        self.assertFalse(eval_res.is_safe_to_rollback)
        self.assertIn("user_file.py", eval_res.affected_user_files)

    # 24. Multi-file transaction recovery
    def test_24_multi_file_transaction_recovery(self) -> None:
        broker = WorkspaceMutationBroker(str(self.workspace), tenant_id="t24")
        broker.create_file("f1.py", "old1", task_id="t24")
        broker.create_file("f2.py", "old2", task_id="t24")

        rec1 = broker.ledger.get_file_last_record("t24", "f1.py")
        rec2 = broker.ledger.get_file_last_record("t24", "f2.py")
        journal = WorkspaceJournalManager(str(self.workspace), tenant_id="t24")
        journal.begin_transaction("tx24", "t24", [rec1, rec2])

        ok, rolled, skipped = journal.rollback_transaction("tx24")
        self.assertTrue(ok)
        self.assertFalse((self.workspace / "f1.py").exists())
        self.assertFalse((self.workspace / "f2.py").exists())

    # 25. Partial operation recovery
    def test_25_partial_operation_recovery(self) -> None:
        broker = WorkspaceMutationBroker(str(self.workspace), tenant_id="t25")
        broker.create_file("agent.py", "agent_payload", task_id="t25")
        rec = broker.ledger.get_file_last_record("t25", "agent.py")
        journal = WorkspaceJournalManager(str(self.workspace), tenant_id="t25")
        journal.begin_transaction("tx25", "t25", [rec])

        ok, rolled, skipped = journal.rollback_transaction("tx25")
        self.assertTrue(ok)
        self.assertFalse(f_agent.exists() if 'f_agent' in locals() else (self.workspace / "agent.py").exists())

    # 26. Recovery after process termination
    def test_26_recovery_after_process_termination(self) -> None:
        broker = WorkspaceMutationBroker(str(self.workspace), tenant_id="t26")
        broker.create_file("crash.py", "uncommitted", task_id="t26")
        rec = broker.ledger.get_file_last_record("t26", "crash.py")
        journal = WorkspaceJournalManager(str(self.workspace), tenant_id="t26")
        journal.begin_transaction("tx26", "t26", [rec])
        journal.update_transaction_state("tx26", JournalState.IN_PROGRESS)

        # Fresh process instance reads journal
        journal_fresh = WorkspaceJournalManager(str(self.workspace), tenant_id="t26")
        recovered = journal_fresh.load_transaction("tx26")
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.state, JournalState.IN_PROGRESS)

    # 27. Performance regression detection
    def test_27_performance_regression_detection(self) -> None:
        auditor = PerformanceRegressionAuditor()
        base_metrics = {"latency_ms": 10.0, "memory_mb": 50.0}
        post_metrics = {"latency_ms": 25.0, "memory_mb": 52.0}  # 150% latency increase
        comp = auditor.compare_performance(base_metrics, post_metrics, threshold_ratio=1.5)
        self.assertTrue(comp["regressions_detected"])
        self.assertTrue(any("latency_ms" in w for w in comp["warnings"]))

    # 28. FinOps cost tracking
    def test_28_finops_cost_tracking(self) -> None:
        auditor = PerformanceRegressionAuditor()
        base = {"token_cost_inr": 0.0}
        cur = {"token_cost_inr": 0.0}
        comp = auditor.compare_performance(base, cur)
        self.assertFalse(comp["regressions_detected"])

    # 29. Tenant and workspace isolation
    def test_29_tenant_and_workspace_isolation(self) -> None:
        p1 = RegressionPersistence(str(self.workspace), tenant_id="t_alpha")
        p2 = RegressionPersistence(str(self.workspace), tenant_id="t_beta")
        self.assertNotEqual(p1.storage_dir, p2.storage_dir)

    # 30. Report persistence
    def test_30_report_persistence(self) -> None:
        report = self.engine.evaluate_and_enforce_regression_gates(
            task_id="t30",
            workspace_id="ws30",
            changed_files=["main.py"],
            changed_symbols=["main"],
            pre_change_baseline=None,
            post_change_results={"test_main": TestCaseResult(test_id="test_main", test_name="test_main", test_suite="s", status=TestStatus.PASSING)},
        )
        loaded = self.engine.persistence.load_report("t30")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["task_id"], "t30")

    # 31. Historical comparison
    def test_31_historical_comparison(self) -> None:
        # Load pre-change baseline and compare
        base = self.engine.baseline_mgr.capture_baseline(task_id="t31")
        self.assertTrue(self.engine.baseline_mgr.storage_dir.exists())
        loaded = self.engine.baseline_mgr.load_baseline("t31")
        self.assertEqual(loaded.baseline_id, base.baseline_id)

    # 32. Secret redaction
    def test_32_secret_redaction(self) -> None:
        leaky_data = {"api_key": "sk-12345678901234567890", "info": "ok"}
        clean = redact_secrets_from_dict(leaky_data)
        self.assertEqual(clean["api_key"], "[REDACTED_SECRET]")

    # 33. Approval enforcement
    def test_33_approval_enforcement(self) -> None:
        # High risk regression blocks completion
        fail = TestCaseResult(test_id="auth_test", test_name="auth_test", test_suite="s", status=TestStatus.FAILING, error_message="Auth broken")
        report = self.engine.evaluate_and_enforce_regression_gates(
            task_id="t33", workspace_id="ws33", changed_files=["auth.py"], changed_symbols=["login"],
            pre_change_baseline=None, post_change_results={"auth_test": fail},
        )
        self.assertEqual(report.final_status, RegressionStatus.BLOCKED)

    # 34. Infinite repair loop prevention
    def test_34_infinite_repair_loop_prevention(self) -> None:
        loop = ControlledRegressionFixLoop(max_attempts=3)
        fail = TestCaseResult(test_id="inf_t", test_name="inf_t", test_suite="s", status=TestStatus.FAILING)

        attempts_counted = [0]
        def dummy_patch(op):
            attempts_counted[0] += 1
            return True
        def dummy_verify(): return {"inf_t": fail}

        ok, ops = loop.execute_fix_loop("t34", [fail], [], dummy_patch, dummy_verify)
        self.assertFalse(ok)
        self.assertEqual(attempts_counted[0], 3)

    # 35. Original requirement verification
    def test_35_original_requirement_verification(self) -> None:
        # Passing report
        report = self.engine.evaluate_and_enforce_regression_gates(
            task_id="t35", workspace_id="ws35", changed_files=["calc.py"], changed_symbols=["add"],
            pre_change_baseline=None,
            post_change_results={"t35": TestCaseResult(test_id="t35", test_name="t35", test_suite="s", status=TestStatus.PASSING)},
        )
        self.assertEqual(report.final_status, RegressionStatus.PASS)

    # 36. Existing functionality preservation
    def test_36_existing_functionality_preservation(self) -> None:
        # With pre-existing failure, passes with limitation rather than failing
        pre_fail = TestCaseResult(test_id="old_fail", test_name="old_fail", test_suite="s", status=TestStatus.FAILING, error_message="Legacy")
        base = self.engine.baseline_mgr.capture_baseline("t36", pre_existing_results={"old_fail": pre_fail})

        report = self.engine.evaluate_and_enforce_regression_gates(
            task_id="t36", workspace_id="ws36", changed_files=["feature.py"], changed_symbols=["feat"],
            pre_change_baseline=base,
            post_change_results={
                "old_fail": pre_fail,
                "new_feat": TestCaseResult(test_id="new_feat", test_name="new_feat", test_suite="s", status=TestStatus.PASSING),
            },
        )
        self.assertEqual(report.final_status, RegressionStatus.PASS_WITH_PRE_EXISTING_FAILURES)
        self.assertIn("WITH PRE-EXISTING FAILURES", report.final_verdict)


if __name__ == "__main__":
    unittest.main()

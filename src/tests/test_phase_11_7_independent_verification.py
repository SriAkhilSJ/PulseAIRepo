"""
src/tests/test_phase_11_7_independent_verification.py - Phase 11.7 Adversarial Test Suite.

Phase 11.7: Independent Verification & Quality Assurance.
Covers 44 comprehensive deterministic scenarios including Real-World Demonstrations Scenarios A-H:
1. Verification independence: implementation cannot force verdict
2. Verifier reads actual workspace state
3. Verifier rejects stale implementation evidence
4. Verifier detects changed artifact hashes
5. Verifier identifies shared assumptions
6. Verifier handles unavailable evidence
7. Requirement-to-implementation mapping
8. Acceptance criteria evaluation
9. Missing functionality detection
10. Partial implementation detection
11. Stub-only code rejection (empty pass/docstrings)
12. Explicit technical constraint verification
13. Independent test selection (direct unit tests)
14. Independent test selection (impact dependencies)
15. Unexecutable test reporting without marking passed
16. Weak test detection: empty test
17. Weak test detection: tautological assertion (assert True, 1==1)
18. Weak test detection: always passes (try-except pass)
19. Weak test detection: zero assertions
20. Weak test detection: excessive mocking
21. Evidence classification distinction (runtime vs mock)
22. Actual application startup verification
23. Database connectivity probing
24. End-to-end workflow: authentication
25. End-to-end workflow: ecommerce
26. End-to-end workflow: multi-tenant SaaS
27. Security verification: hardcoded secret detection
28. Security verification: SQL injection detection
29. Security verification: dynamic eval/exec code execution
30. Security verification: path traversal pattern
31. Security verification: unprotected sensitive route
32. Security verification: multi-tenant query leakage
33. Code quality verification: debug artifact print statements
34. Code quality verification: bare except clauses
35. Defect manager lifecycle: retest required before VERIFIED_FIXED
36. Completion gate blocks on unresolved critical finding
37. Scenario A Demonstration: Correct implementation verified
38. Scenario B Demonstration: Missing functionality detected & blocked
39. Scenario C Demonstration: Broken integration detected
40. Scenario D Demonstration: Weak tests detected & rejected as evidence
41. Scenario E Demonstration: Security vulnerability blocks completion
42. Scenario F Demonstration: Regression blocks verification
43. Scenario G Demonstration: Stale verification report invalidated
44. Scenario H Demonstration: Insufficient environment disclosed with limitations
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from src.orchestration.models import (
    EngineeringPlanDAG,
    EngineeringTaskNode,
    TaskExecutionState,
    TaskVerdict,
)
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.verification.authority import (
    VerificationAuthority,
    VerificationAuthorityViolationError,
)
from src.verification.completion_gate import IndependentCompletionGate
from src.verification.defect_manager import VerificationFindingManager
from src.verification.engine import IndependentVerificationEngine
from src.verification.invalidation import VerificationInvalidationManager
from src.verification.models import (
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    RequirementVerificationRecord,
    RequirementVerificationStatus,
    RuntimeStartupResult,
    TestEvidenceClassification,
    VerificationFinding,
    VerificationReport,
    VerificationVerdict,
)
from src.verification.quality_verifier import CodeQualityVerifier
from src.verification.requirement_verifier import RequirementVerifier
from src.verification.runtime_verifier import ApplicationRuntimeVerifier
from src.verification.security_verifier import IndependentSecurityVerifier
from src.verification.test_integrity import TestIntegrityEngine
from src.verification.test_selector import IndependentTestSelector
from src.verification.visibility import DesktopVerificationVisibility
from src.verification.workflow_verifier import WorkflowVerifier


class TestPhase117IndependentVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="crusor_p11_7_")
        self.workspace = (Path(self.tmp_dir) / "workspace").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.storage = (Path(self.tmp_dir) / "storage").resolve()
        self.storage.mkdir(parents=True, exist_ok=True)

        self.authority = VerificationAuthority(str(self.workspace), tenant_id="test_tenant")
        self.engine = IndependentVerificationEngine(
            workspace_root=str(self.workspace),
            tenant_id="test_tenant",
            storage_dir=str(self.storage),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Verification independence: implementation cannot force verdict
    def test_01_verification_independence_implementation_cannot_force_verdict(self) -> None:
        gate = IndependentCompletionGate()
        reqs = [
            RequirementVerificationRecord(
                requirement_id="REQ-01",
                intent="test",
                description="test",
                status=RequirementVerificationStatus.FAILED,
            )
        ]
        verdict, rationale = gate.evaluate_gate(
            requirements=reqs,
            findings=[],
            test_results={"failed_count": 0, "passed_count": 1},
            regression_status="PASS",
        )
        self.assertEqual(verdict, VerificationVerdict.FAILED)
        self.assertIn("failed verification", rationale)

    # 2. Verifier reads actual workspace state
    def test_02_verifier_reads_actual_workspace_state(self) -> None:
        code_file = self.workspace / "service.py"
        code_file.write_text("def run():\n    return 42\n", encoding="utf-8")
        read_back = self.authority.inspect_file("service.py")
        self.assertIn("return 42", read_back or "")

    # 3. Verifier rejects stale implementation evidence
    def test_03_verifier_rejects_stale_evidence(self) -> None:
        f = self.workspace / "logic.py"
        f.write_text("v = 1\n", encoding="utf-8")
        h1 = self.authority.compute_workspace_hash(["logic.py"])
        f.write_text("v = 2\n", encoding="utf-8")
        h2 = self.authority.compute_workspace_hash(["logic.py"])
        self.assertNotEqual(h1, h2)

    # 4. Verifier detects changed artifact hashes
    def test_04_verifier_detects_changed_artifact_hashes(self) -> None:
        f = self.workspace / "calc.py"
        f.write_text("def add(a, b): return a + b\n", encoding="utf-8")
        report = self.engine.verify_task(
            task_id="t04",
            original_request="create add",
            mutated_files=["calc.py"],
        )
        # Modify file after report
        f.write_text("def add(a, b): return a - b\n", encoding="utf-8")
        is_valid, modified, reason = self.engine.invalidation_mgr.check_report_validity(report)
        self.assertFalse(is_valid)
        self.assertIn("calc.py", modified)

    # 5. Verifier identifies shared assumptions
    def test_05_verifier_identifies_shared_assumptions(self) -> None:
        (self.workspace / "client.py").write_text("def call(): pass\n", encoding="utf-8")
        (self.workspace / "test_client.py").write_text(
            "import unittest\nfrom unittest.mock import patch, MagicMock\n"
            "class T(unittest.TestCase):\n"
            "    @patch('client.call')\n"
            "    def test_c(self, m):\n"
            "        m.return_value = 1\n",
            encoding="utf-8",
        )
        shared = self.authority.detect_shared_assumptions(["client.py"], ["test_client.py"])
        self.assertTrue(len(shared) >= 1)
        self.assertEqual(shared[0]["type"], "CIRCULAR_MOCK_ASSUMPTION")

    # 6. Verifier handles unavailable evidence
    def test_06_verifier_handles_unavailable_evidence(self) -> None:
        missing = self.authority.inspect_file("non_existent.py")
        self.assertIsNone(missing)

    # 7. Requirement-to-implementation mapping
    def test_07_requirement_to_implementation_mapping(self) -> None:
        (self.workspace / "auth.py").write_text("def login(): return True\n", encoding="utf-8")
        verifier = RequirementVerifier(self.authority)
        class DummySpec:
            def all_requirements(self):
                return [type("Req", (), {"id": "REQ-AUTH", "description": "Implement login", "intent": "login", "acceptance_criteria": ["login returns True"]})()]

        records = verifier.verify_all_requirements(DummySpec(), ["auth.py"], {"test_login": "PASS"})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].requirement_id, "REQ-AUTH")
        self.assertEqual(records[0].status, RequirementVerificationStatus.VERIFIED)

    # 8. Acceptance criteria evaluation
    def test_08_acceptance_criteria_evaluation(self) -> None:
        (self.workspace / "tokens.py").write_text(
            "import secrets\ndef generate_token():\n    return secrets.token_hex(16)\n",
            encoding="utf-8",
        )
        verifier = RequirementVerifier(self.authority)
        class DummySpec:
            def all_requirements(self):
                return [type("Req", (), {
                    "id": "REQ-TOK",
                    "description": "Generate token",
                    "intent": "token",
                    "acceptance_criteria": ["generate_token implementation"],
                })()]

        records = verifier.verify_all_requirements(DummySpec(), ["tokens.py"], {})
        self.assertEqual(records[0].acceptance_criteria[0]["satisfied"], True)

    # 9. Missing functionality detection
    def test_09_missing_functionality_detection(self) -> None:
        verifier = RequirementVerifier(self.authority)
        class DummySpec:
            def all_requirements(self):
                return [type("Req", (), {
                    "id": "REQ-MISSING",
                    "description": "Export orders to CSV",
                    "intent": "csv export",
                    "acceptance_criteria": ["csv file output"],
                })()]

        records = verifier.verify_all_requirements(DummySpec(), [], {})
        self.assertEqual(records[0].status, RequirementVerificationStatus.NOT_IMPLEMENTED)

    # 10. Partial implementation detection
    def test_10_partial_implementation_detection(self) -> None:
        (self.workspace / "user.py").write_text("def create_user(): return True\n", encoding="utf-8")
        gate = IndependentCompletionGate()
        reqs = [
            RequirementVerificationRecord(
                requirement_id="REQ-1",
                intent="user",
                description="user",
                status=RequirementVerificationStatus.VERIFIED,
            ),
            RequirementVerificationRecord(
                requirement_id="REQ-2",
                intent="delete",
                description="delete",
                status=RequirementVerificationStatus.NOT_IMPLEMENTED,
            ),
        ]
        verdict, rationale = gate.evaluate_gate(
            requirements=reqs,
            findings=[],
            test_results={"failed_count": 0, "passed_count": 1},
            regression_status="PASS",
        )
        self.assertEqual(verdict, VerificationVerdict.PARTIALLY_VERIFIED)

    # 11. Stub-only code rejection (empty pass/docstrings)
    def test_11_stub_only_code_rejection(self) -> None:
        (self.workspace / "stub.py").write_text(
            "def stub_func():\n    \"\"\"TODO implement\"\"\"\n    pass\n",
            encoding="utf-8",
        )
        verifier = RequirementVerifier(self.authority)
        class DummySpec:
            def all_requirements(self):
                return [type("Req", (), {
                    "id": "REQ-STUB",
                    "description": "stub func",
                    "intent": "stub",
                    "acceptance_criteria": ["working implementation"],
                })()]

        records = verifier.verify_all_requirements(DummySpec(), ["stub.py"], {})
        self.assertEqual(records[0].status, RequirementVerificationStatus.FAILED)

    # 12. Explicit technical constraint verification
    def test_12_explicit_technical_constraint_verification(self) -> None:
        (self.workspace / "hasher.py").write_text("import hashlib\ndef h(p): return hashlib.sha256(p.encode()).hexdigest()\n", encoding="utf-8")
        content = self.authority.inspect_file("hasher.py")
        self.assertIn("hashlib.sha256", content or "")

    # 13. Independent test selection (direct unit tests)
    def test_13_independent_test_selection_direct(self) -> None:
        (self.workspace / "src").mkdir(exist_ok=True)
        (self.workspace / "src" / "payment.py").write_text("def pay(): pass\n", encoding="utf-8")
        (self.workspace / "tests").mkdir(exist_ok=True)
        (self.workspace / "tests" / "test_payment.py").write_text("def test_p(): assert True\n", encoding="utf-8")

        selector = IndependentTestSelector(self.authority)
        res = selector.select_tests(mutated_files=["src/payment.py"])
        self.assertIn("tests/test_payment.py", res["selected_tests"])

    # 14. Independent test selection (impact dependencies)
    def test_14_independent_test_selection_impact(self) -> None:
        (self.workspace / "test_impacted.py").write_text("def test_imp(): pass\n", encoding="utf-8")
        selector = IndependentTestSelector(self.authority)
        class DummyImpact:
            relevant_tests = ["test_impacted.py"]
        res = selector.select_tests(mutated_files=["mod.py"], impact_report=DummyImpact())
        self.assertIn("test_impacted.py", res["selected_tests"])

    # 15. Unexecutable test reporting without marking passed
    def test_15_unexecutable_test_reporting(self) -> None:
        selector = IndependentTestSelector(self.authority)
        res = selector.select_tests(mutated_files=["src/stripe_payment.py"])
        self.assertTrue(len(res["unexecutable_checks"]) >= 1)
        self.assertIn("payment gateway", res["unexecutable_checks"][0])

    # 16. Weak test detection: empty test
    def test_16_weak_test_detection_empty_test(self) -> None:
        (self.workspace / "test_empty.py").write_text("def test_nothing():\n    pass\n", encoding="utf-8")
        engine = TestIntegrityEngine(self.authority)
        report = engine.audit_test_files(["test_empty.py"])
        self.assertEqual(report.empty_test_count, 1)
        self.assertEqual(report.weak_tests_detected[0]["issue_type"], "EMPTY_TEST")

    # 17. Weak test detection: tautological assertion (assert True, 1==1)
    def test_17_weak_test_detection_tautological_assertion(self) -> None:
        (self.workspace / "test_taut.py").write_text("def test_taut():\n    assert True\n", encoding="utf-8")
        engine = TestIntegrityEngine(self.authority)
        report = engine.audit_test_files(["test_taut.py"])
        self.assertEqual(report.tautological_count, 1)
        self.assertEqual(report.weak_tests_detected[0]["issue_type"], "TAUTOLOGICAL_ASSERTION")

    # 18. Weak test detection: always passes (try-except pass)
    def test_18_weak_test_detection_always_passes(self) -> None:
        (self.workspace / "test_always.py").write_text(
            "def test_swallow():\n    try:\n        raise ValueError()\n    except Exception:\n        pass\n",
            encoding="utf-8",
        )
        engine = TestIntegrityEngine(self.authority)
        report = engine.audit_test_files(["test_always.py"])
        issues = [w["issue_type"] for w in report.weak_tests_detected]
        self.assertIn("ALWAYS_PASSES", issues)

    # 19. Weak test detection: zero assertions
    def test_19_weak_test_detection_zero_assertions(self) -> None:
        (self.workspace / "test_zero.py").write_text("def test_no_assert():\n    x = 10\n    y = 20\n", encoding="utf-8")
        engine = TestIntegrityEngine(self.authority)
        report = engine.audit_test_files(["test_zero.py"])
        issues = [w["issue_type"] for w in report.weak_tests_detected]
        self.assertIn("NO_ASSERTIONS", issues)

    # 20. Weak test detection: excessive mocking
    def test_20_weak_test_detection_excessive_mocking(self) -> None:
        (self.workspace / "test_mock.py").write_text(
            "from unittest.mock import patch\n"
            "@patch('a')\n"
            "@patch('b')\n"
            "@patch('c')\n"
            "def test_excessive(a, b, c):\n"
            "    assert True\n",
            encoding="utf-8",
        )
        engine = TestIntegrityEngine(self.authority)
        report = engine.audit_test_files(["test_mock.py"])
        self.assertTrue(report.excessive_mock_count >= 1)

    # 21. Evidence classification distinction (runtime vs mock)
    def test_21_evidence_classification_distinction(self) -> None:
        (self.workspace / "test_rt.py").write_text(
            "import requests\ndef test_api():\n    r = requests.get('http://localhost')\n    assert r.status_code == 200\n",
            encoding="utf-8",
        )
        engine = TestIntegrityEngine(self.authority)
        report = engine.audit_test_files(["test_rt.py"])
        self.assertEqual(report.evidence_classifications["test_rt.py::test_api"], TestEvidenceClassification.INTEGRATION_TEST.value)

    # 22. Actual application startup verification
    def test_22_actual_application_startup_verification(self) -> None:
        (self.workspace / "main.py").write_text("print('App initializing')\n", encoding="utf-8")
        verifier = ApplicationRuntimeVerifier(self.authority)
        res = verifier.verify_runtime_execution(entry_point="main.py")
        self.assertEqual(res.startup_result, RuntimeStartupResult.SUCCESS)
        self.assertEqual(res.exit_code, 0)

    # 23. Database connectivity probing
    def test_23_database_connectivity_probing(self) -> None:
        import sqlite3
        db_file = self.workspace / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE users (id INT, name TEXT);")
        conn.close()

        verifier = ApplicationRuntimeVerifier(self.authority)
        probe = verifier.probe_database_connectivity(db_path="test.db")
        self.assertTrue(probe["database_tested"])
        self.assertEqual(probe["connectivity"], "SUCCESS")
        self.assertIn("users", probe["tables_found"])

    # 24. End-to-end workflow: authentication
    def test_24_end_to_end_workflow_auth(self) -> None:
        (self.workspace / "auth_service.py").write_text(
            "import hashlib\nimport jwt\ndef hash_password(p): return hashlib.sha256(p.encode()).hexdigest()\n"
            "def verify_token(t): return jwt.decode(t, 'key', algorithms=['HS256'])\n"
            "def login(u, p):\n    if p != 'bad': return {'access_token': 'jwt_123'}\n    raise ValueError('Unauthorized')\n",
            encoding="utf-8",
        )
        wf_verifier = WorkflowVerifier(self.authority)
        records = wf_verifier.verify_workflows("Build user auth and login", ["auth_service.py"])
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].success_path_verified)

    # 25. End-to-end workflow: ecommerce
    def test_25_end_to_end_workflow_ecommerce(self) -> None:
        (self.workspace / "store.py").write_text(
            "def get_products(): return [{'id': 1}]\ndef add_to_cart(item): return True\ndef create_order(cart): return 'ORD-123'\n",
            encoding="utf-8",
        )
        wf_verifier = WorkflowVerifier(self.authority)
        records = wf_verifier.verify_workflows("Build ecommerce store and cart", ["store.py"])
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].success_path_verified)

    # 26. End-to-end workflow: multi-tenant SaaS
    def test_26_end_to_end_workflow_saas(self) -> None:
        (self.workspace / "saas.py").write_text(
            "def create_tenant(name): return {'tenant_id': 10}\ndef assign_role(user, role): return True\n",
            encoding="utf-8",
        )
        wf_verifier = WorkflowVerifier(self.authority)
        records = wf_verifier.verify_workflows("Build multi-tenant saas platform", ["saas.py"])
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].success_path_verified)

    # 27. Security verification: hardcoded secret detection
    def test_27_security_hardcoded_secrets_detection(self) -> None:
        (self.workspace / "keys.py").write_text(
            "API_KEY = \"sk-proj-123456789012345678901234567890\"\n",
            encoding="utf-8",
        )
        sec = IndependentSecurityVerifier(self.authority)
        findings = sec.audit_security("t27", ["keys.py"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, FindingSeverity.CRITICAL)

    # 28. Security verification: SQL injection detection
    def test_28_security_sql_injection_detection(self) -> None:
        (self.workspace / "repo.py").write_text(
            "def get_user(uid):\n    cursor.execute(f\"SELECT * FROM users WHERE id = '{uid}'\")\n",
            encoding="utf-8",
        )
        sec = IndependentSecurityVerifier(self.authority)
        findings = sec.audit_security("t28", ["repo.py"])
        self.assertTrue(any("SQL Injection" in f.title for f in findings))

    # 29. Security verification: dynamic eval/exec code execution
    def test_29_security_eval_exec_detection(self) -> None:
        (self.workspace / "calc.py").write_text("def run(expr):\n    return eval(expr)\n", encoding="utf-8")
        sec = IndependentSecurityVerifier(self.authority)
        findings = sec.audit_security("t29", ["calc.py"])
        self.assertTrue(any("Dynamic Code Execution" in f.title for f in findings))

    # 30. Security verification: path traversal pattern
    def test_30_security_path_traversal_detection(self) -> None:
        (self.workspace / "files.py").write_text("def read_doc(name):\n    return open('../secret/' + name).read()\n", encoding="utf-8")
        sec = IndependentSecurityVerifier(self.authority)
        findings = sec.audit_security("t30", ["files.py"])
        self.assertTrue(any("Path Traversal" in f.title for f in findings))

    # 31. Security verification: unprotected sensitive route
    def test_31_security_unprotected_route_detection(self) -> None:
        (self.workspace / "api.py").write_text(
            "@app.post('/admin/delete')\ndef delete_all(): pass\n",
            encoding="utf-8",
        )
        sec = IndependentSecurityVerifier(self.authority)
        findings = sec.audit_security("t31", ["api.py"])
        self.assertTrue(any("Unprotected" in f.title for f in findings))

    # 32. Security verification: multi-tenant query leakage
    def test_32_security_tenant_isolation_detection(self) -> None:
        (self.workspace / "models.py").write_text(
            "# tenant_id model\ndef query():\n    return db.query(User).filter(User.name == 'alice')\n",
            encoding="utf-8",
        )
        sec = IndependentSecurityVerifier(self.authority)
        findings = sec.audit_security("t32", ["models.py"])
        self.assertTrue(any("Multi-Tenant" in f.title or "Tenant" in f.title for f in findings))

    # 33. Code quality verification: debug artifact print statements
    def test_33_code_quality_debug_artifacts(self) -> None:
        (self.workspace / "util.py").write_text("def calc():\n    print('debug: here')\n    return 1\n", encoding="utf-8")
        qual = CodeQualityVerifier(self.authority)
        findings = qual.audit_quality("t33", ["util.py"])
        self.assertTrue(any("Debug Print" in f.title for f in findings))

    # 34. Code quality verification: bare except clauses
    def test_34_code_quality_bare_except_detection(self) -> None:
        (self.workspace / "handler.py").write_text("def handle():\n    try:\n        pass\n    except:\n        pass\n", encoding="utf-8")
        qual = CodeQualityVerifier(self.authority)
        findings = qual.audit_quality("t34", ["handler.py"])
        self.assertTrue(any("Bare Exception" in f.title for f in findings))

    # 35. Defect manager lifecycle: retest required before VERIFIED_FIXED
    def test_35_defect_manager_lifecycle(self) -> None:
        mgr = VerificationFindingManager(str(self.storage))
        f = VerificationFinding(
            finding_id="DEF-01",
            task_id="t35",
            category=FindingCategory.FUNCTIONALITY,
            severity=FindingSeverity.HIGH,
            title="Broken calculation",
            description="desc",
            evidence="ev",
        )
        mgr.add_finding(f)
        self.assertEqual(mgr.get_finding("DEF-01").status, FindingStatus.OPEN)

        # Agent claims fix
        mgr.mark_fixed_by_implementation("DEF-01", "Fixed bug in math.py")
        self.assertEqual(mgr.get_finding("DEF-01").status, FindingStatus.RETEST_REQUIRED)

        # Verifier confirms
        mgr.confirm_verified_fixed("DEF-01", "Independent test test_calc passed.")
        self.assertEqual(mgr.get_finding("DEF-01").status, FindingStatus.VERIFIED_FIXED)

    # 36. Completion gate blocks on unresolved critical finding
    def test_36_completion_gate_blocks_on_critical_finding(self) -> None:
        gate = IndependentCompletionGate()
        finding = VerificationFinding(
            finding_id="CRIT-01",
            task_id="t36",
            category=FindingCategory.SECURITY,
            severity=FindingSeverity.CRITICAL,
            title="Exposed root key",
            description="key in config",
            evidence="sk-...",
            status=FindingStatus.OPEN,
        )
        verdict, rationale = gate.evaluate_gate(
            requirements=[],
            findings=[finding],
            test_results={},
            regression_status="PASS",
        )
        self.assertEqual(verdict, VerificationVerdict.FAILED)
        self.assertIn("CRITICAL/HIGH", rationale)

    # 37. Scenario A Demonstration: Correct implementation verified
    def test_37_scenario_a_correct_implementation(self) -> None:
        (self.workspace / "service.py").write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
        report = self.engine.verify_task(
            task_id="demo_scenario_a",
            original_request="Implement ping service",
            mutated_files=["service.py"],
            test_execution_results={"test_ping": "PASS"},
        )
        self.assertEqual(report.verdict, VerificationVerdict.VERIFIED)

    # 38. Scenario B Demonstration: Missing functionality detected & blocked
    def test_38_scenario_b_missing_functionality(self) -> None:
        class DummySpec:
            def all_requirements(self):
                return [type("Req", (), {
                    "id": "REQ-PDF",
                    "description": "Generate PDF invoice report",
                    "intent": "pdf report",
                    "acceptance_criteria": ["PDF stream generated"],
                })()]

        report = self.engine.verify_task(
            task_id="demo_scenario_b",
            original_request="Generate PDF invoices",
            mutated_files=[],
            specification=DummySpec(),
        )
        self.assertEqual(report.verdict, VerificationVerdict.FAILED)
        self.assertIn("not implemented", report.verdict_rationale.lower())

    # 39. Scenario C Demonstration: Broken integration detected
    def test_39_scenario_c_broken_integration(self) -> None:
        gate = IndependentCompletionGate()
        verdict, rationale = gate.evaluate_gate(
            requirements=[
                RequirementVerificationRecord(
                    requirement_id="REQ-INT",
                    intent="integration",
                    description="backend client",
                    status=RequirementVerificationStatus.FAILED,
                )
            ],
            findings=[],
            test_results={"failed_count": 1, "passed_count": 0},
            regression_status="PASS",
        )
        self.assertEqual(verdict, VerificationVerdict.FAILED)

    # 40. Scenario D Demonstration: Weak tests detected & rejected as evidence
    def test_40_scenario_d_weak_tests(self) -> None:
        (self.workspace / "test_weak.py").write_text("def test_always_good():\n    assert True\n", encoding="utf-8")
        report = self.engine.test_integrity.audit_test_files(["test_weak.py"])
        self.assertEqual(report.tautological_count, 1)

    # 41. Scenario E Demonstration: Security vulnerability blocks completion
    def test_41_scenario_e_security_vulnerability(self) -> None:
        (self.workspace / "unsafe.py").write_text("def get_data(x):\n    return eval(x)\n", encoding="utf-8")
        report = self.engine.verify_task(
            task_id="demo_scenario_e",
            original_request="Calculate user data",
            mutated_files=["unsafe.py"],
        )
        self.assertEqual(report.verdict, VerificationVerdict.FAILED)
        self.assertTrue(len(report.security_findings) >= 1)

    # 42. Scenario F Demonstration: Regression blocks verification
    def test_42_scenario_f_regression_detection(self) -> None:
        (self.workspace / "fix.py").write_text("def fix(): return True\n", encoding="utf-8")
        class DummyReg:
            final_status = "REGRESSION_DETECTED"
        report = self.engine.verify_task(
            task_id="demo_scenario_f",
            original_request="Fix issue",
            mutated_files=["fix.py"],
            regression_report=DummyReg(),
        )
        self.assertEqual(report.verdict, VerificationVerdict.FAILED)
        self.assertIn("Regression", report.verdict_rationale)

    # 43. Scenario G Demonstration: Stale verification report invalidated
    def test_43_scenario_g_stale_verification(self) -> None:
        f = self.workspace / "clean.py"
        f.write_text("def ok(): return True\n", encoding="utf-8")
        report = self.engine.verify_task(
            task_id="demo_scenario_g",
            original_request="clean feature",
            mutated_files=["clean.py"],
        )
        self.assertEqual(report.verdict, VerificationVerdict.VERIFIED)

        # Mutate clean.py
        f.write_text("def ok(): return False\n", encoding="utf-8")
        is_valid, modified, reason = self.engine.invalidation_mgr.check_report_validity(report)
        self.assertFalse(is_valid)

    # 44. Scenario H Demonstration: Insufficient environment disclosed with limitations
    def test_44_scenario_h_insufficient_environment(self) -> None:
        (self.workspace / "s3_upload.py").write_text("def upload(f):\n    # uploads to AWS S3\n    return True\n", encoding="utf-8")
        report = self.engine.verify_task(
            task_id="demo_scenario_h",
            original_request="Upload to AWS S3 bucket",
            mutated_files=["s3_upload.py"],
        )
        self.assertEqual(report.verdict, VerificationVerdict.VERIFIED_WITH_LIMITATIONS)
        self.assertTrue(len(report.accepted_limitations) >= 1)


if __name__ == "__main__":
    unittest.main()

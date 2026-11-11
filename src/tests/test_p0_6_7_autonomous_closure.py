"""P0.6.7 — Autonomous engineering closure (offline).

Covers the lifecycle P0.6.6 lacked:

* real test discovery (generated / explicit / related), runner selection,
  bounded execution, JUnit evidence and hashes;
* normalized failure diagnosis (implementation vs test vs environment vs
  infrastructure vs ambiguous);
* a bounded repair dispatch that reuses the SAME FinOps reserve/settle path and
  re-executes tests;
* completion gates that refuse to report success on failing, unexecuted,
  unverified, incomplete or financially unresolved work;
* analyzer discipline (optional suggestions never expand mandatory scope).

No network: the scripted provider is a local double with authentic usage
receipts, and the priced provider is "groq"/"qwen/qwen3.6-27b".
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import src.orchestration.model_adapter as ma
from src.orchestration.models import ExecutionLimits
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.orchestration.test_execution import (
    FailureCategory,
    RunnerKind,
    classify_failure,
    discover_tests,
    is_test_file,
    persist_run,
    run_discovered_tests,
)
from src.verification.authority import VerificationAuthority
from src.verification.completion_gate import IndependentCompletionGate
from src.verification.models import (
    RequirementVerificationStatus,
    VerificationVerdict,
)
from src.verification.requirement_verifier import RequirementVerifier

os.environ.setdefault("CRUSORAI_PREVIEW_AUTOSTART", "0")


def _workspace(files: dict[str, str], *, git: bool = False) -> Path:
    root = Path(tempfile.mkdtemp(prefix="p0_6_7_test_")).resolve()
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if git:
        subprocess.run(["git", "init", "-q"], cwd=root, check=False)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=root, check=False)
        subprocess.run(["git", "config", "user.name", "a"], cwd=root, check=False)
        subprocess.run(["git", "add", "-A"], cwd=root, check=False)
        subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=root, check=False)
    return root


MODULE_OK = '''"""Slug helpers."""
import re


def slugify(text: str) -> str:
    """Lowercase, collapse non-alphanumerics, trim hyphens."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
'''

MODULE_BUG = '''"""Slug helpers."""
import re


def slugify(text: str) -> str:
    """Lowercase and replace non-alphanumerics with hyphens (missing trim)."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return re.sub(r"[^a-z0-9]+", "-", text.lower())
'''

TESTS_OK = '''import pytest

from src.slugify import slugify


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_punctuation():
    assert slugify("Hello,   World!!!") == "hello-world"


def test_trimmed():
    assert slugify("--Hello World--") == "hello-world"


def test_non_string():
    with pytest.raises(TypeError):
        slugify(42)
'''

PROMPT = (
    "Create src/slugify.py with a function slugify(text) that lowercases the text, "
    "replaces runs of non-alphanumeric characters with '-', strips leading and trailing "
    "'-', and raises TypeError for non-strings. Then create tests/test_slugify.py with "
    "pytest tests covering basic conversion, punctuation collapse, whitespace trimming, "
    "and TypeError for non-strings. Run the tests with pytest."
)


class ScriptedLLM:
    """Deterministic provider double with authentic usage receipts."""

    def __init__(self, *, repair_output: str = MODULE_OK, test_output: str = TESTS_OK):
        self.prompts: list[str] = []
        self.repair_output = repair_output
        self.test_output = test_output
        self._max_attempts = 1

    def invoke(self, prompt: str, **kwargs):
        self.prompts.append(prompt)
        target = ""
        for line in prompt.splitlines():
            if line.startswith("Target file path:"):
                target = line.split(":", 1)[1].strip()
                break
        if "repairing an existing file" in prompt.lower():
            content = self.repair_output
        elif target.endswith("test_slugify.py"):
            content = self.test_output
        elif target.endswith("slugify.py"):
            content = MODULE_BUG if self.repair_output == MODULE_OK else MODULE_BUG
        else:
            content = "# unknown target\n"
        return type("Resp", (), {
            "content": f"```python\n{content}\n```",
            "usage_metadata": {"input_tokens": 180, "output_tokens": 75, "total_tokens": 255},
            "response_metadata": {"finish_reason": "stop"},
        })()


def _run_orchestrator(
    ws: Path,
    *,
    llm: ScriptedLLM,
    limits: ExecutionLimits | None = None,
    cancellation=None,
):
    original = ma.get_llm
    ma.get_llm = lambda provider=None, model=None: llm
    try:
        orch = EngineeringExecutionOrchestrator(
            workspace_root=str(ws),
            tenant_id="p0_6_7_test",
            limits=limits or ExecutionLimits(
                max_cost_inr=5.0, max_dispatch_budget=5,
                max_correction_attempts=3, test_timeout_seconds=120.0,
            ),
            mock_mode=False,
            provider="groq",
            model="qwen/qwen3.6-27b",
        )
        return orch, orch.run_task(
            task_prompt=PROMPT,
            task_id="task_p0_6_7_test",
            cancellation_checker=cancellation,
        )
    finally:
        ma.get_llm = original


class TestDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _workspace({
            "src/slugify.py": MODULE_OK,
            "tests/test_slugify.py": TESTS_OK,
        })

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_generated_test_file_is_discovered(self) -> None:
        discovery = discover_tests(
            self.ws,
            modified_files=["src/slugify.py", "tests/test_slugify.py"],
            prompt="",
        )
        self.assertEqual(discovery.runner, RunnerKind.PYTEST)
        self.assertEqual(discovery.generated, ["tests/test_slugify.py"])
        self.assertIn("tests/test_slugify.py", discovery.files)

    def test_explicit_test_path_in_prompt_is_used(self) -> None:
        discovery = discover_tests(
            self.ws,
            modified_files=["src/slugify.py"],
            prompt="Run tests/test_slugify.py and report.",
        )
        self.assertIn("tests/test_slugify.py", discovery.explicit)
        self.assertIn("tests/test_slugify.py", discovery.files)

    def test_no_tests_means_no_runner(self) -> None:
        empty = _workspace({"src/plain.py": "x = 1\n"})
        try:
            discovery = discover_tests(empty, modified_files=["src/plain.py"], prompt="")
            self.assertEqual(discovery.runner, RunnerKind.NONE)
            self.assertEqual(discovery.files, [])
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_paths_outside_the_workspace_are_refused(self) -> None:
        discovery = discover_tests(
            self.ws,
            modified_files=["src/slugify.py", "../../outside_test.py"],
            prompt="",
        )
        self.assertFalse(any("outside_test" in f for f in discovery.files))
        self.assertTrue(any("outside" in w for w in discovery.warnings))


class TestExecutionAndEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _workspace({
            "src/slugify.py": MODULE_BUG,
            "tests/test_slugify.py": TESTS_OK,
        })
        self.discovery = discover_tests(
            self.ws, modified_files=["src/slugify.py", "tests/test_slugify.py"]
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_real_execution_records_counts_report_and_hashes(self) -> None:
        result = run_discovered_tests(
            self.discovery, workspace=self.ws,
            modified_files=["src/slugify.py", "tests/test_slugify.py"],
            timeout_s=120.0,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.total, 4)
        self.assertEqual(result.passed + result.failed + result.errors, 4)
        self.assertGreaterEqual(result.failed, 1)
        self.assertIsNotNone(result.report_path)
        self.assertTrue(Path(result.report_path).exists())
        self.assertIn("src/slugify.py", result.source_hashes)
        self.assertIn("tests/test_slugify.py", result.source_hashes)
        evidence = persist_run(self.ws, "task", 1, self.discovery, result)
        payload = json.loads(Path(evidence).read_text(encoding="utf-8"))
        self.assertEqual(payload["result"]["total"], 4)
        self.assertIn("command", payload["result"])

    def test_assertion_failure_is_mapped_to_the_module(self) -> None:
        result = run_discovered_tests(
            self.discovery, workspace=self.ws,
            modified_files=["src/slugify.py", "tests/test_slugify.py"],
            timeout_s=120.0,
        )
        diagnosis = classify_failure(
            result, workspace=self.ws,
            modified_files=["src/slugify.py", "tests/test_slugify.py"],
            generated_test_files=["tests/test_slugify.py"],
        )
        self.assertEqual(diagnosis.category, FailureCategory.IMPLEMENTATION_DEFECT)
        self.assertIn("src/slugify.py", diagnosis.target_files)
        self.assertTrue(diagnosis.repairable)

    def test_generated_test_with_wrong_import_is_a_test_defect(self) -> None:
        ws = _workspace({
            "src/mod.py": "def f():\n    return 1\n",
            "tests/test_mod.py": "from mod import f\n\ndef test_f():\n    assert f() == 1\n",
        })
        try:
            discovery = discover_tests(ws, modified_files=["src/mod.py", "tests/test_mod.py"])
            result = run_discovered_tests(
                discovery, workspace=ws,
                modified_files=["src/mod.py", "tests/test_mod.py"], timeout_s=120.0,
            )
            diagnosis = classify_failure(
                result, workspace=ws,
                modified_files=["src/mod.py", "tests/test_mod.py"],
                generated_test_files=["tests/test_mod.py"],
            )
            self.assertEqual(diagnosis.category, FailureCategory.TEST_EXPECTATION_DEFECT)
            self.assertIn("tests/test_mod.py", diagnosis.target_files)
            self.assertTrue(diagnosis.repairable)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_missing_dependency_is_environment_not_code(self) -> None:
        ws = _workspace({
            "src/mod.py": "x = 1\n",
            "tests/test_mod.py": "import definitely_missing_dependency_xyz\n\ndef test_x():\n    assert True\n",
        })
        try:
            discovery = discover_tests(ws, modified_files=["src/mod.py", "tests/test_mod.py"])
            result = run_discovered_tests(
                discovery, workspace=ws,
                modified_files=["src/mod.py", "tests/test_mod.py"], timeout_s=120.0,
            )
            diagnosis = classify_failure(
                result, workspace=ws,
                modified_files=["src/mod.py", "tests/test_mod.py"],
                generated_test_files=["tests/test_mod.py"],
            )
            self.assertEqual(diagnosis.category, FailureCategory.ENVIRONMENT_FAILURE)
            self.assertFalse(diagnosis.repairable)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_invalid_generated_test_is_a_test_defect(self) -> None:
        ws = _workspace({
            "src/mod.py": "def f():\n    return 1\n",
            "tests/test_mod.py": "def test_broken(:\n    pass\n",
        })
        try:
            discovery = discover_tests(ws, modified_files=["src/mod.py", "tests/test_mod.py"])
            result = run_discovered_tests(
                discovery, workspace=ws,
                modified_files=["src/mod.py", "tests/test_mod.py"], timeout_s=120.0,
            )
            diagnosis = classify_failure(
                result, workspace=ws,
                modified_files=["src/mod.py", "tests/test_mod.py"],
                generated_test_files=["tests/test_mod.py"],
            )
            self.assertEqual(diagnosis.category, FailureCategory.TEST_EXPECTATION_DEFECT)
            self.assertIn("tests/test_mod.py", diagnosis.target_files)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_timeout_is_infrastructure_not_a_code_defect(self) -> None:
        ws = _workspace({
            "src/mod.py": "def f():\n    return 1\n",
            "tests/test_slow.py": "import time\n\ndef test_slow():\n    time.sleep(5)\n",
        })
        try:
            discovery = discover_tests(ws, modified_files=["src/mod.py", "tests/test_slow.py"])
            result = run_discovered_tests(
                discovery, workspace=ws,
                modified_files=["src/mod.py", "tests/test_slow.py"], timeout_s=0.3,
            )
            self.assertTrue(result.timed_out)
            diagnosis = classify_failure(
                result, workspace=ws,
                modified_files=["src/mod.py", "tests/test_slow.py"],
                generated_test_files=["tests/test_slow.py"],
            )
            self.assertEqual(diagnosis.category, FailureCategory.EXECUTION_INFRASTRUCTURE_FAILURE)
            self.assertFalse(diagnosis.repairable)
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestAnalyzerDiscipline(unittest.TestCase):
    def test_file_paths_are_not_fragmented_into_requirements(self) -> None:
        from src.intelligence.requirement_extractor import RequirementExtractor

        bundle = RequirementExtractor().extract(
            "Create src/slugify.py with a function slugify(text) that lowercases. "
            "Then create tests/test_slugify.py with pytest tests."
        )
        descriptions = [getattr(r, "description", "") for r in bundle.requirements]
        self.assertFalse(any(d.startswith("py with") for d in descriptions))
        self.assertTrue(any("src/slugify.py" in d for d in descriptions))

    def test_optional_suggestions_never_become_plan_nodes(self) -> None:
        from src.orchestration.planner import EngineeringTaskPlanner

        tmp = Path(tempfile.mkdtemp(prefix="p0_6_7_plan_"))
        try:
            explicit = SimpleNamespace(
                id="REQ-001", title="Explicit", description="Create src/slugify.py",
                classification="EXPLICIT", status=SimpleNamespace(value="ACCEPTED"),
                affected_files=["src/slugify.py"], acceptance_criteria=["Works"],
            )
            optional = SimpleNamespace(
                id="REQ-002", title="Optional", description="Add enterprise SSO",
                classification="REASONABLE_DEFAULT", status=SimpleNamespace(value="PROPOSED"),
                affected_files=["src/sso.py"], acceptance_criteria=["SSO"],
            )
            spec = SimpleNamespace(
                all_requirements=lambda: [explicit, optional],
                requirements=[explicit, optional],
            )
            dag = EngineeringTaskPlanner(str(tmp)).build_plan(
                "t", spec, requested_files=["src/slugify.py"],
            )
            targets = [f for n in dag.nodes.values() for f in n.target_files]
            self.assertIn("src/slugify.py", targets)
            self.assertNotIn("src/sso.py", targets)
            self.assertEqual([o["id"] for o in dag.optional_requirements], ["REQ-002"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


    def test_test_requirement_is_assigned_the_test_file_by_role(self) -> None:
        from src.orchestration.planner import EngineeringTaskPlanner

        tmp = Path(tempfile.mkdtemp(prefix="p0_6_7_plan_role_"))
        try:
            def req(rid: str, description: str):
                return SimpleNamespace(
                    id=rid, title=rid, description=description,
                    classification="EXPLICIT", status=SimpleNamespace(value="ACCEPTED"),
                    affected_files=[], acceptance_criteria=["Works"],
                )

            reqs = [
                req("REQ-001", "Create src/duration.py with parse_duration(value)."),
                req("REQ-002", "Supported units: h, m, s."),
                req("REQ-003", "Then create tests/test_duration.py with pytest tests."),
            ]
            spec = SimpleNamespace(all_requirements=lambda: reqs, requirements=reqs)
            dag = EngineeringTaskPlanner(str(tmp)).build_plan(
                "t", spec,
                requested_files=["src/duration.py", "tests/test_duration.py"],
                task_prompt="Create src/duration.py and tests/test_duration.py",
                max_nodes=5,
            )
            targets = [f for n in dag.nodes.values() for f in n.target_files]
            self.assertIn("src/duration.py", targets)
            self.assertIn("tests/test_duration.py", targets)
            self.assertEqual(targets.count("tests/test_duration.py"), 1,
                             "the test file must be planned once, not dispatched twice")
            test_node = next(
                n for n in dag.nodes.values()
                if n.target_files == ["tests/test_duration.py"]
            )
            self.assertIn("REQ-003", test_node.related_requirement_ids)
            self.assertNotIn("REQ-002", test_node.related_requirement_ids)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestRepairLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _workspace({"README.md": "# ws\n"}, git=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_generate_fail_diagnose_repair_pass(self) -> None:
        llm = ScriptedLLM()
        orch, delivery = _run_orchestrator(self.ws, llm=llm)
        self.assertEqual(delivery.verdict.value, "COMPLETED")
        self.assertTrue(delivery.independently_verified)
        self.assertEqual(len(llm.prompts), 3, "2 implementation + exactly 1 repair")
        self.assertEqual(len(delivery.repair_attempts), 1)
        self.assertEqual(delivery.repair_attempts[0]["target"], "src/slugify.py")
        final = delivery.test_evidence["final_run"]
        self.assertEqual(final["failed"], 0)
        self.assertEqual(final["passed"], 4)
        self.assertTrue(Path(delivery.test_evidence["runs"][-1]).exists())
        fin = orch._last_finops
        self.assertEqual(fin.accounting.calls_count, 3)
        self.assertEqual(len(fin._settled_reservations), 3)
        self.assertEqual(len(fin._active_reservations), 0)
        self.assertEqual(len(fin._uncertain_reservations), 0)
        verified = [r for r in delivery.requirement_verification
                    if r["status"] == "VERIFIED"]
        self.assertGreaterEqual(len(verified), 1)
        journal = list(self.ws.rglob("orchestration_journal.jsonl"))[0]
        events = [json.loads(line)["event_type"] for line in journal.read_text(encoding="utf-8").splitlines()]
        self.assertIn("TESTS_EXECUTED", events)
        self.assertIn("FAILURES_CLASSIFIED", events)
        self.assertIn("REPAIR_DISPATCHED", events)
        self.assertIn("TESTS_REEXECUTED", events)
        self.assertIn("COMPLETION_EVALUATED", events)

    def test_failed_repair_does_not_complete(self) -> None:
        llm = ScriptedLLM(repair_output=MODULE_BUG)
        orch, delivery = _run_orchestrator(
            self.ws, llm=llm,
            limits=ExecutionLimits(
                max_cost_inr=5.0, max_dispatch_budget=5,
                max_correction_attempts=1, test_timeout_seconds=120.0,
            ),
        )
        self.assertEqual(delivery.verdict.value, "FAILED")
        self.assertFalse(delivery.independently_verified)
        self.assertEqual(len(llm.prompts), 3, "2 implementation + 1 exhausted repair")
        self.assertEqual(len(delivery.repair_attempts), 1)
        self.assertGreater(delivery.test_evidence["final_run"]["failed"], 0)

    def test_dispatch_budget_stops_after_the_last_authorized_repair(self) -> None:
        llm = ScriptedLLM(repair_output=MODULE_BUG)
        orch, delivery = _run_orchestrator(
            self.ws, llm=llm,
            limits=ExecutionLimits(
                max_cost_inr=5.0, max_dispatch_budget=3,
                max_correction_attempts=3, test_timeout_seconds=120.0,
            ),
        )
        self.assertEqual(len(llm.prompts), 3, "2 implementation + 1 repair, then the budget is spent")
        self.assertEqual(delivery.verdict.value, "FAILED")
        self.assertEqual(len(delivery.repair_attempts), 1)
        self.assertGreater(delivery.test_evidence["final_run"]["failed"], 0)
        self.assertEqual(orch._last_finops.accounting.calls_count, 3)

    def test_cancellation_stops_the_repair_loop(self) -> None:
        llm = ScriptedLLM()

        def cancelled() -> bool:
            # True only once the test artifact exists, i.e. at/after the loop.
            return (self.ws / "tests" / "test_slugify.py").exists()

        orch, delivery = _run_orchestrator(self.ws, llm=llm, cancellation=cancelled)
        self.assertEqual(delivery.verdict.value, "CANCELLED")
        self.assertEqual(len(llm.prompts), 2, "no repair dispatch after cancellation")

    def test_test_integrity_guard_blocks_weakening(self) -> None:
        orch = EngineeringExecutionOrchestrator(str(self.ws), tenant_id="p0_6_7_test")
        path = self.ws / "tests" / "test_slugify.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TESTS_OK, encoding="utf-8")
        guard = orch._test_integrity_guard("tests/test_slugify.py")
        with self.assertRaises(ValueError):
            guard("")
        with self.assertRaises(ValueError):
            guard("def test_basic():\n    assert True\n")
        self.assertEqual(guard(TESTS_OK), TESTS_OK)


class TestSemanticVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _workspace({"src/slugify.py": MODULE_OK})
        self.verifier = RequirementVerifier(VerificationAuthority(str(self.ws)))
        req = SimpleNamespace(
            id="REQ-001",
            description="Create src/slugify.py",
            intent="Slug behavior",
            classification="EXPLICIT",
            acceptance_criteria=["Works"],
        )
        self.spec = SimpleNamespace(all_requirements=lambda: [req], requirements=[req])

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_file_presence_is_not_verification_when_tests_are_required(self) -> None:
        records = self.verifier.verify_all_requirements(
            self.spec, ["src/slugify.py"], {},
            requirement_files={"REQ-001": ["src/slugify.py"]},
            requirement_tests={"REQ-001": []},
            require_test_evidence=True,
        )
        self.assertEqual(records[0].status, RequirementVerificationStatus.NOT_VERIFIED)

        verdict, _ = IndependentCompletionGate().evaluate_gate(
            requirements=records, findings=[], test_results={},
            regression_status="PASS",
        )
        self.assertEqual(verdict, VerificationVerdict.FAILED)

    def test_executed_passing_test_verifies_the_requirement(self) -> None:
        records = self.verifier.verify_all_requirements(
            self.spec, ["src/slugify.py"], {"tests/test_slugify.py::test_basic": "PASS"},
            requirement_files={"REQ-001": ["src/slugify.py"]},
            requirement_tests={"REQ-001": ["tests/test_slugify.py::test_basic"]},
            require_test_evidence=True,
        )
        self.assertEqual(records[0].status, RequirementVerificationStatus.VERIFIED)

    def test_failed_executed_test_fails_the_requirement(self) -> None:
        records = self.verifier.verify_all_requirements(
            self.spec, ["src/slugify.py"], {"tests/test_slugify.py::test_basic": "FAILED"},
            requirement_files={"REQ-001": ["src/slugify.py"]},
            requirement_tests={"REQ-001": ["tests/test_slugify.py::test_basic"]},
            require_test_evidence=True,
        )
        self.assertEqual(records[0].status, RequirementVerificationStatus.FAILED)

    def test_inconclusive_evidence_blocks_completion(self) -> None:
        records = self.verifier.verify_all_requirements(
            self.spec, ["src/slugify.py"], {},
            requirement_files={"REQ-001": ["src/slugify.py"]},
            require_test_evidence=True,
            test_execution_error="runner crashed",
        )
        self.assertEqual(records[0].status, RequirementVerificationStatus.INCONCLUSIVE)
        verdict, _ = IndependentCompletionGate().evaluate_gate(
            requirements=records, findings=[], test_results={},
            regression_status="PASS",
        )
        self.assertEqual(verdict, VerificationVerdict.BLOCKED)

    def test_optional_suggestion_does_not_block_completion(self) -> None:
        optional = SimpleNamespace(
            id="REQ-002",
            description="Add enterprise SSO",
            intent="SSO",
            classification="REASONABLE_DEFAULT",
            acceptance_criteria=["SSO exists"],
        )
        records = self.verifier.verify_all_requirements(
            SimpleNamespace(all_requirements=lambda: [optional], requirements=[optional]),
            ["src/slugify.py"], {},
            requirement_files={},
            require_test_evidence=True,
        )
        self.assertEqual(records[0].status, RequirementVerificationStatus.NOT_APPLICABLE)
        verdict, _ = IndependentCompletionGate().evaluate_gate(
            requirements=records, findings=[], test_results={},
            regression_status="PASS",
        )
        self.assertNotEqual(verdict, VerificationVerdict.FAILED)


class TestHarnessLifecycleReader(unittest.TestCase):
    def test_journal_is_summarized_for_the_acceptance_harness(self) -> None:
        from benchmarks.crusor_desktop_acceptance.live_turn import read_orchestration_lifecycle

        ws = Path(tempfile.mkdtemp(prefix="p0_6_7_journal_")).resolve()
        try:
            journal = ws / ".crusorai" / "tenants" / "default_tenant" / "tasks" / "t" / "orchestration_journal.jsonl"
            journal.parent.mkdir(parents=True)
            events = [
                {"event_type": "TESTS_EXECUTED", "details": {"run": {"total": 4, "failed": 2, "command": "python -m pytest"}, "evidence": "run1.json"}},
                {"event_type": "FAILURES_CLASSIFIED", "details": {"category": "IMPLEMENTATION_DEFECT"}},
                {"event_type": "REPAIR_DISPATCHED", "details": {"attempt": 1, "target": "src/slugify.py"}},
                {"event_type": "TESTS_REEXECUTED", "details": {"run": {"total": 4, "failed": 0, "command": "python -m pytest"}, "evidence": "run2.json"}},
                {"event_type": "COMPLETION_EVALUATED", "details": {"ok": True, "blocked": False}},
                {"event_type": "TASK_DELIVERED", "details": {"requirement_verification": [{"requirement_id": "REQ-001", "status": "VERIFIED"}]}},
            ]
            journal.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            out = read_orchestration_lifecycle(ws)
            self.assertTrue(out["available"])
            self.assertEqual(len(out["tests"]), 2)
            self.assertEqual(out["final_test_run"]["failed"], 0)
            self.assertEqual(len(out["repairs"]), 1)
            self.assertEqual(len(out["diagnoses"]), 1)
            self.assertTrue(out["completion_ok"])
            self.assertEqual(out["requirement_verification"][0]["status"], "VERIFIED")
        finally:
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

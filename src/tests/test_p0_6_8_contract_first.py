"""P0.6.8 — Contract-first planning and cross-file consistency (offline).

Covers the exact P0.6.7 historical prompt, the 16 adversarial planner
scenarios, contract parsing, plan validation, static cross-file checks,
coverage-preserving test repair, the full lifecycle with the historical failure
class, and FinOps accounting.
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
from src.orchestration.contract import (
    ContractComponent,
    EngineeringContract,
    FileRole,
    PlanValidationError,
    audit_test_repair,
    detect_file_role,
    extract_contract,
    parse_prompt_contract,
    repair_test_imports,
    build_test_inventory,
    validate_contract_plan,
    validate_cross_file,
)
from src.orchestration.models import ExecutionLimits, EngineeringPlanDAG, EngineeringTaskNode
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.orchestration.planner import EngineeringTaskPlanner, PlanBudgetExceeded

os.environ.setdefault("CRUSORAI_PREVIEW_AUTOSTART", "0")

REPO = Path(__file__).resolve().parents[2]
LIVE7_EVIDENCE = REPO / "diagnostics" / "p0_6_7" / "live7" / "evidence.json"
LIVE7_PROMPT = json.loads(LIVE7_EVIDENCE.read_text(encoding="utf-8"))["prompt"]
LIVE7_SHA = "a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8"


def req(rid: str, description: str, classification: str = "EXPLICIT") -> SimpleNamespace:
    return SimpleNamespace(
        id=rid, title=rid, description=description,
        classification=classification, status=SimpleNamespace(value="ACCEPTED"),
        affected_files=[], acceptance_criteria=["Works"],
    )


def _ws(files: dict[str, str] | None = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="p0_6_8_")).resolve()
    for rel, content in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _spec(requests: list[SimpleNamespace]):
    return SimpleNamespace(all_requirements=lambda: requests, requirements=requests)


def _contract_and_plan(prompt, reqs, files, *, max_nodes=5, ws=None, task_id="t"):
    root = ws or _ws()
    contract = extract_contract(prompt, reqs, files, task_id=task_id, workspace=root)
    dag = EngineeringTaskPlanner(str(root)).build_plan(
        task_id, _spec(reqs), requested_files=files, task_prompt=prompt,
        max_nodes=max_nodes, contract=contract,
    )
    return root, contract, dag


# --------------------------------------------------------------------------- #
# contract extraction
# --------------------------------------------------------------------------- #

class TestContractExtraction(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _ws()
        self.reqs = [
            req("REQ-001", "Create src/duration.py with exactly one public function parse_duration(value)."),
            req("REQ-002", "Supported units: h, m, s."),
            req("REQ-003", "Then create tests/test_duration.py with pytest tests."),
            req("REQ-004", "Add enterprise SSO.", "REASONABLE_DEFAULT"),
        ]
        self.contract = extract_contract(
            LIVE7_PROMPT, self.reqs, ["src/duration.py", "tests/test_duration.py"],
            task_id="task_p068", workspace=self.ws,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_prompt_is_the_exact_historical_request(self) -> None:
        self.assertEqual(self.contract.prompt_sha256, LIVE7_SHA)
        self.assertIn("parse_duration", LIVE7_PROMPT)
        self.assertIn("from src.duration import parse_duration", LIVE7_PROMPT)

    def test_api_fields_are_structured(self) -> None:
        fields = parse_prompt_contract(LIVE7_PROMPT)
        self.assertEqual(fields["symbols"], ["parse_duration"])
        self.assertEqual(fields["signatures"]["parse_duration"], ["value"])
        self.assertEqual(fields["returns"], "int")
        self.assertEqual(fields["units"], ["h", "m", "s"])
        self.assertTrue(any(e["type"] == "ValueError" for e in fields["errors"]))
        self.assertTrue(any(e["type"] == "TypeError" for e in fields["errors"]))
        self.assertTrue(any("float" in f for f in fields["forbidden"]))
        self.assertFalse(any("exactly" == s for s in fields["symbols"]))
        self.assertIn({"module": "src.duration", "symbols": ["parse_duration"], "style": "from"}, fields["imports"])
        self.assertTrue(any(c.get("input") == "1h30m" and c.get("expected") == 5400 for c in fields["test_cases"]))
        self.assertTrue(any(c.get("input") == "1h1h" and c.get("raises") == "ValueError" for c in fields["test_cases"]))

    def test_components_have_roles_targets_and_requirements(self) -> None:
        roles = {c.target_file: c.role for c in self.contract.components}
        self.assertEqual(roles, {
            "src/duration.py": "SOURCE",
            "tests/test_duration.py": "TEST",
        })
        self.assertEqual(self.contract.requirement_map["REQ-001"], ["src/duration.py"])
        self.assertEqual(self.contract.requirement_map["REQ-002"], ["src/duration.py"])
        self.assertEqual(self.contract.requirement_map["REQ-003"], ["tests/test_duration.py"])
        self.assertEqual(self.contract.ambiguities, [])
        self.assertEqual([o["id"] for o in self.contract.optional_suggestions], ["REQ-004"])

    def test_contract_is_persisted_and_hashed(self) -> None:
        path = Path(self.ws) / ".crusorai" / "contracts" / "task_p068_contract.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["contract_hash"], self.contract.contract_hash)
        self.assertEqual(data["prompt_sha256"], LIVE7_SHA)

    def test_conflicting_symbols_are_ambiguous(self) -> None:
        prompt = "Create src/x.py with public function alpha() and public function beta()."
        contract = extract_contract(prompt, [req("REQ-1", prompt)], ["src/x.py"],
                                    task_id="amb", workspace=self.ws)
        self.assertTrue(any("conflicting" in a.lower() for a in contract.ambiguities))

    def test_no_symbol_for_a_public_api_is_ambiguous(self) -> None:
        prompt = "Create src/x.py with a public function that returns int."
        contract = extract_contract(prompt, [req("REQ-1", prompt)], ["src/x.py"],
                                    task_id="amb2", workspace=self.ws)
        self.assertTrue(any("symbol" in a.lower() for a in contract.ambiguities))


# --------------------------------------------------------------------------- #
# role-aware assignment + validation (adversarial)
# --------------------------------------------------------------------------- #

class TestRoleAssignment(unittest.TestCase):
    def test_exact_historical_prompt_plans_two_work_units(self) -> None:
        reqs = [
            req("REQ-001", "Create src/duration.py with parse_duration(value)."),
            req("REQ-002", "Supported units: h, m, s."),
            req("REQ-003", "Then create tests/test_duration.py with pytest tests."),
        ]
        contract = extract_contract(
            LIVE7_PROMPT, reqs, ["src/duration.py", "tests/test_duration.py"],
            task_id="exact", workspace=_ws(),
        )
        dag = EngineeringTaskPlanner(".").build_plan(
            "exact", _spec(reqs), requested_files=["src/duration.py", "tests/test_duration.py"],
            task_prompt=LIVE7_PROMPT, max_nodes=5, contract=contract,
        )
        units = [n for n in dag.nodes.values() if n.target_files]
        self.assertEqual(len(units), 2)
        roles = {n.target_files[0]: n.file_role for n in units}
        self.assertEqual(roles, {"src/duration.py": "SOURCE", "tests/test_duration.py": "TEST"})
        test_node = next(n for n in units if n.file_role == "TEST")
        self.assertEqual(test_node.related_requirement_ids, ["REQ-003"])
        source_node = next(n for n in units if n.file_role == "SOURCE")
        self.assertEqual(source_node.related_requirement_ids, ["REQ-001", "REQ-002"])

    def test_interleaved_requirements_get_matching_roles(self) -> None:
        prompt = "Create src/a.py. Add tests/test_a.py. Create src/b.py."
        reqs = [
            req("REQ-1", "Create src/a.py."),
            req("REQ-2", "Add tests/test_a.py."),
            req("REQ-3", "Create src/b.py."),
        ]
        _, contract, dag = _contract_and_plan(prompt, reqs, ["src/a.py", "tests/test_a.py", "src/b.py"])
        mapping = {n.file_role: n.target_files for n in dag.nodes.values() if n.target_files}
        self.assertIn("src/a.py", [f for n in dag.nodes.values() for f in n.target_files])
        self.assertEqual([n for n in dag.nodes.values() if "tests/test_a.py" in n.target_files][0].file_role, "TEST")

    def test_source_file_named_test_is_source(self) -> None:
        prompt = "Create src/test_harness.py with run_checks()."
        reqs = [req("REQ-1", prompt)]
        _, contract, dag = _contract_and_plan(prompt, reqs, ["src/test_harness.py"])
        node = next(n for n in dag.nodes.values() if n.target_files)
        self.assertEqual(node.file_role, "SOURCE")
        self.assertEqual(contract.components[0].role, "SOURCE")

    def test_test_file_without_conventional_name_is_test(self) -> None:
        prompt = "Create src/a.py with f(). Add pytest tests in tests/checks_a.py."
        reqs = [req("REQ-1", "Create src/a.py with f()."), req("REQ-2", "Add pytest tests in tests/checks_a.py.")]
        _, contract, dag = _contract_and_plan(prompt, reqs, ["src/a.py", "tests/checks_a.py"])
        test_component = next(c for c in contract.components if c.target_file == "tests/checks_a.py")
        self.assertEqual(test_component.role, "TEST")
        self.assertIn("REQ-2", test_component.requirement_ids)

    def test_test_directory_is_authoritative(self) -> None:
        self.assertEqual(detect_file_role("spec/duration_spec.py"), FileRole.TEST)
        self.assertEqual(detect_file_role("__tests__/a.js"), FileRole.TEST)
        self.assertEqual(detect_file_role("README.md"), FileRole.DOCUMENTATION)

    def test_one_sentence_naming_source_and_test_maps_both(self) -> None:
        prompt = "Implement src/a.py and tests/test_a.py with f()."
        reqs = [req("REQ-1", prompt)]
        _, contract, dag = _contract_and_plan(prompt, reqs, ["src/a.py", "tests/test_a.py"])
        targets = {c.target_file: c.role for c in contract.components}
        self.assertEqual(targets, {"src/a.py": "SOURCE", "tests/test_a.py": "TEST"})
        self.assertEqual(sorted(contract.requirement_map["REQ-1"]), ["src/a.py", "tests/test_a.py"])
        self.assertEqual(len([n for n in dag.nodes.values() if n.target_files]), 2)

    def test_multiple_sources_and_tests_pair_by_stem(self) -> None:
        prompt = "Create src/a.py, src/b.py, tests/test_a.py, tests/test_b.py."
        reqs = [
            req("REQ-1", "Create src/a.py."), req("REQ-2", "Create src/b.py."),
            req("REQ-3", "Add tests/test_a.py."), req("REQ-4", "Add tests/test_b.py."),
        ]
        _, contract, dag = _contract_and_plan(prompt, reqs, ["src/a.py", "src/b.py", "tests/test_a.py", "tests/test_b.py"])
        self.assertEqual(len([n for n in dag.nodes.values() if n.target_files]), 4)

    def test_test_requirement_is_not_absorbed_into_source(self) -> None:
        prompt = "Create src/a.py with f(). Add tests/test_a.py."
        reqs = [req("REQ-1", "Create src/a.py with f()."), req("REQ-2", "Add tests/test_a.py.")]
        _, _, dag = _contract_and_plan(prompt, reqs, ["src/a.py", "tests/test_a.py"])
        source = next(n for n in dag.nodes.values() if n.target_files == ["src/a.py"])
        test = next(n for n in dag.nodes.values() if n.target_files == ["tests/test_a.py"])
        self.assertNotIn("REQ-2", source.related_requirement_ids)
        self.assertIn("REQ-2", test.related_requirement_ids)

    def test_duplicate_requirement_ids_are_not_lost(self) -> None:
        prompt = "Create src/a.py with f(). Add tests/test_a.py."
        reqs = [req("REQ-1", "Create src/a.py with f()."), req("REQ-1", "Add tests/test_a.py.")]
        _, contract, dag = _contract_and_plan(prompt, reqs, ["src/a.py", "tests/test_a.py"])
        planned = {rid for n in dag.nodes.values() for rid in n.related_requirement_ids}
        self.assertIn("REQ-1", planned)
        self.assertEqual(len(planned), 1)

    def test_unknown_user_file_is_rejected(self) -> None:
        prompt = "Create assets/data.xyz."
        reqs = [req("REQ-1", prompt)]
        contract = extract_contract(prompt, reqs, ["assets/data.xyz"], task_id="u", workspace=_ws())
        self.assertTrue(any("unknown" in a.lower() or "role" in a.lower() for a in contract.ambiguities))

    def test_budget_exceeded_is_refused_before_dispatch(self) -> None:
        prompt = "Create src/a.py and tests/test_a.py."
        reqs = [req("REQ-1", "Create src/a.py."), req("REQ-2", "Add tests/test_a.py.")]
        contract = extract_contract(prompt, reqs, ["src/a.py", "tests/test_a.py"],
                                    task_id="b", workspace=_ws())
        with self.assertRaises(PlanBudgetExceeded):
            EngineeringTaskPlanner(".").build_plan(
                "b", _spec(reqs), requested_files=["src/a.py", "tests/test_a.py"],
                task_prompt=prompt, max_nodes=1, contract=contract,
            )


# --------------------------------------------------------------------------- #
# plan validation
# --------------------------------------------------------------------------- #

class TestPlanValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = EngineeringContract(
            task_id="v", prompt_sha256="x",
            components=[
                ContractComponent(component_id="C1", name="a", responsibility="",
                                  target_file="src/a.py", role="SOURCE",
                                  requirement_ids=["REQ-1"]),
                ContractComponent(component_id="C2", name="test_a", responsibility="",
                                  target_file="tests/test_a.py", role="TEST",
                                  requirement_ids=["REQ-2"]),
            ],
            requirement_map={"REQ-1": ["src/a.py"], "REQ-2": ["tests/test_a.py"]},
        )

    def _dag(self, nodes):
        dag = EngineeringPlanDAG(task_id="v")
        for node in nodes:
            dag.add_node(node)
        return dag

    def test_clean_plan_passes(self) -> None:
        dag = self._dag([
            EngineeringTaskNode(node_id="a", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=["REQ-1"],
                                file_role="SOURCE"),
            EngineeringTaskNode(node_id="t", description="", objective="",
                                target_files=["tests/test_a.py"], related_requirement_ids=["REQ-2"],
                                file_role="TEST"),
        ])
        report = validate_contract_plan(
            self.contract, dag, max_dispatches=5,
            requested_files=["src/a.py", "tests/test_a.py"],
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["work_units"], 2)
        self.assertEqual(report["demand"], 2)

    def test_missing_requirement_assignment_is_rejected(self) -> None:
        dag = self._dag([
            EngineeringTaskNode(node_id="a", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=[],
                                file_role="SOURCE"),
        ])
        with self.assertRaises(PlanValidationError) as ctx:
            validate_contract_plan(self.contract, dag, max_dispatches=5,
                                   requested_files=["src/a.py", "tests/test_a.py"])
        self.assertTrue(any("REQ-1" in r for r in ctx.exception.reasons))
        self.assertTrue(any("REQ-2" in r for r in ctx.exception.reasons))

    def test_duplicate_work_unit_is_rejected(self) -> None:
        dag = self._dag([
            EngineeringTaskNode(node_id="a1", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=["REQ-1"]),
            EngineeringTaskNode(node_id="a2", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=["REQ-1"]),
        ])
        with self.assertRaises(PlanValidationError) as ctx:
            validate_contract_plan(self.contract, dag, max_dispatches=5)
        self.assertTrue(any("duplicate" in r.lower() for r in ctx.exception.reasons))

    def test_role_conflict_is_rejected(self) -> None:
        dag = self._dag([
            EngineeringTaskNode(node_id="a", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=["REQ-1"],
                                file_role="TEST"),
        ])
        with self.assertRaises(PlanValidationError) as ctx:
            validate_contract_plan(self.contract, dag, max_dispatches=5)
        self.assertTrue(any("conflict" in r.lower() for r in ctx.exception.reasons))

    def test_lost_requirement_is_rejected(self) -> None:
        dag = self._dag([
            EngineeringTaskNode(node_id="a", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=["REQ-1"]),
        ])
        with self.assertRaises(PlanValidationError) as ctx:
            validate_contract_plan(self.contract, dag, max_dispatches=5)
        self.assertTrue(any("REQ-2" in r for r in ctx.exception.reasons))

    def test_demand_over_capacity_is_rejected(self) -> None:
        dag = self._dag([
            EngineeringTaskNode(node_id="a", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=["REQ-1"]),
            EngineeringTaskNode(node_id="t", description="", objective="",
                                target_files=["tests/test_a.py"], related_requirement_ids=["REQ-2"]),
        ])
        with self.assertRaises(PlanValidationError) as ctx:
            validate_contract_plan(self.contract, dag, max_dispatches=1)
        self.assertTrue(any("capacity" in r for r in ctx.exception.reasons))

    def test_missing_user_file_is_rejected(self) -> None:
        dag = self._dag([
            EngineeringTaskNode(node_id="a", description="", objective="",
                                target_files=["src/a.py"], related_requirement_ids=["REQ-1"]),
        ])
        with self.assertRaises(PlanValidationError) as ctx:
            validate_contract_plan(self.contract, dag, max_dispatches=5,
                                   requested_files=["tests/test_a.py"])
        self.assertTrue(any("tests/test_a.py" in r for r in ctx.exception.reasons))


# --------------------------------------------------------------------------- #
# cross-file consistency
# --------------------------------------------------------------------------- #

GOOD_SOURCE = '''def slugify(text: str) -> str:
    """Slugify."""
    return text.lower().strip()
'''
GOOD_TEST = '''from src.mod import slugify


def test_basic():
    assert slugify("A") == "a"
'''


class TestCrossFile(unittest.TestCase):
    def _contract(self, **overrides) -> EngineeringContract:
        component = ContractComponent(
            component_id="C1", name="mod", responsibility="", target_file="src/mod.py",
            role="SOURCE", requirement_ids=["REQ-1"], symbols=["slugify"],
            signatures={"slugify": ["text"]}, returns="str",
        )
        for key, value in overrides.items():
            setattr(component, key, value)
        test = ContractComponent(
            component_id="C2", name="test_mod", responsibility="",
            target_file="tests/test_mod.py", role="TEST", requirement_ids=["REQ-2"],
            imports=[{"module": "src.mod", "symbols": ["slugify"]}],
        )
        return EngineeringContract(task_id="x", prompt_sha256="y", components=[component, test])

    def _run(self, source: str, test: str, **overrides):
        ws = _ws({"src/mod.py": source, "tests/test_mod.py": test})
        try:
            return validate_cross_file(ws, self._contract(**overrides), ["src/mod.py", "tests/test_mod.py"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_clean_files_pass(self) -> None:
        report = self._run(GOOD_SOURCE, GOOD_TEST)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["method"], "static_ast")

    def test_wrong_import_path_is_detected(self) -> None:
        report = self._run(GOOD_SOURCE, "from mod import slugify\n\ndef test_x():\n    assert slugify('A') == 'a'\n")
        self.assertFalse(report["ok"])
        self.assertIn("wrong_import_path", [e["code"] for e in report["errors"]])

    def test_missing_symbol_is_detected(self) -> None:
        report = self._run(GOOD_SOURCE, "from src.mod import slugify, exactly\n\ndef test_x():\n    assert slugify('A') == 'a'\n")
        self.assertIn("missing_imported_symbol", [e["code"] for e in report["errors"]])

    def test_signature_mismatch_is_detected(self) -> None:
        report = self._run(GOOD_SOURCE.replace("def slugify(text: str)", "def slugify(value: str)"), GOOD_TEST)
        self.assertIn("signature_mismatch", [e["code"] for e in report["errors"]])

    def test_return_type_mismatch_is_detected(self) -> None:
        source = "from datetime import timedelta\n\ndef slugify(text: str) -> timedelta:\n    return timedelta(0)\n"
        report = self._run(source, GOOD_TEST, returns="int")
        codes = [e["code"] for e in report["errors"]]
        self.assertIn("return_type_mismatch", codes)
        self.assertIn("return_contract_violation", codes)

    def test_extra_public_api_is_detected(self) -> None:
        source = GOOD_SOURCE + "\n\ndef extra():\n    return 1\n"
        report = self._run(source, GOOD_TEST, forbidden=["exactly one public function"])
        self.assertIn("extra_public_api", [e["code"] for e in report["errors"]])

    def test_forbidden_float_is_detected(self) -> None:
        source = GOOD_SOURCE.replace("return text.lower().strip()", "return float(len(text))")
        report = self._run(source, GOOD_TEST, forbidden=["Do not accept floats"])
        self.assertIn("forbidden_float", [e["code"] for e in report["errors"]])

    def test_unparseable_test_is_detected(self) -> None:
        report = self._run(GOOD_SOURCE, "def test_broken(:\n    pass\n")
        self.assertIn("test_unparseable", [e["code"] for e in report["errors"]])

    def test_wrong_symbol_fix_contract_regression(self) -> None:
        source = "def is_valid_email(value: str) -> bool:\n    return True\n"
        report = self._run(source, "from src.mod import is_valid_email\n\ndef test_x():\n    assert is_valid_email('a') is True\n",
                           symbols=["validate_email"], signatures={"validate_email": ["address"]}, returns="bool")
        codes = [e["code"] for e in report["errors"]]
        self.assertIn("missing_symbol", codes)


# --------------------------------------------------------------------------- #
# test repair integrity
# --------------------------------------------------------------------------- #

class TestRepairIntegrity(unittest.TestCase):
    def test_inventory_counts_functions_asserts_and_raises(self) -> None:
        inventory = build_test_inventory(
            "import pytest\n\ndef test_a():\n    assert 1 == 1\n    with pytest.raises(ValueError):\n        raise ValueError\n"
        )
        self.assertIn("test_a", inventory["test_functions"])
        self.assertEqual(inventory["test_functions"]["test_a"]["asserts"], 1)
        self.assertGreaterEqual(inventory["test_functions"]["test_a"]["raises"], 1)

    def test_import_only_repair_preserves_all_tests(self) -> None:
        before = "from mod import slugify\n\ndef test_a():\n    assert slugify('A') == 'a'\n"
        after = "from src.mod import slugify\n\ndef test_a():\n    assert slugify('A') == 'a'\n"
        self.assertEqual(audit_test_repair(before, after), [])

    def test_removing_a_test_is_rejected(self) -> None:
        before = "def test_a():\n    assert 1\n\ndef test_b():\n    assert 2\n"
        after = "def test_a():\n    assert 1\n"
        self.assertTrue(any("removed" in v for v in audit_test_repair(before, after)))

    def test_reducing_assertions_is_rejected(self) -> None:
        before = "def test_a():\n    assert 1\n    assert 2\n"
        after = "def test_a():\n    assert 1\n"
        self.assertTrue(any("assertions reduced" in v for v in audit_test_repair(before, after)))

    def test_skip_is_rejected(self) -> None:
        before = "def test_a():\n    assert 1\n"
        after = "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert 1\n"
        self.assertTrue(any("skip" in v for v in audit_test_repair(before, after)))

    def test_parameter_change_is_rejected(self) -> None:
        before = "def test_a():\n    assert 1\n"
        after = "def test_a(extra):\n    assert 1\n"
        self.assertTrue(any("parameters" in v for v in audit_test_repair(before, after)))

    def test_import_rewrite_removes_invented_symbol_safely(self) -> None:
        ws = _ws({
            "src/mod.py": "def slugify(text: str) -> str:\n    return text\n",
            "tests/test_mod.py": "from mod import slugify, exactly\n\ndef test_a():\n    assert slugify('A') == 'A'\n",
        })
        try:
            contract = EngineeringContract(
                task_id="r", prompt_sha256="x",
                components=[ContractComponent(
                    component_id="C1", name="mod", responsibility="",
                    target_file="src/mod.py", role="SOURCE", requirement_ids=["REQ-1"],
                    symbols=["slugify"], signatures={"slugify": ["text"]}, returns="str",
                )],
            )
            changed, updated, notes = repair_test_imports(ws, "tests/test_mod.py", contract)
            self.assertTrue(changed, notes)
            self.assertIn("from src.mod import slugify", updated)
            self.assertNotIn("exactly", updated)
            self.assertEqual(audit_test_repair(
                (Path(ws) / "tests/test_mod.py").read_text(encoding="utf-8"), updated), [])
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# --------------------------------------------------------------------------- #
# exact historical lifecycle (scripted provider, no network)
# --------------------------------------------------------------------------- #

BAD_MODULE = '''from datetime import timedelta
import re

exactly = "exactly"


def parse_duration(value):
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value.strip():
        raise ValueError("empty duration")
    total = 0.0
    for number, unit in re.findall(r"(\\d+(?:\\.\\d+)?)\\s*([a-z]+)", value):
        if unit in {"h", "hour", "hours"}:
            total += float(number) * 3600
        elif unit in {"m", "min", "minutes"}:
            total += float(number) * 60
        elif unit in {"s", "sec", "seconds"}:
            total += float(number)
        else:
            raise ValueError("unknown unit")
    return timedelta(seconds=total)
'''

BAD_TEST = '''import pytest
from duration import parse_duration, exactly


def test_basic():
    assert parse_duration("1h30m").total_seconds() == 5400


def test_spaces():
    assert parse_duration("2m 15s").total_seconds() == 135


def test_trimmed():
    assert parse_duration("1h 30m 15s").total_seconds() == 5415


def test_duplicate_raises():
    with pytest.raises(ValueError):
        parse_duration("1h1h")


def test_negative_raises():
    with pytest.raises(ValueError):
        parse_duration("-1h")


def test_non_string_raises():
    with pytest.raises(TypeError):
        parse_duration(42)
'''

FIXED_TEST = '''import pytest
from src.duration import parse_duration


def test_basic():
    assert parse_duration("1h30m") == 5400


def test_spaces():
    assert parse_duration("2m 15s") == 135


def test_trimmed():
    assert parse_duration("1h 30m 15s") == 5415


def test_duplicate_raises():
    with pytest.raises(ValueError):
        parse_duration("1h1h")


def test_negative_raises():
    with pytest.raises(ValueError):
        parse_duration("-1h")


def test_non_string_raises():
    with pytest.raises(TypeError):
        parse_duration(42)
'''

FIXED_MODULE = '''from __future__ import annotations
import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_COMPONENT = re.compile(r"(\\d+)([hms])")


def parse_duration(value: str) -> int:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value.strip():
        raise ValueError("empty duration")
    if "-" in value:
        raise ValueError("negative durations are not allowed")
    if "." in value:
        raise ValueError("floats are not accepted")
    compact = value.replace(" ", "")
    units = re.findall(r"([hms])", compact)
    if len(units) != len(set(units)):
        raise ValueError("duplicate units are not allowed")
    position = 0
    total = 0
    for match in _COMPONENT.finditer(compact):
        if match.start() != position:
            raise ValueError("missing number or unknown unit")
        total += int(match.group(1)) * _UNITS[match.group(2)]
        position = match.end()
    if position != len(compact):
        raise ValueError("unknown unit or missing number")
    return total
'''


class HistoricalLLM:
    def __init__(self, *, repairing: bool = True):
        self.prompts: list[str] = []
        self.repairing = repairing
        self._max_attempts = 1

    def invoke(self, prompt: str, **kwargs):
        self.prompts.append(prompt)
        target = ""
        for line in prompt.splitlines():
            if line.startswith("Target file"):
                target = line.split(":", 1)[1].strip()
                break
        if "repairing an existing file" in prompt.lower():
            if not self.repairing:
                content = BAD_MODULE if target.endswith("duration.py") else BAD_TEST
            elif target.endswith("test_duration.py"):
                content = FIXED_TEST
            else:
                content = FIXED_MODULE
        elif target.endswith("test_duration.py"):
            content = BAD_TEST
        else:
            content = BAD_MODULE
        return type("Resp", (), {
            "content": f"```python\n{content}\n```",
            "usage_metadata": {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
            "response_metadata": {"finish_reason": "stop"},
        })()


def _run_historical(ws: Path, llm: HistoricalLLM, *, attempts: int = 2):
    original = ma.get_llm
    ma.get_llm = lambda provider=None, model=None: llm
    try:
        orch = EngineeringExecutionOrchestrator(
            str(ws), tenant_id="p0_6_8",
            limits=ExecutionLimits(max_cost_inr=5.0, max_dispatch_budget=5,
                                   max_correction_attempts=attempts, test_timeout_seconds=120.0),
            mock_mode=False, provider="groq", model="qwen/qwen3.6-27b",
        )
        return orch, orch.run_task(task_prompt=LIVE7_PROMPT, task_id="task_p0_6_8")
    finally:
        ma.get_llm = original


def _git_ws() -> Path:
    ws = _ws({"README.md": "# ws\n"})
    subprocess.run(["git", "init", "-q"], cwd=ws, check=False)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=ws, check=False)
    subprocess.run(["git", "config", "user.name", "a"], cwd=ws, check=False)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=False)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=ws, check=False)
    return ws


class TestExactHistoricalLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _git_ws()

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_historical_failure_is_diagnosed_and_repaired(self) -> None:
        llm = HistoricalLLM()
        orch, delivery = _run_historical(self.ws, llm)
        self.assertEqual(delivery.verdict.value, "COMPLETED", delivery.remaining_limitations)
        self.assertTrue(delivery.independently_verified)
        self.assertEqual(len(llm.prompts), 4, "2 implementation + 2 evidence-backed repairs")
        self.assertEqual(delivery.contract["prompt_sha256"], LIVE7_SHA)
        self.assertEqual(
            [(c["role"], c["target_file"]) for c in delivery.contract["components"]],
            [("SOURCE", "src/duration.py"), ("TEST", "tests/test_duration.py")],
        )
        self.assertEqual(delivery.contract["requirement_map"]["REQ-003"], ["tests/test_duration.py"])
        final = delivery.test_evidence["final_run"]
        self.assertEqual(final["failed"], 0)
        self.assertEqual(final["passed"], 6)
        self.assertTrue(delivery.cross_file_validation["ok"])
        self.assertIn("parse_duration", (self.ws / "src" / "duration.py").read_text(encoding="utf-8"))
        journal = list(self.ws.rglob("orchestration_journal.jsonl"))[0]
        events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
        kinds = [e["event_type"] for e in events]
        for event in ("CONTRACT_EXTRACTED", "FILES_ASSIGNED", "PLAN_VALIDATED",
                      "CROSS_FILE_VALIDATED", "TEST_REPAIR_APPLIED"):
            self.assertIn(event, kinds)
        mechanical = [e for e in events if e["event_type"] == "TEST_REPAIR_APPLIED"]
        self.assertEqual(mechanical[0]["details"]["dispatch"], False)
        fin = orch._last_finops
        self.assertEqual(fin.accounting.calls_count, 4)
        self.assertEqual(len(fin._settled_reservations), 4)
        self.assertEqual(len(fin._active_reservations), 0)
        self.assertEqual(len(fin._uncertain_reservations), 0)

    def test_tests_pass_but_contract_violation_blocks_completion(self) -> None:
        llm = HistoricalLLM(repairing=False)
        orch, delivery = _run_historical(self.ws, llm, attempts=0)
        self.assertEqual(delivery.verdict.value, "FAILED")
        self.assertFalse(delivery.independently_verified)
        self.assertTrue(any("cross-file" in lim.lower() for lim in delivery.remaining_limitations))
        self.assertEqual(orch._last_finops.accounting.calls_count, 2)


class TestAcceptanceIsolation(unittest.TestCase):
    """P0.6.8 live finding: auxiliary calls must not claim acceptance dispatches."""

    def test_acceptance_env_no_longer_disables_autotitle(self) -> None:
        from benchmarks.crusor_desktop_acceptance.live_turn import build_acceptance_env

        env = build_acceptance_env(run_id="r", evidence_dir=Path(tempfile.mkdtemp()))
        self.assertNotEqual(env.get("CRUSORAI_AUTOTITLE", ""), "off")

    def test_bridge_allows_governed_auxiliary_llm_in_acceptance(self) -> None:
        from unittest.mock import patch

        from src.bridge.__main__ import BridgeServer

        server = object.__new__(BridgeServer)
        with patch.dict(os.environ, {"CRUSORAI_ACCEPTANCE_RUN_ID": "run",
                                     "CRUSORAI_AUTOTITLE": ""}, clear=False):
            self.assertTrue(server._auxiliary_llm_allowed())
        with patch.dict(os.environ, {"CRUSORAI_ACCEPTANCE_RUN_ID": "run",
                                     "CRUSORAI_AUTOTITLE": "off"}, clear=False):
            self.assertFalse(server._auxiliary_llm_allowed())


if __name__ == "__main__":
    unittest.main()

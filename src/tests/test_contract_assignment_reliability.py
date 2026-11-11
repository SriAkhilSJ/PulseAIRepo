"""Requirement-to-file assignment reliability (Phase 3.2).

Pins the contract-first pipeline: role-correct synthesis for CONFIG/DOC/BUILD,
user-file precedence, optional exclusion, traceability through planning, no
duplicate work units and dispatch-budget enforcement. Provider-free.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.intelligence.requirement_models import (
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
    RequirementPriority,
    RequirementStatus,
)
from src.orchestration.contract import (
    FileRole,
    PlanValidationError,
    detect_file_role,
    extract_contract,
    requirement_intent,
    validate_contract_plan,
)
from src.orchestration.models import EngineeringPlanDAG
from src.orchestration.planner import EngineeringTaskPlanner


def _req(
    rid: str,
    description: str,
    classification: RequirementClassification = RequirementClassification.EXPLICIT,
) -> RequirementItem:
    return RequirementItem(
        id=rid,
        description=description,
        category=RequirementCategory.FUNCTIONAL,
        classification=classification,
        priority=RequirementPriority.HIGH,
        status=RequirementStatus.ACCEPTED,
        evidence_source=f'User stated: "{description}"',
        acceptance_criteria=[f"Verified: {description}"],
    )


def _contract(tmp_path: Path, prompt: str, requirements, requested=(), task_id="t"):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return extract_contract(
        prompt, requirements, list(requested), task_id=task_id, workspace=str(ws)
    )


def _plan(contract, prompt: str = "task", max_nodes=None):
    planner = EngineeringTaskPlanner(str(Path(contract.task_id) if False else "."))
    dag = EngineeringPlanDAG(task_id=contract.task_id)
    return planner._build_contract_plan(
        dag, contract, task_prompt=prompt, blueprint=None,
        impact_report=None, max_nodes=max_nodes,
    )


def test_source_requirement_without_path_gets_source_target(tmp_path: Path) -> None:
    contract = _contract(tmp_path, "Build a widget", [_req("REQ-001", "Implement widget service")])
    assert contract.requirement_map == {"REQ-001": ["src/req_001_module.py"]}
    component = contract.component_for("src/req_001_module.py")
    assert component.role == FileRole.SOURCE.value


def test_test_requirement_without_path_gets_test_target(tmp_path: Path) -> None:
    contract = _contract(tmp_path, "Add tests", [_req("REQ-001", "Add unit tests for the service")])
    assert contract.requirement_map == {"REQ-001": ["tests/test_req_001.py"]}
    assert contract.component_for("tests/test_req_001.py").role == FileRole.TEST.value


def test_config_requirement_in_new_workspace(tmp_path: Path) -> None:
    contract = _contract(tmp_path, "Configure", [_req("REQ-001", "Add application configuration file")])
    assert contract.requirement_map == {"REQ-001": ["config/req_001.yaml"]}
    assert detect_file_role("config/req_001.yaml") == FileRole.CONFIGURATION


def test_doc_requirement_in_new_workspace(tmp_path: Path) -> None:
    contract = _contract(tmp_path, "Document", [_req("REQ-001", "Write documentation for the API")])
    assert contract.requirement_map == {"REQ-001": ["docs/req_001.md"]}
    assert detect_file_role("docs/req_001.md") == FileRole.DOCUMENTATION


def test_build_requirement_in_new_workspace(tmp_path: Path) -> None:
    contract = _contract(tmp_path, "Add build", [_req("REQ-001", "Add a build system script")])
    assert contract.requirement_map == {"REQ-001": ["build/req_001.py"]}
    assert detect_file_role("build/req_001.py") == FileRole.BUILD


def test_product_language_is_not_a_build_file_requirement() -> None:
    # The Phase 11.6 REQ-001 root cause: "build an app" is a product request.
    assert requirement_intent("Build an online marketplace for my pottery business") == FileRole.SOURCE
    assert requirement_intent("Add a build system script") == FileRole.BUILD


def test_multiple_requirements_share_one_appropriate_target(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        "Update app.py",
        [
            _req("REQ-001", "Implement the primary flow"),
            _req("REQ-002", "Handle errors in the primary flow"),
        ],
        requested=["src/app.py"],
    )
    assert contract.requirement_map == {
        "REQ-001": ["src/app.py"], "REQ-002": ["src/app.py"],
    }
    plan = _plan(contract)
    work = [n for n in plan.nodes.values() if n.node_id != "task_verification"]
    assert len(work) == 1
    node = work[0]
    assert node.related_requirement_ids == ["REQ-001", "REQ-002"]
    validate_contract_plan(contract, plan, max_dispatches=None, requested_files=["src/app.py"])


def test_explicit_source_and_test_files_are_mapped_by_role(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        "Add feature",
        [_req("REQ-001", "Implement feature in src/app.py and test it in tests/test_app.py")],
    )
    assert set(contract.requirement_map["REQ-001"]) == {"src/app.py", "tests/test_app.py"}
    assert contract.component_for("src/app.py").role == FileRole.SOURCE.value
    assert contract.component_for("tests/test_app.py").role == FileRole.TEST.value


def test_user_named_file_stays_authoritative(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        "Update custom module",
        [_req("REQ-001", "Implement the custom module")],
        requested=["lib/custom.py"],
    )
    assert contract.requirement_map == {"REQ-001": ["lib/custom.py"]}


def test_optional_suggestions_do_not_become_work(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        "Add feature",
        [
            _req("REQ-001", "Implement the feature"),
            _req("REQ-002", "Nice-to-have extra", RequirementClassification.REASONABLE_DEFAULT),
        ],
    )
    assert "REQ-002" not in contract.requirement_map
    assert [s["id"] for s in contract.optional_suggestions] == ["REQ-002"]


def test_empty_description_remains_ambiguous_and_blocks(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        "Do it",
        [_req("REQ-001", "Implement the feature"), _req("REQ-002", "")],
    )
    assert any("REQ-002" in a and "no description" in a for a in contract.ambiguities)
    plan = _plan(contract)
    with pytest.raises(PlanValidationError):
        validate_contract_plan(contract, plan, max_dispatches=None)


def test_no_duplicate_target_work_units(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        "Update app.py",
        [_req("REQ-001", "Implement flow"), _req("REQ-002", "Harden flow")],
        requested=["src/app.py"],
    )
    plan = _plan(contract)
    targets = [f for n in plan.nodes.values() for f in n.target_files]
    assert targets.count("src/app.py") == 1
    validate_contract_plan(contract, plan, max_dispatches=None, requested_files=["src/app.py"])


def test_dispatch_budget_is_still_enforced(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        "Two files",
        [
            _req("REQ-001", "Implement source module"),
            _req("REQ-002", "Add tests for the module"),
        ],
    )
    plan = _plan(contract)
    with pytest.raises(PlanValidationError):
        validate_contract_plan(contract, plan, max_dispatches=1)


def test_contract_hash_is_deterministic(tmp_path: Path) -> None:
    reqs = [_req("REQ-001", "Implement the feature")]
    first = _contract(tmp_path, "Add feature", reqs)
    second = _contract(tmp_path, "Add feature", reqs)
    assert first.contract_hash == second.contract_hash

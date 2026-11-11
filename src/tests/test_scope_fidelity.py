"""Scope-fidelity contract tests (product qualification).

Pins that an explicit user-named file is the requirement target, that a
documentation request does not synthesize a source module, and that genuine
source tasks still receive source targets. Provider-free.
"""
from __future__ import annotations

from pathlib import Path

from src.intelligence.requirement_models import (
    RequirementCategory,
    RequirementClassification,
    RequirementItem,
    RequirementPriority,
    RequirementStatus,
)
from src.orchestration.contract import extract_contract
from src.orchestration.models import EngineeringPlanDAG
from src.orchestration.planner import EngineeringTaskPlanner
from src.intelligence.requirement_extractor import RequirementExtractor
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator


def _req(rid: str, description: str) -> RequirementItem:
    return RequirementItem(
        id=rid,
        description=description,
        category=RequirementCategory.FUNCTIONAL,
        classification=RequirementClassification.EXPLICIT,
        priority=RequirementPriority.HIGH,
        status=RequirementStatus.ACCEPTED,
        evidence_source=f'User stated: "{description}"',
        acceptance_criteria=[f"Verified: {description}"],
    )


def _contract(tmp_path: Path, prompt: str, requirements, requested=()):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return extract_contract(
        prompt, requirements, list(requested), task_id="scope-test", workspace=str(ws)
    )


def _planned_targets(contract) -> set[str]:
    planner = EngineeringTaskPlanner(".")
    dag = EngineeringPlanDAG(task_id=contract.task_id)
    plan = planner._build_contract_plan(
        dag, contract, task_prompt="task",
        blueprint=None, impact_report=None, max_nodes=None,
    )
    return {
        target
        for node in plan.nodes.values()
        if node.node_id != "task_verification"
        for target in (node.target_files or [])
    }


def test_create_final_md_is_one_documentation_file(tmp_path: Path) -> None:
    prompt = "Create final.md with a short greeting for the project."
    contract = _contract(tmp_path, prompt, [_req("REQ-001", prompt)], requested=["final.md"])
    assert [c.target_file for c in contract.components] == ["final.md"]
    assert contract.requirement_map == {"REQ-001": ["final.md"]}
    assert "src/req_001_module.py" not in {c.target_file for c in contract.components}
    assert _planned_targets(contract) == {"final.md"}


def test_create_readme_is_one_documentation_file(tmp_path: Path) -> None:
    prompt = "Create README.md describing this project."
    contract = _contract(tmp_path, prompt, [_req("REQ-001", prompt)], requested=["README.md"])
    assert [c.target_file for c in contract.components] == ["README.md"]
    assert _planned_targets(contract) == {"README.md"}


def test_python_calculator_gets_source_implementation(tmp_path: Path) -> None:
    prompt = "Build a Python calculator application."
    contract = _contract(
        tmp_path, prompt, [_req("REQ-001", "Implement a Python calculator application")],
        requested=["src/calculator.py"],
    )
    assert contract.requirement_map == {"REQ-001": ["src/calculator.py"]}
    assert _planned_targets(contract) == {"src/calculator.py"}


def test_docs_and_python_implementation_are_both_kept(tmp_path: Path) -> None:
    prompt = "Create docs/guide.md and add the Python implementation in src/app.py."
    contract = _contract(
        tmp_path,
        prompt,
        [
            _req("REQ-001", "Create docs/guide.md with usage documentation"),
            _req("REQ-002", "Implement the Python application in src/app.py"),
        ],
        requested=["docs/guide.md", "src/app.py"],
    )
    assert contract.requirement_map["REQ-001"] == ["docs/guide.md"]
    assert contract.requirement_map["REQ-002"] == ["src/app.py"]
    assert _planned_targets(contract) == {"docs/guide.md", "src/app.py"}


def test_negative_prohibition_is_not_an_artifact_requirement(tmp_path: Path) -> None:
    prompt = (
        "Create exactly one file named hello.md containing a short greeting for "
        "the Crusor project. Do not create source-code files, tests or any other artifacts."
    )
    bundle = RequirementExtractor().extract(prompt)
    descriptions = [r.description.lower() for r in bundle.requirements]
    assert any("hello.md" in d for d in descriptions)
    assert not any(d.startswith("do not") for d in descriptions)
    contract = _contract(tmp_path, prompt, bundle.requirements, requested=["hello.md"])
    assert [c.target_file for c in contract.components] == ["hello.md"]
    assert _planned_targets(contract) == {"hello.md"}


def test_documentation_only_task_does_not_require_tests() -> None:
    class _Discovery:
        files: list = []
        reason = "no tests discovered"

    dag = EngineeringPlanDAG(task_id="t")
    assert EngineeringExecutionOrchestrator._testing_required(
        "Create hello.md. Do not create tests or other artifacts.", _Discovery(), dag
    ) is False
    assert EngineeringExecutionOrchestrator._testing_required(
        "Create hello.md and write tests for it.", _Discovery(), dag
    ) is True


def test_auth_bug_fix_stays_on_relevant_implementation(tmp_path: Path) -> None:
    prompt = "Fix the existing authentication bug in src/auth.py."
    contract = _contract(
        tmp_path,
        prompt,
        [_req("REQ-001", "Fix the existing authentication bug in src/auth.py")],
        requested=["src/auth.py", "tests/test_auth.py"],
    )
    assert contract.requirement_map == {"REQ-001": ["src/auth.py"]}
    targets = _planned_targets(contract)
    assert "src/auth.py" in targets
    assert "src/req_001_module.py" not in targets

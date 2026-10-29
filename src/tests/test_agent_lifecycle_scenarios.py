"""End-to-End Agent Lifecycle Integration Scenarios for CrusorAI 2.0.

Validates the full interactive lifecycle across all 5 user scenarios + terminal mutation + provider failure:
1. Edit file after test pass -> verification becomes stale.
2. Edit file again -> verification remains stale until rerun.
3. Mandatory test failure -> completion blocked even if model claims done.
4. Optional diagnostic failure -> recorded in diagnostics without failing verified app.
5. Safety denial / budget exhaustion -> preserves execution outcome & verification status independently.
6. Terminal command mutation (redirects, npm, touch) -> increments revision & invalidates receipts.
7. Safeguarded 'not_required' -> model cannot claim not_required when code deliverables exist.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage

from src.runtime.workspace_controller import WorkspaceController
from src.runtime.verification_contracts import VerificationContractEngine
from src.runtime.status_contract import (
    synthesize_status_contract,
    derive_legacy_completed,
    safeguard_verification_status,
)
from src.graphs.chat_graph import finalize_node


# ---------------------------------------------------------------------------
# Scenario 1 & 2: Stale Verification Invalidation & Repeated Edits
# ---------------------------------------------------------------------------

def test_scenario_1_edit_file_after_tests_pass_becomes_stale():
    controller = WorkspaceController()
    # Initial write & pass
    controller.record_mutation("backend/app.py", "write_file")
    controller.record_verification("backend-tests", passed=True)
    assert controller.get_effective_verification_status() == "verified"

    # Edit file after tests pass -> STALE
    controller.record_mutation("backend/app.py", "edit_file")
    assert controller.is_receipt_stale("backend-tests") is True
    assert controller.get_effective_verification_status() == "stale"


def test_scenario_2_repeated_edits_remain_stale_until_rerun():
    controller = WorkspaceController()
    controller.record_mutation("backend/app.py", "write_file")
    controller.record_verification("backend-tests", passed=True)

    # Edit 1
    controller.record_mutation("backend/app.py", "edit_file")
    assert controller.get_effective_verification_status() == "stale"

    # Edit 2
    controller.record_mutation("backend/utils.py", "write_file")
    assert controller.get_effective_verification_status() == "stale"

    # Rerun tests -> VERIFIED again
    controller.record_verification("backend-tests", passed=True)
    assert controller.is_receipt_stale("backend-tests") is False
    assert controller.get_effective_verification_status() == "verified"


# ---------------------------------------------------------------------------
# Scenario 3: Mandatory Test Failure Blocks Completion
# ---------------------------------------------------------------------------

def test_scenario_3_mandatory_test_failure_blocks_completion(tmp_path):
    workspace = tmp_path / "app"
    workspace.mkdir()
    (workspace / "server.py").write_text("broken code", encoding="utf-8")

    state = {
        "messages": [
            HumanMessage(content="Build server.py"),
            AIMessage(
                content="",
                tool_calls=[{"name": "terminal", "args": {"command": "python -m unittest"}, "id": "t1"}],
            ),
            # Mandatory test fails!
            ToolMessage(content="FAILED (failures=1)\nExit code: 1", tool_call_id="t1", name="terminal"),
            # Model falsely claims it is completely finished
            AIMessage(content="I have completely finished the task! Everything is done."),
        ],
        "workspace": str(workspace),
        "steps_completed": [],
        "failed_steps": ["python -m unittest: Exit code 1"],
        "workspace_revision": 1,
        "last_verified_revision": None,
    }

    config = {"configurable": {"thread_id": "test_s3", "workspace": str(workspace)}}
    res = finalize_node(state, config)

    # Must be rejected!
    assert res["task_completed"] is False
    assert res["verification_status"] == "failed"
    assert res["run_outcome"] == "failed"
    assert res["status_contract"]["verification_status"] == "failed"


# ---------------------------------------------------------------------------
# Scenario 4: Optional Diagnostic Failure Records Telemetry Without Failing App
# ---------------------------------------------------------------------------

def test_scenario_4_optional_diagnostic_failure_preserves_verified_app(tmp_path):
    engine = VerificationContractEngine(workspace=tmp_path)
    # Mandatory check passes
    engine.add_check({
        "id": "unit-tests",
        "kind": "unit_tests",
        "required": True,
        "timeout_seconds": 10,
        "command": f'"{sys.executable}" -c "print(\'tests passed\')"',
    })
    # Optional diagnostic fails (e.g. non-essential linter or screenshot timeout)
    engine.add_check({
        "id": "ui-screenshot",
        "kind": "diagnostics",
        "required": False,
        "timeout_seconds": 5,
        "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
    })

    report = engine.execute_all()
    assert report["passed"] is True
    assert report["mandatory_passed"] is True
    assert len(report["diagnostics"]) == 1
    assert report["diagnostics"][0]["check_id"] == "ui-screenshot"

    # Synthesize contract: verified app + recorded diagnostic
    contract = synthesize_status_contract(
        run_outcome="completed",
        verification_status="verified",
        specification_status="complete",
        diagnostics=report["diagnostics"],
    )
    assert contract["task_completed"] is True
    assert contract["verification_status"] == "verified"
    assert len(contract["diagnostics"]) == 1


# ---------------------------------------------------------------------------
# Scenario 5: Safety Denial Preserves Verification Status Independently
# ---------------------------------------------------------------------------

def test_scenario_5_safety_denial_preserves_verified_app(tmp_path):
    workspace = tmp_path / "app"
    workspace.mkdir()
    (workspace / "server.py").write_text("print('hello')", encoding="utf-8")

    state = {
        "current_task": "Build server and test it",
        "latest_instruction": "Build server and test it",
        "workspace": str(workspace),
        "messages": [
            HumanMessage(content="Build server and test it"),
            AIMessage(
                content="",
                tool_calls=[{"name": "write_file", "args": {"path": "server.py"}, "id": "w1"}],
            ),
            ToolMessage(content="File written: server.py", tool_call_id="w1", name="write_file"),
            AIMessage(
                content="",
                tool_calls=[{"name": "terminal", "args": {"command": "python -m unittest tests/test_server.py"}, "id": "t1"}],
            ),
            ToolMessage(content="Ran 5 tests in 0.01s\n\nOK\nExit code: 0", tool_call_id="t1", name="terminal"),
            # Trailing safety policy denial on an out-of-bounds command
            AIMessage(
                content="",
                tool_calls=[{"name": "terminal", "args": {"command": "cd C:/Users/Administrator && ls"}, "id": "t2"}],
            ),
            ToolMessage(
                content="Blocked (safety policy): Out-of-bounds path traversal denied. Choose a safe alternative.",
                tool_call_id="t2",
                name="terminal",
            ),
        ],
        "steps_completed": ["wrote server.py", "passed tests"],
        "failed_steps": ["Blocked (safety policy): Out-of-bounds path traversal denied."],
        "plan": [],
        "workspace_revision": 1,
        "last_verified_revision": 1,
    }

    config = {"configurable": {"thread_id": "test_s5", "workspace": str(workspace)}}
    res = finalize_node(state, config)

    # Independent separation: execution failed due to safety, but application verification is preserved!
    assert res["run_outcome"] == "safety_denial"
    assert res["verification_status"] == "verified"
    assert res["specification_status"] in ("complete", "unknown")
    # Execution ended with safety violation, so task_completed is False
    assert res["task_completed"] is False
    assert res["status_contract"]["run_outcome"] == "safety_denial"
    assert res["status_contract"]["verification_status"] == "verified"


# ---------------------------------------------------------------------------
# Scenario 6: Terminal Command Mutations Invalidate Receipts
# ---------------------------------------------------------------------------

def test_scenario_6_terminal_command_mutations_invalidate_receipts():
    controller = WorkspaceController()
    controller.record_mutation("app.py", "write_file")
    controller.record_verification("unit-tests", passed=True)
    assert controller.get_effective_verification_status() == "verified"

    # Terminal mutation (e.g. echo redirect or npm install)
    rev = controller.record_terminal_mutation("echo 'new_secret=1' > .env")
    assert rev is not None
    assert controller.is_receipt_stale("unit-tests") is True
    assert controller.get_effective_verification_status() == "stale"


# ---------------------------------------------------------------------------
# Scenario 7: Safeguard Against False 'not_required' Claim
# ---------------------------------------------------------------------------

def test_scenario_7_safeguard_blocks_false_not_required():
    # If code was produced, 'not_required' is automatically demoted to 'unverified'
    safe = safeguard_verification_status("not_required", code_deliverables_produced=True)
    assert safe == "unverified"

    # If no code was produced, 'not_required' is legitimate
    safe_read_only = safeguard_verification_status("not_required", code_deliverables_produced=False)
    assert safe_read_only == "not_required"


# ---------------------------------------------------------------------------
# Scenario 8: Optional UI Probe Failure After Mandatory Pass Completes Task
# ---------------------------------------------------------------------------

def test_scenario_8_optional_ui_probe_failure_after_mandatory_test_pass_completes_task(tmp_path):
    workspace = tmp_path / "scenario_8"
    workspace.mkdir()
    (workspace / "server.py").write_text("# server code", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_server.py").write_text("# tests", encoding="utf-8")

    state = {
        "current_task": "build an API rate-limiting gateway simulator with SQLite and unit tests",
        "latest_instruction": "build an API rate-limiting gateway simulator with SQLite and unit tests",
        "workspace": str(workspace),
        "messages": [
            HumanMessage(content="build an API rate-limiting gateway simulator with SQLite and unit tests"),
            AIMessage(content="I wrote the files and ran unit tests.", tool_calls=[{"name": "terminal", "id": "tc1", "args": {}}]),
            ToolMessage(
                name="terminal",
                content="Ran 7 tests in 0.5s\n\nOK\nExit code: 0",
                tool_call_id="tc1",
            ),
            # Trailing tool call is an optional UI probe against an unstarted port:
            AIMessage(content="Let me probe UI routes as well.", tool_calls=[{"name": "verify_ui_routes", "id": "tc2", "args": {}}]),
            ToolMessage(
                name="verify_ui_routes",
                content="❌ UI ROUTE VERIFICATION FAILED: server never became ready on port 8124\nStatus: FAILED Exit code: 0",
                tool_call_id="tc2",
            ),
        ],
        "steps_completed": ["Wrote file: server.py", "python -m unittest tests/test_server.py: OK"],
        "failed_steps": [],
        "plan": [],
        "workspace_revision": 1,
        "last_verified_revision": 1,
    }

    config = {"configurable": {"thread_id": "test_s8", "workspace": str(workspace)}}
    res = finalize_node(state, config)

    # Mandatory tests passed, trailing tool was an unmandated exploratory probe:
    # 1. run_outcome must be "completed"
    assert res["run_outcome"] == "completed"
    assert res["status_contract"]["run_outcome"] == "completed"
    # 2. failure_reason must be None
    assert res["failure_reason"] is None
    assert res["status_contract"]["failure_reason"] is None
    # 3. verification_status must be "verified"
    assert res["verification_status"] == "verified"
    # 4. specification_status must be "complete"
    assert res["specification_status"] == "complete"
    # 5. task_completed must be True!
    assert res["task_completed"] is True
    # 6. The optional failure is preserved in diagnostics:
    assert len(res["diagnostics"]) > 0
    assert any(d["tool"] == "verify_ui_routes" for d in res["diagnostics"])

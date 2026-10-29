"""Unit and regression tests for CrusorAI 2.0 Status Contract.

Validates Decision A & Decision B foundational contracts:
1. Independent 3-dimensional outcome contracts (run_outcome, verification_status, specification_status, diagnostics).
2. Derivation of legacy completed boolean.
3. Stale verification detection when workspace_revision > last_verified_revision.
4. Finalize node integration.
"""
from __future__ import annotations

import pytest
from src.runtime.status_contract import (
    derive_legacy_completed,
    synthesize_status_contract,
    RunOutcome,
    VerificationStatus,
    SpecificationStatus,
)
from src.graphs.chat_graph import finalize_node
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage


def test_derive_legacy_completed_strictness():
    # Only completed + verified (or not_required) + complete delivers True
    assert derive_legacy_completed("completed", "verified", "complete") is True
    assert derive_legacy_completed("completed", "not_required", "complete") is True

    # Any unverified or stale state must reject
    assert derive_legacy_completed("completed", "unverified", "complete") is False
    assert derive_legacy_completed("completed", "stale", "complete") is False
    assert derive_legacy_completed("completed", "failed", "complete") is False

    # Partial specification fulfillment must reject
    assert derive_legacy_completed("completed", "verified", "partial") is False
    assert derive_legacy_completed("completed", "verified", "unknown") is False

    # Non-completed run outcome must reject even if code is verified
    assert derive_legacy_completed("failed", "verified", "complete") is False
    assert derive_legacy_completed("safety_denied", "verified", "complete") is False
    assert derive_legacy_completed("budget_exhausted", "verified", "complete") is False
    assert derive_legacy_completed("timed_out", "verified", "complete") is False
    assert derive_legacy_completed("cancelled", "verified", "complete") is False


def test_synthesize_status_contract_structure():
    res = synthesize_status_contract(
        run_outcome="completed",
        verification_status="verified",
        specification_status="complete",
        diagnostics=[{"tool": "browser_screenshot", "category": "telemetry", "error": "timeout"}],
    )
    assert res["task_completed"] is True
    assert res["run_outcome"] == "completed"
    assert res["verification_status"] == "verified"
    assert res["specification_status"] == "complete"
    assert len(res["diagnostics"]) == 1
    assert res["status_contract"] == {
        "run_outcome": "completed",
        "failure_reason": None,
        "verification_status": "verified",
        "specification_status": "complete",
        "diagnostics": [{"tool": "browser_screenshot", "category": "telemetry", "error": "timeout"}],
    }


def test_finalize_node_emits_status_contract(tmp_path):
    # Setup mock state for a clean verified task
    workspace = tmp_path / "app"
    workspace.mkdir()
    (workspace / "server.py").write_text("print('hello')", encoding="utf-8")

    state = {
        "messages": [
            HumanMessage(content="Build server.py"),
            AIMessage(
                content="",
                tool_calls=[{"name": "terminal", "args": {"command": "python -m unittest tests/test_server.py"}, "id": "call-1"}],
            ),
            ToolMessage(content="Ran 5 tests in 0.02s\n\nOK\nExit code: 0", tool_call_id="call-1", name="terminal"),
            AIMessage(content="I have built server.py"),
        ],
        "workspace": str(workspace),
        "steps_completed": ["wrote server.py", "passed tests"],
        "failed_steps": [],
        "workspace_revision": 2,
        "last_verified_revision": 2,
    }

    config = {"configurable": {"thread_id": "test_thread", "workspace": str(workspace)}}
    res = finalize_node(state, config)

    assert "status_contract" in res
    contract = res["status_contract"]
    assert contract["run_outcome"] == "completed"
    assert contract["verification_status"] == "verified"
    assert contract["specification_status"] == "complete"
    assert res["task_completed"] is True


def test_finalize_node_marks_stale_when_revision_exceeds_verification(tmp_path):
    # Tests ran at revision 2, but workspace was mutated to revision 3
    workspace = tmp_path / "app"
    workspace.mkdir()
    (workspace / "server.py").write_text("print('hello')", encoding="utf-8")

    state = {
        "messages": [
            HumanMessage(content="Build server.py"),
            AIMessage(
                content="",
                tool_calls=[{"name": "terminal", "args": {"command": "python -m unittest tests/test_server.py"}, "id": "call-1"}],
            ),
            ToolMessage(content="Ran 5 tests in 0.02s\n\nOK\nExit code: 0", tool_call_id="call-1", name="terminal"),
            AIMessage(content="I edited the file again after tests"),
        ],
        "workspace": str(workspace),
        "steps_completed": ["wrote server.py"],
        "failed_steps": [],
        "workspace_revision": 3,
        "last_verified_revision": 2,  # Stale!
    }

    config = {"configurable": {"thread_id": "test_thread", "workspace": str(workspace)}}
    res = finalize_node(state, config)

    assert res["verification_status"] == "stale"
    assert res["status_contract"]["verification_status"] == "stale"
    # Stale verification must refuse task completion!
    assert res["task_completed"] is False

"""Provider-free contracts for the inclusive final-response call budget."""
from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from src.graphs import gates
from src.graphs import progress_helpers as ph


def _ready_state(tmp_path) -> dict:
    return {
        "execution_mode": "agent",
        "current_task": "fix the library and run its tests",
        "workspace": str(tmp_path),
        "messages": [
            AIMessage(content="", tool_calls=[{
                "id": "verify-1",
                "name": "terminal",
                "args": {"command": "python -m unittest -v"},
            }]),
            ToolMessage(
                content="Ran 6 tests\nOK\nExit code: 0",
                tool_call_id="verify-1",
                name="terminal",
            ),
        ],
        "turn_tool_execution_count": 1,
        "plan": [],
    }


def _patch_ready_evidence(monkeypatch) -> None:
    monkeypatch.setattr(gates, "_execution_requested", lambda state: True)
    monkeypatch.setattr(gates, "_deliverables_missing_on_disk", lambda state, workspace: [])
    monkeypatch.setattr(ph, "trailing_batch_failed", lambda messages: False)


def test_completion_ready_requires_all_deterministic_evidence(monkeypatch, tmp_path):
    _patch_ready_evidence(monkeypatch)
    state = _ready_state(tmp_path)
    receipt = gates._verification_receipt_status(state)
    assert receipt["static"] is True, "stdlib unittest must count as a check"
    assert receipt["passed"] is True
    assert gates._completion_evidence_ready(state) is True


def test_completion_ready_rejects_missing_delivery_or_verification(monkeypatch, tmp_path):
    _patch_ready_evidence(monkeypatch)
    state = _ready_state(tmp_path)

    monkeypatch.setattr(
        gates,
        "_deliverables_missing_on_disk",
        lambda state, workspace: ["required.py"],
    )
    assert gates._completion_evidence_ready(state) is False

    monkeypatch.setattr(gates, "_deliverables_missing_on_disk", lambda state, workspace: [])
    monkeypatch.setattr(gates, "_verification_ran_and_passed", lambda state: False)
    assert gates._completion_evidence_ready(state) is False


def test_completion_ready_rejects_open_plan_or_trailing_failure(monkeypatch, tmp_path):
    _patch_ready_evidence(monkeypatch)
    state = _ready_state(tmp_path)
    state["plan"] = [{"description": "verify", "status": "in_progress"}]
    assert gates._completion_evidence_ready(state) is False

    state["plan"] = []
    monkeypatch.setattr(ph, "trailing_batch_failed", lambda messages: True)
    assert gates._completion_evidence_ready(state) is False


def test_completion_ready_requires_action_after_a_work_nudge(monkeypatch, tmp_path):
    _patch_ready_evidence(monkeypatch)
    state = _ready_state(tmp_path)
    state["nudged_at_msg_count"] = len(state["messages"])
    assert gates._completion_evidence_ready(state) is False

    state["messages"].extend([
        AIMessage(content="", tool_calls=[{
            "id": "inspect-1",
            "name": "read_file",
            "args": {"path": "slugger.py"},
        }]),
        ToolMessage(content="fixed", tool_call_id="inspect-1", name="read_file"),
    ])
    assert gates._completion_evidence_ready(state) is True

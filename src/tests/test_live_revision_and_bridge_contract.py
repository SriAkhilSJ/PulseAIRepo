"""Test live workspace revision tracking in progress_node and status contract in AgentTurnResult.
"""
from __future__ import annotations

import time
from pathlib import Path
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.graphs.chat_graph import progress_node, AgentTurnResult
from src.graphs.state import AgentState


def test_progress_node_increments_workspace_revision_on_file_write():
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "write_file", "args": {"path": "backend/server.py", "content": "..."}}],
            ),
            ToolMessage(content="File written: backend/server.py", tool_call_id="call_1", name="write_file"),
        ],
        "workspace_revision": 0,
        "last_verified_revision": None,
        "mutation_ledger": [],
    }
    config = {"configurable": {"thread_id": "test_t1", "workspace": "."}}
    update = progress_node(state, config)

    assert update["workspace_revision"] == 1
    assert len(update["mutation_ledger"]) == 1
    assert update["mutation_ledger"][0]["path"] == "backend/server.py"


def test_progress_node_ignores_doc_mutations_for_code_revision():
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "write_file", "args": {"path": "README.md", "content": "# Title"}}],
            ),
            ToolMessage(content="File written: README.md", tool_call_id="call_1", name="write_file"),
        ],
        "workspace_revision": 1,
        "last_verified_revision": 1,
        "mutation_ledger": [],
    }
    config = {"configurable": {"thread_id": "test_t2", "workspace": "."}}
    update = progress_node(state, config)

    # Documentation updates do NOT increment workspace code revision
    assert update["workspace_revision"] == 1
    assert len(update["mutation_ledger"]) == 0


def test_progress_node_increments_revision_on_mutating_terminal():
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "terminal", "args": {"command": "npm install express"}}],
            ),
            ToolMessage(content="added 50 packages\nExit code: 0", tool_call_id="call_1", name="terminal"),
        ],
        "workspace_revision": 1,
        "last_verified_revision": 1,
        "mutation_ledger": [],
    }
    config = {"configurable": {"thread_id": "test_t3", "workspace": "."}}
    update = progress_node(state, config)

    assert update["workspace_revision"] == 2
    assert len(update["mutation_ledger"]) == 1


def test_progress_node_records_last_verified_revision_on_test_pass():
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "terminal", "args": {"command": "python -m unittest discover"}}],
            ),
            ToolMessage(content="Ran 16 tests in 0.5s\nOK\nExit code: 0", tool_call_id="call_1", name="terminal"),
        ],
        "workspace_revision": 5,
        "last_verified_revision": 2,
        "mutation_ledger": [],
    }
    config = {"configurable": {"thread_id": "test_t4", "workspace": "."}}
    update = progress_node(state, config)

    # The test passed, so last_verified_revision catches up to workspace_revision
    assert update["last_verified_revision"] == 5


def test_agent_turn_result_carries_status_contract():
    res = AgentTurnResult(
        "All tasks done",
        completed=True,
        status_contract={
            "run_outcome": "completed",
            "verification_status": "verified",
            "specification_status": "complete",
            "failure_reason": None,
        },
        run_outcome="completed",
        failure_reason=None,
        verification_status="verified",
    )
    assert res.completed is True
    assert res.run_outcome == "completed"
    assert res.verification_status == "verified"
    assert res.failure_reason is None
    assert res.status_contract["specification_status"] == "complete"
    assert str(res) == "All tasks done"

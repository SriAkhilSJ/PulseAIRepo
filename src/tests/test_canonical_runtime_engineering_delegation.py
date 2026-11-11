"""Increment 1: canonical LangGraph lifecycle + engineering delegation.

Provider-free. The engineering engine runs its deterministic mock mode; the
graph chat path uses the scripted model seam. No paid calls.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.graphs.chat_graph import (
    _is_engineering_turn,
    after_task_manager,
    engineering_task_node,
    graph,
    stream_agent,
    tool_node,
)
from src.orchestration.approval_gateway import ApprovalDenied
from src.orchestration.models import DeliveryContract, TaskVerdict
from src.runtime.turn_control import turn_controls


def _prompt_state(text: str, mode: str = "agent") -> dict:
    return {
        "execution_mode": mode,
        "canonical_runtime": True,
        "latest_instruction": text,
        "current_task": text,
        "messages": [],
    }


def test_engineering_classifier_separates_chat_and_engineering() -> None:
    assert _is_engineering_turn(_prompt_state("hello there")) is False
    assert _is_engineering_turn(_prompt_state("what does this function do?")) is False
    assert _is_engineering_turn(_prompt_state("thanks!")) is False
    assert _is_engineering_turn(_prompt_state("Create notes.md with a greeting")) is True
    assert _is_engineering_turn(_prompt_state("Fix authentication in auth_bug.py")) is True
    assert _is_engineering_turn(_prompt_state("Build an online marketplace")) is True
    assert _is_engineering_turn(_prompt_state("anything", mode="plan")) is True
    assert _is_engineering_turn(_prompt_state("anything", mode="ask")) is False


def test_after_task_manager_routes_engineering_and_chat() -> None:
    assert after_task_manager(_prompt_state("Create notes.md with a greeting")) == "engineering_task"
    assert after_task_manager(_prompt_state("hello there")) == "planner"
    assert after_task_manager(_prompt_state("hello", mode="ask")) == "ai"


def test_engineering_node_passes_a_valid_request_and_returns_contract(monkeypatch) -> None:
    captured: dict = {}
    contract = DeliveryContract(
        task_id="turn_t1",
        original_request="Create notes.md",
        verdict=TaskVerdict.COMPLETED,
        what_was_requested="Create notes.md",
        what_was_implemented=["notes.md"],
        files_changed=["notes.md"],
        tests_executed=[],
        tests_passed=[],
        tests_failed=[],
        independently_verified=True,
        remaining_limitations=[],
        user_action_required=None,
    )

    calls: list = []

    def fake_run(self, request, **kwargs):
        calls.append(request)
        captured["request"] = request
        captured["kwargs"] = kwargs
        return contract

    monkeypatch.setattr(
        "src.orchestration.orchestrator.EngineeringExecutionOrchestrator.run_task_request",
        fake_run,
    )
    state = _prompt_state("Create notes.md with a greeting")
    config = {
        "configurable": {
            "thread_id": "t1",
            "workspace": str(Path.cwd()),
            "turn_id": "t1",
            "approval_policy": "workspace_session",
        }
    }
    result = engineering_task_node(state, config)
    request = captured["request"]
    assert len(calls) == 1  # no duplicate planning/delegation
    assert request.task_id == "turn_t1"
    assert request.session_id == "t1"
    assert request.prompt == "Create notes.md with a greeting"
    assert request.approval_policy == "workspace_session"
    assert result["engineering_delivery"]["verdict"] == "COMPLETED"
    assert result["task_completed"] is True
    assert result["messages"] and isinstance(result["messages"][0], AIMessage)


def test_engineering_node_cancellation_before_delegation() -> None:
    thread_id = f"cancel-{uuid.uuid4().hex[:8]}"
    turn_controls.begin(thread_id)
    turn_controls.cancel(thread_id)
    try:
        result = engineering_task_node(
            _prompt_state("Create notes.md"),
            {"configurable": {"thread_id": thread_id, "workspace": str(Path.cwd())}},
        )
        assert result["task_status"] == "cancelled"
        assert "engineering_delivery" not in result
    finally:
        turn_controls.end(thread_id)


def test_engineering_stream_populates_messages_and_checkpoint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CRUSORAI_ORCHESTRATOR_MOCK", "1")
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "0")
    thread = f"eng-stream-{uuid.uuid4().hex[:8]}"
    result = stream_agent(
        "Create notes.md with a short greeting for the project.",
        thread_id=thread,
        workspace=str(tmp_path),
        execution_mode="agent",
        approval_channel=True,
        approval_policy="workspace_session",
        turn_id="t-stream",
        canonical_runtime=True,
    )
    assert result.completed is True
    state = graph.get_state({"configurable": {"thread_id": thread}})
    values = state.values or {}
    messages = values.get("messages") or []
    assert len(messages) >= 2
    assert any(getattr(m, "type", "") == "ai" for m in messages)
    delivery = values.get("engineering_delivery") or {}
    assert delivery.get("verdict") == "COMPLETED"
    assert (tmp_path / "notes.md").exists()


def test_chat_stream_stays_on_chat_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "CRUSORAI_TEST_LLM_SCRIPT",
        json.dumps([{"content": "Hello. How can I help with your project?"}]),
    )
    monkeypatch.setenv("CRUSORAI_TEST_MODE", "1")
    monkeypatch.setenv("MEMORY_NUDGE_INTERVAL", "0")
    thread = f"chat-{uuid.uuid4().hex[:8]}"
    result = stream_agent(
        "hello there",
        thread_id=thread,
        workspace=str(tmp_path),
        execution_mode="agent",
        approval_channel=True,
        approval_policy="ask",
    )
    assert "Engineering Execution Report" not in str(result)
    state = graph.get_state({"configurable": {"thread_id": thread}})
    values = state.values or {}
    assert not values.get("engineering_delivery")
    assert len(values.get("messages") or []) >= 2


def test_graph_direct_mutation_tool_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "blocked.py"
    state = {
        "messages": [AIMessage(
            content="",
            tool_calls=[{
                "name": "write_file",
                "args": {"path": str(target), "content": "print('mutated')\n"},
                "id": "call-write-1",
            }],
        )]
    }
    config = {"configurable": {
        "thread_id": f"mut-{uuid.uuid4().hex[:8]}",
        "workspace": str(tmp_path),
        # Increment 2: write_file is enabled, but only with a digest-bound
        # approval token. No approval channel exists here, so the broker must
        # refuse the write and the file must remain absent.
        "canonical_runtime": True,
        "approval_channel": False,
        "approval_policy": "ask",
    }}
    result = tool_node(state, config)
    messages = result.get("messages") if isinstance(result, dict) else None
    assert messages, result
    denial = messages[0]
    assert isinstance(denial, ToolMessage)
    assert (
        "Workspace safety restriction" in str(denial.content)
        or "approval" in str(denial.content).lower()
    )
    assert not target.exists()

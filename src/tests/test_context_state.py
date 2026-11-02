"""Tests for src.context.core.context_state."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.core.context_state import (
    HASHED_STATE_KEYS,
    ContextState,
    hash_state,
    wire_dicts_to_messages,
    workspace_exceeds_budget,
)


def test_hashed_state_keys():
    assert "workspace" in HASHED_STATE_KEYS
    assert "thread_id" in HASHED_STATE_KEYS
    assert "messages" not in HASHED_STATE_KEYS
    assert "execution_trace" not in HASHED_STATE_KEYS


def test_hash_state_stability():
    state1 = {"current_task": "testing", "workspace": "/tmp", "execution_trace": [1, 2, 3]}
    state2 = {"current_task": "testing", "workspace": "/tmp", "execution_trace": [9, 9, 9]}
    # execution_trace change should NOT change hash
    assert hash_state(state1) == hash_state(state2)

    # changing a hashed key should change hash
    state3 = {"current_task": "other", "workspace": "/tmp"}
    assert hash_state(state1) != hash_state(state3)


def test_workspace_exceeds_budget(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for i in range(5):
        (ws / f"file_{i}.txt").write_text("hi")
    assert workspace_exceeds_budget(str(ws), cap=2) is True
    assert workspace_exceeds_budget(str(ws), cap=10) is False


def test_wire_dicts_to_messages():
    dicts = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi", "tool_calls": [{"name": "foo", "args": {}}]},
        {"role": "system", "content": "rules"},
        {"role": "tool", "content": "result", "id": "call_1", "name": "foo"},
    ]
    msgs = wire_dicts_to_messages(dicts)
    assert len(msgs) == 4
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "hello"
    assert isinstance(msgs[1], AIMessage)
    assert len(msgs[1].tool_calls) == 1
    assert isinstance(msgs[2], SystemMessage)
    assert isinstance(msgs[3], ToolMessage)
    assert msgs[3].tool_call_id == "call_1"


def test_context_state_lifecycle():
    cs = ContextState(thread_id="t1")
    cs.freeze_workspace_snapshot("/cwd", "snapshot content")
    assert cs.get_frozen_workspace_snapshot("/cwd") == "snapshot content"

    cs.layer_cache["workspace"] = "cached"
    cs.invalidate_layer("workspace")
    assert "workspace" not in cs.layer_cache

    cs.reset_session()
    assert cs.get_frozen_workspace_snapshot("/cwd") == ""
    assert len(cs.layer_cache) == 0

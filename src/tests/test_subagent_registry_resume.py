"""Open agent registry + resume + per-call model (OpenCode parity).

OpenCode's task tool spawns AGENTS from an open registry (built-ins
plus user-defined agents with their own prompt/model/permissions),
can RESUME a previous child by session id (the worker keeps its
context, no persona re-applied), accepts a per-call model override,
and hard-errors on an unknown agent with the available list. These
drive the real delegate chain with only invoke_agent faked.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest

import src.graphs.chat_graph as cg
from src.agents import subagent_registry as registry


def _delegate(args: dict, parent: str, workspace: str) -> str:
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    builder = StateGraph(MessagesState)
    builder.add_node("tools", ToolNode([cg.delegate_to_subagent]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    app = builder.compile()
    out = app.invoke(
        {"messages": [{
            "role": "assistant", "content": "",
            "tool_calls": [{"name": "delegate_to_subagent", "id": f"tc-{uuid.uuid4().hex[:8]}", "args": args}],
        }]},
        config={"configurable": {"thread_id": parent, "workspace": workspace}},
    )
    return str(out["messages"][-1].content)


@pytest.fixture()
def captured(monkeypatch):
    calls: list[dict] = []

    def fake_invoke_agent(**kwargs):
        calls.append(kwargs)
        return f"findings from {kwargs.get('thread_id')}"

    monkeypatch.setattr(cg, "invoke_agent", fake_invoke_agent)
    return calls


def test_registry_builtins_aliases_and_unknown():
    assert [a.name for a in registry.available_agents(None)] == ["code", "research", "review", "test"]
    assert registry.resolve_agent("explore").base_mode == "research"
    assert registry.resolve_agent("general").base_mode == "code"
    assert registry.resolve_agent("banana") is None


def test_registry_custom_agent_from_workspace(tmp_path):
    agents_dir = tmp_path / ".crusorai" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "release-writer.md").write_text(
        "---\n"
        "description: Writes release notes\n"
        "base: code\n"
        "capabilities: workspace_read, workspace_write\n"
        "model: cheap-model-1\n"
        "---\n\n"
        "You are a release-notes specialist.\n",
        encoding="utf-8",
    )
    agent = registry.resolve_agent("release-writer", str(tmp_path))
    assert agent is not None
    assert agent.capabilities == ("workspace_read", "workspace_write")
    assert agent.model == "cheap-model-1"
    assert "release-notes specialist" in (agent.prompt or "")
    names = [a.name for a in registry.available_agents(str(tmp_path))]
    assert "release-writer" in names


def test_spawn_policy_gate(monkeypatch):
    monkeypatch.setenv("CRUSORAI_SUBAGENT_DENIED", "review")
    assert registry.denied_reason("review") is not None
    assert registry.denied_reason("code") is None
    monkeypatch.setenv("CRUSORAI_SUBAGENT_ALLOWED", "research, code")
    assert registry.denied_reason("test") is not None
    assert registry.denied_reason("research") is None


def test_delegate_unknown_agent_hard_errors(captured, tmp_path):
    out = _delegate({"mode": "banana", "task": "do things"}, f"p-{uuid.uuid4().hex[:8]}", str(tmp_path))
    assert "Unknown sub-agent 'banana'" in out
    assert "research" in out  # the available list rides along
    assert captured == []  # nothing spawned


def test_delegate_denied_agent_blocked(captured, tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_SUBAGENT_DENIED", "research")
    out = _delegate({"mode": "research", "task": "look around"}, f"p-{uuid.uuid4().hex[:8]}", str(tmp_path))
    assert "denied by policy" in out
    assert captured == []


def test_delegate_model_override_reaches_child(captured, tmp_path):
    parent = f"p-{uuid.uuid4().hex[:8]}"
    out = _delegate(
        {"mode": "research", "task": "look around", "model": "cheap-model-9"},
        parent, str(tmp_path),
    )
    assert "Sub-agent (research) completed" in out
    assert captured and captured[0]["model"] == "cheap-model-9"


def test_delegate_custom_agent_prompt_scope_and_model(captured, tmp_path):
    agents_dir = tmp_path / ".crusorai" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "release-writer.md").write_text(
        "---\ndescription: Writes release notes\nbase: code\n"
        "capabilities: workspace_read, workspace_write\nmodel: cheap-model-1\n---\n\n"
        "You are a release-notes specialist.\n",
        encoding="utf-8",
    )
    out = _delegate(
        {"mode": "release-writer", "task": "Draft the notes"},
        f"p-{uuid.uuid4().hex[:8]}", str(tmp_path),
    )
    assert "completed" in out
    call = captured[0]
    assert "release-notes specialist" in call["message"]
    assert "Task: Draft the notes" in call["message"]
    assert call["model"] == "cheap-model-1"
    assert tuple(call["scope_capabilities"]) == ("workspace_read", "workspace_write")


def test_resume_continues_same_thread_verbatim(captured, tmp_path):
    parent = f"p-{uuid.uuid4().hex[:8]}"
    first = _delegate({"mode": "research", "task": "initial research"}, parent, str(tmp_path))
    assert "Sub-agent (research) completed" in first
    child_id = captured[0]["thread_id"]

    out = _delegate(
        {"task": "now check the other file too", "session_id": child_id},
        parent, str(tmp_path),
    )
    assert "completed" in out
    assert len(captured) == 2
    resumed = captured[1]
    assert resumed["thread_id"] == child_id  # same session, same checkpoint
    # Continuation: the follow-up goes in verbatim — no persona re-applied.
    assert resumed["message"] == "now check the other file too"


def test_resume_rejects_unknown_and_foreign_sessions(captured, tmp_path):
    parent = f"p-{uuid.uuid4().hex[:8]}"
    _delegate({"mode": "research", "task": "initial"}, parent, str(tmp_path))
    child_id = captured[0]["thread_id"]

    unknown = _delegate({"task": "more", "session_id": "sub-research-nope"}, parent, str(tmp_path))
    assert "Cannot resume" in unknown

    other_parent = f"p-{uuid.uuid4().hex[:8]}"
    foreign = _delegate({"task": "more", "session_id": child_id}, other_parent, str(tmp_path))
    assert "Cannot resume" in foreign
    assert len(captured) == 1  # neither attempt ran a child


def test_batch_resume_entry(captured, tmp_path):
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    parent = f"p-{uuid.uuid4().hex[:8]}"
    _delegate({"mode": "research", "task": "initial"}, parent, str(tmp_path))
    child_id = captured[0]["thread_id"]

    builder = StateGraph(MessagesState)
    builder.add_node("tools", ToolNode([cg.delegate_to_subagent_batch]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    app = builder.compile()
    out = app.invoke(
        {"messages": [{
            "role": "assistant", "content": "",
            "tool_calls": [{
                "name": "delegate_to_subagent_batch", "id": "batch-resume-1",
                "args": {"mode": "research", "tasks": [
                    {"task": "follow up on earlier work", "session_id": child_id},
                    "fresh parallel task",
                ]},
            }],
        }]},
        config={"configurable": {"thread_id": parent, "workspace": str(tmp_path)}},
    )
    text = str(out["messages"][-1].content)
    assert "follow up on earlier work" in text and "fresh parallel task" in text
    resumed = [c for c in captured if c["thread_id"] == child_id]
    assert len(resumed) == 2  # initial + resumed, same thread
    assert resumed[1]["message"] == "follow up on earlier work"


def test_bound_delegate_description_lists_workspace_agents(tmp_path):
    """OpenCode builds the task description from the live registry:
    after binding in a workspace with a custom agent, the delegate
    tool's description names it — and rebinding never stacks lists."""
    agents_dir = tmp_path / ".crusorai" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "release-writer.md").write_text(
        "---\ndescription: Writes release notes\n---\n\nYou write notes.\n",
        encoding="utf-8",
    )
    from src.graphs import chat_graph as _cg

    state = {"current_task": "delegate work", "plan": [], "execution_trace": [], "iteration_used": 0}
    config = {"configurable": {"workspace": str(tmp_path)}}
    for _ in range(2):
        bound = _cg._resolve_bound_tools(state, config)
        delegate = next(t for t in bound if t.name == "delegate_to_subagent")
        assert "release-writer" in delegate.description
        assert delegate.description.count("Available agents:") == 1

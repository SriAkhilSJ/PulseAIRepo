"""Sub-agent children bind a strictly-scoped tool waist (cost, 2026-10-15).

field cost investigation: every model call (parent + each child) re-sent
all ~68 registered tool schemas. The capability waist existed
(tools.toolsets.resolve_runtime_tool_names) and the profile resolver
already honored scope_capabilities_strict, but the binder ignored both,
and child scopes collapsed to () because the delegate's mode map named
TOOLS while KNOWN_CAPABILITIES names coarse capabilities. These pins keep
the whole chain honest: mode -> coarse caps -> strict binder -> waist.
"""

from __future__ import annotations

from src.graphs import chat_graph
from src.agents.runtime_profile import KNOWN_CAPABILITIES
from src.agents.subagent_permissions import default_capabilities_for_mode


def _state():
    return {
        "current_task": "delegate work",
        "plan": [],
        "execution_trace": [],
        "iteration_used": 0,
    }


def _config(tmp_path, scope=None):
    cfg = {"workspace": str(tmp_path)}
    if scope is not None:
        cfg["scope_capabilities"] = list(scope)
        cfg["scope_capabilities_strict"] = True
    return {"configurable": cfg}


def test_mode_scopes_speak_coarse_capabilities():
    for mode in ("research", "code", "test", "review", "general", ""):
        caps = default_capabilities_for_mode(mode)
        assert caps, mode
        assert set(caps) <= KNOWN_CAPABILITIES, (mode, caps)
    research = default_capabilities_for_mode("research")
    assert "research" in research and "workspace_read" in research
    assert "workspace_write" not in research
    code = default_capabilities_for_mode("code")
    assert {"workspace_read", "workspace_write", "execution"} <= set(code)


def test_child_binds_strict_waist_not_full_registry(tmp_path):
    names = [t.name for t in chat_graph._resolve_bound_tools(
        _state(), _config(tmp_path, ("research", "workspace_read")))]
    # Waist holds: research + read surface present...
    assert "web_search" in names and "read_file" in names
    # ...everything outside the scope is unbound (no schema bill for it)
    assert "write_file" not in names
    assert "edit_file" not in names
    assert "terminal" not in names
    assert len(names) <= 30, names  # ~61% fewer than the 67-tool full bind


def test_code_child_binds_write_and_execution(tmp_path):
    names = [t.name for t in chat_graph._resolve_bound_tools(
        _state(), _config(tmp_path, default_capabilities_for_mode("code")))]
    assert "write_file" in names and "read_file" in names
    assert "web_search" not in names  # research is not in the code scope


def test_parent_bind_unchanged_without_strict_scope(tmp_path):
    # Knife #1: the parent now binds the narrow model-pulled core (not the
    # full registry) — strict scoping stays child-only, but the general
    # parent no longer pays the full 65-tool schema bill every call.
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    config = _config(tmp_path)
    names = [t.name for t in chat_graph._resolve_bound_tools(
        _state(), config)]
    assert chat_graph._resolve_bound_tools.__doc__ is not None  # binding still task-agnostic
    assert "find_tools" in names
    assert "write_file" in names and "read_file" in names
    # Specialized caps (web, browser, target, delegation) are not in the first
    # parent call — they are available for find_tools and bound after pull.
    assert "web_search" not in names
    assert "browser_navigate" not in names
    assert config["configurable"]["tool_search_active"] is True
    assert "web_search" in config["configurable"]["tool_search_available_names"]
    assert len(names) == 22, names  # core + find_tools, not the 65-tool registry

    # A real find_tools result pulls a specialized tool into the next call.
    activated_state = {
        **_state(),
        "messages": [
            HumanMessage(content="need web"),
            AIMessage(content="", tool_calls=[{
                "name": "find_tools",
                "args": {"query": "web search"},
                "id": "find-web",
            }]),
            ToolMessage(
                content="Activated for the next model call: web_search, web_fetch",
                tool_call_id="find-web",
                name="find_tools",
            ),
        ],
    }
    activated = {t.name for t in chat_graph._resolve_bound_tools(activated_state, _config(tmp_path))}
    assert "web_search" in activated


def test_real_delegate_chain_scopes_the_child_bind(tmp_path):
    """End-to-end without a provider (founder: "verify once becoz i
    have less credits to test"). The REAL delegate tool runs through
    the REAL lifecycle + coordinator; only invoke_agent — the seam
    that would spend credits — is faked, capturing the scope it was
    handed. That captured scope is then fed through the exact config
    shape invoke_agent builds into the real binder."""
    from unittest.mock import patch

    from langchain_core.messages import AIMessage

    captured: dict = {}

    def fake_invoke_agent(**kwargs):
        captured.update(kwargs)
        return "child findings"

    state = {"messages": [AIMessage(
        content="",
        tool_calls=[{
            "name": "delegate_to_subagent",
            "args": {"mode": "research", "task": "audit the parser docs"},
            "id": "call_scope_1",
        }],
    )]}
    config = {"configurable": {"thread_id": "main", "workspace": str(tmp_path)}}

    from src.graphs import chat_graph as cg
    # ToolNode-only harness (the hygiene suite's seam): the delegate
    # tool executes for real; no ai node ever builds a provider.
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node("tools", ToolNode([cg.delegate_to_subagent]))
    graph_builder.add_edge(START, "tools")
    graph_builder.add_edge("tools", END)
    app = graph_builder.compile()
    with patch.object(cg, "invoke_agent", fake_invoke_agent):
        out = app.invoke(state, config=config)

    # The whole chain delivered the research scope, not ().
    assert captured.get("scope_capabilities") == ("research", "workspace_read"), captured

    # invoke_agent's own config shape -> the real binder waist.
    child_config = {"configurable": {
        "thread_id": captured.get("thread_id", "child"),
        "workspace": str(tmp_path),
        "scope_capabilities": list(captured["scope_capabilities"]),
        "scope_capabilities_strict": True,
    }}
    names = [t.name for t in chat_graph._resolve_bound_tools(_state(), child_config)]
    assert "web_search" in names and "read_file" in names
    assert "write_file" not in names and "terminal" not in names
    assert len(names) <= 30, names
    # And the delegate itself reported back to the parent normally.
    assert "child findings" in str(out["messages"][-1].content)

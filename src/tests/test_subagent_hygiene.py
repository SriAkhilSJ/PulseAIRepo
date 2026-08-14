"""Sub-agent coordinator hygiene + crash-survival pins (ARCHITECTURE_REVIEW.md §27).

D7 investigation verdict: the scary claims were STRUCTURALLY COVERED
(depth cap, recursion limit, LLM timeouts, ToolNode error conversion);
the one real bug was the coordinator's unbounded _active_agents dict
(process-lifetime growth) plus a docstring that promised "parallel".
These four pins expire on contact with regressions. No LLM, no network.
"""

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

import src.graphs.chat_graph as cg
from src.agents.sub_agent import _MAX_COMPLETED_AGENTS, subagent_coordinator


@pytest.fixture(autouse=True)
def _clean_registry():
    subagent_coordinator.clear()
    yield
    subagent_coordinator.clear()


def _app():
    """ToolNode reachable only through a compiled graph: in this langgraph
    version, bare ToolNode.invoke() from a unit context dies on missing
    runtime config keys (verified — even for a plain tool). Production
    always executes through the compiled graph, so the pin harness must."""
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([cg.delegate_to_subagent]))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile()


def _tool_state():
    return {"messages": [AIMessage(
        content="",
        tool_calls=[{
            "name": "delegate_to_subagent",
            "args": {"mode": "review", "task": "audit the parser"},
            "id": "call_1",
        }],
    )]}


_CFG = {"configurable": {"thread_id": "main", "workspace": "."}}


def test_crashed_subagent_degrades_not_freezes():
    """invoke_agent raises mid-spawn (provider down / bug). Contract (pinned
    against langgraph 1.2.10, whose DEFAULT ToolNode handler converts ONLY
    ToolInvocationError and re-raises everything else — verified): the crash
    is caught at the spawn boundary and reaches the parent as a normal
    tool-result string. NOTHING may escape the graph."""

    def boom(**_kw):
        raise RuntimeError("sub-agent exploded (provider down)")

    with patch.object(cg, "invoke_agent", boom):
        out = _app().invoke(_tool_state(), config=_CFG)  # must not raise

    msg = out["messages"][-1]
    assert "Sub-agent crashed" in str(msg.content)
    assert "sub-agent exploded" in str(msg.content)  # cause survives for the parent
    assert getattr(msg, "status", "ok") != "error"  # graceful string, not an error frame


def test_result_entry_dies_when_consumed():
    with patch.object(cg, "invoke_agent", lambda **kw: "done"):
        aid = subagent_coordinator.spawn(mode="review", task="t", parent_thread_id="m")
        assert subagent_coordinator._active_agents  # non-empty pre-read
        assert subagent_coordinator.get_result(aid) == "done"
        assert subagent_coordinator._active_agents == {}  # pop-on-read


def test_mystery_or_missing_ids_answer_cleanly():
    assert "No sub-agent found" in subagent_coordinator.get_result("sub-nope-000000")


def test_registry_is_hard_bounded_under_churn():
    """Simulated crash-no-pop churn: pre-seed orphans, then confirm the cap."""
    for i in range(_MAX_COMPLETED_AGENTS + 20):
        subagent_coordinator._active_agents[f"orphan-{i}"] = {
            "mode": "review", "task": "t", "result": "x", "parent": "m",
        }
    with patch.object(cg, "invoke_agent", lambda **kw: "done"):
        subagent_coordinator.spawn(mode="code", task="t", parent_thread_id="m")
    assert len(subagent_coordinator._active_agents) <= _MAX_COMPLETED_AGENTS

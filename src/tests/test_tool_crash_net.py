"""Tool-crash net pins (ARCHITECTURE_REVIEW.md §27-28, debt D17).

langgraph>=1.1 narrowed its DEFAULT ToolNode error policy to validation
errors only (`_default_handle_tool_errors` re-raises anything else —
read and reproduced). One arbitrary tool exception (httpx timeout, file
lock, OSError in a parser...) used to kill the whole agent turn.

Production policy: SafeToolNode builds ToolNode(tools, handle_tool_errors=True)
at the single choke point — crash becomes an error ToolMessage with intact
tool_call pairing, model adapts, turn survives. These pins expire on drift:
if a future langgraph changes True's semantics, they go red loudly.
No LLM, no network.
"""

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

import src.graphs.chat_graph as cg
from src.context.safety_guard import SafetyGuard


@tool
def plain_boom(x: int) -> str:
    """Probe tool that always crashes with a non-validation exception."""
    raise RuntimeError("kaboom arbitrary")


def _build(node_obj):
    """Reachable the production way only: bare ToolNode dies on runtime
    config keys outside a compiled graph (learned in §27)."""
    g = StateGraph(MessagesState)
    g.add_node("tools", node_obj)
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    return g.compile()


def _state():
    return {"messages": [AIMessage(
        content="",
        tool_calls=[{"name": "plain_boom", "args": {"x": 1}, "id": "c1"}],
    )]}


_CFG = {"configurable": {"thread_id": "net-test", "workspace": "."}}


def test_version_drift_tripwire_default_policy_still_narrow():
    """If a future langgraph re-widens the DEFAULT policy this assertion
    becomes falsy-safe (still passes) — its real job is documenting the
    verified baseline that motivated the net (1.2.10 re-raises)."""
    import pytest
    with pytest.raises(RuntimeError, match="kaboom"):
        _build(ToolNode([plain_boom])).invoke(_state(), config=_CFG)


def test_true_policy_is_a_catch_all_with_intact_pairing():
    out = _build(ToolNode([plain_boom], handle_tool_errors=True)).invoke(
        _state(), config=_CFG
    )  # must not raise
    msg = out["messages"][-1]
    assert getattr(msg, "status", None) == "error"
    assert msg.tool_call_id == "c1"  # conversation/tool_call pairing survives
    assert "kaboom arbitrary" in str(msg.content)


def test_production_tool_node_carries_the_net():
    """The one choke point the real agent runs through (chat_graph:1538)."""
    assert cg.tool_node._node._handle_tool_errors is True, (
        "SafeToolNode lost its crash net — a stray tool exception will "
        "again kill turns (see §27-28)"
    )


def test_end_to_end_safe_tool_node_survives_arbitrary_crash():
    node = cg.SafeToolNode([plain_boom], SafetyGuard())
    out = _build(node).invoke(_state(), config=_CFG)  # must not raise
    msg = out["messages"][-1]
    assert getattr(msg, "status", None) == "error"
    assert "kaboom arbitrary" in str(msg.content)

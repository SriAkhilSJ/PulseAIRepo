"""Behavioral contracts for Agent, Plan, Debug, and Ask execution modes."""
from __future__ import annotations

from langchain_core.messages import AIMessage

from src.graphs.chat_graph import after_planner, after_task_manager
from src.graphs.gates import should_continue


def test_ask_routes_directly_to_text_generation_without_planner():
    assert after_task_manager({"execution_mode": "ask", "task_action": "new"}) == "ai"


def test_ask_text_finishes_without_execution_or_verification_nudges():
    state = {
        "execution_mode": "ask",
        "current_task": "Explain how to fix this application",
        "messages": [AIMessage(content="Here is the explanation.")],
        "finish_nudges": 0,
        "verify_nudges": 0,
    }
    assert should_continue(state) == "finalize"


def test_ask_never_routes_an_unsolicited_tool_call_to_execution():
    state = {
        "execution_mode": "ask",
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "terminal",
            "args": {"command": "echo should-not-run"},
            "id": "unexpected",
            "type": "tool_call",
        }])],
    }
    assert should_continue(state) == "finalize"


def test_plan_mode_reasons_in_loop_instead_of_engine_preview():
    """PLAN MODE is a prompt, not an engine (chat_graph planner: hermes
    parity, and the 'hi' costing two provider calls fix): plan requests feed
    the live agent the plan prompt and the model reaches the list through
    plan_update inside the loop. The preview node survives for the
    approve-a-plan reviser flow, but the planner no longer routes to it."""
    assert after_task_manager({"execution_mode": "plan", "task_action": "new"}) == "planner"
    assert after_planner({"execution_mode": "plan"}) == "ai"
    # the preview surface still exists behind plan_reviser
    builder_edges = chat_graph_builder_plan_preview_edge_intact()
    assert builder_edges is True


def chat_graph_builder_plan_preview_edge_intact() -> bool:
    from src.graphs.chat_graph import builder
    return ("plan_reviser", "plan_preview") in set(builder.edges)


def test_agent_and_debug_continue_through_execution_path():
    for mode in ("agent", "debug"):
        assert after_task_manager({"execution_mode": mode, "task_action": "new"}) == "planner"
        assert after_planner({"execution_mode": mode}) == "ai"

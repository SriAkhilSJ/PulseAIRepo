"""Behavioral contracts for Agent, Plan, Debug, and Ask execution modes."""
from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

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


def test_ask_tool_call_is_denied_at_dispatch_then_answered_not_finalized():
    """Hermes /btw discipline (agent/side_question.py): a tool call in an ask
    turn is DENIED at dispatch and the loop continues so the model answers in
    text ("the model may waste an iteration on a (denied) tool call first").
    Finalizing on the call itself ended the turn with an unanswered call and
    no answer — the field "Ask is not working" (2026-09-06)."""
    tool_call_state = {
        "execution_mode": "ask",
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "terminal",
            "args": {"command": "echo should-not-run"},
            "id": "unexpected",
            "type": "tool_call",
        }])],
    }
    assert should_continue(tool_call_state) == "tools"

    text_state = {
        "execution_mode": "ask",
        "messages": [AIMessage(content="Here is the answer.")],
    }
    assert should_continue(text_state) == "finalize"


def test_ask_mode_denies_every_tool_at_dispatch_without_executing(tmp_path):
    """SafeToolNode is hermes' thread-scoped whitelist: the call never runs,
    the denial rides the durable transaction boundary (the renderer's
    tool.call gets a terminal event), and pairing stays intact."""
    from langchain_core.messages import HumanMessage

    from src.graphs.chat_graph import SafeToolNode
    from src.context.safety_guard import SafetyGuard

    executed = []

    def _boom(path: str = "x") -> str:
        """write a file (must never run in ask mode)."""
        executed.append(path)
        return "should never run"

    _boom.name = "write_file"

    state = {
        "execution_mode": "ask",
        "messages": [
            HumanMessage(content="list the files"),
            AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"path": "evil.txt", "content": "no"},
                "id": "call-ask-1",
                "type": "tool_call",
            }]),
        ],
    }
    config = {"configurable": {"thread_id": "ask-deny", "workspace": str(tmp_path)}}

    node = SafeToolNode([_boom], SafetyGuard(str(tmp_path)))
    result = node(state, config)

    assert executed == [], "ask mode must never execute a tool"
    msgs = result["messages"]
    assert len(msgs) == 1
    denial = msgs[0]
    assert isinstance(denial, ToolMessage)
    assert denial.tool_call_id == "call-ask-1"
    assert "denied tool call: write_file" in denial.content
    assert "answer the user directly in text" in denial.content
    # The loop continues after the denial: should_continue sees the denial
    # result (last message is a ToolMessage) and the model answers in text.
    assert should_continue({
        "execution_mode": "ask",
        "messages": state["messages"] + [denial],
    }) == "ai"


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

"""Deterministic regressions for provider output-limit continuation."""

from langchain_core.messages import AIMessage, SystemMessage

from src.graphs.gates import finish_gate_node, should_continue


def incomplete_message(*, tool_calls=None):
    return AIMessage(
        content="",
        tool_calls=tool_calls or [],
        additional_kwargs={
            "pulse_incomplete_response": True,
            "pulse_incomplete_reason": "length",
            "pulse_raw_finish_reason": "lengthlength",
        },
    )


def test_empty_output_limit_has_dedicated_continuation_without_finish_spend():
    state = {
        "messages": [incomplete_message()],
        "incomplete_response_retries": 1,
        "finish_nudges": 2,
        "iteration_used": 1,
    }

    assert should_continue(state) == "finish_gate"
    update = finish_gate_node(state)
    assert isinstance(update["messages"][0], SystemMessage)
    assert "output limit" in update["messages"][0].content
    assert "finish_nudges" not in update


def test_empty_output_limit_continuation_is_bounded():
    state = {
        "messages": [incomplete_message()],
        "incomplete_response_retries": 4,
        "iteration_used": 4,
    }
    assert should_continue(state) == "finalize"


def test_incomplete_tool_call_keeps_paired_rejection_route():
    state = {
        "messages": [incomplete_message(tool_calls=[{
            "name": "write_file",
            "id": "partial",
            "args": {"path": "index.html"},
        }])],
        "incomplete_response_retries": 1,
        "iteration_used": 1,
    }
    assert should_continue(state) == "tools"

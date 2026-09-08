"""Planning must never kill the turn — field log 2026-09-08, engine 60a72ee6.

Two verified failures from one run ("Run failed / Planner did not return a
valid numbered plan", 391.7s in, 20+ completed tool calls): (1) the model
wrote its plan through plan_update with `steps` as a JSON STRING — hermes
todo_tool.py tolerates exactly that ("LLMs sometimes send a JSON string
instead of a list"), pulse's tool did not, so the write failed; (2) a later
triggered replan got a helper-LLM response with no numbered lines and
create_replan's ValueError tore straight through the graph, ending the
turn. The initial planner already degrades (_no_plan, lab run 10); the
replanner now degrades the same way: keep the current plan, continue.
"""
from __future__ import annotations

import json

from src.tools.plan_tool import plan_update


def _invoke(steps):
    return plan_update.invoke({"steps": steps})


def test_plan_update_accepts_json_string_steps():
    steps = [
        {"description": "inspect routes", "status": "completed"},
        {"description": "run build checks", "status": "in_progress"},
        {"description": "exercise routes in a browser", "status": "pending"},
    ]
    result = json.loads(_invoke(json.dumps(steps)))  # the exact field shape
    assert result["summary"]["total"] == 3
    assert [s["description"] for s in result["steps"]] == [
        "inspect routes", "run build checks", "exercise routes in a browser",
    ]


def test_plan_update_unparseable_string_is_a_tool_error_not_a_raise():
    result = json.loads(_invoke("definitely not json or steps"))
    assert "unparseable string" in result["error"]


def test_plan_update_wrong_type_never_reaches_the_loop():
    # A non-string non-list is rejected by langchain's schema validation
    # (pydantic) BEFORE the tool body runs; in the graph SafeToolNode's
    # handle_tool_errors=True converts that into an error ToolMessage, so
    # the model sees a failure receipt while the turn keeps running.
    import pytest as _pytest
    from pydantic_core import ValidationError as _PydanticValidationError
    with _pytest.raises(_PydanticValidationError):
        _invoke(42)


def test_replanner_degrades_when_the_plan_llm_fails(monkeypatch, tmp_path):
    """The field crash: ValueError('Planner did not return a valid numbered
    plan.') from create_replan killed the whole turn. The node must catch
    ANY planner failure, keep the current plan, and continue."""
    import src.graphs.chat_graph as cg

    def _boom(**kwargs):
        raise ValueError("Planner did not return a valid numbered plan.")

    monkeypatch.setattr(cg, "create_replan", _boom)
    state = {
        "replan_needed": True,
        "replan_count": 0,
        "current_task": "browser test and fixx",
        "plan": [{"id": 1, "description": "inspect", "status": "completed"}],
        "failed_steps": ["Ran command failed: npm run build"],
        "prior_attempts": [],
        "token_usage": {},
    }
    config = {"configurable": {
        "thread_id": "replanner-degrade-test",
        "workspace": str(tmp_path),
        "provider": "custom", "model": "fake",
    }}
    result = cg.replanner_node(state, config)
    assert result["replan_needed"] is False, "continue with the current plan"
    assert cg.__dict__.get("create_replan") is not None

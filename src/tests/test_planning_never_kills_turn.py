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


def test_engine_replan_component_no_longer_exists():
    """Hermes pipeline shape (verified in hermes source: no replanner
    component, no plan-LLM consult in the loop — the model adapts from
    failure receipts). Pulse's create_replan engine, should_replan
    consult, replanner node, and its route are removed with this round:
    a failure is handed back to the model like any other observation, so
    the 'Planner did not return a valid numbered plan' crash class is
    structurally impossible."""
    import inspect
    import src.graphs.chat_graph as cg
    import src.graphs.progress_helpers as ph
    assert not hasattr(cg, "replanner_node")
    assert not hasattr(cg, "create_replan")
    assert not hasattr(ph, "maybe_replan")
    na_source = inspect.getsource(ph.next_after_progress)
    assert '"replanner"' not in na_source and "return \"replanner\"" not in na_source
    source = inspect.getsource(cg)
    assert "maybe_replan" not in source

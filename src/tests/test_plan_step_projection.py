"""A plan step must never be able to kill a finished turn.

Windows, 2026-09-02, first turn on a real key: 42 seconds at the provider, then the panel reported
``'str' object has no attribute 'model_dump'`` instead of a plan. Three sites in ``src/graphs/chat_graph.py``
projected planner steps by calling ``model_dump`` on whatever came back -- true for a ``TaskPlanStep`` and
for a dict round-tripped out of checkpointed state, false for the list of strings a provider sometimes
returns, and nothing upstream guarantees the shape since ``steps`` can be assigned without validation.

Test 1 EXECUTES the projection over all three shapes, because that is behaviour. Test 2 is a text pin on the
call sites, written around the forbidden literal so the pin cannot match its own explanation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_every_step_shape_projects_to_the_graph_dict():
    try:
        from src.models.plan_models import TaskPlanStep, steps_to_dicts
    except ModuleNotFoundError as exc:  # pragma: no cover - host gap, never a pass
        pytest.skip(f"pydantic or src not importable on this host: {exc}")

    steps = [
        TaskPlanStep(id=1, description="read the failing test", status="pending"),
        {"id": 2, "description": "patch the parser", "status": "completed"},
        "write the regression test",
    ]
    projected = steps_to_dicts(steps)

    assert [s["id"] for s in projected] == [1, 2, 3]
    assert [s["status"] for s in projected] == ["pending", "completed", "pending"]
    assert [s["description"] for s in projected] == [
        "read the failing test",
        "patch the parser",
        "write the regression test",
    ]
    # start_next_plan_step indexes step["status"] directly, so a missing key is the same
    # crash wearing different clothes.
    assert all("status" in step and "description" in step for step in projected)


def test_call_sites_do_not_dump_models_directly():
    graph = (ROOT / "src/graphs/chat_graph.py").read_text(encoding="utf-8")
    unsafe = "step." + "model_dump()"
    assert unsafe not in graph, (
        "project planner steps through steps_to_dicts so text and dict steps survive"
    )
    assert "steps_to_dicts(" in graph, "the three sites must stay converted"

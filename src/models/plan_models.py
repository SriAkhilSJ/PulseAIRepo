from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


class PlanStep(BaseModel):
    description: str = Field(
        validation_alias=AliasChoices(
            "description",
            "action",
        )
    )

    status: Literal[
        "pending",
        "in_progress",
        "completed",
        "failed",
    ] = "pending"


class PlanSteps(BaseModel):
    steps: list[PlanStep]


class TaskPlanStep(BaseModel):
    id: int
    description: str
    status: Literal[
        "pending",
        "in_progress",
        "completed",
        "failed",
    ] = "pending"


class TaskPlan(BaseModel):
    goal: str
    steps: list[TaskPlanStep]


def step_to_dict(step: object, *, index: int | None = None) -> dict:
    """Project one planner step onto the dict shape the graphs persist.

    A step reaches the graph three ways: a real ``TaskPlanStep``, an
    already-serialized dict coming back out of checkpointed state, or bare text
    from a provider that answered with a list of strings (and ``steps`` can be
    assigned to a plan without validation, so nothing upstream guarantees the
    shape). Only the first two were assumed, so the third raised
    ``'str' object has no attribute 'model_dump'`` -- after 42s of real provider
    time, turning a finished turn into a Python error. Text is a legitimate step:
    it gets an id and ``pending`` here instead of crashing code that reads
    ``status`` unguarded.
    """
    if isinstance(step, dict):
        data = dict(step)
    elif hasattr(step, "model_dump"):
        data = dict(step.model_dump())
    else:
        data = {"description": str(step).strip()}

    if index is not None:
        data.setdefault("id", index)
    data.setdefault("status", "pending")
    # The graph and the row UI have both historically read either key; keep the
    # canonical one populated so neither side paints an empty row.
    data["description"] = str(
        data.get("description") or data.get("step") or ""
    ).strip()
    return data


def steps_to_dicts(steps: object) -> list[dict]:
    """``step_to_dict`` over any iterable of steps, tolerating ``None``."""
    return [
        step_to_dict(step, index=i)
        for i, step in enumerate(list(steps or []), start=1)
    ]

class PlanningDecision(BaseModel):
    needs_plan: bool
    reason: str = ""
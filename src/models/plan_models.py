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

class PlanningDecision(BaseModel):
    needs_plan: bool
    reason: str = ""
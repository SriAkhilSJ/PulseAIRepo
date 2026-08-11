# src/graphs/state.py
"""
Graph state + task-manager structured output (P0-D extraction from
chat_graph.py).

Pure data definitions: no singletons, no import-time side effects, no
dependency on the tool/LLM machinery. Layering root of the graphs package
(budget <- state; gates <- state, budget) so this stays free of cycles.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from typing_extensions import TypedDict
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, AliasChoices
# pyrefly: ignore [missing-import]
from langchain_core.messages import BaseMessage
# pyrefly: ignore [missing-import]
from langgraph.graph.message import add_messages


# ==========================================
# TASK MANAGER STRUCTURED OUTPUT
# ==========================================

class TaskDecision(BaseModel):
    action: Literal["new", "continue", "unrelated"] = Field(
        default="continue",
        validation_alias=AliasChoices(
            "action",
            "classification",
            "type",
            "status",
        ),
        description=(
            "Relationship of the latest instruction to the active task. "
            "Must be new, continue, or unrelated."
        ),
    )

    updated_task: str | None = Field(
        default=None,
        description=(
            "Complete active task after considering the latest "
            "instruction. Use null for unrelated messages."
        ),
    )


# =========================================================
# STATE
# =========================================================
class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]

    execution_mode: Literal["agent", "plan"]

    tool_failures: int
    recovery_mode: bool
    current_task: str
    latest_instruction: str
    task_status: str
    steps_completed: list[str]
    task_action: str
    failed_steps: list[str]
    recovery_attempts: int
    recovery_command: str | None
    plan: list[dict[str, Any]]
    plan_goal: str
    plan_created: bool
    plan_approved: bool
    plan_revision_count: int
    replan_needed: bool
    replan_count: int
    execution_trace: list[dict[str, Any]]
    task_completed: bool
    env_failures: int       # environment-level tool failures (pivot trigger)
    pivot_count: int        # strategy pivots performed (bounded)
    prior_attempts: list[dict[str, Any]]  # NEW: Summarized history of past attempts
    finish_nudges: int      # hermes-style early-finish nudges applied (bounded)
    verify_nudges: int      # Test-2: nudges to run a verification tool (bounded)
    token_usage: dict[str, Any]  # Tracks tokens and cost for this task
    workspace: str  # Root path of the active project
    iteration_used: int     # D40: ai-node LLM calls this run (iteration budget)
    grace_done: int         # D40: grace (text-only) call already performed

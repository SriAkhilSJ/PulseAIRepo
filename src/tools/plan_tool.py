"""``plan_update`` -- the model's own task list, kept inside the action loop.

Hermes parity, stated precisely from the upstream source: planning is never a pre-action provider
call. ``tools/todo_tool.py:316`` exposes one function that reads or replaces the list, and
``:15`` says *"Behavioral guidance lives entirely in the tool schema description"* -- no prompt
layer, no classifier. ``agent/plan_prompt.py`` then treats PLAN MODE as a prompt fed to the live
agent as a normal turn: *"There is no engine and no model-tool footprint."*

Pulse had the mirror image. The owner's measurement was the last straw: a turn of ``hi`` or
``create a hello.py`` spent a classifier call plus a plan-generation call before the agent could
act, and the plan then crashed the step projection. Money, latency, and a worse answer.

This module is the missing half of the parity: the model may write the list when the task earns
one. Nothing calls it for a greeting, because nothing is called before the loop any more.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from src.models.plan_models import steps_to_dicts


@tool
def plan_update(steps: list[dict[str, Any]] | None = None) -> str:
    """Read or replace the task list for the current turn.

    Only use this when the task genuinely needs two or more separate steps: an edit that must be
    followed by a test, a bug to diagnose then fix, several files to change. For a greeting, a
    question, a single lookup, or one small edit, do NOT call this -- answer or act directly.
    An unused list costs the user money and latency, and a decorative list is worse than none.

    Call with `steps` to replace the whole list; each step is
    `{"description": "...", "status": "pending|in_progress|completed|failed"}`.
    Mark at most one step `in_progress` -- that is the step you are doing now. Call again after
    finishing a step so the list reflects reality; never mark a step completed before its evidence
    exists. Call with no arguments to read the current list.
    """

    if steps is None:
        return json.dumps({"steps": [], "summary": {"total": 0}}, ensure_ascii=False)

    normalized = steps_to_dicts(steps)
    if not any(step.get("status") == "in_progress" for step in normalized):
        # Mirror start_next_plan_step: exactly one step is "the one you are doing now".
        for step in normalized:
            if step.get("status") == "pending":
                step["status"] = "in_progress"
                break

    summary = {
        "total": len(normalized),
        "pending": sum(1 for s in normalized if s["status"] == "pending"),
        "in_progress": sum(1 for s in normalized if s["status"] == "in_progress"),
        "completed": sum(1 for s in normalized if s["status"] == "completed"),
        "failed": sum(1 for s in normalized if s["status"] == "failed"),
    }
    return json.dumps({"steps": normalized, "summary": summary}, ensure_ascii=False)


__all__ = ["plan_update"]

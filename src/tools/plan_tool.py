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


VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}
# hermes todo_tool.py caps, verbatim: unbounded list content would defeat the
# compression it rides through.
MAX_TODO_CONTENT_CHARS = 4000
MAX_TODO_ITEMS = 256
_TRUNCATION_MARKER = "… [truncated]"


def _cap_description(description: str) -> str:
    """hermes _cap_content, verbatim: truncate keeping the head + marker."""
    if len(description) > MAX_TODO_CONTENT_CHARS:
        return description[:MAX_TODO_CONTENT_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
    return description


def _validate_step(step: Any) -> dict:
    """hermes _validate, on pulse's vocab (description/content): normalize one
    step to {id, description, status} with placeholders when missing."""
    if isinstance(step, str):
        # hermes' parse layer: a bare string is a legitimate step; its text
        # becomes the description (todo_tool parse, not the invalid path).
        text = step.strip()
        return {"description": _cap_description(text) if text else "(no description)",
                "status": "pending"}
    if not isinstance(step, dict):
        return {"description": "(invalid step)", "status": "pending"}
    description = str(step.get("description") or step.get("content") or "").strip()
    status = str(step.get("status", "pending")).strip().lower()
    return {
        "description": _cap_description(description) if description else "(no description)",
        "status": status if status in VALID_STATUSES else "pending",
    }


def _dedupe_by_description(steps: list) -> list:
    """hermes _dedupe_by_id (pulse steps are id-less until projection): keep
    the LAST occurrence of a duplicate description, in its position."""
    last_index: dict = {}
    for i, step in enumerate(steps):
        if isinstance(step, str):
            key = step.strip()
        elif isinstance(step, dict):
            key = str(step.get("description") or step.get("content") or "").strip()
        else:
            key = f"__invalid_{i}"
        last_index[key or "?"] = i
    return [steps[i] for i in sorted(last_index.values())]


def _normalize_order(steps: list) -> list:
    """hermes _normalize_order: lift the in_progress step ahead of earlier
    pending placeholders so the active step leads."""
    statuses = [s.get("status") for s in steps]
    if "in_progress" not in statuses:
        return steps
    active_index = statuses.index("in_progress")
    if "pending" not in statuses[:active_index]:
        return steps
    normalized = steps.copy()
    normalized.insert(statuses.index("pending"), normalized.pop(active_index))
    return normalized


@tool
def plan_update(
    steps: "list | str | None" = None,
    merge: bool = False,
) -> str:
    """Read or replace the task list for the current turn.

    Only use this when the task genuinely needs two or more separate steps: an edit that must be
    followed by a test, a bug to diagnose then fix, several files to change. For a greeting, a
    question, a single lookup, or one small edit, do NOT call this -- answer or act directly.
    An unused list costs the user money and latency, and a decorative list is worse than none.

    Call with `steps` to replace the whole list; each step is
    `{"description": "...", "status": "pending|in_progress|completed|failed"}`.
    There is NO merge mode: always resend the FULL list, including the steps you want to keep.
    Mark at most one step `in_progress` -- that is the step you are doing now. Call again after
    finishing a step so the list reflects reality; never mark a step completed before its evidence
    exists. Call with no arguments to read the current list.
    """
    # Field 2026-09-10: the model passed merge=True (a habit from the
    # id-keyed hermes todo_list). Silently ignoring it made the model BELIEVE
    # steps were merged while the list was wholesale-REPLACED — three
    # unfinished steps vanished, the shrunken list read "complete", and the
    # plan-complete shortcut cut the turn mid-work. Refuse loudly instead.
    if merge:
        return json.dumps(
            {
                "error": (
                    "plan_update has no merge mode: the list is replace-only "
                    "(steps are description-keyed, there are no ids to merge "
                    "by). Resend the FULL list including every step you want "
                    "to keep, with updated statuses."
                )
            },
            ensure_ascii=False,
        )

    if steps is None:
        return json.dumps({"steps": [], "summary": {"total": 0}}, ensure_ascii=False)

    # hermes tools/todo_tool.py (verbatim tolerance): "LLMs sometimes send a
    # JSON string instead of a list" — parse before judging. Field log
    # 2026-09-08 (engine 60a72ee6): the model sent exactly that shape and
    # the tool failed; progress_node's _plan_tool_steps already tolerates
    # it, the tool itself did not.
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except (json.JSONDecodeError, TypeError):
            return json.dumps(
                {"error": "steps must be a list of objects, got unparseable string"},
                ensure_ascii=False,
            )
    if not isinstance(steps, list):
        return json.dumps(
            {"error": f"steps must be a list, got {type(steps).__name__}"},
            ensure_ascii=False,
        )

    # hermes todo_tool write path (verbatim semantics, pulse vocab):
    # _fresh_items = validate -> dedupe -> order; then the cap keeps the
    # priority head.
    normalized = [
        _validate_step(s) for s in _dedupe_by_description(steps)
    ]
    normalized = _normalize_order(normalized)[:MAX_TODO_ITEMS]
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

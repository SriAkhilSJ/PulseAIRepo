"""P10: planner-family message construction.

The planner / replanner / reviser nodes need small, deterministic
message lists (strict-output system prompt + a human brief built from
plan state). None of that reads engine state — the only coupling is
the strict-output suffix on the planner prompt — so it lives here as
pure functions. The engine keeps the method names
(``build_planner_messages`` & friends, ``_planner_prompt``) as thin
delegates: ``src/agents/planner.py`` calls them on the engine instance
and that seam is preserved.
"""

from typing import Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


def wrap_planner_prompt(planner_prompt: str) -> str:
    """Add strict output rules so reasoning models return parseable plans."""
    return (
        planner_prompt
        + "\n\nReturn ONLY the final plan as a numbered list."
        + "\nStart every line with a number like `1.`."
        + "\nDo not include analysis, reasoning, headings, examples, markdown, commentary, or duplicate steps."
        + "\nDo not include unrelated filler steps."
        + "\nKeep the plan concise: usually 3-8 steps."
    )


def build_planner_messages(task: str, planner_prompt: str) -> list[BaseMessage]:
    """
    Build messages for the planner node.
    This is simpler — just the prompt + the task.
    """
    return [
        SystemMessage(content=wrap_planner_prompt(planner_prompt)),
        HumanMessage(content=task),
    ]


def build_replanner_messages(
    task: str,
    plan: list[dict],
    failed_steps: list[str],
    planner_prompt: str,
    prior_attempts: list[dict] | None = None,
) -> list[BaseMessage]:
    """
    Build messages for the replanner node.
    This includes the original task, completed work, failures,
    and lessons from past attempts.
    """
    completed = [
        step["description"]
        for step in plan
        if step.get("status") == "completed"
    ]

    remaining = [
        step["description"]
        for step in plan
        if step.get("status") != "completed"
    ]

    lines = [
        f"Original task:\n{task}\n",
        "Already completed:",
    ]
    for step in completed:
        lines.append(f"  - {step}")

    lines.append("\nRemaining or blocked work:")
    for step in remaining:
        lines.append(f"  - {step}")

    lines.append("\nFailures:")
    for failure in failed_steps[-3:]:
        lines.append(f"  - {failure}")

    # Add lessons from past attempts
    if prior_attempts:
        lines.append("\n=== LESSONS FROM PAST ATTEMPTS ===")
        for attempt in prior_attempts[-2:]:
            lines.append(f"  - {attempt.get('lesson', 'No lesson recorded')}")

    lines.append("\nCreate a revised plan for ONLY the remaining work.")
    lines.append("Do not repeat completed work.")
    lines.append("Learn from past failures and choose a different approach.")

    return [
        SystemMessage(content=wrap_planner_prompt(planner_prompt)),
        HumanMessage(content="\n".join(lines)),
    ]


def build_reviser_messages(
    task: str,
    plan: list[dict],
    revision: str,
    planner_prompt: str,
) -> list[BaseMessage]:
    """Build messages for the plan reviser node."""
    plan_text = "\n".join(
        f"{step.get('id', i)}. {step.get('description', '')}"
        for i, step in enumerate(plan, start=1)
    )

    content = (
        f"Original task:\n{task}\n\n"
        f"Current plan:\n{plan_text}\n\n"
        f"User requested this plan change:\n{revision}\n\n"
        "Revise the current plan according to the user's request.\n"
        "Preserve steps that do not need to change.\n"
        "Return the complete revised plan.\n"
        "Do not execute anything."
    )

    return [
        SystemMessage(content=wrap_planner_prompt(planner_prompt)),
        HumanMessage(content=content),
    ]

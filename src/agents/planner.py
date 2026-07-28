import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm.factory import get_llm
from src.models.plan_models import TaskPlan, TaskPlanStep
from src.prompts.planner_prompt import PLANNER_PROMPT


def _extract_decision(response_content: object) -> str:
    answer = str(response_content).strip().upper()

    if "</THINK>" in answer:
        answer = answer.split("</THINK>", 1)[1].strip()

    return answer.split()[0] if answer else ""


def should_create_plan(
    task: str,
    provider: str,
    model: str,
) -> bool:
    llm = get_llm(
        provider=provider,
        model=model,
    )

    response = llm.invoke([
        SystemMessage(
            content=(
                "Classify the coding request as PLAN or DIRECT.\n\n"

                "PLAN means the request requires multiple meaningful "
                "steps, investigation, implementation, debugging, "
                "recovery, testing, or verification.\n"

                "DIRECT means the request is a simple single action "
                "such as reading a file, listing files, explaining "
                "something, or running one straightforward command.\n\n"

                "Consider the meaning of the request, not specific "
                "keywords.\n\n"

                "Return exactly one word:\n"
                "PLAN\n"
                "or\n"
                "DIRECT"
            )
        ),
        HumanMessage(content=task),
    ])

    decision = _extract_decision(response.content)

    if decision == "PLAN":
        return True

    if decision == "DIRECT":
        return False

    # Safe fallback: don't create a plan.
    return False


def create_plan(
    task: str,
    provider: str,
    model: str,
) -> TaskPlan:
    llm = get_llm(
        provider=provider,
        model=model,
    )

    result = llm.invoke(
        [
            SystemMessage(
                content=(
                    PLANNER_PROMPT
                    + "\n\nReturn ONLY the final plan as a numbered list."
                    + "\nDo not include analysis, reasoning, headings, examples, "
                    "commentary, or duplicate steps."
                )
            ),
            HumanMessage(content=task),
        ]
    )
    

    content = str(result.content).strip()

    # Reasoning models may include internal <think>...</think>
    # content before the actual plan.
    if "</think>" in content.lower():
        lower_content = content.lower()
        end_index = lower_content.rfind("</think>")
        content = content[end_index + len("</think>"):].strip()

    descriptions = []

    for line in content.splitlines():
        line = line.strip()

        match = re.match(
            r"^\d+[\.\)]\s*(.+)$",
            line,
        )

        if match:
            description = match.group(1).strip()

            if description:
                descriptions.append(description)

    if not descriptions:
        raise ValueError(
            "Planner did not return a valid numbered plan."
        )

    steps = [
        TaskPlanStep(
            id=index,
            description=description,
            status="pending",
        )
        for index, description in enumerate(
            descriptions,
            start=1,
        )
    ]

    return TaskPlan(
        goal=task,
        steps=steps,
    )


def create_replan(
    task: str,
    plan: list[dict],
    failed_steps: list[str],
    provider: str,
    model: str,
) -> TaskPlan:
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

    context = (
        f"Original task:\n{task}\n\n"
        f"Already completed:\n"
        + "\n".join(f"- {step}" for step in completed)
        + "\n\n"
        f"Remaining or blocked work:\n"
        + "\n".join(f"- {step}" for step in remaining)
        + "\n\n"
        f"Failures:\n"
        + "\n".join(f"- {failure}" for failure in failed_steps[-3:])
        + "\n\n"
        "Create a revised plan for ONLY the remaining work. "
        "Do not repeat completed work."
    )

    return create_plan(
        task=context,
        provider=provider,
        model=model,
    )


def revise_plan(
    task: str,
    plan: list[dict],
    revision: str,
    provider: str,
    model: str,
) -> TaskPlan:
    """Revise an existing user-visible plan without executing it."""

    plan_text = "\n".join(
        f"{step.get('id', index)}. {step.get('description', '')}"
        for index, step in enumerate(plan, start=1)
    )

    context = (
        f"Original task:\n{task}\n\n"
        f"Current plan:\n{plan_text}\n\n"
        f"User requested this plan change:\n{revision}\n\n"
        "Revise the current plan according to the user's request.\n"
        "Preserve steps that do not need to change.\n"
        "Return the complete revised plan.\n"
        "Do not execute anything."
    )

    return create_plan(
        task=context,
        provider=provider,
        model=model,
    )



def should_replan(
    task: str,
    plan: list[dict],
    failure: str,
    provider: str,
    model: str,
) -> bool:
    """Decide whether a failure invalidates the plan (REPLAN) or can be recovered within the plan (KEEP)."""
    llm = get_llm(
        provider=provider,
        model=model,
    )

    plan_lines = []
    for step in plan:
        plan_lines.append(
            f"{step.get('id', '')}. [{step.get('status', '')}] {step.get('description', '')}"
        )
    plan_text = "\n".join(plan_lines)

    response = llm.invoke([
        SystemMessage(
            content=(
                "Decide whether an existing execution plan should be kept "
                "or replaced after a failure.\n\n"

                "Return exactly one word: KEEP or REPLAN.\n\n"

                "KEEP when:\n"
                "- The overall strategy is still valid.\n"
                "- The failure is a local implementation/runtime problem.\n"
                "- The same planned approach can continue after a fix.\n"
                "- Examples: syntax errors, wrong paths, ordinary test failures, "
                "incorrect arguments, or recoverable command failures.\n\n"

                "REPLAN when:\n"
                "- The planned approach itself is no longer viable.\n"
                "- A required dependency, service, resource, API, file, or "
                "capability is unavailable and the task requires another approach.\n"
                "- Continuing the remaining plan would repeat or depend on the "
                "invalid assumption.\n"
                "- The strategy must change rather than merely fixing its "
                "implementation.\n\n"

                "Important distinction:\n"
                "If the implementation failed but the strategy remains valid, KEEP.\n"
                "If the strategy's required assumption is false and another "
                "strategy is required, REPLAN.\n\n"

                "Do not propose a solution. Return only KEEP or REPLAN."
            )
        ),
        HumanMessage(
            content=(
                f"Task:\n{task}\n\n"
                f"Current plan:\n{plan_text}\n\n"
                f"Recent failure:\n{failure}"
            )
        ),
    ])
    decision = _extract_decision(response.content)

    if decision == "REPLAN":
        return True

    return False


def start_next_plan_step(
    plan: list[dict],
) -> list[dict]:
    """Mark the next pending step as in_progress."""

    updated = [step.copy() for step in plan]

    # Don't start another step if one is already active.
    if any(
        step["status"] == "in_progress"
        for step in updated
    ):
        return updated

    for step in updated:
        if step["status"] == "pending":
            step["status"] = "in_progress"
            break

    return updated


def update_plan_from_tool(
    plan: list[dict],
    tool_name: str,
    tool_args: dict,
    failed: bool,
) -> list[dict]:
    """Update the active plan step from the tool operation."""

    updated = [step.copy() for step in plan]

    if failed:
        return updated

    active = next(
        (
            step
            for step in updated
            if step.get("status") == "in_progress"
        ),
        None,
    )

    if active is None:
        return updated

    description = active.get("description", "").lower()

    matched = False

    if tool_name in {"list_files", "read_file", "search_code"}:
        matched = any(
            word in description
            for word in (
                "inspect",
                "read",
                "find",
                "search",
                "check",
                "identify",
                "review",
            )
        )

    elif tool_name in {"write_file", "edit_file"}:
        matched = any(
            word in description
            for word in (
                "create",
                "write",
                "edit",
                "modify",
                "implement",
                "add",
                "update",
                "fix",
            )
        )

    elif tool_name in {
        "run_terminal",
        "check_terminal",
    }:
        matched = any(
            word in description
            for word in (
                "run",
                "execute",
                "test",
                "verify",
                "check",
            )
        )

    if not matched:
        return updated

    active["status"] = "completed"

    for step in updated:
        if step.get("status") == "pending":
            step["status"] = "in_progress"
            break

    return updated

def finalize_plan(
    plan: list[dict],
    task_succeeded: bool,
) -> list[dict]:
    """Finalize plan state after verified task completion."""

    updated = [step.copy() for step in plan]

    if not task_succeeded:
        return updated

    for step in updated:
        if step.get("status") in {
            "pending",
            "in_progress",
        }:
            step["status"] = "completed"

    return updated
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm.factory import get_llm
from src.models.plan_models import TaskPlan, TaskPlanStep
from src.prompts.planner_prompt import PLANNER_PROMPT
from src.context.context_engine import ContextEngine
from src.config.settings import CONTEXT_MODEL

# Planner context engine: no summarizer needed (planners don't see tool output history)
plan_context_engine = ContextEngine(max_tokens=4000, model=CONTEXT_MODEL, llm=None)


def _invoke_and_track(
    llm,
    messages: list,
    model: str,
    usage_list: list | None = None,
):
    """
    Call llm.invoke() and optionally record token usage.

    usage_list: If provided, appends a TokenUsage object for this call.
    """
    result = llm.invoke(messages)

    if usage_list is not None:
        from src.context.token_tracker import TokenTracker

        usage = TokenTracker.record_call(messages, result, model)
        usage_list.append(usage)

    return result


def _looks_like_plan_task(task: str) -> bool:
    """Deterministic fallback for obvious multi-step coding tasks."""
    text = task.lower()

    creation_words = (
        "create",
        "build",
        "add",
        "implement",
        "write",
        "fix",
        "update",
    )
    execution_words = (
        "run",
        "verify",
        "test",
        "execute",
        "confirm",
    )

    return (
        any(word in text for word in creation_words)
        and any(word in text for word in execution_words)
    )


def _extract_decision(response_content: object) -> str:
    answer = str(response_content).strip().upper()

    if "</THINK>" in answer:
        answer = answer.split("</THINK>", 1)[1].strip()

    return answer.split()[0] if answer else ""


def should_create_plan(
    task: str,
    provider: str,
    model: str,
    usage_list: list | None = None,
) -> bool:
    llm = get_llm(
        provider=provider,
        model=model,
    )

    messages = [
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
    ]

    response = _invoke_and_track(llm, messages, model, usage_list)

    decision = _extract_decision(response.content)

    if decision == "PLAN":
        return True

    if decision == "DIRECT":
        return _looks_like_plan_task(task)

    # Safe fallback: use deterministic heuristic for obvious multi-step tasks.
    return _looks_like_plan_task(task)


def create_plan(
    task: str,
    provider: str,
    model: str,
    usage_list: list | None = None,
) -> TaskPlan:
    """
    Create a plan from scratch.
    """
    messages = plan_context_engine.build_planner_messages(
        task=task,
        planner_prompt=PLANNER_PROMPT,
    )

    return _execute_plan_llm(messages, provider, model, task, usage_list=usage_list)


def create_replan(
    task: str,
    plan: list[dict],
    failed_steps: list[str],
    provider: str,
    model: str,
    prior_attempts: list[dict] | None = None,
    usage_list: list | None = None,
) -> TaskPlan:
    """
    Create a new plan when the old one failed.
    Now includes lessons from past attempts!
    """
    messages = plan_context_engine.build_replanner_messages(
        task=task,
        plan=plan,
        failed_steps=failed_steps,
        planner_prompt=PLANNER_PROMPT,
        prior_attempts=prior_attempts,
    )

    return _execute_plan_llm(messages, provider, model, task, usage_list=usage_list)


def revise_plan(
    task: str,
    plan: list[dict],
    revision: str,
    provider: str,
    model: str,
    usage_list: list | None = None,
) -> TaskPlan:
    """Revise an existing user-visible plan without executing it."""
    messages = plan_context_engine.build_reviser_messages(
        task=task,
        plan=plan,
        revision=revision,
        planner_prompt=PLANNER_PROMPT,
    )

    return _execute_plan_llm(messages, provider, model, task, usage_list=usage_list)


def _execute_plan_llm(
    messages: list,
    provider: str,
    model: str,
    task: str,
    usage_list: list | None = None,
) -> TaskPlan:
    """
    Shared helper: Send messages to LLM and parse the plan.
    """
    llm = get_llm(provider=provider, model=model)

    result = _invoke_and_track(llm, messages, model, usage_list)

    content = str(result.content).strip()

    # Reasoning models may include internal text before the actual plan
    if "</think" in content.lower():
        lower_content = content.lower()
        end_index = lower_content.rfind("</think")
        if end_index != -1:
            closing_index = content.find(">", end_index)
            if closing_index != -1:
                content = content[closing_index + 1:].strip()
            else:
                content = content[end_index + len("</think"):].strip()

    descriptions = []
    seen_descriptions = set()

    skip_phrases = (
        "analyze the request",
        "determine steps",
        "refine steps",
        "final polish",
        "output generation",
        "final output construction",
        "thinking process",
        "reasoning",
        "final plan formulation",
        "analyze the current plan",
        "apply constraints",
        "drafting the revised plan",
        "refining the steps",
        "double check",
        "check constraints",
    )

    for line in content.splitlines():
        line = line.strip()

        match = re.match(
            r"^\d+[\.\)]\s*(.+)$",
            line,
        )

        if not match:
            continue

        description = match.group(1).strip()
        description = description.strip(" -*`")

        lowered = description.lower().strip()

        if not description or lowered.endswith(":"):
            continue

        if any(phrase in lowered for phrase in skip_phrases):
            continue

        if lowered in {"eat apple", "eat orange"}:
            continue

        normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()

        if normalized in seen_descriptions:
            continue

        seen_descriptions.add(normalized)
        descriptions.append(description)

        # Plans should stay concise. This also prevents runaway reasoning output
        # from becoming a 50+ step plan.
        if len(descriptions) >= 12:
            break

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

def should_replan(
    task: str,
    plan: list[dict],
    failure: str,
    provider: str,
    model: str,
    usage_list: list | None = None,
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

    messages = [
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
    ]

    response = _invoke_and_track(llm, messages, model, usage_list)
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
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


# Obvious single-action questions — DIRECT by the classifier prompt's own
# definition ("explaining something"). Measured why this list exists
# (founder-pbr004-1): the model returned a confident-wrong PLAN for
# "Summarize the workspace." and the plan loop burned 20 full-context laps
# (21 calls / 118k tokens / $0.12) to answer one question.
_DIRECT_QUESTION_PATTERNS = (
    "summarize",
    "explain",
    "describe",
    "what is",
    "what are",
    "why is",
    "why does",
    "how does",
    "tell me about",
    "list the",
    "show me",
)


def _looks_like_direct_question(task: str) -> bool:
    """Obvious one-step question that must never enter the plan loop —
    and must not even spend the PLAN/DIRECT classifier call."""
    text = str(task).lower().strip()
    if not text or len(text) > 200:
        return False  # long prompts may genuinely need steps
    if _looks_like_plan_task(text):
        return False  # creation+execution pairs outrank question verbs
    return any(p in text for p in _DIRECT_QUESTION_PATTERNS)


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
    # Obvious one-step questions never enter the plan loop and never spend
    # the classifier call (founder-pbr004-1: "Summarize the workspace." got
    # a wrong PLAN verdict and cost 20 full-context laps).
    if _looks_like_direct_question(task):
        return False

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
        # Measured override (founder-pbr004-1): a confident-wrong PLAN on an
        # obvious one-step question is overridden — the heuristic only wins
        # when the task is NOT also an obvious multi-step plan task.
        return not _looks_like_direct_question(task)

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

def check_ambiguity(
    task: str,
    provider: str,
    model: str,
    usage_list: list | None = None,
) -> str | None:
    """
    Check if the task is ambiguous and needs clarification.
    Returns the clarification question or None.
    """
    llm = get_llm(provider=provider, model=model)
    
    messages = [
        SystemMessage(content=(
            "You are a senior developer analyzing a task for potential ambiguity.\n"
            "If the task is clear, return 'CLEAR'.\n"
            "If the task is missing critical info (paths, libs, specific behavior), "
            "ask a concise, targeted question to clarify.\n\n"
            "Ambiguity Examples:\n"
            "- 'Fix the bug' (Which bug? Where?)\n"
            "- 'Build a website' (What kind? Using what tech?)\n"
            "- 'Add a feature' (Which feature? To which file?)\n\n"
            "Non-Ambiguity Examples:\n"
            "- 'Read main.py and explain it'\n"
            "- 'Run tests in src/tests/'\n"
            "- 'Create a hello world script in Python'\n"
        )),
        HumanMessage(content=task)
    ]
    
    response = _invoke_and_track(llm, messages, model, usage_list)
    result = str(response.content).strip()
    
    if result.upper() == "CLEAR":
        return None
        
    return result

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


_READ_TOOLS = frozenset({"list_files", "read_file", "search_code", "session_search"})
_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


def required_tool_receipts(description: str) -> dict[str, int]:
    """Infer the minimum evidence contract for a plan step.

    Hermes does not trust a prose plan status: completion is projected from
    durable tool receipts. Keep this generic and description-driven so focused
    IDE profiles gain strictness without hardcoding benchmark filenames.
    """
    d = (description or "").lower()
    required: dict[str, int] = {}

    def need(name: str, count: int = 1) -> None:
        required[name] = max(required.get(name, 0), count)

    if "screenshot" in d or "visual proof" in d:
        need("browser_screenshot")
    if "browser_navigate" in d or "navigate" in d and "browser" in d:
        need("browser_navigate")
    if "browser_snapshot" in d or "snapshot" in d and "browser" in d:
        need("browser_snapshot")
    if "typecheck" in d or "tsc" in d or "type check" in d:
        need("typecheck_workspace")
    if "scaffold" in d:
        need("scaffold_nextjs")
    if "copy" in d:
        # A single plan step that explicitly joins two copy deliverables must
        # receive two copy receipts. Repeated source markers are the strongest
        # signal; "both" is a conservative fallback.
        source_mentions = d.count("_provided/")
        need("copy_file", max(2 if "both" in d else 1, source_mentions))
    if "start" in d and ("server" in d or "development" in d):
        need("start_terminal")
    if "ready" in d and "server" in d:
        need("check_terminal")
    if "verify" in d and not required:
        need("verify")
    if any(word in d for word in ("create", "write", "edit", "modify", "implement", "update", "fix")) \
            and not any(k in required for k in ("typecheck_workspace", "browser_screenshot")):
        # Alternatives are represented by a synthetic receipt family. When a
        # step names several concrete files, require one landed mutation per
        # file so the first write cannot advance a four-file batch to verify.
        paths = set(re.findall(
            r"`([^`]+\.(?:py|ts|tsx|js|jsx|css|html|json|md|yaml|yml|toml))`",
            description or "", re.IGNORECASE,
        ))
        need("__file_mutation__", max(1, min(len(paths), 12)))
    if any(word in d for word in ("inspect", "read", "find", "search", "identify", "review")) \
            and not required:
        need("__read__")
    if "install" in d and "scaffold_nextjs" not in required:
        need("__install__")
    return required


def _receipt_name(tool_name: str) -> tuple[str, ...]:
    names = [tool_name]
    if tool_name in {"verify_ui_workspace", "verify_ui_routes"}:
        names.extend((
            "typecheck_workspace", "start_terminal", "check_terminal",
            "browser_navigate", "browser_snapshot", "browser_screenshot",
        ))
    if tool_name in _READ_TOOLS:
        names.append("__read__")
    if tool_name in _WRITE_TOOLS:
        names.append("__file_mutation__")
    if tool_name in {"run_terminal", "scaffold_nextjs"}:
        names.append("__install__")
    return tuple(names)


def required_file_paths(description: str) -> set[str]:
    return set(re.findall(
        r"`([^`]+\.(?:py|ts|tsx|js|jsx|css|html|json|md|yaml|yml|toml))`",
        description or "", re.IGNORECASE,
    ))


def step_receipts_satisfied(step: dict) -> bool:
    description = str(step.get("description", ""))
    required = required_tool_receipts(description)
    if not required:
        return bool(step.get("evidence_receipts"))
    observed = step.get("evidence_receipts") or {}
    paths = required_file_paths(description)
    if paths and "__file_mutation__" in required:
        landed = set(step.get("evidence_paths") or [])
        if not paths.issubset(landed):
            return False
    return all(int(observed.get(name, 0)) >= count for name, count in required.items())


def update_plan_from_tool(
    plan: list[dict],
    tool_name: str,
    tool_args: dict,
    failed: bool,
    result: str = "",
) -> list[dict]:
    """Advance only when the active step's evidence contract is satisfied."""
    updated = [step.copy() for step in plan]
    if failed:
        return updated
    active = next((s for s in updated if s.get("status") == "in_progress"), None)
    if active is None:
        return updated

    description = str(active.get("description", "")).lower()
    required = required_tool_receipts(description)
    receipt_names = _receipt_name(tool_name)
    if required and not any(name in required for name in receipt_names):
        return updated
    if not required:
        # Conservative fallback for prose the contract parser does not know:
        # only semantically compatible tool families may advance it.
        compatible = (
            (tool_name in _READ_TOOLS and any(w in description for w in ("inspect", "read", "find", "search", "review")))
            or (tool_name in _WRITE_TOOLS and any(w in description for w in ("create", "write", "edit", "modify", "implement", "add", "update", "fix")))
            or (tool_name in {"run_terminal", "check_terminal"} and any(w in description for w in ("run", "execute", "test", "check")))
            or (tool_name == "verify" and "verify" in description)
        )
        if not compatible:
            return updated

    # A running terminal is not readiness evidence. Likewise a browser/tool
    # result that plainly failed cannot satisfy a prose step merely because the
    # tool was invoked.
    low_result = (result or "").lower()
    if (
        tool_name == "check_terminal"
        and "status: running" in low_result
        and not any(marker in low_result for marker in ("ready in", "local:", "listening on"))
    ):
        return updated
    if any(marker in low_result for marker in (
        "timed out", "failed to navigate", "internal server error",
        "visual quality failed", "error: screenshot",
    )):
        return updated

    required_paths = required_file_paths(description)
    if tool_name in _WRITE_TOOLS | {"copy_file"} and required_paths:
        landed_path = str(tool_args.get("path") or tool_args.get("dst") or "")
        matched_path = landed_path if landed_path in required_paths else next(
            (p for p in required_paths if p.rsplit("/", 1)[-1] == landed_path.rsplit("/", 1)[-1]),
            "",
        )
        if not matched_path:
            return updated
        landed = set(active.get("evidence_paths") or [])
        # A rewrite of the same path is repair evidence, not delivery of a
        # second named file.
        already_landed = matched_path in landed
        landed.add(matched_path)
        active["evidence_paths"] = sorted(landed)
    else:
        already_landed = False

    receipts = dict(active.get("evidence_receipts") or {})
    for name in receipt_names:
        if name == "__file_mutation__" and already_landed:
            continue
        receipts[name] = receipts.get(name, 0) + 1
    active["evidence_receipts"] = receipts

    if required and not step_receipts_satisfied(active):
        return updated
    if not required and not receipts:
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
    """Preserve receipt truth; finalization never fabricates completed steps."""
    updated = [step.copy() for step in plan]
    if not task_succeeded:
        return updated
    for step in updated:
        if step.get("status") in {"pending", "in_progress"} and step_receipts_satisfied(step):
            step["status"] = "completed"
    return updated

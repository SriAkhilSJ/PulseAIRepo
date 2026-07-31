from typing import Annotated
from typing_extensions import TypedDict
# pyrefly: ignore [missing-import]
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    AIMessage,
)
from typing import Literal,cast,Any
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, AliasChoices
# pyrefly: ignore [missing-import]
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# pyrefly: ignore [missing-import]
from langgraph.checkpoint.memory import MemorySaver
# pyrefly: ignore [missing-import]
from langgraph.graph import StateGraph, START, END
# pyrefly: ignore [missing-import]
from langgraph.graph.message import add_messages
# pyrefly: ignore [missing-import]
from langgraph.prebuilt import ToolNode

from src.config.settings import LLM_PROVIDER, LLM_MODEL
from src.llm.factory import get_llm
from src.context.context_engine import ContextEngine
from src.context.memory_manager import MemoryManager
from src.context.token_tracker import TokenTracker, TokenUsage
from src.agents.planner import (
    create_plan,
    create_replan,
    revise_plan,
    should_create_plan,
    should_replan,
    start_next_plan_step,
    update_plan_from_tool,
    finalize_plan,
)
from src.tools.file_tools import (
    read_file,
    list_files,
    search_code,
    write_file,
    edit_file,
)

from src.tools.math_tools import add

from src.tools.terminal_tools import (
    run_terminal,
    start_terminal,
    check_terminal,
    stop_terminal,
    list_terminal_processes,
    cleanup_terminal_processes,
    read_terminal_output
)
from src.tools.web_tools import web_search, web_fetch

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
    prior_attempts: list[dict[str, Any]]  # NEW: Summarized history of past attempts
    token_usage: dict[str, Any]  # Tracks tokens and cost for this task
    workspace: str  # Root path of the active project
# =========================================================
# TOOLS
# =========================================================

@tool
def think(reasoning: str) -> str:
    """
    Record your reasoning before taking a meaningful action.

    WHEN TO USE:
    - Before reading, writing, editing, running commands, searching code, or using web tools.
    - When deciding the next step in a plan.
    - When diagnosing an error or choosing a recovery strategy.

    Include what you are trying to do, why this approach is appropriate,
    what could go wrong, and how you will verify success.
    """
    return f"[THINKING RECORDED] {reasoning[:500]}"


@tool
def verify(
    step_description: str,
    expected_result: str,
    actual_result: str,
    success: bool,
) -> str:
    """
    Verify the result of the previous meaningful action.

    WHEN TO USE:
    - After read_file, write_file, edit_file, run_terminal, search_code, web_search, or web_fetch.
    - Before moving to the next plan step after a tool result.
    - When deciding whether to continue, retry, fix, or replan.

    Do not call verify to verify another verify call.
    """
    if success:
        return "VERIFIED: Step completed successfully. Proceed to the next step."

    return (
        "VERIFICATION FAILED: "
        f"Expected {expected_result!r}, got {actual_result!r}. "
        "Diagnose and fix before proceeding."
    )


@tool
def ask_user(question: str) -> str:
    """
    Ask the user a clarifying question when the request is ambiguous.

    WHEN TO USE:
    - The user did not specify a required file name, library, format, or approach.
    - Multiple valid interpretations exist and choosing one would be risky.
    - You are about to make an irreversible or destructive change.

    WHEN NOT TO USE:
    - Do not ask for errors you can diagnose with tools.
    - Do not ask if the repo map, files, or tests provide enough information.
    """
    return f"[WAITING FOR USER] {question}"


tools = [
    think,
    verify,
    ask_user,

    add,

    # File tools
    read_file,
    list_files,
    search_code,
    write_file,
    edit_file,

    # Terminal tools
    run_terminal,
    start_terminal,
    check_terminal,
    stop_terminal,
    list_terminal_processes,
    cleanup_terminal_processes,
    read_terminal_output,

    # Web tools
    web_search,
    web_fetch,
]


# =========================================================
# SYSTEM PROMPT
# =========================================================

system_message = SystemMessage(
    content="""You are PulseCodeAI, an expert coding agent. You solve coding tasks by thinking, planning, acting, and verifying.

=== MANDATORY WORKFLOW ===

For every user request, follow this sequence. Do not skip verification.

STEP 1 - THINK:
Before using a meaningful action tool, reason explicitly. Prefer calling think() first for non-trivial tool use.
Your reasoning should answer:
- What does the user want?
- What do I already know from context, repo map, memory, and plan?
- What is the next logical step?
- Which tool is appropriate?
- What could go wrong?
- How will I verify success?

STEP 2 - ACT:
Use tools to perform the work. Use at most ONE non-meta action tool per turn.
Meta tools are think(), verify(), and ask_user(); do not get stuck repeatedly calling meta tools.

STEP 3 - VERIFY:
After receiving output from a meaningful action tool, evaluate the result before proceeding:
- Did the command/file/search operation succeed?
- Is the output what I expected?
- Are there errors? If yes, what is the root cause?
- Should I proceed, fix something, ask the user, or replan?
Use verify() when the result needs explicit validation. Do not verify a verify() call.

STEP 4 - REPORT:
When the task is complete, tell the user what you did and the verified result. Be specific:
- Files changed
- Commands run
- Outputs verified
- Errors encountered and fixes applied

=== TOOL SELECTION RULES ===

Choose tools using this decision tree:

Need to see what is in a file?
-> read_file(path)

Need to change a small part of an existing file?
-> edit_file(path, old_text, new_text) after read_file

Need to create a new file or overwrite entirely?
-> write_file(path, content)

Need to run a command, install packages, or test code?
-> run_terminal(command) for short commands
-> start_terminal(command) for long-running commands

Do not know where something is?
-> Check the repo map first, then use search_code(query, path) or list_files(path)

Need current external docs, unknown APIs, or unfamiliar errors?
-> web_search(query), then web_fetch(url) for promising results

Need to ask before choosing an approach?
-> ask_user(question)

=== TOOL DESCRIPTIONS AND WHEN TO USE ===

- think: Record reasoning before meaningful actions. Use it to slow down and avoid impulsive wrong tool calls.
- verify: Check whether the previous meaningful action produced the expected result. Use it before moving to the next step when success is not obvious.
- ask_user: Ask a clarifying question when ambiguity would cause risky guessing.
- read_file: Read file contents. Use before editing existing files and to verify file contents.
- list_files: Inspect directories. Use when the repo map is insufficient.
- search_code: Search recursively for code/text. Use to find symbols, imports, examples, or errors.
- write_file: Create or overwrite files. Use for new files or full replacements.
- edit_file: Replace exact existing text in a file. Preferred for small edits.
- run_terminal: Run short commands and tests. Inspect exit code/output.
- start_terminal/check_terminal/read_terminal_output/stop_terminal: Manage long-running processes.
- web_search/web_fetch: Verify external documentation, package names, APIs, and unfamiliar errors.

=== ERROR HANDLING ===

When you see an error, follow this exact pattern:

1. READ the error message carefully. Quote the relevant part internally.
2. IDENTIFY the root cause:
   - File not found -> wrong path or file does not exist
   - ModuleNotFoundError -> missing package or wrong environment
   - SyntaxError -> invalid syntax at a specific line
   - Permission denied -> permissions or unsafe path
   - Port already in use -> existing process or wrong port
   - Unknown API/config -> web_search documentation
3. FIX the root cause with the smallest appropriate change.
4. RETRY or verify the original step.
5. If it fails 3 times, stop automatic recovery and ask the user or report the blocker.

Never claim success unless the relevant tool output proves it. Never invent file contents, terminal output, process state, or search results.

=== PLAN FOLLOWING ===

- If a plan exists, follow it step by step.
- Mark steps complete only after verified success.
- If a step fails, fix it before moving to the next step.
- If all plan steps are complete, finalize instead of calling more tools.
- If the plan is clearly wrong or based on a false assumption, trigger replanning rather than ignoring the plan.

=== CLARIFICATION ===

If the user's request is ambiguous and tools/context cannot resolve it, ask before acting:
- Do you want pandas or the standard csv module?
- Should I overwrite the existing file or create a backup?
- What should the output file be named?

Do not ask unnecessary questions when a safe, conventional default exists or the repo/tests make the answer clear.

=== VERIFICATION CHECKLIST ===

Before finalizing, verify:
- All plan steps are completed or the direct task is done
- Code runs without errors when runnable
- Output matches what the user asked for
- Relevant edge cases are handled: missing files, empty input, invalid data, bad paths
- Any changed files contain the intended content

=== CONTEXT AWARENESS ===

You receive layered context from the Context Engine:
- Repo map / codebase structure
- Current task and latest instruction
- Active plan
- Successful and failed steps
- Recovery and replan status
- Long-term memories
- Trimmed/summarized history

Use this context. Do not ignore previous failures, completed steps, or repo map paths.

=== OUTPUT FORMAT ===

When responding to the user:
1. Start with a brief summary of what you did.
2. Mention specific files changed.
3. Mention commands run and results.
4. Mention verification outcome.
5. If there are warnings or edge cases, note them.
6. Keep normal responses concise.

=== TASK STATE PRIVACY ===

Task state is internal metadata. Do not expose raw internal field names such as current_task, task_action, task_status, token_usage, recovery_command, or prior_attempts unless the user explicitly asks for diagnostics/status.

=== SELF-CORRECTION ===

If you realize you made a mistake:
1. Stop the mistaken path.
2. Acknowledge the correction briefly if user-visible.
3. Use tools to inspect or fix the issue.
4. Verify the corrected result.

Never pretend a failed step succeeded. Never ignore errors.
"""
)



def _zero_token_usage() -> dict[str, Any]:
    """Return an empty token usage snapshot."""
    return TokenUsage().to_dict()


def _merge_token_usage(existing: dict[str, Any] | None, additions: list[TokenUsage]) -> dict[str, Any]:
    """Merge a list of TokenUsage records into an existing state snapshot."""
    total = TokenUsage.from_dict(existing)

    for usage in additions:
        total = total + usage

    return total.to_dict()


# =========================================================
# AI NODE (with Context Engine)
# =========================================================
def ai_node(
    state: AgentState,
    config: RunnableConfig,
):
    configurable = config["configurable"]

    provider = configurable["provider"]
    model = configurable["model"]

    llm = get_llm(
        provider=provider,
        model=model,
    )

    llm_with_tools = llm.bind_tools(tools)

    # Use the Context Engine to build clean, organized messages.
    messages = context_engine.build_ai_messages(
        state=dict(state),
        system_message=system_message,
    )

    result = llm_with_tools.invoke(messages)

    # =========================================================
    # TRACK TOKEN USAGE
    # =========================================================
    call_usage = TokenTracker.record_call(messages, result, model)
    token_usage = _merge_token_usage(
        state.get("token_usage", {}),
        [call_usage],
    )

    return {
        "messages": [result],
        "token_usage": token_usage,
    }


# =========================================================
# ROUTING
# =========================================================

def should_continue(state: AgentState):
    last_message = state["messages"][-1]

    if getattr(last_message, "tool_calls", None):
        return "tools"

    return "finalize"

def finalize_node(state: AgentState):
    plan = finalize_plan(
        plan=list(state.get("plan", [])),
        task_succeeded=True,
    )

    # Store successful task in long-term memory.
    # This helps the agent remember what worked for similar future tasks.
    current_task = state.get("current_task", "")
    steps_completed = state.get("steps_completed", [])

    if current_task and steps_completed:
        memory_manager.store_task_completion(
            task=current_task,
            steps_completed=steps_completed,
            plan=plan,
        )

    return {
        "plan": plan,
        "task_completed": True,
    }


def is_plan_approval(message: str) -> bool:
    normalized = message.strip().lower()

    approvals = {
        "approve",
        "approved",
        "execute",
        "execute plan",
        "run plan",
        "proceed",
        "go ahead",
        "continue",
        "yes",
    }

    return normalized in approvals


def is_plan_revision(message: str) -> bool:
    normalized = message.strip().lower()

    revision_signals = (
        "change ",
        "modify ",
        "update ",
        "replace ",
        "remove ",
        "add ",
        "instead",
        "revise ",
    )

    return any(
        signal in normalized
        for signal in revision_signals
    )


def is_plan_cancellation(message: str) -> bool:
    normalized = message.strip().lower()

    cancellations = {
        "cancel",
        "cancel plan",
        "reject",
        "reject plan",
        "discard",
        "discard plan",
        "stop",
        "never mind",
        "nevermind",
    }

    return normalized in cancellations


# =========================================================
# TASK NODE
# =========================================================
def task_manager_node(
    state: AgentState,
    config: RunnableConfig,
):
    configurable = config["configurable"]

    provider = configurable["provider"]
    model = configurable["model"]

    current_task = state.get("current_task", "")
    latest_instruction = state["latest_instruction"]

    if (
        is_plan_cancellation(latest_instruction)
        and state.get("plan_created")
        and state.get("plan")
    ):
        return {
            "current_task": "",
            "plan": [],
            "plan_goal": "",
            "plan_created": False,
            "plan_approved": False,
            "plan_revision_count": 0,
            "replan_needed": False,
            "replan_count": 0,
            "steps_completed": [],
            "failed_steps": [],
            "execution_trace": [],
            "task_action": "plan_cancelled",
            "task_status": "cancelled",
            "task_completed": False,
            "prior_attempts": [],
            "token_usage": _zero_token_usage(),
            "workspace": config["configurable"].get("workspace", "."),
        }

    if (
        is_plan_approval(latest_instruction)
        and state.get("plan_created")
        and state.get("plan")
    ):
        return {
            "execution_mode": "agent",
            "plan_approved": True,
            "task_action": "execute_approved_plan",
            "current_task": state.get(
                "plan_goal",
                state.get("current_task", ""),
            ),
            "token_usage": state.get("token_usage", _zero_token_usage()),
            "workspace": config["configurable"].get("workspace", "."),
        }

    if is_plan_approval(latest_instruction):
        return {
            "task_action": "approval_without_plan",
            "task_status": "idle",
            "plan_approved": False,
            "token_usage": state.get("token_usage", _zero_token_usage()),
        }

    if (
        state.get("execution_mode") == "plan"
        and state.get("plan_created")
        and state.get("plan")
        and is_plan_revision(latest_instruction)
    ):
        return {
            "task_action": "revise_plan",
            "latest_instruction": latest_instruction,
            "token_usage": state.get("token_usage", _zero_token_usage()),
        }

    # First turn: there is no previous active task.
    if not current_task:
        return {
            "current_task": latest_instruction,
            "task_status": "in_progress",
            "task_action": "new",
            "steps_completed": [],
            "failed_steps": [],
            "recovery_attempts": 0,
            "recovery_mode": False,
            "tool_failures": 0,
            "recovery_command": None,
            "plan": [],
            "plan_goal": "",
            "plan_created": False,
            "plan_approved": False,
            "plan_revision_count": 0,
            "replan_needed": False,
            "replan_count": 0,
            "execution_trace": [],
            "task_completed": False,
            "prior_attempts": [],
            "token_usage": _zero_token_usage(),
            "workspace": config["configurable"].get("workspace", "."),
        }

    llm = get_llm(
        provider=provider,
        model=model,
    )

    task_llm = llm.with_structured_output(
        TaskDecision
    )

    task_messages = [
        SystemMessage(
            content="""
You manage the active task for an AI coding agent.

Classify the latest user instruction as:

new:
The user is starting a different coding task.

continue:
The instruction refers to, modifies, extends, or continues
the existing active task.

unrelated:
The message is conversational, informational, or otherwise
should not replace the active coding task.

For "continue", updated_task must describe the complete
task including the new instruction.

For "new", updated_task must be the new task.

For "unrelated", preserve the existing active task exactly.
"""
        ),
        HumanMessage(
            content=(
                f"Current active task:\n{current_task}\n\n"
                f"Latest instruction:\n{latest_instruction}"
            )
        ),
    ]

    decision = cast(
        TaskDecision,
        task_llm.invoke(task_messages),
    )

    call_usage = TokenTracker.record_call(task_messages, decision, model)

    if decision.action == "new":
        token_usage = _merge_token_usage(
            _zero_token_usage(),
            [call_usage],
        )
    else:
        token_usage = _merge_token_usage(
            state.get("token_usage", {}),
            [call_usage],
        )

    if decision.action == "unrelated":
        updated_task = current_task
    elif decision.updated_task:
        updated_task = decision.updated_task
    else:
        updated_task = current_task

    if decision.action == "new":
        return {
            "current_task": updated_task,
            "task_action": decision.action,
            "task_status": "in_progress",
            "steps_completed": [],
            "failed_steps": [],
            "recovery_attempts": 0,
            "tool_failures": 0,
            "recovery_mode": False,
            "recovery_command": None,
            "plan": [],
            "plan_goal": "",
            "plan_created": False,
            "plan_approved": False,
            "plan_revision_count": 0,
            "replan_needed": False,
            "replan_count": 0,
            "execution_trace": [],
            "task_completed": False,
            "prior_attempts": [],
            "token_usage": token_usage,
            "workspace": config["configurable"].get("workspace", "."),
        }

    return {
        "current_task": updated_task,
        "task_action": decision.action,
        "token_usage": token_usage,
        "workspace": config["configurable"].get("workspace", "."),
    }

def progress_node(
    state: AgentState,
    config: RunnableConfig,
):
    """Track successful and failed tool operations."""

    messages = state.get("messages", [])

    plan = list(
        state.get("plan", [])
    )

    steps_completed = list(
        state.get("steps_completed", [])
    )

    failed_steps = list(
        state.get("failed_steps", [])
    )
    
    execution_trace = list(
        state.get("execution_trace", [])
    )
    recovery_attempts = state.get(
    "recovery_attempts",
    0,
)
    recovery_mode = state.get("recovery_mode", False)
    tool_failures = state.get("tool_failures", 0)
    recovery_command = state.get(
    "recovery_command"
)
    replan_needed = state.get("replan_needed", False)
    total_usage = TokenUsage.from_dict(state.get("token_usage", {}))

    # ==========================================
    # FIND LATEST TOOL MESSAGES
    # ==========================================

    latest_tools: list[ToolMessage] = []

    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            latest_tools.append(message)
        else:
            break

    latest_tools.reverse()

    # ==========================================
    # PROCESS TOOL MESSAGES
    # ==========================================

    for message in latest_tools:
        tool_name = message.name or "unknown_tool"
        result = str(message.content)
        result_lower = result.lower()

        # ------------------------------------------
        # Find matching tool arguments FIRST
        # ------------------------------------------

        tool_args = {}

        for previous_message in reversed(messages):
            if not hasattr(previous_message, "tool_calls"):
                continue

            for tool_call in previous_message.tool_calls:
                if tool_call.get("id") == message.tool_call_id:
                    tool_args = tool_call.get("args", {})
                    break

            if tool_args:
                break

        # ------------------------------------------
        # Determine success / failure
        # ------------------------------------------

        failed = (
            "error:" in result_lower
            or "traceback" in result_lower
            or "unknown process id" in result_lower
            or "path escapes workspace" in result_lower
        )

        if tool_name == "run_terminal":
            if "exit code: 0" not in result_lower:
                failed = True

        elif tool_name == "check_terminal":
            if "status: running" in result_lower:
                continue

            if "status: completed" in result_lower:
                if "exit code: 0" not in result_lower:
                    failed = True

        # ------------------------------------------
        # Record trace
        # ------------------------------------------
        trace_entry = {
            "type": "tool",
            "tool": tool_name,
            "args": tool_args.copy(),
            "status": "failed" if failed else "success",
            "result": result[-1000:],
        }
        execution_trace.append(trace_entry)

        # ------------------------------------------
        # Record failure
        # ------------------------------------------

        if failed:
            tool_failures += 1

            if tool_name == "run_terminal":
                command = tool_args.get(
                    "command",
                    "unknown command",
                )

                # Every failed terminal execution counts.
                recovery_attempts += 1

                if not recovery_mode:
                    recovery_mode = True
                    recovery_command = command

                failure = (
                    f"Command failed: {command}\n"
                    f"Actual tool output:\n{result[-3000:]}"
                )

            elif tool_name == "check_terminal":
                process_id = tool_args.get(
                    "process_id",
                    "unknown",
                )

                recovery_attempts += 1

                if not recovery_mode:
                    recovery_mode = True
                    recovery_command = f"process:{process_id}"

                failure = (
                    f"Terminal process failed: {process_id}\n"
                    f"Actual tool output:\n{result[-3000:]}"
                )

            else:
                if recovery_mode:
                    recovery_attempts += 1

                failure = f"Tool failed: {tool_name}"

            if failure not in failed_steps:
                failed_steps.append(failure)

            if plan:
                configurable = config["configurable"]

                usages: list[TokenUsage] = []

                replan_needed = should_replan(
                    task=state.get("current_task", ""),
                    plan=plan,
                    failure=failure,
                    provider=configurable["provider"],
                    model=configurable["model"],
                    usage_list=usages,
                )

                for usage in usages:
                    total_usage = total_usage + usage

            continue

        # ------------------------------------------
        # Record success
        # ------------------------------------------

        if plan:
            plan = update_plan_from_tool(
                plan=plan,
                tool_name=tool_name,
                tool_args=tool_args,
                failed=False,
            )

        if tool_name == "read_file":
            path = tool_args.get("path", "unknown")
            step = f"Read file: {path}"

        elif tool_name == "write_file":
            path = tool_args.get("path", "unknown")
            step = f"Wrote file: {path}"

        elif tool_name == "edit_file":
            path = tool_args.get("path", "unknown")
            step = f"Edited file: {path}"

        elif tool_name == "search_code":
            query = tool_args.get("query", "")
            path = tool_args.get("path", ".")
            step = f"Searched for '{query}' inside {path}"

        elif tool_name == "list_files":
            path = tool_args.get("path", ".")
            step = f"Listed files: {path}"

        elif tool_name == "run_terminal":
            command = tool_args.get(
                "command",
                "unknown command",
            )
            step = f"Ran command successfully: {command}"

            # Recovery only finishes when the SAME operation
            # that originally failed now succeeds.
            if (
                recovery_mode
                and recovery_command is not None
                and command == recovery_command
            ):
                recovery_mode = False
                recovery_command = None

        elif tool_name == "start_terminal":
            command = tool_args.get(
                "command",
                "unknown command",
            )
            step = f"Started background command: {command}"

        elif tool_name == "check_terminal":
            process_id = tool_args.get(
                "process_id",
                "unknown",
            )
            step = (
                "Terminal process completed successfully: "
                f"{process_id}"
            )

        elif tool_name == "stop_terminal":
            process_id = tool_args.get(
                "process_id",
                "unknown",
            )
            step = f"Stopped terminal process: {process_id}"

        else:
            step = f"Completed tool: {tool_name}"

        if step not in steps_completed:
            steps_completed.append(step)

    # ==========================================
    # RETURN AFTER THE LOOP
    # ==========================================

    result = {
        "steps_completed": steps_completed,
        "failed_steps": failed_steps,
        "tool_failures": tool_failures,
        "recovery_mode": recovery_mode,
        "recovery_command": recovery_command,
        "recovery_attempts": recovery_attempts,
        "plan": plan,
        "replan_needed": replan_needed,
        "execution_trace": execution_trace,
        "token_usage": total_usage.to_dict(),
    }

    if latest_tools:
        result["messages"] = [
            SystemMessage(
                content=(
                    "TOOL RESULT RECEIVED. Before the next meaningful action, "
                    "verify whether the previous tool output succeeded, whether "
                    "it matched expectations, and whether to proceed, fix, or replan. "
                    "Do not call verify() just to verify think(), verify(), or ask_user()."
                )
            )
        ]

    return result


def is_plan_complete(state: AgentState) -> bool:
    plan = state.get("plan", [])

    if not plan:
        return False

    return all(
        step.get("status") == "completed"
        for step in plan
    )


def after_progress(state: AgentState) -> str:
    recovery_mode = state.get("recovery_mode", False)
    recovery_attempts = state.get("recovery_attempts", 0)

    if recovery_mode and recovery_attempts >= 3:
        return "recovery_limit"

    if state.get("replan_needed", False):
        return "replanner"

    # If the active plan is complete after tool execution, stop instead of
    # giving weaker/cheap models another chance to keep calling tools forever.
    if is_plan_complete(state):
        return "finalize"

    return "ai"

def recovery_limit_node(state: AgentState):
    failed_steps = state.get("failed_steps", [])

    if failed_steps:
        latest_failure = failed_steps[-1]
    else:
        latest_failure = "Unknown failure"

    return {
        "messages": [
            AIMessage(
                content=(
                    "Automatic recovery stopped after 3 failed "
                    "attempts. The latest recorded failure was:\n\n"
                    f"{latest_failure}\n\n"
                    "Further automatic retries were stopped to avoid "
                    "an unproductive recovery loop."
                )
            )
        ]
    }

# =========================================================
# PLANNER NODE
# =========================================================

def planner_node(
    state: AgentState,
    config: RunnableConfig,
):
    current_task = state.get("current_task", "")
    plan_created = state.get("plan_created", False)

    configurable = config["configurable"]
    provider = configurable["provider"]
    model = configurable["model"]

    # Keep the existing plan for the active task.
    if plan_created:
        return {}

    # Nothing meaningful to plan.
    if not current_task:
        return {}

    usages: list[TokenUsage] = []

    needs_plan = should_create_plan(
        task=current_task,
        provider=provider,
        model=model,
        usage_list=usages,
    )

    if not needs_plan:
        token_usage = _merge_token_usage(
            state.get("token_usage", {}),
            usages,
        )

        return {
            "plan": [],
            "plan_goal": "",
            "plan_created": False,
            "token_usage": token_usage,
        }

    task_plan = create_plan(
        task=current_task,
        provider=provider,
        model=model,
        usage_list=usages,
    )

    token_usage = _merge_token_usage(
        state.get("token_usage", {}),
        usages,
    )

    plan = [
        step.model_dump()
        for step in task_plan.steps
    ]

    plan = start_next_plan_step(plan)

    return {
        "plan": plan,
        "plan_goal": task_plan.goal,
        "plan_created": True,
        "token_usage": token_usage,
    }


def after_task_manager(state: AgentState) -> str:
    """Route to AI directly if executing an approved plan, else to planner."""

    if state.get("task_action") == "plan_cancelled":
        return "plan_cancelled"

    if state.get("task_action") == "approval_without_plan":
        return "approval_without_plan"

    if state.get("task_action") == "execute_approved_plan":
        return "ai"

    if state.get("task_action") == "revise_plan":
        return "plan_reviser"

    return "planner"


def plan_cancelled_node(state: AgentState):
    return {
        "messages": [
            AIMessage(
                content=(
                    "Plan cancelled. No changes were made."
                )
            )
        ]
    }


def approval_without_plan_node(state: AgentState):
    return {
        "messages": [
            AIMessage(
                content=(
                    "There is no pending plan to approve."
                )
            )
        ]
    }


def after_planner(state: AgentState) -> str:
    """Choose whether to execute the plan or only preview it."""

    if state.get("execution_mode", "agent") == "plan":
        return "plan_preview"

    return "ai"


def plan_preview_node(state: AgentState):
    """Return the generated plan without executing it."""

    plan = state.get("plan", [])

    if not plan:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "This request does not require "
                        "a multi-step execution plan."
                    )
                )
            ]
        }

    lines = []

    for step in plan:
        lines.append(
            f"{step['id']}. {step['description']}"
        )

    return {
        "messages": [
            AIMessage(
                content=(
                    "Plan:\n\n"
                    + "\n".join(lines)
                )
            )
        ]
    }


def plan_reviser_node(
    state: AgentState,
    config: RunnableConfig,
):
    current_plan = state.get("plan", [])

    if not current_plan:
        return {}

    configurable = config["configurable"]

    usages: list[TokenUsage] = []

    revised = revise_plan(
        task=state.get("plan_goal", state.get("current_task", "")),
        plan=current_plan,
        revision=state.get("latest_instruction", ""),
        provider=configurable["provider"],
        model=configurable["model"],
        usage_list=usages,
    )

    token_usage = _merge_token_usage(
        state.get("token_usage", {}),
        usages,
    )

    revised_plan = [
        step.model_dump()
        for step in revised.steps
    ]

    # Plan is still only a preview.
    # Do NOT start execution yet.
    for step in revised_plan:
        step["status"] = "pending"

    return {
        "plan": revised_plan,
        "plan_created": True,
        "plan_approved": False,
        "plan_revision_count": (
            state.get("plan_revision_count", 0) + 1
        ),
        "token_usage": token_usage,
    }





# =========================================================
# REPLANNER NODE
# =========================================================

def replanner_node(
    state: AgentState,
    config: RunnableConfig,
):
    if not state.get("replan_needed", False):
        return {}

    replan_count = state.get("replan_count", 0)

    if replan_count >= 2:
        return {
            "replan_needed": False,
        }

    current_task = state.get("current_task", "")
    old_plan = state.get("plan", [])
    failed_steps = state.get("failed_steps", [])

    configurable = config["configurable"]

    usages: list[TokenUsage] = []

    task_plan = create_replan(
        task=current_task,
        plan=old_plan,
        failed_steps=failed_steps,
        provider=configurable["provider"],
        model=configurable["model"],
        prior_attempts=state.get("prior_attempts", []),  # NEW: Pass learning memory
        usage_list=usages,
    )

    token_usage = _merge_token_usage(
        state.get("token_usage", {}),
        usages,
    )

    # Preserve completed steps.
    completed = [
        step.copy()
        for step in old_plan
        if step.get("status") == "completed"
    ]

    new_steps = [
        step.model_dump()
        for step in task_plan.steps
    ]

    # Give the new steps IDs after the preserved steps.
    next_id = len(completed) + 1

    for step in new_steps:
        step["id"] = next_id
        step["status"] = "pending"
        next_id += 1

    new_steps = start_next_plan_step(new_steps)

    # Summarize this failed attempt for future learning (short-term)
    latest_failure = failed_steps[-1] if failed_steps else "Unknown failure"
    attempt_summary = {
        "strategy_summary": f"Plan with {len(old_plan)} steps failed at step {len(completed) + 1}",
        "failure_reason": latest_failure,
        "lesson": f"Original approach failed. Switching to new strategy with {len(new_steps)} steps.",
    }

    # Store in LONG-TERM memory (cross-session learning).
    memory_manager.store_replan_lesson(
        task=current_task,
        old_plan=old_plan,
        failure=latest_failure,
        new_strategy=f"New plan with {len(new_steps)} steps",
    )

    prior_attempts = list(state.get("prior_attempts", []))
    prior_attempts.append(attempt_summary)

    return {
        "plan": completed + new_steps,
        "replan_needed": False,
        "replan_count": replan_count + 1,
        "prior_attempts": prior_attempts,  # NEW: Save lessons learned
        "token_usage": token_usage,
    }


# =========================================================
# GRAPH
# =========================================================

tool_node = ToolNode(tools)

builder = StateGraph(AgentState)

builder.add_node(
    "task_manager",
    task_manager_node,
)

builder.add_node(
    "finalize",
    finalize_node,
)

builder.add_node(
    "planner",
    planner_node,
)

builder.add_node(
    "ai",
    ai_node,
)

builder.add_node(
    "tools",
    tool_node,
)

builder.add_node(
    "progress",
    progress_node,
)

builder.add_node(
    "replanner",
    replanner_node,
)

builder.add_node(
    "recovery_limit",
    recovery_limit_node,
)

builder.add_node(
    "plan_preview",
    plan_preview_node,
)

builder.add_node(
    "plan_reviser",
    plan_reviser_node,
)

builder.add_node(
    "plan_cancelled",
    plan_cancelled_node,
)

builder.add_node(
    "approval_without_plan",
    approval_without_plan_node,
)


# ---------------------------------------------------------
# ENTRY FLOW
# ---------------------------------------------------------

builder.add_edge(
    START,
    "task_manager",
)

builder.add_conditional_edges(
    "task_manager",
    after_task_manager,
    {
        "ai": "ai",
        "planner": "planner",
        "plan_reviser": "plan_reviser",
        "plan_cancelled": "plan_cancelled",
        "approval_without_plan": "approval_without_plan",
    },
)

builder.add_edge(
    "plan_cancelled",
    END,
)

builder.add_edge(
    "approval_without_plan",
    END,
)

builder.add_conditional_edges(
    "planner",
    after_planner,
    {
        "ai": "ai",
        "plan_preview": "plan_preview",
    },
)

builder.add_edge(
    "plan_reviser",
    "plan_preview",
)

builder.add_edge(
    "plan_preview",
    END,
)



# ---------------------------------------------------------
# AI -> TOOLS / END
# ---------------------------------------------------------

builder.add_conditional_edges(
    "ai",
    should_continue,
)

builder.add_edge(
    "finalize",
    END,
)


# ---------------------------------------------------------
# TOOLS -> PROGRESS
# ---------------------------------------------------------

builder.add_edge(
    "tools",
    "progress",
)


# ---------------------------------------------------------
# PROGRESS -> AI / RECOVERY LIMIT
# ---------------------------------------------------------

builder.add_conditional_edges(
    "progress",
    after_progress,
    {
        "ai": "ai",
        "replanner": "replanner",
        "recovery_limit": "recovery_limit",
        "finalize": "finalize",
    },
)

builder.add_edge(
    "replanner",
    "ai",
)


# ---------------------------------------------------------
# RECOVERY LIMIT -> END
# ---------------------------------------------------------

builder.add_edge(
    "recovery_limit",
    END,
)

# =========================================================
# MEMORY
# =========================================================

# Create ONE memory manager for the whole agent (cross-session memory).
memory_manager = MemoryManager()

# Main context engine: heuristic summarization only (saves money).
# To enable LLM-powered summarization for massive outputs, pass llm=get_llm(...).
# Give it the memory manager so it can retrieve past lessons.
context_engine = ContextEngine(
    max_tokens=8000,
    model=LLM_MODEL,
    llm=None,
    memory_manager=memory_manager,
)

memory = MemorySaver()

graph = builder.compile(
    checkpointer=memory
)


# =========================================================
# NORMAL INVOCATION
# =========================================================
def invoke_agent(
    message: str,
    thread_id: str = "default",
    provider: str = LLM_PROVIDER,
    model: str = LLM_MODEL,
    workspace: str = ".",
    execution_mode: Literal["agent", "plan"] = "agent",
) -> str:

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "provider": provider,
            "model": model,
            "workspace": workspace,
        },
        "recursion_limit": 50,
    }

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content=message)
            ],
            "latest_instruction": message,
            "execution_mode": execution_mode,
        },
        config=config,
    )

    return result["messages"][-1].content

# =========================================================
# STREAMING INVOCATION
# =========================================================

def stream_agent(
    message: str,
    thread_id: str = "default",
    provider: str = LLM_PROVIDER,
    model: str = LLM_MODEL,
    workspace: str = ".",
    execution_mode: Literal["agent", "plan"] = "agent",
) -> str:

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "provider": provider,
            "model": model,
            "workspace": workspace,
        },
        "recursion_limit": 50,
    }

    final_response = ""

    for event in graph.stream(
    {
        "messages": [
            HumanMessage(content=message)
        ],
        "latest_instruction": message,
        "execution_mode": execution_mode,
    },
    config=config,
    stream_mode="updates",
):
        # ---------------------------------------------
        # AI NODE
        # ---------------------------------------------

        if "ai" in event:
            ai_messages = event["ai"].get(
                "messages",
                [],
            )

            if not ai_messages:
                continue

            last_message = ai_messages[-1]

            # AI requested tools
            if last_message.tool_calls:
                for tool_call in last_message.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]

                    print(
                        f"\n[Tool] "
                        f"{tool_name} "
                        f"{tool_args}"
                    )

            # AI produced final text
            elif last_message.content:
                final_response = last_message.content

        # ---------------------------------------------
        # TOOL NODE
        # ---------------------------------------------

        if "tools" in event:
            print("[Tool completed]")

    return final_response

from src.agents.agent_status import build_agent_status


def get_agent_status(
    thread_id: str,
) -> dict:
    """Return a read-only status snapshot for a saved agent thread."""

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    snapshot = graph.get_state(config)

    if snapshot is None:
        return build_agent_status(
            {},
            memory_count=memory_manager.get_memory_count(),
        )

    values = snapshot.values or {}

    return build_agent_status(
        dict(values),
        memory_count=memory_manager.get_memory_count(),
    )
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
# =========================================================
# TOOLS
# =========================================================

tools = [
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
    read_terminal_output
]


# =========================================================
# SYSTEM PROMPT
# =========================================================

system_message = SystemMessage(
    content="""
You are PulseCodeAI, an autonomous AI coding agent operating inside the user's active project workspace.

Your goal is to complete the user's programming task by inspecting the project, reasoning about the problem, using tools when necessary, making changes, and verifying the result.

CORE BEHAVIOR

- Act like a coding agent, not a general chatbot.
- When the user asks you to perform an action, use the appropriate tools instead of merely explaining how they could do it.
- Inspect relevant files before making changes when their current contents matter.
- Never claim that you read, wrote, edited, executed, tested, built, installed, stopped, or verified something unless the corresponding tool actually succeeded.
- Use tool results as the source of truth.
- Do not invent file contents, terminal output, process status, or tool results.
- Do not repeat a failed action unchanged. Inspect the error and choose a better next step.
- Continue through reasonable intermediate steps when they are necessary to complete the user's task.
- When the task is complete, give a concise summary of what was actually done.

FILE TOOLS

- Use list_files to inspect directories.
- Use read_file before modifying an existing file when you need its current contents.
- Use search_code to locate symbols, functions, classes, imports, errors, or relevant code.
- Use write_file when creating a new file or intentionally replacing an entire file.
- Use edit_file for precise modifications to existing files.
- Prefer edit_file over rewriting an entire existing file when only a small change is required.
- All file operations must remain inside the active workspace.
- If a path is rejected because it escapes the workspace, do not attempt to bypass the restriction.

TERMINAL TOOLS

There are two execution modes.

1. run_terminal
   - Use for short commands expected to finish quickly.
   - Examples: git status, git diff, directory inspection, version checks, and quick tests.
   - Do not use it for long builds, installations, development servers, compilation, deliberate waits, or commands expected to remain running.

2. start_terminal
   - Use for long-running commands.
   - Examples: package installation, builds, compilation, development servers, long test suites, and commands containing deliberate waits.
   - start_terminal returns a process ID.
   - Remember that process ID and use it for subsequent process operations.
   - Do not simulate background execution using &, start /b, temporary scripts, or similar shell tricks when start_terminal is available.

TERMINAL LOG RETRIEVAL

- Terminal processes retain their captured output internally.
- check_terminal may truncate large output to protect the context window.
- If relevant information may exist inside an omitted section, use read_terminal_output instead of rerunning the command.
- Use start_line and end_line to request only the relevant portion.
- Do not request unnecessarily large ranges.
- Prefer targeted log inspection around suspected errors or relevant line ranges.
- Rerun a completed command only when rerunning is actually necessary; do not rerun merely to recover truncated output.

PROCESS MONITORING

- Use check_terminal only for processes created by start_terminal.
- Use the exact process ID returned by start_terminal.
- If a process is still running, do not start the same command again.
- Avoid rapid zero-second polling.
- Use wait_seconds when waiting for useful progress.
- Choose wait_seconds according to the expected task duration.
- A monitoring wait is NOT a process execution timeout.
- The underlying process may continue running after check_terminal returns RUNNING.
- If the process completes during the wait, inspect its output and exit code before deciding what to do next.
- Exit code 0 normally indicates success.
- A non-zero exit code indicates failure or abnormal termination; inspect the output before deciding on the next action.
- Do not claim success merely because a process was started.

PROCESS MANAGEMENT

- Use list_terminal_processes to inspect processes created by start_terminal.
- Never use stop_terminal merely because a process is taking a long time.
- Never stop a process just because check_terminal reports RUNNING.
- A long-running process is not considered stuck merely because it is taking time.
- If the user asks only to START a background process, start it, return its process ID, and leave it running.
- If the user asks to WAIT for completion, monitor it using check_terminal with appropriate wait_seconds values until it completes.
- Use stop_terminal when the user explicitly asks to stop, cancel, terminate, or restart a process.
- Before stopping a process for any other reason, ask the user for confirmation.
- Never claim a process was stopped unless stop_terminal confirms it.

TASK COMPLETION

For coding tasks, when appropriate follow this workflow:

understand task
→ inspect relevant project state
→ make the smallest appropriate change
→ run or test the result
→ inspect failures
→ fix if necessary
→ verify
→ report completion

Do not stop after writing code if the user's request reasonably requires testing or verification and the necessary tools are available.

ERROR HANDLING

- Treat tool errors as information.
- Read the actual error before choosing the next action.
- Do not fabricate a successful result after a tool failure.
- Do not repeatedly retry the identical failing command without a reason.
- Prefer diagnosing the root cause.
- If the task cannot be completed with available tools, clearly explain what blocked it.

AUTOMATIC RECOVERY

- A failed tool call does not automatically end the task.
- When a command or tool fails unexpectedly, inspect the actual error and determine whether the problem can reasonably be fixed with the available tools.
- If the failure is recoverable, diagnose the root cause, make the smallest appropriate corrective change, and retry or verify the operation.
- Do not blindly repeat the identical failed command. Change something relevant first, unless retrying unchanged is justified by the error or explicitly requested by the user.
- Continue the recovery loop until:
  1. the task succeeds,
  2. the failure requires user input or permission,
  3. the required capability is unavailable, or
  4. further automatic attempts would be unsafe or unreasonable.
- Never hide failed attempts. The final response should accurately summarize the verified outcome.
- An intentionally failing command requested by the user is not something to automatically repair.

RECOVERY SUCCESS

- Once the operation that previously failed is retried after a corrective change and succeeds, the recovery objective is complete.
- Stop automatic recovery immediately after verified success.
- Do not try alternative executables, commands, environments, or fixes after the corrected operation has already succeeded.
- A terminal command is verified successful when the relevant tool result reports exit code 0.
- After verified success, report the result to the user unless another part of the user's task remains unfinished.

RECOVERY LIMITS

- Make at most 3 failed automatic recovery attempts for an active task.
- After 3 failed recovery attempts, stop speculative automatic repair and report the blocker.
- Successful inspection or editing steps do not reset the failure count.
- A new task resets the recovery count.
- Explicit user instructions may start another attempt even after the automatic recovery limit.



TASK STATE PRIVACY

- TASK STATE is internal agent metadata.
- Never expose, print, quote, or reproduce internal task-state fields in the final response.
- Never output labels such as "action:", "updated_task:", "current_task:", "task_action:", "task_status:", or "steps_completed:" to the user.
- Use task state only to understand and continue the user's work.
- Final responses should contain only the useful result of the user's request.
- Keep normal responses concise.
- Do not narrate every internal decision.
- Tool calls perform the work; the final response summarizes the verified result.

"""
)


# =========================================================
# AI NODE
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
    
    completed_steps = state.get("steps_completed", [])

    if completed_steps:
        progress_text = "\n".join(
            f"- {step}" for step in completed_steps
        )
    else:
        progress_text = "- No successful steps recorded yet."
    failed_steps = state.get("failed_steps", [])

    if failed_steps:
        failure_text = "\n".join(
            f"- {step}" for step in failed_steps
        )
    else:
        failure_text = "- No failed attempts recorded."
    
    recovery_attempts = state.get(
    "recovery_attempts",
    0,
)

    recovery_mode = state.get("recovery_mode", False)
    recovery_command = state.get("recovery_command")

    if recovery_mode:
        latest_failure = (
            failed_steps[-1]
            if failed_steps
            else "Unknown failure"
        )

        recovery_context = (
            "RECOVERY MODE IS ACTIVE.\n"
            f"Original failed operation: {recovery_command}\n"
            f"Recovery failures: {recovery_attempts}/3\n\n"
            "Latest recorded failure:\n"
            f"{latest_failure}\n\n"
            "The previous operation failed and the task is not complete.\n"
            "Diagnose the root cause before retrying.\n"
            "Do NOT repeat the identical failed command as your next "
            "action unless the failure indicates that an unchanged retry "
            "is genuinely appropriate.\n"
            "For coding/runtime failures, inspect the relevant source "
            "when necessary and make the smallest corrective change.\n"
            "After a corrective action, retry the original failed "
            "operation and verify it succeeds.\n"
            "Preserve the current overall strategy unless the failure "
            "shows that strategy is no longer viable.\n"
            "Stop speculative recovery after 3 failed executions."
        )
    else:
        recovery_context = (
            f"Recovery failures during this task: "
            f"{recovery_attempts}/3.\n"
            "Recovery mode is not active."
        )

    replan_count = state.get("replan_count", 0)

    replan_context = (
        f"Automatic replans during this task: {replan_count}/2.\n"
        "This is separate from recovery_attempts.\n"
        "If asked for the replan count, report this value exactly."
    )

    plan = state.get("plan", [])
    plan_goal = state.get("plan_goal", "")

    if plan:
        plan_lines = []

        for step in plan:
            plan_lines.append(
                f"{step['id']}. "
                f"[{step['status']}] "
                f"{step['description']}"
            )

        plan_context = (
            f"Plan goal: {plan_goal}\n"
            + "\n".join(plan_lines)
        )
    else:
        plan_context = "No explicit plan for this task."

    task_context = SystemMessage(
    content=(
        "The user is working on this ongoing coding task:\n"
        f"{state.get('current_task', '')}\n\n"

        "Their latest request is:\n"
        f"{state.get('latest_instruction', '')}\n\n"

        "Previous successful work:\n"
        f"{progress_text}\n\n"

        "Previous failed attempts:\n"
        f"{failure_text}\n\n"

        "Use this history only as operational context. "
        "Do not expose or reproduce these internal lists unless "
        "the user explicitly asks about progress or failures. "

        "Do not blindly repeat a failed operation. "
        "If an operation previously failed, inspect the available "
        "failure context and choose a different approach when appropriate. "

        "If the user explicitly asks to retry or repeat an operation, "
        "perform it even if it previously failed. "

        "Do not assume previous successful work is still valid if "
        "later changes may have invalidated it.\n\n"
        "TERMINAL FAILURE SEMANTICS\n\n"

        "- A terminal process with exit code 0 is successful.\n"
        "- A terminal process with a non-zero exit code is a failed execution.\n"
        "- This remains true even when the user intentionally requested a "
        "command that was expected to fail.\n"
        "- Distinguish between 'the user's test behaved as expected' and "
        "'the terminal process succeeded'.\n"
        "- If a command intentionally exits with code 1, say that the test "
        "behaved as expected, but the command itself failed with exit code 1.\n"
        "- When asked what failed, use the recorded failed-attempt history "
        "as the source of truth.\n\n"

        "ACTIVE PLAN\n"
        f"{plan_context}\n\n"

        "PLAN COMPLETION\n"
        f"All planned steps completed: {is_plan_complete(state)}\n"
        "If all planned steps are completed, do not call more tools "
        "unless verification actually failed or the user's task still "
        "has an unmet requirement. Return the concise final result.\n\n"

        "RECOVERY POLICY\n"
        f"{recovery_context}\n"
        "Once a previously failed operation succeeds after a corrective "
        "change, consider that recovery objective satisfied. "
        "Do not perform additional speculative retries or try alternative "
        "executables after verified success unless another requirement "
        "remains unfinished.\n\n"

        "REPLAN STATUS\n"
        f"{replan_context}\n"
    )
)
    
    messages = [
        system_message,
        task_context,
        *state["messages"],
    ]

    result = llm_with_tools.invoke(messages)

    return {
        "messages": [result]
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
        }

    if is_plan_approval(latest_instruction):
        return {
            "task_action": "approval_without_plan",
            "task_status": "idle",
            "plan_approved": False,
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
            "tool_failures":0,
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
        }

    llm = get_llm(
        provider=provider,
        model=model,
    )

    task_llm = llm.with_structured_output(
        TaskDecision
    )

    decision = cast(
    TaskDecision,
    task_llm.invoke(
        [
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
    ),
)

    if decision.action == "unrelated":
        updated_task = current_task
    elif decision.updated_task:
        updated_task = decision.updated_task
    else:
        updated_task = current_task


    if decision.action =="new":
        return {
        "current_task": updated_task,
        "task_action": decision.action,
        "task_status": "in_progress",
        "steps_completed": [],
        "failed_steps": [],
        "recovery_attempts": 0,
        "tool_failures":0,
        "recovery_mode":False,
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
    }
    return {
        "current_task": updated_task,
        "task_action": decision.action,
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

                replan_needed = should_replan(
                    task=state.get("current_task", ""),
                    plan=plan,
                    failure=failure,
                    provider=configurable["provider"],
                    model=configurable["model"],
                )

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

    return {
        "steps_completed": steps_completed,
        "failed_steps": failed_steps,
        "tool_failures": tool_failures,
        "recovery_mode": recovery_mode,
        "recovery_command": recovery_command,
        "recovery_attempts": recovery_attempts,
        "plan": plan,
        "replan_needed": replan_needed,
        "execution_trace": execution_trace,
    }


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

    needs_plan = should_create_plan(
        task=current_task,
        provider=provider,
        model=model,
    )

    if not needs_plan:
        return {
            "plan": [],
            "plan_goal": "",
            "plan_created": False,
        }

    task_plan = create_plan(
        task=current_task,
        provider=provider,
        model=model,
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

    revised = revise_plan(
        task=state.get("plan_goal", state.get("current_task", "")),
        plan=current_plan,
        revision=state.get("latest_instruction", ""),
        provider=configurable["provider"],
        model=configurable["model"],
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

    task_plan = create_replan(
        task=current_task,
        plan=old_plan,
        failed_steps=failed_steps,
        provider=configurable["provider"],
        model=configurable["model"],
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

    return {
        "plan": completed + new_steps,
        "replan_needed": False,
        "replan_count": replan_count + 1,
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
        return build_agent_status({})

    values = snapshot.values or {}

    return build_agent_status(dict(values))
import os
import sqlite3
import threading
from collections import OrderedDict
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
from langgraph.checkpoint.sqlite import SqliteSaver
# pyrefly: ignore [missing-import]
from langgraph.graph import StateGraph, START, END
# pyrefly: ignore [missing-import]
from langgraph.graph.message import add_messages
# pyrefly: ignore [missing-import]
from langgraph.prebuilt import ToolNode, InjectedState

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
    check_ambiguity,
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
from src.prompts.claude_persona import CLAUDE_SYSTEM_PERSONA

from src.agents.cost_router import cost_router
from src.agents.skill_manager import skill_manager
from src.agents.sub_agent import subagent_coordinator
from src.dashboard.event_bus import event_bus

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
    formatted = (
        f"💭 **Thinking:**\n\n"
        f"{reasoning[:1000]}\n\n"
        f"---\n"
        f"*Proceeding with the approach above.*"
    )
    return formatted


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
        return "✅ That step checks out. On to the next one."

    return (
        f"❌ That didn't match what I expected for '{step_description}'. "
        f"I was looking for:\n\n{expected_result!r}\n\n"
        f"But got:\n\n{actual_result!r}\n\n"
        "Let me diagnose what went wrong before moving on."
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
    return (
        f"❓ **I need a bit more clarity:**\n\n"
        f"{question}\n\n"
        f"*Once you reply, I'll get right back to work.*"
    )


@tool
def delegate_to_subagent(
    mode: Literal["research", "code", "test", "review"],
    task: str,
) -> str:
    """
    Delegate a focused sub-task to a specialized sub-agent.

    WHEN TO USE:
    - The task has a clear separable piece (research, coding, testing, review)
    - You want parallel exploration of different approaches
    - The sub-task is complex enough to benefit from focused attention

    WHEN NOT TO USE:
    - Trivial one-step tasks
    - Tasks that depend on your immediate previous action
    """
    from src.config.settings import LLM_PROVIDER, LLM_MODEL

    agent_id = subagent_coordinator.spawn(
        mode=mode,
        task=task,
        parent_thread_id="main",
        provider=LLM_PROVIDER,
        model=LLM_MODEL,
    )

    result = subagent_coordinator.get_result(agent_id)

    return (
        f"🤖 Sub-agent ({mode}) completed.\n\n"
        f"**Task:** {task}\n\n"
        f"**Result:**\n{result[:2000]}\n\n"
        f"*Agent ID: {agent_id}*"
    )


tools = [
    think,
    verify,
    ask_user,
    delegate_to_subagent,

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


def compute_unified_diff(old_content: str, new_content: str, file_path: str) -> dict:
    """
    Compute a unified diff between old and new file content.
    Returns a dict that the dashboard can render.
    """
    import difflib
    import time
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=file_path, tofile=file_path,
        lineterm="",
    ))

    # Parse into chunks
    chunks = []
    current_chunk = None
    chunk_id = 0
    for line in diff:
        if line.startswith("@@"):
            if current_chunk:
                chunks.append(current_chunk)
            # Parse @@ -start,count +start,count @@
            parts = line.split("@@")[1].strip()
            old_part, new_part = parts.split(" +")
            old_start = int(old_part.split(",")[0].replace("-", ""))
            old_count = int(old_part.split(",")[1]) if "," in old_part else 1
            new_start = int(new_part.split(",")[0])
            new_count = int(new_part.split(",")[1]) if "," in new_part else 1
            
            chunk_id += 1
            current_chunk = {
                "chunk_id": f"chunk-{chunk_id}",
                "old_start": old_start,
                "old_lines": old_count,
                "new_start": new_start,
                "new_lines": new_count,
                "lines": [],
            }
        elif current_chunk is not None:
            if line.startswith("+"):
                current_chunk["lines"].append({
                    "type": "added",
                    "old_no": None,
                    "new_no": current_chunk["new_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("added", "context")]),
                    "text": line[1:],
                })
            elif line.startswith("-"):
                current_chunk["lines"].append({
                    "type": "removed",
                    "old_no": current_chunk["old_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("removed", "context")]),
                    "new_no": None,
                    "text": line[1:],
                })
            elif line.startswith(" "):
                current_chunk["lines"].append({
                    "type": "context",
                    "old_no": current_chunk["old_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("removed", "context")]),
                    "new_no": current_chunk["new_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("added", "context")]),
                    "text": line[1:],
                })

    if current_chunk:
        chunks.append(current_chunk)

    return {
        "diff_id": f"diff-{int(time.time() * 1000)}",
        "file": file_path,
        "old_path": file_path,
        "new_path": file_path,
        "chunks": chunks,
    }

# =========================================================
# SYSTEM PROMPT
# =========================================================

system_message = SystemMessage(content=CLAUDE_SYSTEM_PERSONA)


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

    # Cost-aware routing: try to use a cheaper/better model for this task
    task_for_routing = state.get("current_task", "")
    plan_for_routing = state.get("plan", [])
    routed_provider, routed_model = cost_router.route(task_for_routing, plan_for_routing)

    try:
        llm = get_llm(provider=routed_provider, model=routed_model)
        provider = routed_provider
        model = routed_model
    except Exception:
        # Fallback to the originally configured provider if routing fails
        llm = get_llm(provider=provider, model=model)

    llm_with_tools = llm.bind_tools(tools)

    # Use the Context Engine to build clean, organized messages.
    # Session-scoped: this thread's thread_id selects an isolated engine
    # (cache, attribution snapshot, learned weights all independent).
    messages = get_context_engine(config).build_ai_messages(
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

def finalize_node(state: AgentState, config: RunnableConfig):
    plan = finalize_plan(
        plan=list(state.get("plan", [])),
        task_succeeded=True,
    )

    # Store successful task in long-term memory.
    current_task = state.get("current_task", "")
    steps_completed = state.get("steps_completed", [])
    failed_steps = state.get("failed_steps", [])

    if memory_manager and current_task and steps_completed:
        memory_manager.store_task_completion(
            task=current_task,
            steps_completed=steps_completed,
            plan=plan,
        )

    # Feedback loop: record FAILURE if the task ended with failed steps,
    # otherwise success. (Previously success was recorded unconditionally,
    # so the learning loop only ever saw wins.)
    try:
        engine = get_context_engine(config)
        if state.get("failed_steps"):
            engine.record_feedback(success=False, task=current_task)
        else:
            engine.record_feedback(success=True, task=current_task)
    except Exception:
        pass  # Feedback is best-effort; never block finalization


    # Build a beautiful completion message
    lines = []
    task_display = current_task[:70] if current_task else "Task"
    lines.append(f"## ✅ Finished: {task_display}")
    lines.append("")

    # Summarize what was done
    if steps_completed:
        lines.append("### 📁 What I did:")
        for step in steps_completed[-8:]:
            lines.append(f"- {step}")
        lines.append("")

    # Note any issues
    if failed_steps:
        lines.append("### ⚠️ Issues I ran into:")
        for failure in failed_steps[-3:]:
            lines.append(f"- {failure}")
        lines.append("")

    lines.append("---")
    lines.append("*Need any tweaks? Just let me know!*")

    # Add proactive suggestions
    from src.context.reflection_engine import ReflectionEngine
    reflector = ReflectionEngine()
    reflection = reflector.reflect(
        task=current_task,
        steps_completed=steps_completed,
        failed_steps=failed_steps,
        plan=plan,
    )

    suggestions_text = reflector.format_suggestions(reflection.get("suggestions", []))
    if suggestions_text:
        # insert before the final sign-off
        lines.insert(-2, suggestions_text)

    # Export analytics for dashboard
    from src.agents.cost_router import cost_router
    from src.agents.skill_manager import skill_manager

    # Calculate token usage for emissions
    usage = state.get("token_usage", {})
    cost_usd = usage.get("estimated_cost_usd", 0)
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    call_count = usage.get("calls_made", 0)

    event_bus.emit("analytics.update", {
        "totalCost": cost_usd,
        "tokensIn": prompt_tokens,
        "tokensOut": completion_tokens,
        "apiCalls": call_count,
        "model": LLM_MODEL,
        "tier": (getattr(cost_router, "_last_route", None) or {}).get("tier", "standard"),
        "provider": LLM_PROVIDER,
        "skills": len(skill_manager.list_skills()),
    })

    event_bus.emit("suggestions", {
        "suggestions": [{"text": s} for s in reflection.get("suggestions", [])],
    })

    return {
        "plan": plan,
        "task_completed": True,
        "messages": [AIMessage(content="\n".join(lines))],
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
        # Store tool output for semantic retrieval
        # (feeds the "RELEVANT PAST TOOL OUTPUTS" layer)
        # ------------------------------------------
        if result.strip() and tool_name != "think":
            try:
                # Anchor the memory with the tool's target so later tasks
                # mentioning the same file/command/query can retrieve it.
                anchor = ""
                for key in ("path", "command", "query", "process_id"):
                    val = tool_args.get(key)
                    if val:
                        anchor = f"{key}={val}"
                        break

                # Failures: the error lives at the tail of the output.
                # Successes: the useful content starts at the head.
                if failed:
                    summary = result[-300:].replace("\n", " ")
                else:
                    summary = result[:300].replace("\n", " ")

                memory_manager.store_tool_memory(
                    tool_name=tool_name,
                    query=state.get("current_task", ""),
                    summary=f"{'FAILED' if failed else 'OK'} {anchor} | {summary}",
                    full_output=result[:2000],
                )
            except Exception:
                pass  # Tool memory is best-effort; never block execution

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
            
            content = tool_args.get("content", "")
            event_bus.emit("diff.show", {
                "file": path,
                "lines": content.split("\n")[:20],
            })
            event_bus.emit("files.changed", {
                "messageId": message.tool_call_id,
                "files": [path],
            })

        elif tool_name == "edit_file":
            path = tool_args.get("path", "unknown")
            step = f"Edited file: {path}"

            event_bus.emit("files.changed", {
                "messageId": message.tool_call_id,
                "files": [path],
            })

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
                    "You just received a tool result. Take a moment to evaluate it:\n"
                    "- Did the tool succeed or fail?\n"
                    "- Does the output match what you expected?\n"
                    "- Should you proceed, fix something, ask the user, or replan?\n\n"
                    "Use verify() when the result needs explicit validation. "
                    "Don't verify meta-tools like think(), verify(), or ask_user()."
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

def recovery_limit_node(state: AgentState, config: RunnableConfig):
    failed_steps = state.get("failed_steps", [])

    # Record failure feedback: recovery was exhausted — the layer combination
    # used for this task correlated with failure.
    try:
        get_context_engine(config).record_feedback(
            success=False, task=state.get("current_task", "")
        )
    except Exception:
        pass  # Feedback is best-effort; never block the graph

    if failed_steps:
        latest_failure = failed_steps[-1]
    else:
        latest_failure = "Unknown failure"
    return {
        "messages": [
            AIMessage(
                content=(
                    "I stopped trying to automatically recover after 3 failed attempts. "
                    "The last issue I ran into was:\n\n"
                    f"{latest_failure}\n\n"
                    "I don't want to keep retrying the same thing and waste your time (and tokens). "
                    "Could you take a look and let me know how you'd like to proceed?"
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

    # Cost-aware routing for planning
    routed_provider, routed_model = cost_router.route(current_task)

    try:
        # create_plan uses the provider/model strings, not the llm object directly
        # So we just pass the routed ones; if they fail, fallback below
        task_plan = create_plan(
            task=current_task,
            provider=routed_provider,
            model=routed_model,
            usage_list=usages,
        )
    except Exception:
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
                    "No problem — I've cancelled the plan and no changes were made. "
                    "Let me know if you'd like to take a different approach."
                )
            )
        ]
    }


def approval_without_plan_node(state: AgentState):
    return {
        "messages": [
            AIMessage(
                content=(
                    "I don't see a pending plan waiting for approval right now. "
                    "Would you like me to create one for your current task?"
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
                        "This looks like something I can handle directly "
                        "without a formal execution plan. I'll get right to it."
                    )
                )
            ]
        }
    lines = []
    lines.append("Here's my plan for this task:\n")
    for step in plan:
        lines.append(
            f"{step['id']}. {step['description']}"
        )
    lines.append("\nLet me know if you'd like me to proceed or adjust anything!")
    return {
        "messages": [
            AIMessage(
                content="\n".join(lines)
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
        # Give-up: plan was unrecoverable even after 2 replans.
        # Record failure feedback so the learning loop sees negative samples.
        try:
            get_context_engine(config).record_feedback(
                success=False, task=state.get("current_task", "")
            )
        except Exception:
            pass  # Feedback is best-effort; never block the graph
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
    # Guarded: memory_manager is None in degraded-boot environments.
    if memory_manager:
        memory_manager.store_replan_lesson(
            task=current_task,
            old_plan=old_plan,
            failure=latest_failure,
            new_strategy=f"New plan with {len(new_steps)} steps",
        )

    # Also store a reflection about this failure
    from src.context.reflection_engine import ReflectionEngine
    ReflectionEngine().reflect(
        task=f"{current_task} [REPLAN]",
        steps_completed=[f"Original plan failed: {latest_failure}"],
        failed_steps=[latest_failure],
        plan=old_plan,
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

# Wrap ToolNode with safety guard
from src.context.safety_guard import SafetyGuard

class SafeToolNode:
    """
    Wrapper around ToolNode that checks safety before executing.
    """
    def __init__(self, tools, safety_guard: SafetyGuard):
        self._node = ToolNode(tools)
        self._guard = safety_guard
        # SafetyGuards are stateless except for their workspace, so keep one
        # per distinct workspace instead of rebuilding on every tool call.
        # NOTE: keyed by workspace — the injected guard is bound to the
        # import-time cwd, which may differ from the per-session workspace
        # passed via config["configurable"]["workspace"].
        self._guards_by_workspace: dict[str, SafetyGuard] = {
            str(safety_guard.workspace): safety_guard
        }

    def __call__(self, state, config=None):
        # Check the last AI message for tool calls
        messages = state.get("messages", [])
        if not messages:
            return self._node.invoke(state, config)

        last_msg = messages[-1]
        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return self._node.invoke(state, config)

        # Get workspace from config
        workspace = "."
        if config and "configurable" in config:
            workspace = config["configurable"].get("workspace", ".")

        from pathlib import Path
        ws_key = str(Path(workspace).resolve())
        guard = self._guards_by_workspace.get(ws_key)
        if guard is None:
            guard = SafetyGuard(workspace)
            self._guards_by_workspace[ws_key] = guard

        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            is_safe, warning = guard.check_tool_call(tool_name, tool_args)
            if not is_safe:
                # Return a tool result that looks like a blocked execution
                # This triggers the agent to ask the user
                blocked_msg = AIMessage(
                    content=(
                        f"🛑 I was about to run `{tool_name}` but I need your confirmation first.\n\n"
                        f"{warning}\n\n"
                        f"Please reply so I know how to proceed."
                    )
                )
                return {"messages": [blocked_msg]}

        # All safe — proceed to real tool execution
        return self._node.invoke(state, config)

tool_node = SafeToolNode(tools, SafetyGuard())

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
# Use PersistentMemoryWrapper so memories survive across restarts.
from src.context.persistent_memory import PersistentMemoryWrapper

# Long-term memory needs the embedding backend (sentence-transformers, ~100MB
# model). VectorMemory RAISES when that backend is unavailable (fresh CI,
# slim containers) — and because this runs at module import time, it would
# crash the entire agent on boot. Degrade to memory_manager=None instead,
# matching the ContextEngine's documented fallback pattern (all memory layers
# already treat None as "feature off").
try:
    base_memory = MemoryManager()
    memory_manager = PersistentMemoryWrapper(base_memory)
except Exception as exc:  # e.g. RuntimeError from VectorMemory
    print(f"[chat_graph] Long-term memory DISABLED (boot degraded): {exc}")
    memory_manager = None

# ---------------------------------------------------------------------
# SESSION-SCOPED CONTEXT ENGINES (D1)
# ---------------------------------------------------------------------
# One ContextEngine per conversation thread. The old module-level singleton
# silently shared _layer_cache, _last_layers_sent, feedback history AND the
# learned LAYER_RELEVANCE weights across every dashboard session — proven
# corruption: session A's outcome was attributed to (and punished) session
# B's layer composition, and A's weight drift steered B's next build.
# Registry is memoized + LRU-capped; construction matches the retired
# singleton (model auto-resolution, shared memory manager — long-term
# memory stays intentionally global: single-product, not multi-tenant).
#
# Planner note: src/agents/planner.py keeps its own engine singleton and
# needs no registry — its build_*_messages methods are pure construction
# (verified: zero self-mutation), so threads can share it safely.

_ENGINES: "OrderedDict[str, ContextEngine]" = OrderedDict()
_ENGINES_LOCK = threading.Lock()
_ENGINES_MAX = 128  # LRU cap: engines are light; unbounded growth is not.


def _session_key_from_config(config: RunnableConfig | None) -> str:
    try:
        thread_id = (config or {}).get("configurable", {}).get("thread_id")
    except AttributeError:
        thread_id = None
    return str(thread_id) if thread_id else "default"


def get_context_engine(
    config_or_key: RunnableConfig | str | None = None,
) -> ContextEngine:
    """Memoized per-session ContextEngine.

    Nodes pass their RunnableConfig (thread_id lives in configurable);
    tools/tests may pass a raw key string. Unknown -> "default".
    """
    key = (
        config_or_key
        if isinstance(config_or_key, str)
        else _session_key_from_config(config_or_key)
    )
    with _ENGINES_LOCK:
        engine = _ENGINES.get(key)
        if engine is None:
            engine = ContextEngine(
                model=LLM_MODEL,
                llm=None,
                memory_manager=memory_manager,
            )
            _ENGINES[key] = engine
            if len(_ENGINES) > _ENGINES_MAX:
                _ENGINES.popitem(last=False)  # evict least-recently-used
        else:
            _ENGINES.move_to_end(key)
        return engine

# Persistent session checkpointer — thread state survives restarts.
# NOTE: SqliteSaver.from_conn_string() returns a context manager (verified),
# so for a module-level saver we hold a direct connection instead.
# check_same_thread=False is required: the dashboard server runs the graph
# from worker threads, and sqlite connections are thread-bound by default.
_CHECKPOINT_DB = os.path.join(os.path.expanduser("~"), ".pulseai", "sessions.db")
os.makedirs(os.path.dirname(_CHECKPOINT_DB), exist_ok=True)
_checkpoint_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
memory = SqliteSaver(_checkpoint_conn)
memory.setup()

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
    from src.context.convention_learner import ConventionLearner
    ConventionLearner().scan_workspace(workspace)
    
    event_bus.emit("session.status", {"status": "busy", "thread_id": thread_id})

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
    current_step = 0
    total_steps = 0

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
        # PLANNER NODE — show plan creation
        # ---------------------------------------------
        if "planner" in event:
            plan_data = event["planner"]
            plan = plan_data.get("plan", [])
            if plan:
                total_steps = len(plan)
                print(f"\n📋 Plan created: {total_steps} steps")
                event_bus.emit("plan.created", {
                    "steps": plan,
                    "thread_id": thread_id,
                })

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

            # Show cost routing decision
            from src.agents.cost_router import cost_router
            route_info = cost_router.get_last_route_info()
            if "tier" in route_info.lower():
                print(f"\n🧭 {route_info}")

            # AI requested tools
            if last_message.tool_calls:
                event_bus.emit("message.agent.start", {"thread_id": thread_id})
                for tool_call in last_message.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    
                    tool_id = f"{thread_id}-{tool_call.get('id', '')}"
                    
                    # Emit tool call event
                    event_bus.emit("tool.call", {
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "thread_id": thread_id,
                    })

                    if tool_name == "think":
                        reasoning = tool_args.get("reasoning", "")
                        print(f"\n💭 {reasoning[:350]}...")
                    else:
                        current_step += 1
                        step_label = f"({current_step}/{total_steps})" if total_steps else ""
                        print(
                            f"\n🔧 {step_label} {tool_name} "
                            f"{tool_args}"
                        )

            # AI produced final text
            elif last_message.content:
                final_response = last_message.content
                # Stream the whole content as one chunk for now
                event_bus.emit("message.agent.chunk", {
                    "chunk": final_response,
                    "thread_id": thread_id,
                })

        # ---------------------------------------------
        # PROGRESS NODE — show step completion
        # ---------------------------------------------
        if "progress" in event:
            progress_data = event["progress"]
            steps_completed = progress_data.get("steps_completed", [])
            failed_steps = progress_data.get("failed_steps", [])

            if steps_completed and len(steps_completed) > 0:
                latest = steps_completed[-1]
                print(f"  ✅ {latest}")
                event_bus.emit("plan.step.complete", {
                    "step": latest,
                    "thread_id": thread_id,
                })

            if failed_steps and len(failed_steps) > 0:
                latest = failed_steps[-1]
                print(f"  ❌ {latest}")

        # ---------------------------------------------
        # REPLANNER NODE
        # ---------------------------------------------
        if "replanner" in event:
            print("\n🔄 Replanning... adjusting strategy based on what we learned.")

        # ---------------------------------------------
        # RECOVERY LIMIT
        # ---------------------------------------------
        if "recovery_limit" in event:
            print("\n⛔ Recovery limit reached. Pausing for user input.")

    event_bus.emit("session.status", {"status": "idle", "thread_id": thread_id})
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
            memory_count=memory_manager.get_memory_count() if memory_manager else 0,
        )

    values = snapshot.values or {}

    return build_agent_status(
        dict(values),
        memory_count=memory_manager.get_memory_count() if memory_manager else 0,
    )
def fork_conversation(
    source_thread_id: str,
    new_thread_id: str | None = None,
) -> str:
    """
    Fork a conversation: copy the current state into a new thread.
    This lets you explore alternatives without losing the original.
    """
    import uuid

    if new_thread_id is None:
        new_thread_id = f"fork-{uuid.uuid4().hex[:8]}"

    source_config = {"configurable": {"thread_id": source_thread_id}}
    snapshot = graph.get_state(source_config)

    if snapshot is None:
        return f"No saved state found for thread '{source_thread_id}'."

    new_config = {"configurable": {"thread_id": new_thread_id}}
    graph.update_state(new_config, snapshot.values)

    return new_thread_id

def export_session_analytics(thread_id: str) -> dict:
    """
    Export all analytics for the dashboard.
    Call this after every task or on demand.
    """
    from src.context.reflection_engine import ReflectionEngine
    status = get_agent_status(thread_id)
    cost = status.get("cost", {})
    return {
        "totalCost": cost.get("estimated_cost_usd", 0),
        "tokensIn": cost.get("prompt_tokens", 0),
        "tokensOut": cost.get("completion_tokens", 0),
        "apiCalls": cost.get("calls_made", 0),
        "cheapCalls": getattr(cost_router, "_cheap_count", 0),
        "standardCalls": getattr(cost_router, "_standard_count", 0),
        "premiumCalls": getattr(cost_router, "_premium_count", 0),
        "replans": status.get("replan", {}).get("count", 0),
        "recoveries": status.get("recovery", {}).get("attempts", 0),
        "skills": len(skill_manager.list_skills()),
        "memories": memory_manager.get_memory_count() if memory_manager else 0,
        "reflections": len(ReflectionEngine()._reflections),
        "currentTask": status.get("task", ""),
        "planSteps": status.get("plan", {}).get("total", 0),
        "completedSteps": status.get("plan", {}).get("completed", 0),
    }

def export_dashboard_analytics(
    thread_id: str,
    task: str = "",
    cost: dict | None = None,
    model: str = "",
    tier: str = "",
    provider: str = "",
    skills: int = 0,
    tool_calls: list | None = None,
) -> None:
    """
    Export analytics after every task so the dashboard shows live data.
    Call this from finalize_node or after every tool execution.
    """
    import json
    import time
    from pathlib import Path

    analytics_path = Path.home() / ".pulseai" / "session_analytics.json"

    # Read existing
    existing = {}
    if analytics_path.exists():
        try:
            with open(analytics_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    # Merge
    existing.update({
        "timestamp": time.time(),
        "thread_id": thread_id,
        "currentTask": task[:100],
        "totalCost": cost.get("estimated_cost_usd", 0) if cost else 0,
        "tokensIn": cost.get("prompt_tokens", 0) if cost else 0,
        "tokensOut": cost.get("completion_tokens", 0) if cost else 0,
        "apiCalls": cost.get("calls_made", 0) if cost else 0,
        "model": model,
        "tier": tier,
        "provider": provider,
        "skills": skills,
        "tool_calls": tool_calls or [],
    })

    analytics_path.parent.mkdir(parents=True, exist_ok=True)
    with open(analytics_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

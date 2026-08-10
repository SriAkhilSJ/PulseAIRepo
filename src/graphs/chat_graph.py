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
from src.llm.factory import get_llm, get_auxiliary_llm
from src.context.context_engine import ContextEngine
from src.context.memory_manager import MemoryManager
from src.context.token_tracker import TokenTracker, TokenUsage
from src.agents.planner import (
    create_plan,
    create_replan,
    revise_plan,
    should_create_plan,
    start_next_plan_step,
    finalize_plan,
    check_ambiguity,
)
from src.graphs import progress_helpers as ph
from src.tools.file_tools import (
    read_file,
    list_files,
    search_code,
    write_file,
    edit_file,
)


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
from src.tools.code_exec_tool import execute_code
from src.tools.session_search_tool import session_search
from src.prompts.claude_persona import system_persona  # D35 (§47)

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
    env_failures: int       # environment-level tool failures (pivot trigger)
    pivot_count: int        # strategy pivots performed (bounded)
    prior_attempts: list[dict[str, Any]]  # NEW: Summarized history of past attempts
    finish_nudges: int      # hermes-style early-finish nudges applied (bounded)
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
    config: RunnableConfig,
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

    # Depth cap: sub-agents run the SAME graph with the SAME tools, so a
    # sub-agent could spawn its own sub-agent ad infinitum (cost + latency
    # bomb). Exactly one level of delegation is allowed.
    caller_thread = (config or {}).get("configurable", {}).get("thread_id", "")
    if str(caller_thread).startswith("sub-"):
        return (
            "⛔ Sub-agents cannot spawn further sub-agents (depth cap). "
            "Complete the decomposed steps directly instead."
        )

    agent_id = subagent_coordinator.spawn(
        mode=mode,
        task=task,
        parent_thread_id=str(caller_thread) or "main",
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


@tool
def delegate_to_subagent_batch(
    mode: Literal["research", "code", "test", "review"],
    tasks: list[str],
    config: RunnableConfig,
) -> str:
    """
    Delegate SEVERAL independent sub-tasks at once — they run in parallel.

    WHEN TO USE:
    - 2-5 INDEPENDENT pieces of the same kind (e.g. "review these 3 files",
      "research these 2 libraries"). Independence means: different files,
      no piece needs another piece's output.

    WHEN NOT TO USE:
    - A single sub-task (use delegate_to_subagent).
    - Pieces that depend on each other or touch the same file — run those
      sequentially yourself. Parallel code sub-agents are protected from
      clobbering each other's files, but dependencies still need order.

    Returns each sub-agent's result in the SAME order as the tasks list.
    """
    from src.config.settings import LLM_PROVIDER, LLM_MODEL

    caller_thread = (config or {}).get("configurable", {}).get("thread_id", "")
    if str(caller_thread).startswith("sub-"):
        return (
            "⛔ Sub-agents cannot spawn further sub-agents (depth cap). "
            "Complete the decomposed steps directly instead."
        )
    if not tasks:
        return "⛔ Empty batch: provide at least one task."
    if len(tasks) > 5:
        return (
            f"⛔ Batch too large ({len(tasks)} tasks, max 5): split it "
            f"into smaller batches."
        )

    agent_ids = subagent_coordinator.spawn_batch(
        mode=mode,
        tasks=tasks,
        parent_thread_id=str(caller_thread) or "main",
        provider=LLM_PROVIDER,
        model=LLM_MODEL,
    )

    parts = [f"🤖 Sub-agent batch ({mode}) — {len(agent_ids)} completed:\n"]
    for i, (task, agent_id) in enumerate(zip(tasks, agent_ids), 1):
        result = subagent_coordinator.get_result(agent_id)
        parts.append(
            f"--- [{i}] Task: {task} ---\n{result[:2000]}\n(ID: {agent_id})\n"
        )
    return "\n".join(parts)


tools = [
    think,
    verify,
    ask_user,
    delegate_to_subagent,
    delegate_to_subagent_batch,


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

    # Programmatic tool calling: ONE scripted call can chain the tools
    # above and return only printed output (D18, hermes PTC pattern).
    execute_code,

    # Zero-LLM recall of past sessions (D16, hermes session-search shape).
    session_search,
]



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
system_message = SystemMessage(content=system_persona())


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

    base_provider = configurable["provider"]
    base_model = configurable["model"]

    # Cost-aware routing: try to use a cheaper/better model for this task
    task_for_routing = state.get("current_task", "")
    plan_for_routing = state.get("plan", [])
    routed_provider, routed_model = cost_router.route(task_for_routing, plan_for_routing)

    provider = routed_provider
    model = routed_model
    try:
        llm = get_llm(provider=routed_provider, model=routed_model)
    except Exception:
        # Fallback to the originally configured provider if routing fails
        provider, model = base_provider, base_model
        llm = get_llm(provider=provider, model=model)

    llm_with_tools = llm.bind_tools(tools)

    # D31: start of an AI iteration — reset shadow-checkpoint dedup so the
    # first mutation this iteration snapshots the pre-change workspace.
    from src.tools.shadow_checkpoints import begin_agent_turn
    begin_agent_turn()

    # Use the Context Engine to build clean, organized messages.
    # Session-scoped: this thread's thread_id selects an isolated engine
    # (cache, attribution snapshot, learned weights all independent).
    messages = get_context_engine(config).build_ai_messages(
        state=dict(state),
        system_message=system_message,
    )

    try:
        result = llm_with_tools.invoke(messages)
    except Exception as exc:
        # F3/F6 (lab run 10): LLM-layer errors — a 403 on a blocked routed
        # tier (cost_router -> groq/llama-3.1-8b-instant), rate limits, etc.
        # — must not kill the turn. Fail over to the base provider/model
        # once (hermes-style provider failover). Only the base tier may
        # raise. Token accounting below uses the model that actually served.
        if (provider, model) == (base_provider, base_model):
            raise
        print(
            f"[ai_node] provider failover {provider}/{model} -> "
            f"{base_provider}/{base_model} ({type(exc).__name__})"
        )
        provider, model = base_provider, base_model
        llm = get_llm(provider=provider, model=model)
        llm_with_tools = llm.bind_tools(tools)
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

# Execution-flavored task markers: on these, a plain-text finish with no
# real tool work is treated as an early stop and nudged once (hermes
# _CODEX_INCOMPLETE_NUDGE pattern, conversation_loop.py).
_EXECUTION_TASK_MARKERS = (
    "build", "create", "implement", "integrate", "install", "fix",
    "refactor", "debug", "test", "scaffold", "develop", "deploy",
    "configure", "write a", "make a", "add ", "migrate", "upgrade",
)

_FINISH_NUDGE_BUDGET = 2  # max early-finish nudges before finalize is allowed

_FINISH_NUDGE = (
    "[System: You declared the task finished, but almost no real work has "
    "been done — few or no tool calls have executed and the deliverable does "
    "not exist yet. This is an execution task: do not summarize, do not ask "
    "questions, do not repeat this finish message. Make the tool call you "
    "were planning right now (write the file, run the command, build the "
    "artifact) and keep going until the deliverable actually exists.]"
)


def _looks_like_execution_task(task: str) -> bool:
    t = (task or "").lower()
    return any(marker in t for marker in _EXECUTION_TASK_MARKERS)


def _tool_call_count(state: AgentState) -> int:
    return sum(
        1 for m in state.get("messages", [])
        if getattr(m, "tool_calls", None)
    )


def should_continue(state: AgentState):
    last_message = state["messages"][-1]

    if getattr(last_message, "tool_calls", None):
        return "tools"

    # Finish gate: an execution task that ends with <2 tool calls total is an
    # early stop, not completion. Nudge once (bounded via finish_nudges) so
    # the model actually acts; after the budget, allow finalize.
    if state.get("finish_nudges", 0) < _FINISH_NUDGE_BUDGET:
        if _looks_like_execution_task(state.get("current_task", "")):
            if _tool_call_count(state) < 2:
                return "finish_gate"

    return "finalize"


def finish_gate_node(state: AgentState) -> dict:
    """Push the model back to work after an early finish declaration."""
    nudge = SystemMessage(content=_FINISH_NUDGE)
    return {
        "messages": [nudge],
        "finish_nudges": state.get("finish_nudges", 0) + 1,
    }

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
def _task_manager_llm(provider: str, model: str):
    """Task classification is MANAGEMENT-class work (short structured
    output, not user-facing prose): route it to the auxiliary client
    (D21). Main model is the fallback, mirroring ai_node's cost-router
    fallback policy — routing must never block a turn."""
    try:
        return get_auxiliary_llm()
    except Exception:
        return get_llm(provider=provider, model=model)


# ==========================================
# D30 TASK-CLASSIFIER QUICK PATH (§46)
# ==========================================
# The task manager used to pay ONE aux-LLM structured-output call for EVERY
# user message once a task was active. Measured reality of sessions: a huge
# share of follow-ups are unambiguous approvals ("ok go", "yess") or
# explicit resets ("new task: ..."). This quick path classifies ONLY those
# slam-dunks for free; anything with a whiff of ambiguity STILL pays the
# aux call (the LLM path below is unchanged). Kill-switch:
# PULSEAI_TASK_CLASSIFIER=llm restores always-LLM behavior.

_D30_ACK_VOCAB = frozenset({
    # single-message approvals/acks — every token must be in this set and
    # the message at most 4 tokens (double-guarded), else the LLM decides.
    "ok", "okay", "k", "kk", "okk", "okkk", "okey", "yes", "yeah", "yeh",
    "yep", "yepp", "yup", "ya", "yah", "yahh", "yess", "yesss", "ys", "ye",
    "y", "sure", "go", "ahead", "proceed", "continue", "do", "it", "lgtm",
    "good", "great", "perfect", "fine", "thanks", "thank", "you", "thx",
    "ty", "cool", "nice", "awesome", "bet", "done", "roger", "copy",
    "aight", "alright", "welp", "bro", "please", "works", "noted", "then",
    "correct", "exactly", "right", "brilliant", "sounds", "looks",
    "for", "amazing", "love", "you're",
    "👍", "✅", "🙏", "🔥", "💯", "❤️", "😍", "🎉",
})

_D30_DANGER_TOKENS = frozenset({
    # ANY of these anywhere => definitely not a plain ack: LLM decides.
    "no", "not", "nope", "nah", "stop", "wait", "hold", "but", "however",
    "redo", "revert", "undo", "change", "actually", "instead", "don't",
    "dont", "why", "what", "how", "explain", "show", "list", "which",
    "wrong", "broken", "error", "fail", "failed", "failing", "issue",
    "doesn't", "didn't", "can't", "wont", "won't", "?", "delete", "remove",
})

_D30_APPROVAL_WORDS = frozenset({
    # must stay in sync with is_plan_approval()'s set: these are routing
    # decisions, not classifications — the approval branch owns them.
    "yes", "proceed", "go ahead", "continue",
    "approve", "approved", "execute", "execute plan", "run plan",
})

_D30_NEW_PREFIXES = (
    "new task", "different task", "another task", "start over",
    "fresh task",
)
_D30_FORGET_PHRASES = (
    "forget the previous task", "forget previous task",
    "forget the current task", "forget current task", "forget this task",
    "forget the old task", "forget that task", "scrap that", "scrap this",
    "scrap everything", "abandon this task",
)


def _quick_task_decision(
    current_task: str, latest_instruction: str
) -> tuple[str, str] | None:
    """Return (action, updated_task) for slam-dunk messages, else None.

    D30 (§46): free classification for the two unambiguous shapes sessions
    are full of — bare acknowledgments (= continue, task text unchanged)
    and explicit task resets (= new). CONSERVATIVE by design, both paths
    double-guarded; every uncertain message returns None and pays the aux
    LLM exactly like before. Kill-switch: PULSEAI_TASK_CLASSIFIER=llm.
    """
    if os.environ.get("PULSEAI_TASK_CLASSIFIER", "").strip().lower() == "llm":
        return None

    raw = (latest_instruction or "").strip()
    if not raw or "\n" in raw:  # multi-line messages are never slam-dunks
        return None
    norm = " ".join(raw.lower().split()).strip(" .!…~")
    if not norm:
        return None

    # Bare plan-approval words BELONG to the approval branch above (which
    # claims them before the quick path ever runs). The veto compares the
    # EXACT phrase (punctuation kept): "yes" is vetoed ("yes, execute the
    # plan" routing), but "yes!" / "yess" are plain acks the approval
    # branch never claimed — safely free. This makes the function safe for
    # ANY future caller, not just today's wiring.
    if " ".join(raw.lower().split()) in _D30_APPROVAL_WORDS:
        return None

    tokens = norm.split()
    if any(t in _D30_DANGER_TOKENS for t in tokens):
        return None

    # --- explicit reset => "new" ----------------------------------------
    import re as _re
    for prefix in _D30_NEW_PREFIXES:
        m = _re.match(
            r"(?is)^" + _re.escape(prefix) + r"(?=\W|$)"
            r"\s*[:,\-–—]?\s*(?:with\s+)?",
            raw,
        )
        if m:
            remainder = raw[m.end():].strip()
            return "new", remainder if len(remainder) >= 3 else raw
    for phrase in _D30_FORGET_PHRASES:
        m = _re.match(
            r"(?is)^" + _re.escape(phrase) + r"(?=\W|$)\s*[:,\-–—]?\s*",
            raw,
        )
        if m:
            remainder = raw[m.end():].strip()
            return "new", remainder if len(remainder) >= 3 else raw

    # --- bare acknowledgment => "continue" --------------------------------
    if len(tokens) <= 4 and all(t in _D30_ACK_VOCAB for t in tokens):
        return "continue", current_task

    return None


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

    # D30 (§46): slam-dunk messages classified for free — ack => continue
    # (task text unchanged), explicit reset => new. Only these two shapes;
    # everything else pays the aux LLM below, exactly like before. (Note:
    # the aux client is constructed AFTER this check — a quick-path turn
    # costs zero LLM anything, not even client setup.)
    quick = _quick_task_decision(current_task, latest_instruction)
    if quick is not None:
        action, updated_task = quick
        if action == "new":
            return {
                "current_task": updated_task,
                "task_action": "new",
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
                "token_usage": _zero_token_usage(),
                "workspace": config["configurable"].get("workspace", "."),
            }
        return {
            "current_task": updated_task,
            "task_action": action,
            "token_usage": state.get("token_usage", _zero_token_usage()),
            "workspace": config["configurable"].get("workspace", "."),
        }

    llm = _task_manager_llm(provider, model)

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
    """Track successful and failed tool operations.

    D9 (§40): this node is now a thin orchestrator over
    src/graphs/progress_helpers.py — every fork of the bookkeeping lives
    there unit-tested; the ORDER of operations below is the behavior
    contract (trace -> memory -> failure/success -> dedupe).
    """

    messages = state.get("messages", [])

    plan = list(state.get("plan", []))
    steps_completed = list(state.get("steps_completed", []))
    failed_steps = list(state.get("failed_steps", []))
    execution_trace = list(state.get("execution_trace", []))
    recovery_attempts = state.get("recovery_attempts", 0)
    recovery_mode = state.get("recovery_mode", False)
    tool_failures = state.get("tool_failures", 0)
    recovery_command = state.get("recovery_command")
    replan_needed = state.get("replan_needed", False)
    env_failures = state.get("env_failures", 0)
    total_usage = TokenUsage.from_dict(state.get("token_usage", {}))

    latest_tools = ph.latest_tool_messages(messages)

    for message in latest_tools:
        tool_name = message.name or "unknown_tool"
        result = str(message.content)
        tool_args = ph.find_tool_args(messages, message.tool_call_id)

        outcome = ph.classify_tool_outcome(tool_name, result)
        if outcome == ph.OUTCOME_SKIP:
            continue  # check_terminal still running: record NOTHING

        failed = outcome == ph.OUTCOME_FAILED

        # Trace comes before memory/failure/success handling (pre-D9 order).
        execution_trace.append(
            ph.make_trace_entry(tool_name, tool_args, result, failed)
        )

        # Store tool output for semantic retrieval (best-effort inside).
        ph.record_tool_memory(
            memory_manager,
            tool_name,
            state.get("current_task", ""),
            result,
            tool_args,
            failed,
        )

        if failed:
            failure, updates = ph.build_failure(
                tool_name, result, tool_args, recovery_mode, recovery_command
            )
            tool_failures += updates["tool_failures_inc"]
            recovery_attempts += updates["recovery_attempts_inc"]
            recovery_mode = updates["recovery_mode"]
            recovery_command = updates["recovery_command"]
            if updates["env_failure"]:
                env_failures += 1

            if failure not in failed_steps:
                failed_steps.append(failure)

            # Environment-level failures repeat identically on retry: skip
            # replanning (the plan isn't wrong, the environment is) and let
            # the recovery loop route to a strategy pivot instead of
            # retry-until-recovery-limit.
            if not updates["env_failure"]:
                needed, usages = ph.maybe_replan(
                    task=state.get("current_task", ""),
                    plan=plan,
                    failure=failure,
                    provider=config["configurable"]["provider"],
                    model=config["configurable"]["model"],
                )
                if usages:
                    replan_needed = needed
                    for usage in usages:
                        total_usage = total_usage + usage
            continue

        # ---------------- success ----------------
        if plan:
            plan = ph.update_plan_from_tool(
                plan=plan,
                tool_name=tool_name,
                tool_args=tool_args,
                failed=False,
            )

        label, events = ph.success_step_label(
            tool_name, tool_args, message.tool_call_id
        )
        for event_name, payload in events:
            event_bus.emit(event_name, payload)

        # Same-operation rule: recovery clears only when the command that
        # originally failed now succeeds.
        recovery_mode, recovery_command = ph.resolve_recovery_on_success(
            tool_name, tool_args, recovery_mode, recovery_command
        )

        if label not in steps_completed:
            steps_completed.append(label)

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
        "env_failures": env_failures,
        "token_usage": total_usage.to_dict(),
    }

    if latest_tools:
        result["messages"] = [
            SystemMessage(content=ph.PROGRESS_REFLECTION_PROMPT)
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
    """Route after tool progress. Decision lives in ph.next_after_progress
    (unit-testable); this node adds plan-completeness and delegates."""
    return ph.next_after_progress(
        recovery_mode=state.get("recovery_mode", False),
        recovery_attempts=state.get("recovery_attempts", 0),
        replan_needed=state.get("replan_needed", False),
        plan_complete=is_plan_complete(state),
        env_failures=state.get("env_failures", 0),
        pivot_count=state.get("pivot_count", 0),
    )

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

def pivot_node(state: AgentState):
    """Strategy pivot on repeated environment-level tool failures.

    Lab run 10: the agent re-ran the same failing command class (npx
    scaffold) until the recovery limit and paused for user input, never
    taking the task's own "provide instructions" branch. This node injects
    explicit pivot guidance, resets the recovery budget so the limit does
    not re-trigger, and routes back to ai with a bounded pivot count."""
    return {
        "messages": [
            SystemMessage(content=ph.PIVOT_GUIDANCE_PROMPT)
        ],
        "pivot_count": state.get("pivot_count", 0) + 1,
        "env_failures": 0,
        "recovery_mode": False,
        "recovery_command": None,
        "recovery_attempts": 0,
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

    def _no_plan() -> dict:
        """Graceful degradation: planning is advisory — a failed plan must
        never kill the turn (lab run 10: planner emitted {"planner": None}
        and stream_agent crashed). Return an empty plan so the agent still
        runs (execution_mode=agent routes planner -> ai)."""
        return {
            "plan": [],
            "plan_goal": "",
            "plan_created": False,
            "token_usage": _merge_token_usage(
                state.get("token_usage", {}),
                usages,
            ),
        }

    try:
        needs_plan = should_create_plan(
            task=current_task,
            provider=provider,
            model=model,
            usage_list=usages,
        )

        if not needs_plan:
            return _no_plan()

        # Cost-aware routing for planning
        routed_provider, routed_model = cost_router.route(current_task)

        try:
            # create_plan uses the provider/model strings, not the llm object
            # directly. Pass the routed ones; if they fail, fallback below.
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
    except Exception as exc:
        print(
            f"[planner] plan generation failed; degrading to no-plan "
            f"({type(exc).__name__}: {exc})"
        )
        return _no_plan()

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

    Interactive threads (human reading): an unsafe call returns an
    approval-question AIMessage and nothing executes.

    Sub-agent threads (``sub-`` prefix, no human reading): that prompt is
    a dead end — verified pre-fix that sub-agents got the identical "please
    confirm" message as mains, facing a reader who does not exist. D20
    adopts hermes' delegate_tool.py policy: non-interactive AUTO-DENY.
    Unsafe calls become denial ToolMessages (model adapts in one turn
    instead of looping to the recursion cap), safe calls in the same batch
    still execute, and every denial is audit-logged. Opt-in escape hatch
    for batch/cron-style runs: PULSEAI_SUBAGENT_AUTO_APPROVE=1 (their
    ``subagent_auto_approve`` config), also audit-logged.
    """
    def __init__(self, tools, safety_guard: SafetyGuard):
        # handle_tool_errors=True — the crash net, decided by experiment
        # (ARCHITECTURE_REVIEW.md §27-28): langgraph>=1.1's DEFAULT handler
        # converts only ToolInvocationError and re-raises anything else,
        # so any unhandled tool exception (file lock, httpx, OSError...) used
        # to kill the whole turn. True = catch-all -> error ToolMessage with
        # intact tool_call pairing; the model reads the error and adapts.
        # GraphInterrupt/GraphBubbleUp are exempted inside ToolNode (verified
        # in 1.2.10 source), so control flow is unaffected.
        self._node = ToolNode(tools, handle_tool_errors=True)
        self._guard = safety_guard
        # D34 (§46): identity registry for parallel-batch eligibility —
        # a call is only parallel-executed when we can identify its tool.
        self._tools_by_name = {t.name: t for t in tools}
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

        # Get workspace + thread from config
        workspace = "."
        thread_id = ""
        if config and "configurable" in config:
            workspace = config["configurable"].get("workspace", ".")
            thread_id = str(config["configurable"].get("thread_id", ""))

        from pathlib import Path
        ws_key = str(Path(workspace).resolve())
        guard = self._guards_by_workspace.get(ws_key)
        if guard is None:
            guard = SafetyGuard(workspace)
            self._guards_by_workspace[ws_key] = guard

        # --- D20: sub-agent threads auto-deny instead of prompting -------
        if thread_id.startswith("sub-") and os.environ.get(
            "PULSEAI_SUBAGENT_AUTO_APPROVE", ""
        ).strip() != "1":
            verdicts = [
                (tc, *guard.check_tool_call(tc.get("name", ""), tc.get("args", {})))
                for tc in tool_calls
            ]
            unsafe = [v for v in verdicts if not v[1]]
            if not unsafe:
                return self._node.invoke(state, config)

            import logging
            log = logging.getLogger("pulseai.safety")
            denials: dict[str, ToolMessage] = {}
            for tc, _, warning in unsafe:
                first_line = warning.strip().splitlines()[0] if warning else "blocked operation"
                denials[tc["id"]] = ToolMessage(
                    content=(
                        f"⛔ AUTO-DENIED (sub-agent safety policy): "
                        f"`{tc.get('name', '')}` was blocked. {first_line}\n"
                        "Sub-agents cannot ask the human for approval, so "
                        "dangerous operations are denied immediately. Do not "
                        "retry this operation; either accomplish the task a "
                        "safe way, or finish and report that this step needs "
                        "the human to run it directly in the main session."
                    ),
                    tool_call_id=tc["id"],
                    name=tc.get("name", ""),
                    status="error",
                )
                log.warning(
                    "sub-agent %s AUTO-DENIED %s args=%s",
                    thread_id, tc.get("name", ""), str(tc.get("args", {}))[:160],
                )

            safe_tcs = [tc for tc, ok, _ in verdicts if ok]
            results: dict[str, ToolMessage] = dict(denials)
            if safe_tcs:
                filtered_ai = AIMessage(
                    content=last_msg.content,
                    tool_calls=safe_tcs,
                    id=getattr(last_msg, "id", None),
                )
                filtered_state = dict(state)
                filtered_state["messages"] = messages[:-1] + [filtered_ai]
                executed = self._node.invoke(filtered_state, config)
                for m in executed.get("messages", []):
                    if isinstance(m, ToolMessage):
                        results[m.tool_call_id] = m

            # Return ToolMessages in the model's original tool_call order:
            # pairing/order invariants (see §28 crash-net round) must hold
            # regardless of which batch members were denied.
            ordered = [results[tc["id"]] for tc in tool_calls if tc.get("id") in results]
            return {"messages": ordered}

        if thread_id.startswith("sub-"):
            import logging
            logging.getLogger("pulseai.safety").warning(
                "sub-agent %s AUTO-APPROVED %d tool call(s) unchecked "
                "(PULSEAI_SUBAGENT_AUTO_APPROVE=1): %s",
                thread_id, len(tool_calls),
                [tc.get("name", "") for tc in tool_calls],
            )
            return self._node.invoke(state, config)

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

        # All safe — proceed to real tool execution.
        # D34 (§46): the tool-batch gate. ToolNode runs multi-call batches
        # CONCURRENTLY by default (measured — v1's "serial" premise was
        # wrong and is owned in §46), including write+read on the SAME
        # file (a race — the reader can get stale content). So: eligible
        # batches keep concurrent execution here; REFUSED batches
        # (conflicting paths / wildcard blast radius) are forced
        # SEQUENTIAL in input order — write-then-read deterministically
        # reads the fresh content. Singletons and unknown tool names fall
        # through to ToolNode (its unknown-tool error text stays
        # canonical). PULSEAI_PARALLEL_TOOLS=off => true legacy below.
        from src.graphs.parallel_tools import (
            try_parallel_batch,
            try_sequential_batch,
        )
        parallel = try_parallel_batch(
            tool_calls, self._tools_by_name, config, workspace
        )
        if parallel is not None:
            return {"messages": parallel}
        sequential = try_sequential_batch(
            tool_calls, self._tools_by_name, config, workspace
        )
        if sequential is not None:
            return {"messages": sequential}
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
    "pivot",
    pivot_node,
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

builder.add_node(
    "finish_gate",
    finish_gate_node,
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
    {
        "tools": "tools",
        "finalize": "finalize",
        "finish_gate": "finish_gate",
    },
)

builder.add_edge(
    "finish_gate",
    "ai",
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
        "pivot": "pivot",
    },
)

builder.add_edge(
    "replanner",
    "ai",
)

builder.add_edge(
    "pivot",
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
_WARNED_DEFAULT_BUCKET = False


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
    if key == "default":
        # Sessions with no thread_id all collapse into one shared engine —
        # the SAFE degradation (isolation loss, never correctness loss, thanks
        # to the per-engine lock), but it means somebody bypassed session
        # plumbing. Say so ONCE per process, never silently.
        global _WARNED_DEFAULT_BUCKET
        if not _WARNED_DEFAULT_BUCKET:
            _WARNED_DEFAULT_BUCKET = True
            print(
                "[chat_graph] ContextEngine request without thread_id — "
                "bucketing to the shared 'default' engine. If this is the "
                "dashboard, a session is missing its thread_id."
            )
    with _ENGINES_LOCK:
        engine = _ENGINES.get(key)
        if engine is None:
            # D21: >8000-char tool outputs may be summarized by the
            # AUXILIARY model (janitor prices) when explicitly enabled;
            # free heuristics remain the default floor (SUMMARIZER_LLM).
            summarizer_llm = None
            from src.config.settings import SUMMARIZER_LLM
            if SUMMARIZER_LLM == "aux":
                try:
                    summarizer_llm = get_auxiliary_llm()
                except Exception:
                    summarizer_llm = None
            engine = ContextEngine(
                model=LLM_MODEL,
                llm=summarizer_llm,
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
            # F2 fix: a planner no-op can emit {"planner": None}; treat as no plan
            # instead of crashing the whole session on .get() of None.
            plan = (plan_data or {}).get("plan", [])
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

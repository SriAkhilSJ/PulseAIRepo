import os
import re
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
from src.llm.factory import (
    get_llm, get_auxiliary_llm, TurnCancelledError, provider_response_info,
)
from src.context.context_engine import ContextEngine
from src.context.memory_manager import MemoryManager
from src.context.token_tracker import TokenTracker, TokenUsage


def _drop_tool_pairs(messages: list) -> list:
    """Strip tool-call/result pairs from a message list so it is a valid
    NO-TOOLS request. The grace call binds no tools, so any AIMessage with
    tool_calls and the ToolMessages answering them must not be sent —
    OpenAI-compat providers hard-400 on "Tool messages found but no tools
    provided". Text-only AIMessages survive (they carry reasoning)."""
    out: list = []
    for m in messages:
        if isinstance(m, ToolMessage):
            continue
        tcs = getattr(m, "tool_calls", None)
        if tcs:
            continue
        out.append(m)
    return out


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
    copy_file,
    typecheck_workspace,
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
# #8 (external review): fault-tolerant browser-tool import. The optional
# mcp/pywintypes stack must never break engine boot — if it is missing the
# browser tools are simply unbound (the D5 fake-verification hole is
# documented in browser_mcp's docstring) and the degradation is loud.
try:
    from src.tools.browser_mcp import BROWSER_TOOLS
except Exception as _browser_mcp_exc:  # ImportError + any transitive boot failure
    BROWSER_TOOLS = []
    print(
        f"[chat_graph] browser tools UNAVAILABLE (import failed: "
        f"{type(_browser_mcp_exc).__name__}: {_browser_mcp_exc}) — "
        "engine boots without them",
        flush=True,
    )
from src.tools.code_exec_tool import execute_code
from src.tools.scaffold_tools import scaffold_nextjs
from src.tools.ui_verification import verify_ui_workspace, verify_ui_routes
from src.tools.session_search_tool import session_search
from src.tools.host_tools import HOST_TOOLS
from src.prompts.claude_persona import system_persona  # D35 (§47)

from src.agents.cost_router import cost_router
from src.agents.skill_manager import skill_manager
from src.agents.sub_agent import subagent_coordinator
from src.dashboard.event_bus import event_bus

# P0-D: state, budget, and gate machinery extracted to focused modules.
from src.graphs.state import AgentState, TaskDecision
from src.graphs.budget import (
    _GRACE_NUDGE,
    _iteration_budget,
    _recursion_limit,
    _budget_exhausted,
    _verification_reserve_reached,
)
from src.graphs.gates import (
    _deliverable_targets,
    _deliverables_missing_on_disk,
    _looks_like_copy_task,
    _looks_like_execution_task,
    _verify_unsatisfied,
    _ran_verification,
    _verification_ran_and_passed,
    _wrote_code_files,
    finish_gate_node,
    should_continue,
)

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
    copy_file,

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

    # Deterministic UI-project setup that preserves _provided inputs and
    # prevents create-next-app workspace/workspace nesting.
    scaffold_nextjs,

    # Zero-LLM recall of past sessions (D16, hermes session-search shape).
    session_search,

    # Lazily discovered read-only intelligence from the native Code OSS host.
    *HOST_TOOLS,

    # Verification receipts: static compiler proof and a deterministic UI
    # pipeline that owns server/browser mechanics without extra model turns.
    typecheck_workspace,
    verify_ui_workspace,
    verify_ui_routes,

    # Test-2 retest (workspace_d): the agent's EYES. A real browser the
    # agent can navigate/snapshot/screenshot — the only thing that can
    # prove a UI app actually renders (D5 faked verification because no
    # browser tool was bound; see browser_mcp docstring). Lazy-spawned, so
    # registering them costs nothing at import.
    *BROWSER_TOOLS,
]


# --------------------------------------------------------------------------- #
# P0-A: Toolset waist (Hermes Law #2 — narrow core, capability at the edges). #
# `tools` stays the FULL registry (the SafeToolNode executes whatever the     #
# model calls), but only the RESOLVED subset is bound on each call, so the    #
# model only pays the token cost for the tools its task actually needs.       #
# Kill-switch: PULSEAI_TOOLSETS=off restores the all-tools binding.           #
# --------------------------------------------------------------------------- #
_TOOLS_BY_NAME: dict[str, Any] = {t.name: t for t in tools}

# Resolve once at import (env rarely changes mid-process); cheap to read.
_PULSEAI_TOOLSETS_ON = (
    os.environ.get("PULSEAI_TOOLSETS", "on").strip().lower() != "off"
)

_FILE_DELIVERY_TOOLS = frozenset({
    "write_file", "edit_file", "copy_file", "scaffold_nextjs",
})
_FILE_DELIVERY_WORDS = frozenset({
    "build", "create", "implement", "write", "fix", "edit", "modify",
    "update", "scaffold", "deliver",
})


def _has_landed_file_delivery(state: AgentState) -> bool:
    """Whether this turn has a successful file-producing receipt."""
    for item in state.get("execution_trace", []) or []:
        if (
            item.get("status") == "success"
            and item.get("tool") in _FILE_DELIVERY_TOOLS
        ):
            return True
    return False


def _requires_file_delivery(state: AgentState) -> bool:
    """Conservative task/plan signal for the pre-delivery loop guard."""
    text = " ".join([
        str(state.get("current_task", "")),
        *(str(step.get("description", "")) for step in state.get("plan", []) or []),
    ]).lower()
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in _FILE_DELIVERY_WORDS)


def _pre_delivery_observation_count(state: AgentState) -> int:
    """Completed tool observations before the first file delivery.

    This count is independent of the model-iteration budget. Test5-6 exposed
    why that matters: execute_code-only turns were refunded, so four different
    empty-workspace scripts could keep the iteration counter below the forced
    delivery threshold forever.
    """
    count = 0
    for item in state.get("execution_trace", []) or []:
        if (
            item.get("status") == "success"
            and item.get("tool") in _FILE_DELIVERY_TOOLS
        ):
            break
        count += 1
    return count


def _pre_delivery_stalled(state: AgentState, *, threshold: int = 4) -> bool:
    """Hermes-style no-progress cap across varied inspection strategies."""
    return (
        _requires_file_delivery(state)
        and not _has_landed_file_delivery(state)
        and (
            int(state.get("iteration_used", 0)) >= threshold
            or _pre_delivery_observation_count(state) >= threshold
        )
    )


def _workspace_is_effectively_empty(workspace: Any) -> bool:
    """Whether a fresh delivery workspace has no user-visible input files."""
    from pathlib import Path
    root = Path(workspace)
    try:
        return not any(
            path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts)
            for path in root.rglob("*")
        )
    except (OSError, ValueError):
        return False


def _resolve_bound_tools(state: AgentState, config: RunnableConfig) -> list:
    """The tool OBJECTS to bind for this turn (narrowed by task type).

    The autonomous surface deliberately has a smaller waist than interactive
    IDE chat. It cannot answer ask_user, and broad meta/delegation/process
    schemas diluted the direct actions in six Test-5 traces.
    """
    if not _PULSEAI_TOOLSETS_ON:
        return tools
    from src.tools.toolsets import resolve_toolset_names
    names = resolve_toolset_names(
        state.get("current_task", ""), config
    )
    autonomous = _is_autonomous_workspace(config)
    if autonomous:
        autonomous_tools = {
            "read_file", "list_files", "search_code",
            "discover_host_capabilities", "invoke_host_capability",
            "write_file", "edit_file", "copy_file",
            "run_terminal", "typecheck_workspace",
            "web_search", "web_fetch",
            "verify_ui_workspace", "verify_ui_routes",
        }
        names = [name for name in names if name in autonomous_tools]
    # A verifier with no project cannot produce evidence. Hiding it is stronger
    # than repeatedly telling a weak model not to call it: Test5-5 paid three
    # model/replan cycles for typecheck_workspace on an empty directory.
    from pathlib import Path
    workspace = Path(config.get("configurable", {}).get("workspace", "."))
    if not (workspace / "tsconfig.json").exists():
        names = [name for name in names if name != "typecheck_workspace"]
    resolved_names = list(names)

    from src.runtime.execution_phases import derive_execution_phase, filter_tool_names
    phase = derive_execution_phase(dict(state))
    names = filter_tool_names(resolved_names, phase)
    empty_autonomous_delivery = (
        autonomous
        and _requires_file_delivery(state)
        and not _has_landed_file_delivery(state)
        and _workspace_is_effectively_empty(workspace)
    )
    if _pre_delivery_stalled(state) or empty_autonomous_delivery:
        # A fresh autonomous build has nothing useful to inspect. Hermes begins
        # headless jobs with action-capable tools; Pulse previously exposed 33
        # schemas and waited four paid observations before narrowing. Make the
        # first provider decision structurally about delivery, while retaining
        # the four-observation cap for non-empty interactive workspaces.
        forced = {"write_file"} if empty_autonomous_delivery else {
            "write_file", "edit_file", "copy_file"
        }
        names = [name for name in resolved_names if name in forced]
        phase = type(phase)(
            "forced_delivery", frozenset(forced),
            max_file_mutations_per_turn=2,
            guidance=(
                "DIRECT DELIVERY PHASE: this task requires files and no file has "
                "landed. Exploration and verification are disabled until a real "
                "file exists. Call write_file NOW with a complete minimal "
                "baseline. Additional files and dependencies can be handled on "
                "the next iteration."
            ),
        )
    elif (
        _verification_reserve_reached(state)
        and _wrote_code_files(state)
        and not _verification_ran_and_passed(state)
    ):
        # Preserve a bounded final slice of the existing token ceiling for
        # dependency/runtime proof. This is a phase change, not a cap increase.
        # Before the first receipt, expose checks rather than another menu of
        # inspection tools: Attempt 12 spent its reserve reading instead of
        # discovering a concrete failure. Once a check fails, re-open narrow
        # inspect/repair tools so the receipt can drive a targeted correction.
        first_check_tools = {
            "run_terminal", "start_terminal", "check_terminal",
            "read_terminal_output", "stop_terminal", "typecheck_workspace",
            "verify_ui_workspace", "verify_ui_routes",
        }
        repair_tools = first_check_tools | {
            "read_file", "search_code", "write_file", "edit_file", "copy_file",
        }
        verification_attempted = _ran_verification(state)
        verification_tools = repair_tools if verification_attempted else first_check_tools
        names = [name for name in resolved_names if name in verification_tools]
        phase_name = (
            "verification_repair" if verification_attempted else "verification_first_check"
        )
        guidance = (
            "VERIFICATION REPAIR PHASE: a concrete check has run but required "
            "evidence is still missing. Inspect only the files named by the "
            "failure, make the smallest repair, and rerun the failed check."
            if verification_attempted else
            "VERIFICATION FIRST-CHECK PHASE: delivery has entered the final "
            "reserved slice of the existing run budget. Stop inspecting and stop "
            "adding features. Run the actual composite UI verifier or project "
            "static/build/test command NOW. The resulting receipt will identify "
            "any exact file that may be reopened for repair."
        )
        phase = type(phase)(
            phase_name, frozenset(verification_tools),
            max_file_mutations_per_turn=2, guidance=guidance,
        )
    # Persist the same allowlist into the tool-node config: textual tool-call
    # repair or a provider quirk must not bypass phase-specific binding.
    configurable = config.setdefault("configurable", {})
    configurable["execution_phase"] = phase.name
    configurable["phase_allowed_tools"] = list(names) if phase.allowed is not None else None
    configurable["phase_max_file_mutations"] = phase.max_file_mutations_per_turn
    configurable["phase_guidance"] = phase.guidance
    bound = [_TOOLS_BY_NAME[n] for n in names if n in _TOOLS_BY_NAME]
    if bound:
        return bound
    # A guarded phase never falls back to the full registry. Keep ask_user as
    # the safe escape hatch; general mode retains the historical safe superset.
    if phase.allowed is not None and "ask_user" in _TOOLS_BY_NAME:
        return [_TOOLS_BY_NAME["ask_user"]]
    return list(tools)


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
autonomous_system_message = SystemMessage(content=system_persona(autonomous=True))


def _is_autonomous_workspace(config: RunnableConfig) -> bool:
    """True for the non-interactive desktop/benchmark workspace surface."""
    return str(config.get("configurable", {}).get("approval_policy", "")).strip().lower() == "workspace_session"


def _insert_system_prefix(messages: list, content: str) -> None:
    """Insert runtime guidance before conversation history, never after user.

    Sarvam receives an OpenAI-compatible role sequence. Appending SystemMessage
    after HumanMessage made the highest-priority delivery instruction a trailing
    role that some adapters/models handle inconsistently. Hermes assembles its
    stable/context/volatile system prefix before conversation messages.
    """
    index = next(
        (i for i, message in enumerate(messages) if getattr(message, "type", "") != "system"),
        len(messages),
    )
    messages.insert(index, SystemMessage(content=content))


def ai_node(
    state: AgentState,
    config: RunnableConfig,
):
    configurable = config["configurable"]
    session_id = str(configurable.get("thread_id") or "default")
    from src.runtime.turn_control import turn_controls
    if turn_controls.cancelled(session_id):
        return {
            "messages": [AIMessage(
                content="Operation cancelled by the user.",
                additional_kwargs={"pulse_cancelled": True},
            )],
            "iteration_used": int(state.get("iteration_used", 0)),
        }

    base_provider = configurable["provider"]
    base_model = configurable["model"]

    # Cost-aware routing: try to use a cheaper/better model for this task
    task_for_routing = state.get("current_task", "")
    plan_for_routing = state.get("plan", [])
    if _is_autonomous_workspace(config):
        # The guarded runner authorizes one named provider/model. Never route a
        # headless paid run through process-global alternative credentials.
        routed_provider, routed_model = base_provider, base_model
    else:
        routed_provider, routed_model = cost_router.route(
            task_for_routing, plan_for_routing
        )

    provider = routed_provider
    model = routed_model
    try:
        llm = get_llm(provider=routed_provider, model=routed_model)
    except Exception:
        # Fallback to the originally configured provider if routing fails
        provider, model = base_provider, base_model
        llm = get_llm(provider=provider, model=model)

    # P0-A: bind only the task-relevant tool subset (narrow waist). The full
    # registry stays available to SafeToolNode for execution; the model just
    # never sees gated tools, so it never calls them (and never pays their
    # per-call definition cost).
    llm_with_tools = llm.bind_tools(_resolve_bound_tools(state, config))

    # D31: start of an AI iteration — reset shadow-checkpoint dedup so the
    # first mutation this iteration snapshots the pre-change workspace.
    from src.tools.shadow_checkpoints import begin_agent_turn
    begin_agent_turn()

    # D40: iteration budget. Once exhausted, tools are hidden and the model
    # may only produce text (the hermes grace call). The FIRST exhausted call
    # carries the grace nudge; a model that keeps hallucinating tool calls
    # still cannot — no tools are bound — and should_continue finalizes the
    # text. iteration_used increments on BOTH paths so budget accounting is
    # monotonic.
    iteration_used = int(state.get("iteration_used", 0))
    budget_exhausted = _budget_exhausted(state)
    grace_done = bool(state.get("grace_done", 0))

    # Use the Context Engine to build clean, organized messages.
    # Session-scoped: this thread's thread_id selects an isolated engine
    # (cache, attribution snapshot, learned weights all independent).
    context_state = dict(state)
    context_state["_autonomous_workspace"] = _is_autonomous_workspace(config)
    messages = get_context_engine(config).build_ai_messages(
        state=context_state,
        system_message=(
            autonomous_system_message
            if context_state["_autonomous_workspace"]
            else system_message
        ),
    )
    phase_guidance = str(configurable.get("phase_guidance") or "").strip()
    if phase_guidance:
        _insert_system_prefix(
            messages,
            f"=== RUNTIME EXECUTION PHASE: {configurable.get('execution_phase')} ===\n"
            + phase_guidance,
        )

    # State the actual shell contract before the model guesses. The terminal
    # tool uses shell=True, which is cmd.exe on the founder's Windows runtime;
    # Test5-5 wasted its first execution calls discovering that ls/pwd/find do
    # not exist. Keep this dynamic so Linux/macOS behavior is unchanged.
    import platform as _platform
    _os_name = _platform.system() or os.name
    if _os_name == "Windows":
        _insert_system_prefix(
            messages,
            "=== ACTIVE TERMINAL PLATFORM ===\n"
            "Windows cmd.exe. NEVER use POSIX commands such as ls, pwd, find, "
            "head, grep, cat, rm, cp, mv, touch, chmod, or /tmp paths. Use "
            "dir, cd, where, type, findstr, copy, move, del, or an explicit "
            "PowerShell -NoProfile -Command invocation. Prefer native file "
            "tools over shell inspection.",
        )

    if (
        _requires_file_delivery(state)
        and not _has_landed_file_delivery(state)
        and int(state.get("iteration_used", 0)) >= 2
        and configurable.get("execution_phase") != "forced_delivery"
    ):
        _insert_system_prefix(
            messages,
            "=== PRE-DELIVERY NO-PROGRESS WARNING ===\n"
            "This task requires files, but no file mutation has landed after "
            "multiple main-agent iterations. Stop inspecting/planning. Your "
            "next response must create the smallest complete baseline with "
            "write_file (batch independent files). Do not verify an empty "
            "workspace.",
        )
    steers = turn_controls.drain_steer(session_id)
    if steers:
        messages.append(SystemMessage(content=(
            "=== OUT-OF-BAND USER STEER ===\n"
            "The user sent this correction during the active turn. Adjust now; "
            "do not repeat already-completed work.\n" + "\n".join(steers)
        )))

    call_model = model
    call_llm = llm_with_tools
    if configurable.get("execution_phase") in {"deliver", "forced_delivery"}:
        try:
            delivery_cap = int(os.environ.get("PULSEAI_DELIVERY_MAX_TOKENS", "4096"))
        except (TypeError, ValueError):
            delivery_cap = 4096
        bind_generation = getattr(llm_with_tools, "bind", None)
        if callable(bind_generation):
            call_llm = bind_generation(
                max_tokens=max(512, min(delivery_cap, 8192))
            )
    if budget_exhausted:
        call_llm = llm  # unhidden tools: the model cannot make more calls
        if not grace_done:
            messages = [SystemMessage(content=_GRACE_NUDGE)] + messages
        # D40 (lab retest 2026-08-13): the grace call binds NO tools, but
        # the raw history still ends in an AIMessage(tool_calls) +
        # ToolMessage tail. OpenAI-compat providers reject "Tool messages
        # found but no tools provided" with a 400 — the harness paid for
        # a full budget run (54 calls) and died on the FAREWELL call.
        # Drop tool pairs so the no-tools request is a clean text chat.
        messages = _drop_tool_pairs(messages)

    # RetryLLMProxy.invoke() owns request-scoped abort registration for every
    # model path. Keep the active-session binding at the turn boundary; clearing
    # it here would make later planner/classifier requests uninterruptible.
    try:
        result = call_llm.invoke(messages)
    except Exception as exc:
        # A Stop that fired while the request was in flight wins over provider
        # failover: never launch a base-provider request after cancellation.
        if turn_controls.cancelled(session_id):
            print(
                f"[ai_node] provider-failover path cancelled for {session_id}; "
                f"NOT failing over to {base_provider}/{base_model}"
            )
            return {
                "messages": [AIMessage(
                    content="Operation cancelled by the user.",
                    additional_kwargs={"pulse_cancelled": True},
                )],
                "iteration_used": int(state.get("iteration_used", 0)),
            }
        if (provider, model) == (base_provider, base_model):
            raise
        print(
            f"[ai_node] provider failover {provider}/{model} -> "
            f"{base_provider}/{base_model} ({type(exc).__name__})"
        )
        provider, model = base_provider, base_model
        llm = get_llm(provider=provider, model=model)
        llm_with_tools = llm.bind_tools(_resolve_bound_tools(state, config))
        from src.context.cache_preservation import redecorate_for_failover
        messages, _d37_info = redecorate_for_failover(messages)
        call_model = model
        call_llm = llm_with_tools
        if configurable.get("execution_phase") in {"deliver", "forced_delivery"}:
            try:
                delivery_cap = int(os.environ.get("PULSEAI_DELIVERY_MAX_TOKENS", "4096"))
            except (TypeError, ValueError):
                delivery_cap = 4096
            bind_generation = getattr(llm_with_tools, "bind", None)
            if callable(bind_generation):
                call_llm = bind_generation(
                    max_tokens=max(512, min(delivery_cap, 8192))
                )
        if budget_exhausted:
            call_llm = llm
        try:
            result = call_llm.invoke(messages)
        except TurnCancelledError:
            return {
                "messages": [AIMessage(
                    content="Operation cancelled by the user.",
                    additional_kwargs={"pulse_cancelled": True},
                )],
                "iteration_used": int(state.get("iteration_used", 0)),
            }

    # ── Post-LLM cancellation gate ──────────────────────────────
    # Check immediately after every blocking LLM invocation. If the
    # user pressed Stop while the HTTP request was in flight, the
    # result contains tool_calls that MUST NOT execute. Replace the
    # result with a cancellation message and let should_continue
    # route to finalize (pulse_cancelled=True). Preserve valid
    # tool-call/result pairing by never returning orphaned tool
    # calls into the graph.
    if turn_controls.cancelled(session_id):
        print(
            f"[ai_node] post-LLM cancellation detected for {session_id}; "
            f"discarding LLM result with {len(getattr(result, 'tool_calls', None) or [])} tool_call(s)"
        )
        return {
            "messages": [AIMessage(
                content="Operation cancelled by the user.",
                additional_kwargs={"pulse_cancelled": True},
            )],
            "iteration_used": int(state.get("iteration_used", 0)),
        }

    # Hermes-pattern repair: some models emit tool calls as TEXT
    # (<tool_call>NAME<arg_key>...<arg_value>...) instead of structured
    # tool_calls. Parse them so the loop can execute instead of stalling.
    from src.graphs.parallel_tools import repair_text_tool_calls
    result = repair_text_tool_calls(result)

    # Hermes refuses to dispatch tool arguments from a token-limited response.
    # Preserve the assistant/tool pairing, but mark the message so SafeToolNode
    # returns an explicit error observation instead of mutating the workspace.
    # The next iteration can split the write or continue with a larger budget.
    completion = provider_response_info(result)
    incomplete_retries = int(state.get("incomplete_response_retries", 0))
    if completion["incomplete"]:
        incomplete_retries += 1
        extra = dict(getattr(result, "additional_kwargs", {}) or {})
        extra["pulse_incomplete_response"] = True
        extra["pulse_incomplete_reason"] = completion["finish_reason"]
        extra["pulse_raw_finish_reason"] = completion["raw_finish_reason"]
        try:
            result = result.model_copy(update={"additional_kwargs": extra})
        except AttributeError:
            result.additional_kwargs = extra
    else:
        incomplete_retries = 0

    # =========================================================
    # TRACK TOKEN USAGE
    # =========================================================
    call_usage = TokenTracker.record_call(messages, result, call_model)
    token_usage = _merge_token_usage(
        state.get("token_usage", {}),
        [call_usage],
    )
    turn_token_usage = _merge_token_usage(
        state.get("turn_token_usage", {}),
        [call_usage],
    )

    # Every provider iteration counts. Hermes refunds execute_code-only turns,
    # but it also runs a much larger default parent budget and a separate tool
    # guardrail controller. Copying only the refund into Pulse's 20-call paid
    # harness created an unbounded blind spot: Test5-6 issued four os.walk
    # execute_code inspections without advancing the counter that activates
    # forced delivery. PTC still saves round trips when it batches real work;
    # it is not free when it consumes another provider request.
    next_used = iteration_used + 1

    return {
        "messages": [result],
        "token_usage": token_usage,
        "turn_token_usage": turn_token_usage,
        "iteration_used": next_used,
        "incomplete_response_retries": incomplete_retries,
        "grace_done": 1 if budget_exhausted else grace_done,
    }




def finalize_node(state: AgentState, config: RunnableConfig):
    last = state.get("messages", [])[-1] if state.get("messages") else None
    if bool(getattr(last, "additional_kwargs", {}).get("pulse_cancelled")):
        return {
            "task_completed": False,
            "task_status": "cancelled",
            "messages": [AIMessage(content="Operation cancelled by the user.")],
        }

    plan = finalize_plan(
        plan=list(state.get("plan", [])),
        task_succeeded=True,
    )

    # Store successful task in long-term memory.
    current_task = state.get("current_task") or state.get("latest_instruction", "")
    steps_completed = state.get("steps_completed", [])
    failed_steps = state.get("failed_steps", [])

    # Feedback loop: record FAILURE if the task ended with failed steps,
    # otherwise success. (Previously success was recorded unconditionally,
    # so the learning loop only ever saw wins.)
    #
    # D9: a run that finalizes with UNVERIFIED code (budget exhausted or
    # the model stopped early) is a failure, not a success — record it as
    # such so the learning loop never rewards an unproven "finished".
    # Honesty is independent of the bounded nudge budget. A run that exhausted
    # its continuation attempts is still unverified when required receipts are
    # absent; bounded routing must never turn missing evidence into a PASS.
    from src.graphs.gates import _verification_ran_and_passed
    unverified = (
        _looks_like_execution_task(current_task)
        and _wrote_code_files(state)
        and not _verification_ran_and_passed(state)
    )
    task_succeeded = not unverified and not bool(failed_steps)
    if not task_succeeded:
        plan = finalize_plan(
            plan=list(state.get("plan", [])),
            task_succeeded=False,
        )
    elif memory_manager and current_task and steps_completed:
        memory_manager.store_task_completion(
            task=current_task,
            steps_completed=steps_completed,
            plan=plan,
        )
    try:
        engine = get_context_engine(config)
        if state.get("failed_steps") or unverified:
            engine.record_feedback(success=False, task=current_task)
        else:
            engine.record_feedback(success=True, task=current_task)
    except Exception:
        pass  # Feedback is best-effort; never block finalization


    # Build a beautiful completion message. Honesty gate (D9): the
    # finalize node used to stamp "## ✅ Finished" unconditionally — a
    # budget-exhausted run with a failing typecheck and a broken app
    # still closed with a green checkmark. When verification never
    # passed, say so plainly instead of claiming success.
    lines = []
    task_display = current_task[:70] if current_task else "Task"
    if unverified:
        lines.append(f"## ⚠️ Ended unverified: {task_display}")
        lines.append("")
        lines.append(
            "**This run did NOT pass verification.** Code was written but "
            "no check proved it sound — typecheck failed or never ran, and "
            "the app was not proven to render. Do not treat this as a "
            "working deliverable until verification passes."
        )
        lines.append("")
    elif failed_steps:
        lines.append(f"## ⚠️ Ended incomplete: {task_display}")
        lines.append("")
        lines.append("**This run ended with unresolved failures.**")
        lines.append("")
    else:
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

    _final_thread_id = str(config.get("configurable", {}).get("thread_id", "default"))
    event_bus.emit("analytics.update", {
        "thread_id": _final_thread_id,
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
        "thread_id": _final_thread_id,
        "suggestions": [{"text": s} for s in reflection.get("suggestions", [])],
    })

    return {
        "plan": plan,
        "task_completed": task_succeeded,
        "task_status": (
            "unverified" if unverified
            else "failed" if failed_steps
            else "completed"
        ),
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

    # Boundary consistency (external review #7, round 3): an ack CONTAINING
    # an approval phrase is approval-flavoured ("ok go ahead" ~ "go ahead")
    # and must pay the classifier like the exact phrase. Matching is on
    # WHOLE TOKENS / token n-grams, never substrings — "yesterday" must not
    # match "yes". Free "continue" stays reserved for pure acks.
    norm_tokens = norm.split()
    norm_ngrams = {
        " ".join(norm_tokens[i:i + n])
        for n in (1, 2, 3)
        for i in range(len(norm_tokens) - n + 1)
    }
    approval_hits = norm_ngrams & _D30_APPROVAL_WORDS
    # Punctuation changes routing semantics for one-word approvals: the plan
    # approval branch claims bare "yes", but intentionally does not claim
    # conversational acknowledgements such as "yes!". Do not erase that
    # distinction when building normalized n-grams. Multi-word approval
    # phrases (for example "go ahead" inside "go ahead bro") remain guarded.
    punctuated_single_ack = (
        len(norm_tokens) == 1
        and raw.lower() != norm
        and norm in _D30_APPROVAL_WORDS
    )
    if approval_hits and not punctuated_single_ack:
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
            # Programmatic/IDE callers may seed an already-approved plan to
            # avoid two advisory planner calls on deterministic workflows.
            # Ordinary chat supplies no plan and retains the legacy path.
            "plan": list(state.get("plan", [])),
            "plan_goal": state.get("plan_goal", ""),
            "plan_created": bool(state.get("plan_created") and state.get("plan")),
            "plan_approved": bool(state.get("plan_approved")),
            "plan_revision_count": 0,
            "replan_needed": False,
            "replan_count": 0,
            "execution_trace": [],
            "task_completed": False,
            "prior_attempts": [],
            "token_usage": _zero_token_usage(),
            "turn_token_usage": _zero_token_usage(),
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
                "turn_token_usage": _zero_token_usage(),
                "workspace": config["configurable"].get("workspace", "."),
            }
        return {
            "current_task": updated_task,
            "task_action": action,
            "token_usage": state.get("token_usage", _zero_token_usage()),
            "workspace": config["configurable"].get("workspace", "."),
        }

    # ── Pre-LLM cancellation gate (task_manager) ──────────────
    session_id_tm = str(configurable.get("thread_id") or "default")
    from src.runtime.turn_control import turn_controls as _tc_tm
    if _tc_tm.cancelled(session_id_tm):
        return {
            "current_task": current_task,
            "task_action": "cancelled",
            "task_status": "cancelled",
            "task_completed": False,
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
            "turn_token_usage": _merge_token_usage({}, [call_usage]),
            "iteration_used": 0,
            "grace_done": 0,
            "workspace": config["configurable"].get("workspace", "."),
        }

    return {
        "current_task": updated_task,
        "task_action": decision.action,
        "token_usage": token_usage,
        "turn_token_usage": _merge_token_usage({}, [call_usage]),
        "iteration_used": 0,
        "grace_done": 0,
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
    command_retries = dict(state.get("command_retries", {}))

    latest_tools = ph.latest_tool_messages(messages)
    injected: list = []
    processed_tools = 0

    for message in latest_tools:
        tool_name = message.name or "unknown_tool"
        result = str(message.content)
        tool_args = ph.find_tool_args(messages, message.tool_call_id)

        outcome = ph.classify_tool_outcome(tool_name, result)
        if outcome == ph.OUTCOME_SKIP:
            continue  # running/unavailable check: record NOTHING

        processed_tools += 1
        failed = outcome == ph.OUTCOME_FAILED

        # Trace comes before memory/failure/success handling (pre-D9 order).
        execution_trace.append(
            ph.make_trace_entry(tool_name, tool_args, result, failed)
        )

        # Store tool output for semantic retrieval in interactive sessions.
        # Autonomous context deliberately excludes historical/tool memory; do
        # not initialize a sentence-transformer after the first landed file
        # merely to write memory the same run will never read. Attempt 8 proved
        # this boundary could wedge for >10 minutes between tool_call_end and
        # the second provider request.
        if not _is_autonomous_workspace(config):
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

            # R3-1: identical-retry cap. Fingerprint a failed terminal/exec
            # call by its command; when the SAME command has failed 3+ times
            # identically, stop the loop HERE with a directive (R3 burned 25
            # identical `mkdir -p /tmp/...` calls against Windows back-to-back —
            # the model was re-learning the same error every turn). The nudge
            # appends as a SystemMessage routed back to the model BEFORE the
            # next ai call, and a count == 3 means it fires exactly once per
            # fingerprint.
            if tool_name in ("run_terminal", "execute_code") and tool_args:
                fingerprint = ph.command_fingerprint(tool_name, tool_args)
                if fingerprint:
                    command_retries[fingerprint] = command_retries.get(fingerprint, 0) + 1
                    if command_retries[fingerprint] == 3:
                        injected.append(
                            SystemMessage(
                                content=ph.IDENTICAL_FAILURE_NUDGE.format(
                                    tool_name=tool_name,
                                    count=command_retries[fingerprint],
                                )
                            )
                        )

            if failure not in failed_steps:
                failed_steps.append(failure)

            # Environment-level failures repeat identically on retry: skip
            # replanning (the plan isn't wrong, the environment is) and let
            # the recovery loop route to a strategy pivot instead of
            # retry-until-recovery-limit.
            # ── Pre-LLM cancellation gate (progress replan) ─────
            # maybe_replan consults the LLM (should_replan); after a Stop the
            # failure bookkeeping above still lands, but the replan LLM must
            # not be paid for.
            _sid_pg = str(config["configurable"].get("thread_id") or "default")
            from src.runtime.turn_control import turn_controls as _tc_pg
            if not updates["env_failure"] and not _tc_pg.cancelled(_sid_pg):
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
        # A successful read may still be a no-progress loop when the model
        # repeatedly receives the same observation but fails to act on it.
        # Nudge after the third identical name+args+result, before an external
        # watchdog has to kill the fourth call.
        read_fp = ph.read_fingerprint(tool_name, tool_args, result)
        if read_fp:
            command_retries[read_fp] = command_retries.get(read_fp, 0) + 1
            if command_retries[read_fp] == 3:
                injected.append(
                    SystemMessage(
                        content=ph.IDENTICAL_READ_NUDGE.format(
                            tool_name=tool_name,
                            count=command_retries[read_fp],
                        )
                    )
                )

        if plan:
            plan = ph.update_plan_from_tool(
                plan=plan,
                tool_name=tool_name,
                tool_args=tool_args,
                failed=False,
                result=result,
            )

        label, events = ph.success_step_label(
            tool_name, tool_args, message.tool_call_id
        )
        for event_name, payload in events:
            event_bus.emit(event_name, {
                **payload,
                "thread_id": str(config.get("configurable", {}).get("thread_id", "default")),
            })

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

    if processed_tools:
        # ToolMessage already carries the observation. The generic reflection
        # system message repeats planning/verify/ask guidance after every tool
        # and competed with direct progress in non-interactive runs. Preserve it
        # for rich IDE chat; autonomous execution gets only concrete recovery
        # injections, if any.
        if _is_autonomous_workspace(config):
            if injected:
                result["messages"] = injected
        else:
            result["messages"] = [
                SystemMessage(content=ph.PROGRESS_REFLECTION_PROMPT)
            ]
            if injected:
                result["messages"] = result["messages"] + injected

    if command_retries:
        result["command_retries"] = command_retries

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
    (unit-testable); this node adds plan-completeness and delegates.

    D7 hardening: next_after_progress finalizes a plan-complete task
    WITHOUT consulting the verify gate — and plan completion is model-
    DECLARED (self-marked steps). A model that marks "verify in browser"
    complete without doing it used to finalize clean (D7: typecheck
    failed 57 errors, zero browser calls, 8/8 steps self-marked). When
    the plan-complete route would finalize but verification is
    unsatisfied, route through finish_gate so the bounded nudge fires.
    E2-1: likewise, a named deliverable missing on disk must not
    finalize through the plan-complete shortcut — the E2 copy nudge
    fires instead.
    """
    route = ph.next_after_progress(
        recovery_mode=state.get("recovery_mode", False),
        recovery_attempts=state.get("recovery_attempts", 0),
        replan_needed=state.get("replan_needed", False),
        plan_complete=is_plan_complete(state),
        env_failures=state.get("env_failures", 0),
        pivot_count=state.get("pivot_count", 0),
    )
    if route == "finalize" and (
        _verify_unsatisfied(state)
        or _deliverables_missing_on_disk(state, state.get("workspace", "."))
    ):
        return "finish_gate"
    return route

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
    configurable = config["configurable"]

    # ── Pre-LLM cancellation gate (planner) ───────────────────
    # planning calls the LLM (should_create_plan / create_plan); a Stop that
    # fired before this node must never pay for a new model invocation.
    session_id_pl = str(configurable.get("thread_id") or "default")
    from src.runtime.turn_control import turn_controls as _tc_pl
    if _tc_pl.cancelled(session_id_pl):
        return {
            "messages": [AIMessage(
                content="Operation cancelled by the user.",
                additional_kwargs={"pulse_cancelled": True},
            )],
        }

    current_task = state.get("current_task", "")
    plan_created = state.get("plan_created", False)

    provider = configurable["provider"]
    model = configurable["model"]

    # Keep the existing plan for the active task.
    if plan_created:
        return {}

    # Nothing meaningful to plan.
    if not current_task:
        return {}

    # The autonomous workspace request is already a complete task contract and
    # has a finite provider budget. Pulse previously spent multiple provider
    # calls classifying, generating, and validating a plan before the action
    # loop, unlike Hermes' direct headless conversation loop. Planning remains
    # available in explicit plan mode and throughout interactive IDE chat.
    if _is_autonomous_workspace(config) and state.get("execution_mode", "agent") == "agent":
        return {
            "plan": [],
            "plan_goal": "",
            "plan_created": False,
            "token_usage": state.get("token_usage", _zero_token_usage()),
        }

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
    # A cancelled planner/plan_reviser must surface the cancellation message
    # instead of the (possibly stale) plan preview.
    last = state.get("messages", [])[-1] if state.get("messages") else None
    if bool(getattr(last, "additional_kwargs", {}).get("pulse_cancelled")):
        return {"messages": [AIMessage(content="Operation cancelled by the user.")]}
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
    configurable = config["configurable"]

    # ── Pre-LLM cancellation gate (plan_reviser) ──────────────
    # revise_plan invokes the LLM; a Stop must short-circuit before it.
    session_id_rv = str(configurable.get("thread_id") or "default")
    from src.runtime.turn_control import turn_controls as _tc_rv
    if _tc_rv.cancelled(session_id_rv):
        return {
            "messages": [AIMessage(
                content="Operation cancelled by the user.",
                additional_kwargs={"pulse_cancelled": True},
            )],
        }

    current_plan = state.get("plan", [])

    if not current_plan:
        return {}

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

    # ── Pre-LLM cancellation gate (replanner) ─────────────────
    # create_replan invokes the LLM; a Stop must short-circuit before it.
    session_id_rp = str(configurable.get("thread_id") or "default")
    from src.runtime.turn_control import turn_controls as _tc_rp
    if _tc_rp.cancelled(session_id_rp):
        return {
            "messages": [AIMessage(
                content="Operation cancelled by the user.",
                additional_kwargs={"pulse_cancelled": True},
            )],
        }

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

    def _cancelled_tool_messages(self, tool_calls: list[dict], config) -> list[ToolMessage]:
        return [
            self._durable_denial(
                tc, "⛔ Operation cancelled by the user — tool not executed.", config
            )
            for tc in tool_calls
        ]

    @staticmethod
    def _session_id(config) -> str:
        return str(
            (config or {}).get("configurable", {}).get("thread_id") or "default"
        )

    def _execute_durable(self, tool_calls: list[dict], config) -> list[ToolMessage]:
        """Admit and execute known calls through the durable journal path."""
        from src.runtime.turn_control import turn_controls

        if not turn_controls.admit_action(self._session_id(config)):
            return self._cancelled_tool_messages(tool_calls, config)
        from src.graphs.parallel_tools import run_durable_batch_sequential
        return run_durable_batch_sequential(
            tool_calls, self._tools_by_name, config
        )

    def _diff_payload(self, tool_call: dict, workspace: str) -> dict | None:
        name = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        if name not in {"write_file", "edit_file", "copy_file"}:
            return None
        try:
            from src.tools.file_tools import resolve_workspace_path
            path_arg = args.get("path") or args.get("dst") or ""
            path = resolve_workspace_path(workspace, str(path_arg))
            old = path.read_text(encoding="utf-8") if path.is_file() else None
            if name == "write_file":
                new = str(args.get("content", ""))
            elif name == "edit_file":
                needle = str(args.get("old_text", ""))
                replacement = str(args.get("new_text", ""))
                new = old.replace(needle, replacement, 1) if old is not None and needle in old else replacement
            else:
                src = resolve_workspace_path(workspace, str(args.get("src", "")))
                new = src.read_text(encoding="utf-8", errors="replace") if src.is_file() else ""
            return {"path": str(path), "old_text": old, "new_text": new}
        except Exception as exc:
            return {"error": f"could not prepare diff: {exc}"}

    @staticmethod
    def _durable_denial(tc: dict, content: str, config) -> ToolMessage:
        """Close a blocked tool lifecycle without invoking the blocked tool.

        The renderer emits ``tool.call`` as soon as the model proposes a call.
        Safety denials used to return only a ToolMessage, leaving that visible
        start permanently unmatched. Route the denial text through the durable
        transaction boundary so journal and UI receive a terminal error event.
        """
        from src.runtime.tool_middleware import execute_tool_transaction
        outcome = execute_tool_transaction(
            name=tc.get("name", ""), args=dict(tc.get("args") or {}),
            tool_call_id=tc.get("id", ""), config=config,
            invoke=lambda: content,
        )
        return ToolMessage(
            content=outcome.content, tool_call_id=tc.get("id", ""),
            name=tc.get("name", ""), status="error",
        )

    def _deny_and_execute_safe_batch(
        self, *, tool_calls, verdicts, unsafe, state, messages, last_msg,
        config, denial_content, log_line,
    ):
        """Shared unsafe-batch path (#9, external review): the sub-agent
        auto-deny and the autonomous main-thread deny were two copy-pasted
        50-line blocks — a bug fixed in one silently lived on in the other.
        One implementation now owns the whole shape: denial ToolMessages for
        the unsafe calls, execution of the SAFE remainder, results returned
        in the model's original tool_call order (pairing/order invariants
        hold regardless of which batch members were denied). Callers own the
        denial TEXT and the audit-log line; everything else is identical
        because it must be.
        """
        denials: dict[str, ToolMessage] = {}
        for tc, _, warning in unsafe:
            first_line = warning.strip().splitlines()[0] if warning else "blocked operation"
            content = denial_content(tc, first_line)
            denials[tc["id"]] = self._durable_denial(tc, content, config)
            log_line(tc)
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
            for m in self._execute_durable(safe_tcs, config):
                results[m.tool_call_id] = m
        ordered = [results[tc["id"]] for tc in tool_calls if tc.get("id") in results]
        return ordered

    def __call__(self, state, config=None):
        # ── Pre-execution cancellation gate ─────────────────────────
        # If the user pressed Stop before tool execution begins, deny
        # ALL pending tool calls with cancellation ToolMessages. This
        # prevents any tool (write_file, run_terminal, etc.) from
        # running after the user asked to stop. The AI result's
        # tool_calls are still in the state; we must produce a
        # ToolMessage for each one to preserve valid pairing.
        _cfg_ws = "."
        _cfg_tid = ""
        if config and "configurable" in config:
            _cfg_ws = config["configurable"].get("workspace", ".")
            _cfg_tid = str(config["configurable"].get("thread_id", ""))
        _cfg_sid = str(config["configurable"].get("thread_id") or "default") if config and "configurable" in config else "default"
        from src.runtime.turn_control import turn_controls as _tc
        if _tc.cancelled(_cfg_sid):
            print(
                f"[SafeToolNode] pre-execution cancellation for {_cfg_sid}; "
                f"denying all pending tool calls"
            )
            messages = state.get("messages", [])
            if not messages:
                return self._node.invoke(state, config)
            last_msg = messages[-1]
            tool_calls = getattr(last_msg, "tool_calls", None)
            if not tool_calls:
                return self._node.invoke(state, config)
            return {"messages": self._cancelled_tool_messages(tool_calls, config)}

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

        # hermes _uniquify_tool_call_ids (#58327): models occasionally
        # reuse or omit call ids inside one batch — a reused id silently
        # loses the later call's result. Repair deterministically and
        # rewrite the assistant message (same id, so add_messages replaces
        # it) so result pairing stays consistent for the next model call.
        from src.graphs.parallel_tools import repair_tool_call_ids
        _repaired_tcs, _ids_changed = repair_tool_call_ids(tool_calls)
        _repaired_ai = None
        if _ids_changed:
            tool_calls = _repaired_tcs
            _repaired_ai = AIMessage(
                content=last_msg.content,
                tool_calls=_repaired_tcs,
                id=getattr(last_msg, "id", None),
            )

        def _with_repaired(msg_list: list) -> dict:
            if _repaired_ai is None:
                return {"messages": msg_list}
            return {"messages": [_repaired_ai, *msg_list]}

        def _cancelled_result(calls: list[dict] | None = None) -> dict:
            return _with_repaired(
                self._cancelled_tool_messages(calls or tool_calls, config)
            )

        # Never execute tool arguments from a token-limited provider response.
        # Hermes treats a mid-tool/length completion as incomplete and asks the
        # model to split or continue; Attempt 8 showed that accepting a partial
        # write can land a syntactically valid JSON string whose file content
        # ends mid-CSS. Return one paired error per call, with zero side effects.
        incomplete = bool(
            getattr(last_msg, "additional_kwargs", {}).get(
                "pulse_incomplete_response"
            )
        )
        if incomplete:
            reason = str(
                getattr(last_msg, "additional_kwargs", {}).get(
                    "pulse_incomplete_reason", "provider token limit"
                )
            )
            return _with_repaired([
                self._durable_denial(
                    tc,
                    "Error: provider response was incomplete "
                    f"({reason}); tool was NOT executed. Split large file "
                    "writes into smaller complete files/calls and continue.",
                    config,
                )
                for tc in tool_calls
            ])

        # Phase allowlist is enforced again at execution time. Binding is the
        # normal control, but textual tool-call repair must not become a bypass.
        phase_allowed = None
        phase_name = "general"
        if config and "configurable" in config:
            phase_allowed = config["configurable"].get("phase_allowed_tools")
            phase_name = str(config["configurable"].get("execution_phase") or "general")
        if phase_allowed is not None:
            denied = [tc for tc in tool_calls if tc.get("name", "") not in set(phase_allowed)]
            if denied:
                denied_names = ", ".join(sorted({tc.get("name", "") for tc in denied}))
                denial = (
                    f"⛔ PHASE POLICY DENIED batch in {phase_name}: {denied_names}. "
                    "No calls in this batch executed. Use only the tools exposed for "
                    "the current plan phase and make the required progress now."
                )
                return _with_repaired([
                    self._durable_denial(tc, denial, config) for tc in tool_calls
                ])

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
                return _with_repaired(self._execute_durable(tool_calls, config))

            import logging
            _log = logging.getLogger("pulseai.safety")

            def _content(tc, first_line):
                return (
                    f"⛔ AUTO-DENIED (sub-agent safety policy): "
                    f"`{tc.get('name', '')}` was blocked. {first_line}\n"
                    "Sub-agents cannot ask the human for approval, so "
                    "dangerous operations are denied immediately. Do not "
                    "retry this operation; either accomplish the task a "
                    "safe way, or finish and report that this step needs "
                    "the human to run it directly in the main session."
                )

            def _log_line(tc):
                _log.warning(
                    "sub-agent %s AUTO-DENIED %s args=%s",
                    thread_id, tc.get("name", ""), str(tc.get("args", {}))[:160],
                )

            ordered = self._deny_and_execute_safe_batch(
                tool_calls=tool_calls, verdicts=verdicts, unsafe=unsafe,
                state=state, messages=messages, last_msg=last_msg,
                config=config, denial_content=_content, log_line=_log_line,
            )
            return _with_repaired(ordered)

        if thread_id.startswith("sub-"):
            import logging
            logging.getLogger("pulseai.safety").warning(
                "sub-agent %s AUTO-APPROVED %d tool call(s) unchecked "
                "(PULSEAI_SUBAGENT_AUTO_APPROVE=1): %s",
                thread_id, len(tool_calls),
                [tc.get("name", "") for tc in tool_calls],
            )
            return _with_repaired(self._execute_durable(tool_calls, config))

        verdicts = [
            (tc, *guard.check_tool_call(tc.get("name", ""), tc.get("args", {})))
            for tc in tool_calls
        ]
        unsafe = [v for v in verdicts if not v[1]]
        autonomous = os.environ.get("PULSEAI_AUTO_APPROVE_WRITES", "").strip() == "1"
        if unsafe and autonomous:
            # D11: per-call DENIAL instead of a fabricated AIMessage — the
            # AUTONOMOUS path (no human to answer). The old main-thread
            # path returned an AIMessage that READ as the model's own
            # words ("🛑 I was about to run write_file but I need your
            # confirmation first") — in a session with no human it dead-
            # ended: the model waited for a reply that never came, looped
            # through ask_user, and declared "Finished" on broken code
            # (D9 transcript: that text appears 4x, plus 2 ask_user
            # stalls). It ALSO rejected the ENTIRE batch when one call
            # was unsafe — teaching the model that batching loses work,
            # which is the measured cause of the 1-call-per-turn pattern.
            # Autonomous unsafe calls become denial ToolMessages (model
            # adapts in one turn, hermes delegate policy), safe calls in
            # the same batch still execute, order preserved.
            import logging
            _log = logging.getLogger("pulseai.safety")

            def _content(tc, first_line):
                return (
                    f"⛔ BLOCKED (safety policy): `{tc.get('name', '')}` was not "
                    f"executed. {first_line}\n"
                    f"Choose a safe alternative (edit_file for small "
                    f"changes, a different path, or a non-destructive "
                    f"command) and continue — do not wait for approval."
                )

            def _log_line(tc):
                _log.warning(
                    "BLOCKED %s args=%s", tc.get("name", ""), str(tc.get("args", {}))[:160]
                )

            ordered = self._deny_and_execute_safe_batch(
                tool_calls=tool_calls, verdicts=verdicts, unsafe=unsafe,
                state=state, messages=messages, last_msg=last_msg,
                config=config, denial_content=_content, log_line=_log_line,
            )
            return _with_repaired(ordered)

        approval_channel = bool(
            (config or {}).get("configurable", {}).get("approval_channel", False)
        )
        approval_policy = str(
            (config or {}).get("configurable", {}).get("approval_policy", "ask")
        )
        unsafe_by_id = {tc.get("id"): warning for tc, _, warning in unsafe}
        mutation_names = {"write_file", "edit_file", "copy_file", "scaffold_nextjs"}
        approval_candidates = []
        if approval_channel:
            for tc in tool_calls:
                warning = unsafe_by_id.get(tc.get("id"), "")
                is_mutation = tc.get("name") in mutation_names
                auto_safe_mutation = (
                    is_mutation
                    and approval_policy in {"workspace_session", "session"}
                    and tc.get("id") not in unsafe_by_id
                )
                if tc.get("id") in unsafe_by_id or (is_mutation and not auto_safe_mutation):
                    approval_candidates.append((tc, False, warning))
        if approval_candidates and approval_channel:
            # Real pre-execution UI approval: publish the proposed diff, wait
            # on this session's request, deny on timeout/failure, then execute
            # only approved + originally-safe calls through the durable path.
            from src.dashboard.event_bus import approval_queue
            timeout = float(
                (config or {}).get("configurable", {}).get("approval_timeout", 300.0)
            )
            unsafe_ids = {tc.get("id") for tc, _, _ in approval_candidates}
            approved_ids: set[str] = set()
            denials: dict[str, ToolMessage] = {}
            for tc, _, warning in approval_candidates:
                tool_id = str(tc.get("id") or "")
                request_item = approval_queue.request(
                    tool_id, tc.get("name", ""), tc.get("args", {}) or {},
                    session_id=thread_id or "default",
                    diff=self._diff_payload(tc, workspace),
                )
                event_bus.emit("tool.approval.request", {
                    **request_item, "thread_id": thread_id or "default",
                    "warning": warning,
                })

                # Stop must wake an approval wait immediately rather than leave
                # the bridge blocked for the full approval timeout.
                def _cancel_approval(
                    pending_tool_id=tool_id,
                    pending_session=thread_id or "default",
                ):
                    approval_queue.resolve(
                        pending_tool_id, False, session_id=pending_session
                    )

                _tc.register_abort(_cfg_sid, _cancel_approval)
                try:
                    decision = approval_queue.wait_for_decision(
                        tool_id, timeout=timeout
                    )
                finally:
                    _tc.unregister_abort(_cfg_sid, _cancel_approval)
                if decision and decision.get("decision") is True:
                    approved_ids.add(tool_id)
                else:
                    reason = (
                        "cancelled"
                        if _tc.cancelled(_cfg_sid)
                        else "timed out"
                        if decision and decision.get("timeout")
                        else "denied"
                    )
                    denials[tool_id] = self._durable_denial(
                        tc,
                        f"⛔ Tool `{tc.get('name', '')}` {reason} before execution.",
                        config,
                    )
            runnable = [
                tc for tc in tool_calls
                if tc.get("id") not in unsafe_ids or tc.get("id") in approved_ids
            ]
            results = {m.tool_call_id: m for m in self._execute_durable(runnable, config)}
            results.update(denials)
            ordered = [results[tc["id"]] for tc in tool_calls if tc.get("id") in results]
            return _with_repaired(ordered)

        if unsafe:
            # CLI fallback without an approval transport: return a human-readable
            # pause. Dashboard/IDE paths always set approval_channel=True.
            # No side effect has happened.
            # INTERACTIVE main thread (a human is reading): the first
            # unsafe call returns an approval-question AIMessage and
            # nothing executes — the human confirms and the model
            # continues.
            tc, _, warning = unsafe[0]
            blocked_msg = AIMessage(
                content=(
                    f"🛑 I was about to run `{tc.get('name', '')}` but I need your "
                    f"confirmation first.\n\n"
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
        if not _tc.admit_action(_cfg_sid):
            return _cancelled_result()
        parallel = try_parallel_batch(
            tool_calls, self._tools_by_name, config, workspace
        )
        if parallel is not None:
            return _with_repaired(parallel)

        if not _tc.admit_action(_cfg_sid):
            return _cancelled_result()
        sequential = try_sequential_batch(
            tool_calls, self._tools_by_name, config, workspace
        )
        if sequential is not None:
            return _with_repaired(sequential)
        if os.environ.get("PULSEAI_PARALLEL_TOOLS", "").strip().lower() == "off":
            # Explicit compatibility kill-switch: restore ToolNode's historical
            # execution semantics (including its concurrent batch behavior).
            if _repaired_ai is not None:
                state = dict(state)
                state["messages"] = messages[:-1] + [_repaired_ai]
            if not _tc.admit_action(_cfg_sid):
                return _cancelled_result()
            return _with_repaired(self._node.invoke(state, config)["messages"])
        if all(tc.get("name", "") in self._tools_by_name for tc in tool_calls):
            return _with_repaired(self._execute_durable(tool_calls, config))
        # Unknown names remain ToolNode's responsibility so its canonical
        # validation error and tool-call pairing behavior are preserved.
        if _repaired_ai is not None:
            state = dict(state)
            state["messages"] = messages[:-1] + [_repaired_ai]
        if not _tc.admit_action(_cfg_sid):
            return _cancelled_result()
        return _with_repaired(self._node.invoke(state, config)["messages"])

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
        "finish_gate": "finish_gate",
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

# Long-term memory is optional and must not perform model/network/database work
# while this graph module imports. Construct it on first real use; failures are
# isolated by the lazy proxy and degrade to no-op memory for the process.
if os.environ.get("PULSEAI_DISABLE_LONG_TERM_MEMORY", "").strip().lower() in {
    "1", "true", "yes", "on"
}:
    memory_manager = None
else:
    from src.context.lazy_memory import LazyMemoryManager

    def _create_memory_manager():
        return PersistentMemoryWrapper(MemoryManager())

    memory_manager = LazyMemoryManager(_create_memory_manager)

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
    requested_model = LLM_MODEL
    if isinstance(config_or_key, dict):
        requested_model = str(
            config_or_key.get("configurable", {}).get("model") or LLM_MODEL
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
        # Context budgeting/tokenization must follow the model that will
        # actually receive this session's requests, not the process-global
        # default captured at import. Recreate only when a caller explicitly
        # changes models for the same thread.
        if engine is not None and str(getattr(engine, "model", "")) != requested_model:
            _ENGINES.pop(key, None)
            engine = None
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
                model=requested_model,
                llm=summarizer_llm,
                memory_manager=memory_manager,
                thread_id=None if key == "default" else key,
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
    scope_capabilities: tuple[str, ...] | None = None,
) -> str:
    from src.runtime.turn_control import set_active_session, turn_controls

    turn_controls.begin(thread_id)
    set_active_session(thread_id)
    try:
        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "provider": provider,
                "model": model,
                "workspace": workspace,
                "scope_capabilities": list(scope_capabilities or ()),
                "scope_capabilities_strict": scope_capabilities is not None,
            },
            "recursion_limit": _recursion_limit(),
        }

        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(content=message)
                ],
                "latest_instruction": message,
                "execution_mode": execution_mode,
                # Safety budgets are turn-scoped even when checkpoint state is resumed.
                "iteration_used": 0,
                "grace_done": 0,
                "incomplete_response_retries": 0,
                "turn_token_usage": _zero_token_usage(),
            },
            config=config,
        )

        from src.context.self_curation import maybe_spawn_memory_review
        try:
            maybe_spawn_memory_review(thread_id)
        except Exception:
            pass

        # Only an ASSISTANT message is a final answer (same rule the
        # stream_agent fallback enforces): a graph ending on a ToolMessage or
        # nudge must never surface tool output as the response.
        ai_messages = [m for m in result["messages"] if getattr(m, "type", "") == "ai"]
        if not ai_messages:
            return ""
        final = ai_messages[-1].content
        if isinstance(final, list):
            # Multimodal content blocks: join text blocks (same rule as the
            # stream_agent fallback) so callers always get a string.
            final = "".join(
                b.get("text", "") for b in final if isinstance(b, dict)
            ) or str(final)
        return final
    finally:
        turn_controls.end(thread_id)
        set_active_session(None)

# =========================================================
# STREAMING INVOCATION
# =========================================================

class AgentTurnResult(str):
    """String-compatible final response carrying the graph's honest verdict."""

    def __new__(cls, message: str, *, completed: bool):
        value = super().__new__(cls, message)
        value.completed = bool(completed)
        return value


def stream_agent(
    message: str,
    thread_id: str = "default",
    provider: str = LLM_PROVIDER,
    model: str = LLM_MODEL,
    workspace: str = ".",
    execution_mode: Literal["agent", "plan"] = "agent",
    approval_channel: bool = False,
    approval_timeout: float = 300.0,
    approval_policy: str = "ask",
    turn_id: str | None = None,
    initial_plan: list[dict[str, Any]] | None = None,
) -> str:
    from src.context.convention_learner import ConventionLearner
    # P1-fix: warm the conventions cache WITHOUT re-scanning every turn.
    # scan_workspace() rebuilds unconditionally; get_conventions_text()
    # scans only when the disk state is empty or the workspace changed
    # (the engine's convention layer reuses the same disk state, so one
    # bounded scan per workspace-change serves both).
    ConventionLearner().get_conventions_text(workspace)
    from src.runtime.turn_control import turn_controls, set_active_session
    turn_controls.begin(thread_id)
    set_active_session(thread_id)

    event_bus.emit("session.status", {"status": "busy", "thread_id": thread_id})

    try:

        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "provider": provider,
                "model": model,
                "workspace": workspace,
                "approval_channel": approval_channel,
                "approval_timeout": approval_timeout,
                "approval_policy": approval_policy,
                "turn_id": turn_id,
            },
            "recursion_limit": _recursion_limit(),
        }

        final_response = ""
        turn_completed: bool | None = None
        current_step = 0
        total_steps = 0

        initial_state = {
            "messages": [HumanMessage(content=message)],
            "latest_instruction": message,
            "execution_mode": execution_mode,
            # Safety budgets are turn-scoped even when checkpoint state is resumed.
            "iteration_used": 0,
            "grace_done": 0,
            "incomplete_response_retries": 0,
            "turn_token_usage": _zero_token_usage(),
        }
        if initial_plan is not None:
            initial_state.update({
                "plan": list(initial_plan),
                "plan_goal": message,
                "plan_created": bool(initial_plan),
                "plan_approved": bool(initial_plan),
            })

        for event in graph.stream(
            initial_state,
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

            # FINALIZE NODE — its verdict, not mere transport closure, owns
            # turn completion. Attempt 11 discarded this state and returned
            # the preceding "I will inspect" text as completed=true.
            if "finalize" in event:
                finalize_data = event.get("finalize") or {}
                turn_completed = bool(finalize_data.get("task_completed", False))
                final_messages = finalize_data.get("messages") or []
                if final_messages:
                    content = getattr(final_messages[-1], "content", "")
                    if isinstance(content, list):
                        content = "".join(
                            block.get("text", "") for block in content
                            if isinstance(block, dict)
                        ) or str(content)
                    if content:
                        final_response = str(content)
                        event_bus.emit("message.agent.chunk", {
                            "chunk": final_response,
                            "thread_id": thread_id,
                        })

        event_bus.emit("session.status", {"status": "idle", "thread_id": thread_id})
        # D38: post-run bounded background self-curation (memory review on the
        # aux model). Never blocks the response — state is snapshotted from the
        # checkpointer and reviewed on a daemon thread.
        from src.context.self_curation import maybe_spawn_memory_review
        try:
            maybe_spawn_memory_review(thread_id)
        except Exception:
            pass

        # Read the persisted verdict even when an earlier ai event supplied
        # text. Transport completion and task completion are different facts.
        # Keep the string return API compatible while carrying the verdict for
        # the bridge's terminal frame.
        snap_values: dict[str, Any] = {}
        try:
            snap = graph.get_state(config)
            snap_values = dict(snap.values or {})
        except Exception:
            pass

        if not final_response:
            msgs = snap_values.get("messages", [])
            # Only an ASSISTANT message is a final answer. Falling back to
            # msgs[-1] blindly returns tool output / system prompts /
            # cancellation nudges to the user as the "response".
            ai_msgs = [m for m in msgs if getattr(m, "type", "") == "ai"]
            if ai_msgs:
                final_response = ai_msgs[-1].content
                if isinstance(final_response, list):
                    final_response = "".join(
                        b.get("text", "") for b in final_response
                        if isinstance(b, dict)
                    ) or str(final_response)

        if turn_completed is None:
            # Preview/chat paths may intentionally end without finalize and are
            # complete by transport convention. Finalize updates are captured
            # above and are authoritative when present.
            turn_completed = True

        return AgentTurnResult(str(final_response or ""), completed=turn_completed)
    finally:
        turn_controls.end(thread_id)
        set_active_session(None)

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

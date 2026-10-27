import json
import os
import re
import sqlite3
import threading
import time
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
    RemoveMessage,
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

from src.config.settings import LLM_PROVIDER, LLM_MODEL  # noqa: F401  (REASONING_EFFORT now read at call time)
from src.config.reasoning_config import parse_reasoning_effort
from src.llm.factory import (
    get_llm, get_auxiliary_llm, TurnCancelledError, provider_response_info,
)
from src.llm.repetition_guard import (
    REPETITION_DOMINATED_NOTICE, is_degenerate_output,
)
from src.context.context_engine import ContextEngine
from src.context.memory_manager import MemoryManager
from src.context.user_interest import (
    UserInterest,
    interest_from_state,
    render_user_interest,
    resolve_user_interest,
)
from src.context.token_tracker import TokenTracker, TokenUsage

# --- CopilotKit A2UI fixed-schema wiring (Crusor domain) ---
from pathlib import Path as _A2UIPath
try:
    # pyrefly: ignore [missing-import]
    from copilotkit import a2ui
except Exception:  # fallback for offline validation without copilotkit
    class _A2UIFallback:  # type: ignore
        def load_schema(self, p):  # noqa: ANN001
            import json
            return json.load(open(p, encoding="utf-8"))
        def create_surface(self, sid, catalog_id=None):  # noqa: ANN001
            return {"version": "v0.9", "createSurface": {"surfaceId": sid, "catalogId": catalog_id}}
        def update_components(self, sid, comps):  # noqa: ANN001
            return {"version": "v0.9", "updateComponents": {"surfaceId": sid, "components": comps}}
        def update_data_model(self, sid, data, path="/"):  # noqa: ANN001
            return {"version": "v0.9", "updateDataModel": {"surfaceId": sid, "path": path, "value": data}}
        def render(self, operations):  # noqa: ANN001
            import json as _j
            return _j.dumps({"a2ui_operations": operations})
    a2ui = _A2UIFallback()  # type: ignore

CATALOG_ID = "copilotkit://crusor-task-catalog"
SURFACE_ID = "crusor-task"
_SCHEMAS_DIR = _A2UIPath(__file__).parent.parent / "a2ui_schemas"
try:
    CRUSOR_TASK_SCHEMA = a2ui.load_schema(_SCHEMAS_DIR / "crusor_task_schema.json")
except Exception:
    CRUSOR_TASK_SCHEMA = []


def _env_reasoning_effort() -> str:
    """Read REASONING_EFFORT at call time, not import time.

    An env var set after process start (or between turns) must take effect;
    a module-level constant would freeze the value at first import.
    """
    return os.getenv("REASONING_EFFORT", "").strip()


def _resolve_reasoning_config(configurable: dict | None = None) -> dict | None:
    """Resolve the reasoning config for this turn.

    The desktop's Think picker sends ``reasoning_effort`` on every prompt
    frame; the bridge threads it through ``stream_agent`` into
    ``configurable``. A manual pick therefore wins over the static
    ``REASONING_EFFORT`` env var.

    When thinking is not explicitly configured or set, default to disabled
    (none / {"enabled": False}) so models never emit unwanted thinking tokens
    and no Thought card appears unless the user explicitly chooses to enable it.
    """
    if (
        isinstance(configurable, dict)
        and isinstance(configurable.get("configurable"), dict)
    ):
        configurable = configurable["configurable"]
    per_turn = str((configurable or {}).get("reasoning_effort") or "").strip()
    if per_turn:
        parsed = parse_reasoning_effort(per_turn)
        if parsed is not None:
            return parsed
    env_effort = _env_reasoning_effort()
    if env_effort:
        parsed = parse_reasoning_effort(env_effort)
        if parsed is not None:
            return parsed
    # Unset thinking defaults to disabled (none)
    return {"enabled": False}


def _drop_tool_pairs(messages: list) -> list:
    """Strip tool-call/result pairs from a message list so it is a valid
    NO-TOOLS request. The grace call binds no tools, so any AIMessage with
    tool_calls and the ToolMessages answering them must not be sent —
    OpenAI-compat providers hard-400 on "Tool messages found but no tools
    provided". Text-only AIMessages survive (they carry reasoning).

    Hermes parity: sanitize_api_messages 6-step + repair_message_sequence.
    This is the D40 fallback and the final safety net for strict providers
    (Sarvam, DeepSeek). It also handles empty tool_calls arrays which strict
    providers reject.
    """
    # Delegate to the canonical implementation in request_sanitizer which now
    # handles empty tool_calls, nameless calls, stray results, etc.
    try:
        from src.llm.request_sanitizer import strip_tool_pairs
        return strip_tool_pairs(messages)
    except Exception:
        # Fallback inline implementation if import fails
        out: list = []
        for m in messages:
            if isinstance(m, ToolMessage):
                continue
            tcs = getattr(m, "tool_calls", None)
            if tcs:
                # Preserve text content if present, drop tool_calls
                content = getattr(m, "content", "")
                text = content if isinstance(content, str) else str(content or "")
                if text.strip():
                    try:
                        out.append(
                            AIMessage(
                                content=text,
                                id=getattr(m, "id", None),
                                additional_kwargs={
                                    k: v
                                    for k, v in (getattr(m, "additional_kwargs", {}) or {}).items()
                                    if k != "tool_calls"
                                },
                            )
                        )
                    except Exception:
                        out.append(AIMessage(content=text))
                continue
            out.append(m)
        return out


# hermes :1934 — the honest final answer when the summary came back empty twice.
_EMPTY_SUMMARY_RESPONSE = (
    "I reached the iteration limit and couldn't generate a summary."
)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _is_tool_messages_rejection(exc: Exception) -> bool:
    """The D40 provider 400: tool traffic present but no tools declared."""
    text = str(exc).lower()
    return "tool" in text and (
        "no tools" in text
        or "without tools" in text
        or "tools provided" in text
        or "tool message" in text
    )


def _finish_reason_is_tool_calls(result: Any) -> bool:
    """Check if the LLM result indicates it WANTED to call tools but
    delivered an empty tool_calls array (DeepSeek v4, Claude on Copilot)."""
    # Check response_metadata for finish_reason
    rm = getattr(result, "response_metadata", None) or {}
    fr = str(rm.get("finish_reason", "")).lower()
    if fr in ("tool_calls", "function_call", "stop"):
        # "stop" with empty tool_calls and non-empty content could be
        # the model narrating instead of calling — only flag tool_calls
        if fr == "tool_calls":
            return True
    # Also check additional_kwargs
    akw = getattr(result, "additional_kwargs", None) or {}
    fr2 = str(akw.get("finish_reason", "")).lower()
    return fr2 in ("tool_calls", "function_call")


# Duplicate-response guard (field 2026-10-15): a weak router model called
# list_files three times in ONE turn -- each loop streamed another full
# answer variant into the transcript. The progress node's nudge (3rd
# identical read) is advisory; this is the hard stop at the only chokepoint
# every call passes: ai_node's return. Read-only calls are dropped when the
# identical name+args already executed this turn and nothing mutating ran
# after that execution (a write in between legitimately changes the read).
_READ_ONLY_CALLS = {
    "list_files", "read_file", "search_files", "search_code",
    "glob_files", "find_files", "list_directory", "web_fetch", "web_extract",
}
_MUTATING_CALLS = {
    "write_file", "edit_file", "copy_file", "delete_file", "move_file",
    "run_terminal", "start_terminal", "terminal", "execute_code",
    "apply_patch", "generate_image", "media_download",
    # Installing an SDK changes what later probes/creations observe.
    "install_toolchain",
}


def _tool_call_key(tc: dict) -> str:
    import json as _json
    try:
        args = _json.dumps(tc.get("args") or {}, sort_keys=True, default=str)
    except Exception:
        args = str(tc.get("args") or {})
    return f"{tc.get('name', '')}:{args}"


def _doom_repeats(tc: dict, state: dict | None) -> int:
    """Consecutive identical calls already ANSWERED this turn
    (OpenCode's doom_loop: the same tool call repeats with
    identical input). Trailing run only — a different call in
    between (a write between two reads) breaks the loop."""
    key = _tool_call_key(tc)
    messages = list((state or {}).get("messages") or [])
    start = 0
    for i, m in enumerate(messages):
        if getattr(m, "type", "") == "human":
            start = i + 1
    answered = {
        str(getattr(m, "tool_call_id", "") or "")
        for m in messages
        if getattr(m, "type", "") == "tool"
    }
    executed: list[str] = []
    for m in messages[start:]:
        for prior in (getattr(m, "tool_calls", None) or []):
            if str(prior.get("id") or "") in answered:
                executed.append(_tool_call_key(prior))
    count = 0
    for prior_key in reversed(executed):
        if prior_key != key:
            break
        count += 1
    return count


def _permission_decisions(tool_calls, *, workspace: str, thread_id: str, state, guard) -> dict[str, dict]:
    """OpenCode permission evaluation for one batch, over the guard.

    Returns {tool_call_id: {"effect", "warning", "action"}} for every
    call the config does NOT simply allow. Deny is final; ask routes
    to the approval dock on the desktop channel and auto-denies where
    no human can answer (sub-agents, autonomous runs). The guard's
    own verdicts are computed separately by the caller and always
    outrank an "allow" here.
    """
    from src.context.permission_config import (
        effect_for, load_permission_rules, tool_action_resources,
    )

    agent_key = "build"
    if thread_id.startswith("sub-"):
        agent_key = ""
        try:
            from src.runtime.subagent_store import get_store
            row = get_store().get_by_child(thread_id)
            agent_key = str(getattr(row, "mode", "") or "") if row else ""
        except Exception:
            agent_key = ""
    rules = load_permission_rules(workspace, agent_key)
    workspace_root = guard.workspace
    decisions: dict[str, dict] = {}
    for tc in tool_calls:
        tc_id = str(tc.get("id") or "")
        args = tc.get("args", {}) or {}
        action, resources = tool_action_resources(tc.get("name", ""), args)
        effect = effect_for(action, resources, rules)
        # An "always" verdict releases later asks only inside its
        # own session: SafeToolNode checks the ApprovalQueue grant
        # store before queueing. Nothing is persisted across
        # sessions (founder 2026-10-17: session-only permissions;
        # upstream's PermissionSaved file layer was removed), so a
        # config ask always reaches that session check unchanged.
        warning = ""
        # Guard action: touching paths outside the project directory.
        # The file tools resolve through the workspace clamp and
        # physically cannot leave it, so asking there would promise
        # access the tools refuse anyway; the real escape is the
        # shell (absolute paths in the command text) and any other
        # tool carrying an unclamped path arg.
        clamped = {
            "read_file", "write_file", "edit_file", "copy_file",
            "list_files", "search_files", "search_code",
            "delete_file", "move_file",
        }
        candidates: list[str] = []
        if tc.get("name", "") in ("run_terminal", "start_terminal", "terminal"):
            import re as _re
            cmd_text = resources[0] if resources else ""
            # Token-boundary anchor (field 2026-10-21): the slash must
            # START a token — preceded by whitespace, a quote, `=`, a
            # bracket or a shell separator, or begin the text. The old
            # unanchored scan mined the slash INSIDE relative paths, so
            # `ls build/web/flutter_bootstrap.js` asked about a phantom
            # "/web/flutter_bootstrap.js" at the drive root. Windows
            # drive paths mine in both slash spellings.
            _BOUNDARY = r"(?<![^\s'\"=(;|&<>`])"
            candidates = _re.findall(
                _BOUNDARY + r"(?:[A-Za-z]:[\\/][^\s'\";|]+|/[^\s'\";|]+)",
                cmd_text,
            )
            candidates = [c.rstrip(")]}") for c in candidates]
            # Field 2026-10-17: `cat ~/.bashrc` sailed past this check
            # because only absolute paths were mined -- home-relative
            # paths are outside the project too.
            candidates += _re.findall(
                _BOUNDARY + r"(?:~[/\\][^\s'\";|]+|\$HOME[/\\][^\s'\";|]+)",
                cmd_text,
            )
            # A shell cat is still a read: .env rules follow the file,
            # not the tool (field 2026-10-17: (test -f .env && cat .env)
            # read the secret the read_file deny protects).
            for token in _re.findall(r"[^\s'\";|]+", cmd_text):
                base = token.replace("\\", "/").rsplit("/", 1)[-1]
                if base == ".env" or (base.startswith(".env.") and base != ".env.example"):
                    env_effect = effect_for("read", [base], rules)
                    if env_effect == "deny":
                        effect = "deny"
                    elif env_effect == "ask" and effect != "deny":
                        effect = "ask"
                        warning = "**Sensitive file:** this call touches a protected file (credentials / secrets / environment variables)."
        elif tc.get("name", "") not in clamped:
            for arg_key in ("path", "file_path", "dst", "src", "cwd"):
                raw = args.get(arg_key)
                if isinstance(raw, str) and raw.strip():
                    candidates.append(raw)
        external_paths = []
        external_raw = []
        external_ask = False
        for raw in candidates:
            if raw.startswith(("~", "$HOME")):
                import os as _os
                resolved = _A2UIPath(_os.path.expanduser(
                    ("~" + raw[5:]) if raw.startswith("$HOME") else raw
                ))
            else:
                resolved = guard._resolve_path(raw)
            if resolved != workspace_root and workspace_root not in resolved.parents:
                external_paths.append(str(resolved))
                external_raw.append(raw)
        if external_paths:
            external_effect = effect_for("external_directory", external_paths, rules)
            if external_effect == "deny":
                effect = "deny"
            elif external_effect == "ask" and effect != "deny":
                # This ask IS the outside-project ask (not a ride-along
                # on some other rule's ask): an "Allow always" verdict
                # scopes its session grant to the judged path(s) below.
                external_ask = effect != "ask"
                effect = "ask"
                # Name the judged path(s) verbatim, founder 2026-10-20:
                # the human (and the log reader) must see WHICH path was
                # judged outside — a false ask (e.g. an MSYS-spelled
                # in-workspace path) has to be recognizable at a glance.
                warning = (
                    "🌐 **Outside the project:** "
                    + ", ".join(external_raw)
                    + " — outside the project directory."
                )
        # Guard action: the same call repeating with identical input.
        if _doom_repeats(tc, state) >= 2:
            doom_effect = effect_for("doom_loop", ["*"], rules)
            if doom_effect == "deny":
                effect = "deny"
            elif doom_effect == "ask" and effect != "deny":
                effect = "ask"
                external_ask = False
                warning = "🌀 **Doom loop:** the same call has repeated 3 times with identical input."
        if effect == "deny":
            decisions[tc_id] = {
                "effect": "deny", "action": action,
                "warning": f"⛔ Permission denied: {action} blocked by the permission config.",
            }
        elif effect == "ask":
            decisions[tc_id] = {
                "effect": "ask", "action": action, "warning": warning,
                "external_ask": external_ask,
                "grant_paths": list(external_paths) if external_ask else [],
            }
    return decisions


def _drop_repeated_read_calls(result: Any, state: dict, *, doom_defers: bool = False) -> Any:
    """Strip read-only tool calls that already ran identically this turn.

    Doom-loop hand-off (field 2026-10-17): when the permission rules
    would ASK (or deny) about a repeated loop, dropping silently
    swallows the human's decision — the founder's run showed three
    dropped reads and no dock. With `doom_defers`, repeats pass
    through untouched and SafeToolNode's doom counter owns them
    (2nd executes, 3rd asks). Under doom_loop="allow" the old silent
    drop stands, which is what that policy means.
    """
    if doom_defers:
        return result
    calls = list(getattr(result, "tool_calls", None) or [])
    if not calls:
        return result
    messages = list(state.get("messages") or [])
    start = 0
    for i, m in enumerate(messages):
        if getattr(m, "type", "") == "human":
            start = i + 1
    answered_ids = {
        str(getattr(m, "tool_call_id", "") or "")
        for m in messages
        if getattr(m, "type", "") == "tool"
    }
    executed: list[tuple[str, str]] = []  # (key, name) in execution order
    for m in messages[start:]:
        for tc in (getattr(m, "tool_calls", None) or []):
            if str(tc.get("id") or "") in answered_ids:
                executed.append((_tool_call_key(tc), str(tc.get("name", ""))))
    if not executed:
        return result
    last_seen: dict[str, int] = {}
    for idx, (key, _name) in enumerate(executed):
        last_seen[key] = idx

    def _is_repeat(tc: dict) -> bool:
        if str(tc.get("name", "")) not in _READ_ONLY_CALLS:
            return False
        key = _tool_call_key(tc)
        idx = last_seen.get(key)
        if idx is None:
            return False
        return not any(
            name in _MUTATING_CALLS for _k, name in executed[idx + 1:]
        )

    kept = [tc for tc in calls if not _is_repeat(tc)]
    if len(kept) == len(calls):
        return result
    dropped = [str(tc.get("name", "")) for tc in calls if _is_repeat(tc)]
    print(
        f"[ai_node] duplicate-read guard: dropped {len(dropped)} repeated "
        f"call(s) {dropped} -- identical result already in this turn",
        flush=True,
    )
    try:
        return result.model_copy(update={"tool_calls": kept})
    except Exception:
        result.tool_calls = kept
        return result


def _should_reprompt_dropped_toolcall(result: Any, tools_bound: bool, retries: int) -> bool:
    """Dropped-toolcall re-prompt gate (field 2026-10-15, second pass).

    hermes re-prompts when a provider signals tool_calls but delivers
    none -- the call was DROPPED. But velona/GLM mislabels plain text
    answers with finish_reason=tool_calls on nearly every reply, so the
    ungated re-prompt double-billed (and double-painted) every step.
    A genuinely dropped call delivers no answer text; a mislabelled
    answer delivers a full one. Only the dropped shape re-prompts --
    a delivered text answer is accepted as the answer.
    """
    if not tools_bound or retries >= 3:
        return False
    if getattr(result, "tool_calls", None):
        return False
    if not _finish_reason_is_tool_calls(result):
        return False
    return not _result_answer_text(result).strip()


def _summary_text_from(result: Any) -> str:
    """Answer text of a summary response, <think> blocks stripped
    (hermes :2132-2133)."""
    text = result.content if isinstance(result.content, str) else ""
    if not text:
        extracted = _result_answer_text(result)
        text = extracted or ""
    if "<think>" in text:
        text = _THINK_BLOCK_RE.sub("", text).strip()
    return text.strip()


def _finalize_iteration_summary(result: Any, reinvoke) -> Any:
    """hermes handle_max_iterations tail (:2126-2138): one retry on an empty
    summary; still empty -> the honest fallback text. The summary IS the
    turn's final assistant message.

    Fix: reinvoke must also handle strict providers that reject tool messages
    without tools. The grace path binds no tools, so any reinvoke with full
    history would 400 again (field 2026-09-12: sarvam-105b 400 after 10.7s
    successful text-only fallback, because empty summary triggered reinvoke
    with original tool history). The reinvoke lambda now receives stripped
    messages via closure, but we also guard here with try/except for tool
    rejection.
    """
    text = _summary_text_from(result)
    if not text:
        try:
            result = reinvoke()
            text = _summary_text_from(result)
        except Exception as exc:
            if _is_tool_messages_rejection(exc):
                print(
                    f"[grace] reinvoke also rejected (tool messages without tools): {type(exc).__name__} — using fallback text",
                    flush=True,
                )
                text = ""
            else:
                # Re-raise non-tool errors? No, fallback to honest text to avoid killing turn
                print(
                    f"[grace] reinvoke failed ({type(exc).__name__}: {str(exc)[:150]}) — using fallback text",
                    flush=True,
                )
                text = ""
    if not text:
        text = _EMPTY_SUMMARY_RESPONSE
    return AIMessage(content=text, id=getattr(result, "id", None))


from src.agents.planner import (
    revise_plan,
    start_next_plan_step,
    finalize_plan,
    check_ambiguity,
)
from src.models.plan_models import steps_to_dicts
from src.tools.plan_tool import plan_update
from src.tools.todo_tool import todo_list, inject_active_todos, clear_todo_store
from src.tools.clarify_tool import clarify
from src.graphs import progress_helpers as ph
from src.tools.file_tools import (
    read_file,
    list_files,
    search_files,
    search_code,
    write_file,
    edit_file,
    copy_file,
    typecheck_workspace,
)


from src.tools.terminal_tools import (
    run_terminal,
    start_terminal,
    terminal,
    check_terminal,
    stop_terminal,
    list_terminal_processes,
    cleanup_terminal_processes,
    read_terminal_output
)
from src.tools.web_tools import web_search, web_fetch, web_extract
from src.tools.media_tools import media_search, media_download, generate_image
from src.tools.skill_tools import skills_list, skill_view, skill_manage
from src.tools.skill_hub_tools import hub_search, hub_install, hub_update, hub_list, hub_remove
# #8 (external review): fault-tolerant browser-tool import. The optional
# stack must never break engine boot — if it is missing the browser tools
# are simply unbound (the D5 fake-verification hole is documented in the
# browser_tools docstring) and the degradation is loud.
# Backend history: browser_mcp.py (puppeteer-MCP, hardcoded lab paths) is
# REPLACED by hermes' local browser stack — the agent-browser CLI port
# (browser_tools.py, hermes tools/browser_tool*.py). Same browser_* names
# the renderer already maps to explore cards, hermes' contracts.
try:
    from src.tools.browser_tools import BROWSER_TOOLS
except Exception as _browser_mcp_exc:  # ImportError + any transitive boot failure
    BROWSER_TOOLS = []
    print(
        f"[chat_graph] browser tools UNAVAILABLE (import failed: "
        f"{type(_browser_mcp_exc).__name__}: {_browser_mcp_exc}) — "
        "engine boots without them",
        flush=True,
    )
from src.tools.code_exec_tool import execute_code
from src.tools.target_tools import (
    build_target,
    check_target_toolchains,
    detect_targets,
    device_action,
    device_preview,
    device_logs,
    device_screenshot,
    device_ui,
    verify_target_app,
)
from src.tools.toolchain_install import install_toolchain
from src.tools.ui_verification import verify_ui_workspace, verify_ui_routes
from src.tools.session_search_tool import session_search
from src.tools.host_tools import HOST_TOOLS
from src.prompts.claude_persona import system_persona  # D35 (§47)

from src.agents.cost_router import cost_router
from src.agents.skill_manager import skill_manager
from src.agents.sub_agent import subagent_coordinator
from src.dashboard.event_bus import event_bus

# P0-D: state, budget, and gate machinery extracted to focused modules.
from src.graphs.state import AgentState, ExecutionMode, TaskDecision
from src.graphs.budget import (
    _FINAL_RESPONSE_RESERVE_REQUEST,
    _MAX_ITERATIONS_SUMMARY_REQUEST,
    _iteration_budget,
    _recursion_limit,
    _budget_exhausted,
    _final_response_reserve_reached,
    _verification_reserve_reached,
)
from src.graphs.gates import (
    _completion_evidence_ready,
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
    - After read_file, write_file, edit_file, terminal, search_files, web_search, web_extract, media_search, or media_download.
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


# ask_user (legacy echo tool) REMOVED from the model surface — hermes has ONE
# ask tool, `clarify` (blocking, structured, UI card). The after_progress
# finalize rule below survives only as legacy-replay compat for old sessions.
@tool
def delegate_to_subagent(
    mode: str = "general",
    task: str = "",
    description: str = "",
    subagent_type: str = "",
    background: bool = False,
    prompt: str = "",
    model: str = "",
    session_id: str = "",
    config: RunnableConfig = None,  # type: ignore
) -> str:
    """
    Delegate a focused sub-task to a specialized sub-agent - PREFERRED FOR PARALLEL WORK.

    WHEN TO USE (STRONGLY PREFERRED):
    - Analyzing multiple folders/files - spawn ONE sub-agent per folder IN PARALLEL (like opencode: Spawn agents to analyze folders -> 5x Explore in parallel)
    - Any task with separable pieces that can run in parallel (research, coding, testing)
    - Example: "Analyze dog folders" -> delegate_to_subagent for each folder: playground, PulseAIRepo, pulse-res, etc. IN ONE BATCH CALL
    - Use delegate_to_subagent_batch for multiple at once

    WHEN NOT TO USE:
    - Trivial one-step tasks
    - Tasks that depend on your immediate previous action

    OpenCode parity extensions:
    - description: short 3-5 words label (for UI card, e.g., "Analyze playground folder")
    - subagent_type: alias for mode (general, explore, etc.) - use "explore" or "research" for folder analysis
    - background: run async, returns immediately
    - prompt: alias for task (OpenCode shape)
    - model: run this child on a different model than yours (cost lever: cheap model for research children); default inherits the agent's configured model, then yours
    - session_id: RESUME a previous sub-agent session instead of spawning fresh — the worker keeps its context; `task` is the follow-up. Use the session id from an earlier delegation result.
    - Agents are an open registry: built-ins research/code/test/review plus custom agents defined in .crusorai/agents/*.md (pass the agent's name as mode).
    """
    from src.config.settings import LLM_PROVIDER, LLM_MODEL
    import os

    # Normalize args — support both Crusor and OpenCode shapes
    # OpenCode sends prompt + description + subagent_type, Crusor sends mode + task
    actual_task = (prompt or task or "").strip()
    actual_mode = (subagent_type or mode or "general").strip().lower() or "general"
    # Map general/explore to internal modes. Custom agent names (the
    # registry, .crusorai/agents/*.md) pass through untouched here and
    # are resolved — or rejected with the available list — once the
    # workspace is known below.
    mode_map = {"general": "code", "explore": "research", "build": "code", "plan": "research"}
    internal_mode = mode_map.get(actual_mode, actual_mode)
    actual_description = (description or actual_task[:50] or f"{actual_mode} task").strip()[:200]

    # Config may be passed as second arg if called with OpenCode shape (tool def positional)
    # Handle RunnableConfig being in different positions
    runnable_config = config
    if isinstance(config, str):
        # config is actually description
        actual_description = config
        runnable_config = None
    if runnable_config is None:
        # Try to get from kwargs or default
        runnable_config = {}

    caller_thread = (runnable_config or {}).get("configurable", {}).get("thread_id", "") if isinstance(runnable_config, dict) else ""
    # Also check if config is RunnableConfig object
    if not caller_thread and hasattr(runnable_config, "get"):
        try:
            caller_thread = str(runnable_config.get("configurable", {}).get("thread_id", "") or "")
        except Exception:
            caller_thread = ""
    if not caller_thread:
        # Fallback: check thread-local or default
        caller_thread = "main"

    # Agent resolution (OpenCode: an open registry — built-ins plus
    # workspace/global custom agents). Unknown agents are a hard error
    # with the available list, never a silent remap; spawning can be
    # policy-gated per agent. Model: per-call override > the agent's
    # configured model > the parent's model.
    from src.agents.subagent_registry import available_agents, denied_reason, resolve_agent

    _workspace = ""
    if isinstance(runnable_config, dict):
        _workspace = str(runnable_config.get("configurable", {}).get("workspace") or "")
    agent_def = resolve_agent(actual_mode, _workspace or None)
    if agent_def is None:
        _names = ", ".join(a.name for a in available_agents(_workspace or None))
        return f"⛔ Unknown sub-agent '{actual_mode}'. Available agents: {_names}."
    _denied = denied_reason(agent_def.name)
    if _denied:
        return f"⛔ {_denied}"
    internal_mode = agent_def.base_mode
    resolved_model = (model or "").strip() or agent_def.model or LLM_MODEL

    # Depth check via store + prefix (OpenCode parity: cfg.subagent_depth default 1)
    try:
        from src.runtime.subagent_store import get_store
        store = get_store()
        depth = store.depth_of(str(caller_thread))
        # Also prefix check for legacy
        if str(caller_thread).startswith("sub-"):
            depth = max(depth, 1)
        max_depth = int(os.getenv("CRUSORAI_SUBAGENT_DEPTH", "1"))
        if depth >= max_depth:
            return (
                f"⛔ Subagent depth cap reached ({max_depth}). "
                f"Increase CRUSORAI_SUBAGENT_DEPTH to allow nested subagents. "
                "Complete the decomposed steps directly instead."
            )
    except Exception:
        # Fallback to legacy prefix check
        if str(caller_thread).startswith("sub-"):
            return (
                "⛔ Sub-agents cannot spawn further sub-agents (depth cap). "
                "Complete the decomposed steps directly instead."
            )

    # Background flag check (OpenCode parity)
    if background:
        if os.getenv("CRUSORAI_EXPERIMENTAL_BACKGROUND_SUBAGENTS", "").lower() not in {"1", "true", "yes", "on"}:
            # Still allow but warn — OpenCode errors, Crusor degrades to foreground
            # For strict parity, we could error, but we allow with note
            pass

    # Extract tool_call_id if available from config
    tool_call_id = None
    try:
        # LangChain injects tool_call_id in some contexts
        if isinstance(runnable_config, dict):
            tool_call_id = runnable_config.get("configurable", {}).get("tool_call_id") or runnable_config.get("tool_call_id")
    except Exception:
        pass

    # Resume (OpenCode sessionID): continue a settled child session of
    # THIS parent — same thread, same checkpoint. Validation failures are
    # honest errors, never a silent fresh spawn wearing the old id.
    handle = None
    if session_id:
        try:
            from src.agents.subagent_lifecycle import subagent_lifecycle as _lifecycle

            handle = _lifecycle.resume_child(
                session_id.strip(), goal=actual_task,
                parent_session_id=str(caller_thread) or "main",
                workspace=_workspace or None,
                provider=LLM_PROVIDER, model=resolved_model,
                description=actual_description,
            )
        except ValueError as exc:
            return f"⛔ Cannot resume sub-agent session '{session_id}': {exc}"
        except Exception:
            return "⛔ Resume unavailable right now; spawn a fresh sub-agent instead."

    # Use lifecycle service for persistence + events (OpenCode parity: child session with parentID)
    # Crucial: choose env-aware depth, derive capabilities, inherit deny permissions
    try:
        from src.agents.subagent_lifecycle import subagent_lifecycle
        from src.agents.runtime_profile import KNOWN_CAPABILITIES
        # Parent capabilities from config (scope_capabilities) — env path aware
        parent_caps = ()
        try:
            if isinstance(runnable_config, dict):
                cfg = runnable_config.get("configurable", {}) or {}
                pc = cfg.get("scope_capabilities") or cfg.get("parent_capabilities") or ()
                if pc:
                    parent_caps = tuple(pc)
        except Exception:
            parent_caps = ()
        # Allowed caps based on mode — COARSE capability vocabulary
        # (runtime_profile.KNOWN_CAPABILITIES), the only vocabulary the
        # toolset waist and the strict binder understand. This map
        # previously named TOOLS (web_search, read_file, ...) and the
        # KNOWN_CAPABILITIES filter below silently reduced every child's
        # requested scope to (), so children ran strict-empty.
        # The resolved agent's own capability scope (registry: built-ins
        # carry MODE_CAPABILITIES; custom agents declare their own).
        requested_caps = tuple(agent_def.capabilities)
        # Filter to known
        requested_caps = tuple(c for c in requested_caps if c in KNOWN_CAPABILITIES)
        # Derive via permission module (subset enforcement)
        try:
            from src.agents.subagent_permissions import derive_subagent_capabilities, derive_subagent_session_permission
            derived_caps = derive_subagent_capabilities(tuple(parent_caps), tuple(requested_caps))
            # Permission ruleset: inherit parent deny + external_directory (OpenCode parity)
            # In Crusor, parent permission is not explicit, but we derive empty -> todowrite/task deny
            parent_perm = []  # Could be loaded from env or config in future
            subagent_perm = []  # Subagent's own allows (e.g., if mode is general, it might allow task)
            derived_perm = derive_subagent_session_permission(parent_perm, subagent_perm)
        except Exception:
            derived_caps = requested_caps
            derived_perm = []
            parent_perm = []
            subagent_perm = []
        if handle is None:
            handle = subagent_lifecycle.launch(
                parent_session_id=str(caller_thread) or "main",
                goal=actual_task,
                mode=internal_mode,
                parent_capabilities=tuple(parent_caps),
                allowed_capabilities=tuple(derived_caps),
                description=actual_description,
                agent_name=agent_def.name,
                tool_call_id=tool_call_id,
                background=background,
                parent_permission=parent_perm,
                subagent_permission=subagent_perm,
                workspace=str(runnable_config.get("configurable", {}).get("workspace") or "") or None,
                provider=LLM_PROVIDER,
                model=resolved_model,
                agent_prompt=agent_def.prompt,
            )
        child_id = handle.subagent_id

        # If background, return immediately with running state (OpenCode BACKGROUND_STARTED)
        if background:
            from src.agents.subagent_permissions import format_task_output, BACKGROUND_STARTED
            return format_task_output(
                session_id=child_id,
                state="running",
                text=BACKGROUND_STARTED,
                summary="Background task started",
            )

        # Foreground: wait for completion. Stop on the parent cascades
        # into the child (OpenCode: jobs.block onInterrupt interrupts
        # the child): register an abort on the parent's turn that
        # cancels the child's turn — the same registry that wakes the
        # child's own blocking clarify/approval waits.
        _abort_child = None
        try:
            from src.runtime.turn_control import turn_controls as _tc
            _abort_child = lambda: subagent_lifecycle.cancel(handle)  # noqa: E731
            _tc.register_abort(str(caller_thread) or "main", _abort_child)
        except Exception:
            _abort_child = None
        try:
            result_dict = subagent_lifecycle.wait(handle, timeout=600)
        finally:
            if _abort_child is not None:
                try:
                    from src.runtime.turn_control import turn_controls as _tc
                    _tc.unregister_abort(str(caller_thread) or "main", _abort_child)
                except Exception:
                    pass
        # The child's model seconds accumulated under ITS thread id;
        # settle them onto this thread's sub-agent bucket so the turn
        # receipt stops reporting them as "non-model" (a still-running
        # child after a wait timeout keeps its wall — it transfers
        # when it actually settles or is resumed to completion).
        if not result_dict.get("timed_out"):
            note_subagent_model_wall(str(caller_thread) or "main", child_id)
        # OpenCode's foreground contract (tool/plugin/subagent.ts):
        # the run's exit status decides the tool's answer — error and
        # cancelled FAIL the tool call with the child's session id in
        # the message (so the parent can resume that exact child),
        # and a wait that times out on a still-running child reports
        # running, never a fake completion. Only a succeeded run
        # earns the completed shape below.
        from src.agents.subagent_permissions import format_task_output as _fmt_task
        _child_state = str(result_dict.get("state") or "")
        if result_dict.get("timed_out") and _child_state in ("running", "pending"):
            return _fmt_task(
                session_id=child_id,
                state="running",
                text=(
                    f"Sub-agent still running (session_id: {child_id}). "
                    "It was not waited out; check on it later or resume "
                    "it by session_id — do not duplicate its work."
                ),
                summary="Sub-agent still running",
            )
        if _child_state == "failed":
            return (
                f"⛔ Subagent failed (session_id: {child_id}): "
                f"{result_dict.get('error') or result_dict.get('result') or 'unknown error'}"
            )
        if _child_state in ("cancelled", "cancel_requested"):
            return f"⛔ Subagent cancelled (session_id: {child_id})"
        result_text = result_dict.get("result") or result_dict.get("error") or "No result"
        state = "completed" if _child_state == "succeeded" else "error"

        # The result is delivered ONCE, whole up to OpenCode's
        # tool-output limits. It used to be pasted twice (friendly
        # blob + XML), each copy head-cut at 2,000 characters — the
        # child's conclusion, which sits at the end of its answer,
        # never reached the parent at all (founder field 2026-10-16:
        # the parent then re-asked the user what the child was
        # supposed to have settled).
        from src.agents.subagent_permissions import truncate_delegate_result
        return (
            f"🤖 Sub-agent ({actual_mode}) completed.\n\n"
            f"**Description:** {actual_description}\n"
            f"**Task:** {actual_task[:500]}\n\n"
            f"**Result:**\n{truncate_delegate_result(result_text, child_id)}\n\n"
            f"*Agent ID: {child_id}*"
        )
    except Exception:
        # Fallback to legacy coordinator path (no lifecycle)
        pass

    # Legacy fallback (original behavior)
    agent_id = subagent_coordinator.spawn(
        mode=internal_mode,
        task=actual_task,
        parent_thread_id=str(caller_thread) or "main",
        provider=LLM_PROVIDER,
        model=resolved_model,
        allowed_capabilities=tuple(agent_def.capabilities),
        description=actual_description,
        background=background,
        tool_call_id=tool_call_id,
        agent_prompt=agent_def.prompt,
        workspace=str(runnable_config.get("configurable", {}).get("workspace") or "") or None,
    )

    _outcome_state, result = subagent_coordinator.get_outcome(agent_id)
    note_subagent_model_wall(str(caller_thread) or "main", agent_id)
    if _outcome_state == "failed":
        # Same upstream failure line as the lifecycle path: the
        # session id stays visible so the parent can resume it.
        return f"⛔ Subagent failed (session_id: {agent_id}): {result}"

    # One delivery, whole up to OpenCode's tool-output limits (the
    # duplicated XML second copy and 2,000-char head-cut are gone —
    # see the lifecycle path above).
    from src.agents.subagent_permissions import truncate_delegate_result
    try:
        return (
            f"🤖 Sub-agent ({actual_mode}) completed.\n\n"
            f"**Description:** {actual_description}\n"
            f"**Task:** {actual_task[:500]}\n\n"
            f"**Result:**\n{truncate_delegate_result(result, agent_id)}\n\n"
            f"*Agent ID: {agent_id}*"
        )
    except Exception:
        return (
            f"🤖 Sub-agent ({internal_mode}) completed.\n\n"
            f"**Task:** {actual_task}\n\n"
            f"**Result:**\n{truncate_delegate_result(result, agent_id)}\n\n"
            f"*Agent ID: {agent_id}*"
        )


@tool
def delegate_to_subagent_batch(
    mode: str = "code",
    tasks: list = None,  # type: ignore
    model: str = "",
    config: RunnableConfig = None,  # type: ignore
) -> str:
    """
    Delegate SEVERAL independent sub-tasks at once — they run in parallel.

    WHEN TO USE:
    - 2-5 INDEPENDENT pieces (e.g. "review these 3 files",
      "research these 2 libraries"). Independence means: different files,
      no piece needs another piece's output.

    TASK SHAPE: each entry is either a plain string (runs with the batch
    `mode`) or {"task": "...", "mode": "<agent>"}. Give EVERY task the
    agent ITS work needs — a task that writes or runs code must be a
    code agent even when batched next to research tasks: the agent sets
    the child's tools and instructions, and a writer in research mode
    cannot write. Agents are the open registry: research/code/test/
    review plus custom agents from .crusorai/agents/*.md. An entry may
    also carry "session_id" to RESUME that earlier sub-agent session
    with this task as its follow-up (runs first, in order).

    WHEN NOT TO USE:
    - A single sub-task (use delegate_to_subagent).
    - Pieces that depend on each other or touch the same file — run those
      sequentially yourself. Parallel code sub-agents are protected from
      clobbering each other's files, but dependencies still need order.

    Returns each sub-agent's result in the SAME order as the tasks list.
    OpenCode parity: depth check via store, XML output.
    """
    from src.config.settings import LLM_PROVIDER, LLM_MODEL
    import os

    # Normalize entries: plain strings take the batch mode; dict entries
    # carry their own agent ({"task": ..., "mode": ...}) and optionally a
    # session_id to resume. A write task in research clothing cannot
    # write — per-task agents are the fix. Agent NAMES stay raw here;
    # the registry resolves (or rejects) them once the workspace is
    # known, so custom agents work per-task too.
    actual_tasks: list[str] = []
    task_modes: list[str] = []
    task_session_ids: list[str] = []
    for _entry in (tasks or []):
        if isinstance(_entry, dict):
            _text = str(_entry.get("task") or _entry.get("prompt") or _entry.get("description") or "").strip()
            _m = str(_entry.get("mode") or _entry.get("subagent_type") or "").strip().lower()
            if _text:
                actual_tasks.append(_text)
                task_modes.append(_m)
                task_session_ids.append(str(_entry.get("session_id") or "").strip())
        elif _entry is not None and str(_entry).strip():
            actual_tasks.append(str(_entry))
            task_modes.append("")
            task_session_ids.append("")
    if isinstance(tasks, dict):
        actual_tasks = []
        task_modes = []
        task_session_ids = []
    runnable_config = config if isinstance(config, dict) else {}
    caller_thread = (runnable_config or {}).get("configurable", {}).get("thread_id", "") if isinstance(runnable_config, dict) else ""
    if isinstance(config, dict) and not caller_thread:
        caller_thread = (config or {}).get("configurable", {}).get("thread_id", "")
    if not caller_thread:
        # also try original config param when tasks shift
        try:
            if isinstance(tasks, dict):
                caller_thread = tasks.get("configurable", {}).get("thread_id", "")
        except Exception:
            pass
    if not caller_thread:
        caller_thread = "main"

    try:
        from src.runtime.subagent_store import get_store
        store = get_store()
        depth = store.depth_of(str(caller_thread))
        if str(caller_thread).startswith("sub-"):
            depth = max(depth, 1)
        max_depth = int(os.getenv("CRUSORAI_SUBAGENT_DEPTH", "1"))
        if depth >= max_depth:
            return f"⛔ Subagent depth cap reached ({max_depth}). Complete steps directly."
    except Exception:
        if str(caller_thread).startswith("sub-"):
            return (
                "⛔ Sub-agents cannot spawn further sub-agents (depth cap). "
                "Complete the decomposed steps directly instead."
            )

    if not actual_tasks:
        return "⛔ Empty batch: provide at least one task."
    if len(actual_tasks) > 5:
        return (
            f"⛔ Batch too large ({len(actual_tasks)} tasks, max 5): split it "
            f"into smaller batches."
        )

    # Resolve every task's agent (open registry + spawn policy), the
    # same rules as the single delegate: unknown agent = hard error
    # with the available list; denied agent = policy error.
    from src.agents.subagent_registry import available_agents, denied_reason, resolve_agent

    _ws = str(runnable_config.get("configurable", {}).get("workspace") or "") or None
    defs = []
    for _name in task_modes:
        _def = resolve_agent(_name, _ws) or resolve_agent(mode, _ws)
        if _def is None:
            _names = ", ".join(a.name for a in available_agents(_ws))
            return f"⛔ Unknown sub-agent '{_name or mode}'. Available agents: {_names}."
        _denied = denied_reason(_def.name)
        if _denied:
            return f"⛔ {_denied}"
        defs.append(_def)
    batch_model = (model or "").strip() or LLM_MODEL

    # Stop on the parent cascades into every batch child (OpenCode:
    # interrupt cancels the job and its children): an abort registered
    # on the parent's turn cancels each running child's turn, which
    # also wakes any blocking clarify/approval waits inside them.
    _parent_thread = str(caller_thread) or "main"

    def _abort_batch_children() -> None:
        try:
            from src.runtime.subagent_store import get_store as _gs
            from src.runtime.turn_control import turn_controls as _tc

            for _row in _gs().list_by_parent(_parent_thread):
                if str(getattr(_row, "state", "") or "") in ("running", "pending"):
                    _tc.cancel(str(getattr(_row, "child_thread_id", "") or ""))
        except Exception:
            pass

    try:
        from src.runtime.turn_control import turn_controls as _tc2

        _tc2.register_abort(_parent_thread, _abort_batch_children)
    except Exception:
        pass
    agent_ids: list[str] = [""] * len(actual_tasks)
    resume_results: dict[int, str] = {}
    resume_states: dict[int, str] = {}
    try:
        # Resume entries first, in order (a follow-up continues its own
        # session — sequential by nature); fresh spawns then run parallel.
        spawn_indexes: list[int] = []
        for _i, _sid in enumerate(task_session_ids):
            if not _sid:
                spawn_indexes.append(_i)
                continue
            agent_ids[_i] = _sid
            try:
                from src.agents.subagent_lifecycle import subagent_lifecycle as _lc

                _handle = _lc.resume_child(
                    _sid, goal=actual_tasks[_i], parent_session_id=_parent_thread,
                    workspace=_ws, provider=LLM_PROVIDER, model=batch_model,
                )
                _res = _lc.wait(_handle, timeout=600)
                resume_results[_i] = _res.get("result") or _res.get("error") or "No result"
                resume_states[_i] = str(_res.get("state") or "")
            except ValueError as exc:
                resume_results[_i] = f"⛔ Cannot resume sub-agent session '{_sid}': {exc}"
            except Exception:
                resume_results[_i] = "⛔ Resume unavailable right now; spawn a fresh sub-agent instead."
        if spawn_indexes:
            _spawned = subagent_coordinator.spawn_batch(
                mode=defs[spawn_indexes[0]].base_mode,
                tasks=[actual_tasks[_i] for _i in spawn_indexes],
                parent_thread_id=_parent_thread,
                provider=LLM_PROVIDER,
                model=batch_model,
                workspace=_ws,
                modes=[defs[_i].base_mode for _i in spawn_indexes],
                agent_prompts=[defs[_i].prompt for _i in spawn_indexes],
                capabilities=[tuple(defs[_i].capabilities) for _i in spawn_indexes],
            )
            for _i, _spawned_id in zip(spawn_indexes, _spawned):
                agent_ids[_i] = _spawned_id
    finally:
        try:
            from src.runtime.turn_control import turn_controls as _tc3

            _tc3.unregister_abort(_parent_thread, _abort_batch_children)
        except Exception:
            pass

    # Each child's section carries ITS OWN settled state (upstream:
    # status is a fact of the run, never a blanket "completed" over
    # the batch) — a crashed child reads error with its crash text,
    # and the header counts only the children that actually finished.
    def _section(i: int, task: str, agent_id: str) -> tuple[str, bool]:
        if (i - 1) in resume_results:
            result = resume_results[i - 1]
            done = resume_states.get(i - 1) == "succeeded"
        else:
            _ostate, result = subagent_coordinator.get_outcome(agent_id)
            done = _ostate == "succeeded"
        return result, done

    try:
        from src.agents.subagent_permissions import truncate_delegate_result
        sections: list[str] = []
        _done_count = 0
        for i, (task, agent_id) in enumerate(zip(actual_tasks, agent_ids), 1):
            result, done = _section(i, task, agent_id)
            _done_count += 1 if done else 0
            # One copy per child, whole up to OpenCode's tool-output
            # limits (was: friendly copy + XML copy, each head-cut
            # at 2,000 characters — conclusions never arrived).
            sections.append(
                f"--- [{i}] Task: {task[:200]} ---\n{truncate_delegate_result(result, agent_id)}\n(ID: {agent_id})\n"
            )
        for _aid in agent_ids:
            note_subagent_model_wall(str(caller_thread) or "main", _aid)
        header = f"🤖 Sub-agent batch ({mode}) — {_done_count}/{len(agent_ids)} completed:\n"
        return "\n".join([header, *sections])
    except Exception:
        from src.agents.subagent_permissions import truncate_delegate_result
        sections = []
        for i, (task, agent_id) in enumerate(zip(actual_tasks, agent_ids), 1):
            result, _done = _section(i, task, agent_id)
            sections.append(
                f"--- [{i}] Task: {task} ---\n{truncate_delegate_result(result, agent_id)}\n(ID: {agent_id})\n"
            )
        header = f"🤖 Sub-agent batch ({mode}) — {len(agent_ids)} result(s):\n"
        return "\n".join([header, *sections])


class CrusorTask(TypedDict):
    """Shape the LLM should fill for display_crusor_task — steers JSON schema."""

    title: str
    description: str
    status: str
    priority: str
    assignee: str
    taskId: str


@tool
def display_crusor_task(
    title: str,
    description: str,
    status: str,
    priority: str,
    assignee: str,
    taskId: str,
) -> str:
    """Show a Crusor task card for the given work item.

    Use concise title and description, status like "In progress", priority like "high",
    assignee like "Crusor Agent", taskId like "crusor-123".

    After this tool returns, the task card is already rendered via the A2UI surface —
    the JSON returned is the surface descriptor, NOT a status code. Do NOT call again
    for the same task. Reply with one short confirmation sentence and stop.
    """
    return a2ui.render(
        operations=[
            a2ui.create_surface(SURFACE_ID, catalog_id=CATALOG_ID),
            a2ui.update_components(SURFACE_ID, CRUSOR_TASK_SCHEMA),
            a2ui.update_data_model(
                SURFACE_ID,
                {
                    "title": title,
                    "description": description,
                    "status": status,
                    "priority": priority,
                    "assignee": assignee,
                    "taskId": taskId,
                },
            ),
        ],
    )


tools = [
    think,
    verify,
    terminal,
    plan_update,
    todo_list,
    clarify,
    delegate_to_subagent,
    delegate_to_subagent_batch,
    display_crusor_task,


    # File tools
    read_file,
    list_files,
    search_files,
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
    web_extract,

    # Media tools — stock image/video search, binary download into the
    # workspace, and custom text-to-image AI generation.
    media_search,
    media_download,
    generate_image,

    # Skill pull tools — Agent Skills / Copilot parity: the compact index
    # rides the system prompt; the full SKILL.md body loads on demand when
    # the model calls skill_view(name). skills_list is that index as a tool.
    skills_list,
    skill_view,
    skill_manage,

    # Skills Hub — the INSTALL side: search the curated catalog, install
    # community SKILL.md skills (SHA-pinned, capped, traversal-proof), list
    # and remove hub installs. Nothing from an installed skill executes
    # during install; running skill scripts stays behind approval gates.
    hub_search,
    hub_install,
    hub_update,
    hub_list,
    hub_remove,

    # Programmatic tool calling: ONE scripted call can chain the tools
    # above and return only printed output (D18, hermes PTC pattern).
    execute_code,

    # Zero-LLM recall of past sessions (D16, hermes session-search shape).
    session_search,

    # Lazily discovered read-only intelligence from the native Code OSS host.
    *HOST_TOOLS,

    # Verification receipts: static compiler proof and a deterministic UI
    # pipeline that owns server/browser mechanics without extra model turns.
    typecheck_workspace,
    verify_ui_workspace,
    verify_ui_routes,

    # Multi-platform receipts (src/targets/): Android/iOS/desktop/flutter/RN
    # apps are built, installed, launched and PROVEN (foreground app, simulator
    # install, CDP window, live process, UI dump, crash-free log slice) in one
    # deterministic call — plus the device-interaction surface for follow-up
    # flows and the toolchain doctor for actionable refusals.
    detect_targets,
    check_target_toolchains,
    install_toolchain,
    build_target,
    verify_target_app,
    device_action,
    device_screenshot,
    device_ui,
    device_logs,
    device_preview,

    # Test-2 retest (workspace_d): the agent's EYES. A real browser the
    # agent can navigate/snapshot/screenshot — the only thing that can
    # prove a UI app actually renders (D5 faked verification because no
    # browser tool was bound; see browser_mcp docstring). Lazy-spawned, so
    # registering them costs nothing at import.
    *BROWSER_TOOLS,
]


# --------------------------------------------------------------------------- #
# Tool binding — hermes' registry snapshot (agent_init._load_tools).          #
# Hermes loads agent.tools ONCE from the registry and binds the SAME list on  #
# every call; narrowing exists only as operator toolset opt-in/out and        #
# check_fn availability (deps missing -> tool unregistered). Crusor matched    #
# that on 2026-09-07 after the field proved the old task-keyword waist is a   #
# failure generator ("browser testing" lost its tools to the word "build";    #
# a differently-worded ask would never bind them at all). `tools` IS the      #
# bound list; the SafeToolNode executes whatever the model calls.             #
# --------------------------------------------------------------------------- #
_TOOLS_BY_NAME: dict[str, Any] = {t.name: t for t in tools}
# Base descriptions of the delegate tools, captured before the binder
# starts refreshing them with the live agent registry listing.
_DELEGATE_BASE_DESCRIPTIONS: dict[str, str] = {}
_TOOL_AVAILABILITY_REPORTED = False  # hermes load-line: once per process

_FILE_DELIVERY_TOOLS = frozenset({
    "write_file", "edit_file", "copy_file",
})
_FILE_DELIVERY_WORDS = frozenset({
    "build", "create", "implement", "write", "fix", "edit", "modify",
    "update", "scaffold", "deliver",
})

# An answer/no-change turn may inspect local or public information, but it must
# not acquire a side-effecting schema and accidentally turn an inquiry into
# implementation. The same allowlist is copied into the SafeToolNode phase
# config below, so provider quirks cannot bypass model-time binding.
_READ_ONLY_INTEREST_TOOLS = frozenset({
    "think", "verify", "clarify",
    "read_file", "list_files", "search_files", "search_code",
    "web_search", "web_fetch", "web_extract", "media_search",
    "skills_list", "skill_view", "hub_search", "hub_list",
    "session_search", "discover_host_capabilities", "open_preview",
    "browser_navigate", "browser_snapshot", "browser_scroll", "browser_back",
    "browser_console", "browser_get_images", "browser_screenshot",
})
_NO_CHANGE_ACTION_TOOLS = _READ_ONLY_INTEREST_TOOLS | frozenset({
    # Explicit verification/execution without source mutation. Shell access is
    # needed for user-requested tests; the contract and phase guidance still
    # prohibit edit/generator/install commands.
    "terminal", "run_terminal", "start_terminal", "check_terminal",
    "stop_terminal", "list_terminal_processes", "cleanup_terminal_processes",
    "read_terminal_output", "typecheck_workspace", "verify_ui_workspace",
    "verify_ui_routes", "detect_targets", "check_target_toolchains",
    "verify_target_app", "device_screenshot", "device_ui", "device_logs",
    "device_preview", "browser_click", "browser_type", "browser_press",
})


def _stored_user_interest(state: AgentState) -> UserInterest | None:
    return UserInterest.from_state(state.get("user_interest"))


def _active_interest_text(state: AgentState) -> str:
    """Objective plus newest substantive steering, never a social ack."""
    focus = interest_from_state(state).focus_text()
    return focus or str(state.get("current_task", "") or "")


def _read_only_interest(state: AgentState) -> bool:
    interest = _stored_user_interest(state)
    return bool(interest is not None and interest.mode in {"answer", "social"})


def _no_change_action_interest(state: AgentState) -> bool:
    interest = _stored_user_interest(state)
    return bool(
        interest is not None
        and interest.mode == "act"
        and interest.change_policy == "no_changes"
    )


def _execution_requested_by_interest(state: AgentState) -> bool:
    interest = _stored_user_interest(state)
    if interest is not None:
        if _read_only_interest(state) or interest.relationship == "cancelled":
            return False
        if interest.mode == "act":
            return True
    return _looks_like_execution_task(_active_interest_text(state))


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
    if _read_only_interest(state) or _no_change_action_interest(state):
        return False
    text = " ".join([
        _active_interest_text(state),
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
    """Whether a fresh delivery workspace has no task-owned input files.

    Agent Core creates ``diagnostics/`` before the first model call. Counting
    that runtime-owned trace as user content disables the fresh-workspace
    forced-delivery phase and exposes exploration/shell tools before any file
    can land. Dot-prefixed runtime/test fixtures are ignored for the same
    reason; any other visible file still makes the workspace non-empty.
    """
    from pathlib import Path

    root = Path(workspace)
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(root).parts
            if any(part.startswith(".") for part in parts):
                continue
            if parts and parts[0] == "diagnostics":
                continue
            return False
        return True
    except (OSError, ValueError):
        return False


def _resolve_bound_tools(state: AgentState, config: RunnableConfig) -> list:
    """The tool OBJECTS to bind for this turn (narrowed by task type).

    The autonomous surface deliberately has a smaller waist than interactive
    IDE chat. It cannot answer clarify, and broad meta/delegation/process
    schemas diluted the direct actions in six Test-5 traces.
    """
    # The registry snapshot, hermes-shaped: every registered tool is bound,
    # every turn, regardless of task wording (agent_init._load_tools loads
    # the registry once; per-message narrowing does not exist in hermes).
    names = [t.name for t in tools]
    hidden_receipts: list[str] = []
    # check_fn availability (hermes registration semantics): the browser
    # stack is bound only when the agent-browser CLI resolves. Resolution is
    # cached, so a missing CLI costs one fast raise per turn and the tools
    # stay unbound instead of the model paying for a doomed call.
    try:
        from src.tools.browser_tools import find_agent_browser
        find_agent_browser()
    except Exception as _cli_exc:
        hidden_receipts.append(
            "browser_* tools (agent-browser CLI not found — install with "
            "`npm install -g agent-browser`, then run `agent-browser install` "
            "once; set CRUSORAI_AGENT_BROWSER to the CLI path to override)")
        names = [name for name in names if not name.startswith("browser_")]
    # check_fn: a verifier with no project cannot produce evidence. Hiding it
    # is stronger than repeatedly telling a weak model not to call it:
    # Test5-5 paid three model/replan cycles for typecheck_workspace on an
    # empty directory. (Workspace STATE, not task words.)
    from pathlib import Path
    from src.tools.file_tools import find_typecheck_project_root
    workspace = Path(config.get("configurable", {}).get("workspace", "."))
    if find_typecheck_project_root(workspace) is None:
        hidden_receipts.append(
            "typecheck_workspace (no tsconfig.json in the workspace or its "
            "immediate project folders)"
        )
        names = [name for name in names if name != "typecheck_workspace"]
    # hermes agent_init._load_tools paints availability once at load ("Loaded
    # N tools" + "⚠️ Some tools may not work due to missing requirements").
    # Crusor binds lazily per turn, so the receipt prints on the FIRST binding
    # per process — a silently hidden browser stack read as "the agent
    # cannot test" in the field (2026-09-07 1:34 PM) with no trace why.
    global _TOOL_AVAILABILITY_REPORTED
    if hidden_receipts and not _TOOL_AVAILABILITY_REPORTED:
        _TOOL_AVAILABILITY_REPORTED = True
        print(
            f"[tools] binding {len(names)} tools; unavailable this session: "
            + "; ".join(hidden_receipts),
            flush=True,
        )
    autonomous = _is_autonomous_workspace(config)
    resolved_names = list(names)

    # Strict scope waist (sub-agent children): when the run carries an
    # explicit capability scope, bind ONLY what the capability waist grants
    # (tools.toolsets.resolve_runtime_tool_names over the strict profile).
    # This is the per-call schema bill: children previously re-sent all
    # ~68 registered schemas on every round while their scope collapsed
    # to () upstream and nothing here ever applied it (2026-10-15 cost
    # investigation). The parent bind is untouched (strict is child-only).
    try:
        _cfg = config.get("configurable", {}) if isinstance(config, dict) else {}
        if _cfg.get("scope_capabilities_strict"):
            from src.agents.runtime_profile import resolve_runtime_profile
            from src.tools.toolsets import resolve_runtime_tool_names
            _waist_profile = resolve_runtime_profile("", config)
            _waist = set(resolve_runtime_tool_names(_waist_profile, config))
            _scoped = [n for n in resolved_names if n in _waist]
            if _scoped:
                resolved_names = _scoped
    except Exception:
        pass  # scoping must never break binding; worst case = today's surface

    read_only_interest = _read_only_interest(state)
    no_change_action_interest = _no_change_action_interest(state)
    interest_allowlist = (
        _READ_ONLY_INTEREST_TOOLS
        if read_only_interest
        else _NO_CHANGE_ACTION_TOOLS if no_change_action_interest else None
    )
    if interest_allowlist is not None:
        resolved_names = [
            name for name in resolved_names if name in interest_allowlist
        ]

    # Tool cap: some models (notably DeepSeek) return empty tool_calls when
    # overwhelmed by 40+ schemas. CRUSORAI_MAX_TOOLS=0 disables the cap.
    _max_env = os.getenv("CRUSORAI_MAX_TOOLS", "0").strip()
    _max_tools = int(_max_env) if _max_env.isdigit() else 0
    if _max_tools > 0 and len(resolved_names) > _max_tools:
        # Keep the most important tools (write_file, edit_file, read_file,
        # list_files, search_files, terminal) at the front, then fill up
        _priority = [
            "write_file", "edit_file", "read_file", "list_files",
            "search_files", "terminal", "copy_file",
        ]
        _priority = [n for n in _priority if n in resolved_names]
        _rest = [n for n in resolved_names if n not in _priority]
        resolved_names = (_priority + _rest)[:_max_tools]
        if not _TOOL_AVAILABILITY_REPORTED:
            _TOOL_AVAILABILITY_REPORTED = True
            print(
                f"[tools] binding {len(resolved_names)} tools (cap {_max_tools}; "
                f"skipped: {len(names) - len(resolved_names)})",
                flush=True,
            )

    from src.runtime.execution_phases import base_phase
    # Neutral base: phases are STATE-derived only (hermes has no keyword
    # phase machinery — see execution_phases.py). The state-driven phases
    # below replace this object when their conditions hold.
    phase = base_phase()
    # Neutral base: phases are STATE-derived only (hermes has no keyword
    # phase machinery — see execution_phases.py). The state-driven phases
    # below replace this object when their conditions hold.
    names = resolved_names
    empty_autonomous_delivery = (
        autonomous
        and _requires_file_delivery(state)
        and not _has_landed_file_delivery(state)
        and _workspace_is_effectively_empty(workspace)
    )
    if read_only_interest:
        phase = type(phase)(
            "read_only_interest",
            frozenset(_READ_ONLY_INTEREST_TOOLS),
            max_file_mutations_per_turn=0,
            guidance=(
                "READ-ONLY INTEREST: answer the user's inquiry from available "
                "evidence. Do not edit files, run side-effecting commands, "
                "delegate implementation, install anything, or create artifacts."
            ),
        )
    elif no_change_action_interest:
        phase = type(phase)(
            "no_change_action",
            frozenset(_NO_CHANGE_ACTION_TOOLS),
            max_file_mutations_per_turn=0,
            guidance=(
                "NO-CHANGE ACTION: perform the requested inspection or "
                "verification, but do not edit/create files, install software, "
                "run generators, or delegate implementation."
            ),
        )
    elif _pre_delivery_stalled(state) or empty_autonomous_delivery:
        # A fresh autonomous build has nothing useful to inspect. Hermes begins
        # headless jobs with action-capable tools; Crusor previously exposed 33
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
            "terminal", "run_terminal", "start_terminal", "check_terminal",
            "read_terminal_output", "stop_terminal", "typecheck_workspace",
            "verify_ui_workspace", "verify_ui_routes",
            "build_target", "verify_target_app", "detect_targets",
            "check_target_toolchains",
        }
        repair_tools = first_check_tools | {
            "read_file", "search_files", "search_code", "write_file",
            "edit_file", "copy_file",
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
    # Dynamic agent list (OpenCode builds the task tool's description
    # from the live registry): refresh the delegate tools' descriptions
    # with the agents THIS workspace has, so the model can name custom
    # agents it was never hard-coded to know. Rebuilt from the stored
    # base each bind — never appended twice.
    if "delegate_to_subagent" in names or "delegate_to_subagent_batch" in names:
        try:
            from src.agents.subagent_registry import available_agents

            _listing = "; ".join(
                f"{agent.name} — {agent.description}"
                for agent in available_agents(str(workspace))
            )
            for _tool_name in ("delegate_to_subagent", "delegate_to_subagent_batch"):
                _tool_obj = _TOOLS_BY_NAME.get(_tool_name)
                if _tool_obj is None:
                    continue
                if _tool_name not in _DELEGATE_BASE_DESCRIPTIONS:
                    _DELEGATE_BASE_DESCRIPTIONS[_tool_name] = _tool_obj.description
                _tool_obj.description = (
                    f"{_DELEGATE_BASE_DESCRIPTIONS[_tool_name]}\n\nAvailable agents: {_listing}"
                )
        except Exception:
            pass  # description refresh must never break binding
    bound = [_TOOLS_BY_NAME[n] for n in names if n in _TOOLS_BY_NAME]
    if bound:
        return bound
    # A guarded phase never falls back to the full registry. Keep clarify as
    # the safe escape hatch (hermes' one ask tool); general mode retains the
    # historical safe superset.
    if phase.allowed is not None and "clarify" in _TOOLS_BY_NAME:
        return [_TOOLS_BY_NAME["clarify"]]
    return list(tools)


def _zero_token_usage() -> dict[str, Any]:
    """Return an empty token usage snapshot."""
    return TokenUsage().to_dict()


def _turn_scoped_resets() -> dict[str, Any]:
    """Fresh safety/gate state for every user turn.

    These counters bound retries *within* one turn.  Letting a resumed
    checkpoint carry them into the next prompt makes behavior depend on what
    the previous prompt spent: desktop evidence bd057959 showed later prompts
    skipping finish laps because the first prompt had already consumed the
    budget.  Keep active-task history separately; reset only turn-local valves.
    """
    return {
        "iteration_used": 0,
        "grace_done": 0,
        "budget_warning_done": 0,
        "incomplete_response_retries": 0,
        "plan_wrap_nudges": 0,
        "wrap_summary": 0,
        "finish_nudges": 0,
        "verify_nudges": 0,
        "stall_continuations": 0,
        "nudged_at_msg_count": -1,
        "turn_token_usage": _zero_token_usage(),
        # Do not derive this from execution_trace: informational/unavailable
        # receipts are intentionally absent from that progress ledger but are
        # still real executions in the diagnostics report.
        "turn_tool_execution_count": 0,
        "turn_tool_execution_names": [],
    }


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


def _session_system_message(config: RunnableConfig, state: dict, *, autonomous: bool):
    """The session-cached 3-tier prefix, or the legacy persona when unavailable.

    Hermes builds the system prompt ONCE per session and reuses it every turn;
    only compaction rebuilds it (that is what keeps the provider's prompt cache
    warm, and therefore what keeps cost and latency down). Crusor's equivalent
    lives in ``src/prompts/hermes/session.py``, keyed by ``thread_id``.

    Fallback is deliberate and total: if the engine cannot build a prefix for
    any reason, this returns the pre-port persona object untouched, so prompt
    engineering can never take a live turn down with it.
    """
    from src.prompts.hermes.session import system_prompt_for_session

    text = system_prompt_for_session(config, state, autonomous=autonomous)
    if not text:
        return autonomous_system_message if autonomous else system_message
    return SystemMessage(content=text)


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


def _fuse_system_head(messages: list) -> list:
    """Hermes request shape (run_agent.py:2657): ONE system message, then the
    conversation. Runtime prefixes (mode banner, CopilotKit context, safety
    guard, terminal platform, grace nudge) are inserted as separate
    SystemMessages for assembly clarity, and nodes append guidance blocks into
    the transcript (the tool cycle's progress reflection, out-of-band steers);
    before the provider call EVERY system block folds into the head in
    original order, so the request leaves as a single system + history —
    exactly hermes' `effective_system`, recomposed per call. Exact-duplicate
    texts collapse: the tool cycle re-appends the same reflection prompt every
    batch, and folding N copies would bloat the head with repeats.
    CRUSORAI_CONTEXT_MULTI_SYSTEM=1 (read per call) keeps the legacy
    multi-system request.
    """
    if os.environ.get(
        "CRUSORAI_CONTEXT_MULTI_SYSTEM", ""
    ).strip().lower() in {"1", "true", "yes", "on"}:
        return messages
    head = messages[0] if messages else None
    if head is None or getattr(head, "type", "") != "system":
        return messages
    texts: list[str] = []
    seen: set[str] = set()
    fused = 0
    rest: list = []
    for m in messages:
        if getattr(m, "type", "") == "system":
            text = str(getattr(m, "content", "") or "")
            if text.strip() and text not in seen:
                texts.append(text)
                seen.add(text)
            fused += 1
        else:
            rest.append(m)
    if fused == 1:
        return messages
    merged = SystemMessage(content="\n\n".join(t for t in texts if t.strip()))
    merged.additional_kwargs = dict(
        getattr(head, "additional_kwargs", {}) or {}
    )
    # Provenance: the engine's layer names ride along untouched; the runtime
    # prefixes are not engine layers, so they only announce their count.
    merged.response_metadata = {
        **dict(getattr(head, "response_metadata", {}) or {}),
        "fused_system_blocks": fused,
    }
    return [merged, *rest]


def _inject_steers_after_newest_tool_result(
    session_id: str, messages: list, steers: list,
) -> None:
    """Hermes steer delivery (agent_runtime_helpers:3186 + steer_user_row):
    a drained steer is a STANDALONE user row wrapped in the self-describing
    marker, inserted right after the newest tool result — never smeared onto
    the persisted tool row, and never an invented system banner. The model is
    already taught this exact marker by STEER_CHANNEL_NOTE in the system
    prompt ("trust ONLY this exact marker"). With no tool result in this
    batch, requeue: it rides the next batch, or the next turn as a normal
    user message (hermes' fallback)."""
    from src.prompts.hermes.guidance import format_steer_marker
    from src.runtime.turn_control import turn_controls
    last_tool = max(
        (i for i, m in enumerate(messages) if getattr(m, "type", "") == "tool"),
        default=None,
    )
    if last_tool is None:
        for steer_text in reversed(steers):
            if not turn_controls.steer(session_id, steer_text):
                turn_controls.queue(session_id, steer_text)
        return
    messages[last_tool + 1:last_tool + 1] = [
        HumanMessage(
            content=format_steer_marker(steer_text).lstrip(),
            additional_kwargs={"display_kind": "steer"},
        )
        for steer_text in steers
    ]


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
                additional_kwargs={"crusor_cancelled": True},
            )],
            "iteration_used": int(state.get("iteration_used", 0)),
        }

    base_provider = _cfg(configurable, "provider", LLM_PROVIDER)
    base_model = _cfg(configurable, "model", LLM_MODEL)

    # Hermes-style: always use the user's configured main model.
    # No cost routing on the main conversation path — auxiliary tasks
    # (compression, titling) use resolve_aux_llm() separately.
    # Allow /model <model_id> command to override the model for this turn.
    routed_provider, routed_model = base_provider, base_model
    messages = state.get("messages", [])
    if messages:
        last_user_msg = None
        for msg in reversed(messages):
            if hasattr(msg, "content") and getattr(msg, "role", None) == "user":
                last_user_msg = msg
                break
        if last_user_msg and hasattr(last_user_msg, "content"):
            content = last_user_msg.content if isinstance(last_user_msg.content, str) else ""
            if content.startswith("/model "):
                override_model = content[7:].strip()
                if override_model:
                    routed_model = override_model
                    # Extract provider from model id (e.g. "openai/gpt-4o" -> "openai")
                    if "/" in override_model:
                        routed_provider = override_model.split("/")[0]

    provider = routed_provider
    model = routed_model
    reasoning_config = _resolve_reasoning_config(config)
    try:
        llm = get_llm(provider=routed_provider, model=routed_model, reasoning_config=reasoning_config)
    except Exception:
        # Fallback to the originally configured provider if routing fails
        provider, model = base_provider, base_model
        llm = get_llm(provider=provider, model=model, reasoning_config=reasoning_config)

    execution_mode = cast(ExecutionMode, state.get("execution_mode", "agent"))

    # Ask is structurally conversational: no tool schema is sent and no tool
    # call can be executed. Other modes retain the phase-scoped tool waist.
    llm_with_tools = (
        llm if execution_mode == "ask"
        else llm.bind_tools(_resolve_bound_tools(state, config))
    )

    # D31: start of an AI iteration — reset shadow-checkpoint dedup so the
    # first mutation this iteration snapshots the pre-change workspace.
    from src.tools.shadow_checkpoints import begin_agent_turn
    begin_agent_turn()

    # D40: inclusive iteration budget. The final configured provider slot is
    # tool-free, following OpenCode's max-step shape, so an N-call boundary
    # includes its closing response instead of requiring an N+1 grace request.
    # Legacy checkpoints already at the wall retain the Hermes compatibility
    # grace. iteration_used remains monotonic. Any pending real tool calls from
    # an older budget-crossing checkpoint still dispatch before that grace.
    iteration_used = int(state.get("iteration_used", 0))
    budget_exhausted = _budget_exhausted(state)
    final_response_slot = _final_response_reserve_reached(state)
    completion_evidence_ready = (
        final_response_slot and _completion_evidence_ready(state)
    )
    grace_done = bool(state.get("grace_done", 0))
    # True when THIS call is the first tool-free closing request: either the
    # inclusive reserved final slot or a legacy already-exhausted grace call.
    grace_summary_lap1 = False

    # Use the Context Engine to build clean, organized messages.
    # Session-scoped: this thread's thread_id selects an isolated engine
    # (cache, attribution snapshot, learned weights all independent).
    context_state = dict(state)
    context_state["_autonomous_workspace"] = _is_autonomous_workspace(config)
    messages = get_context_engine(config).build_ai_messages(
        state=context_state,
        system_message=_session_system_message(
            config,
            context_state,
            autonomous=bool(context_state["_autonomous_workspace"]),
        ),
    )
    if execution_mode == "ask":
        _insert_system_prefix(
            messages,
            "=== ASK MODE ===\n"
            "Answer and explain without changing files, running commands, or calling tools. "
            "Be clear about uncertainty and suggest next steps when useful.",
        )
        # A resumed session can contain earlier Agent-mode tool pairs. Ask sends
        # no tool declarations, so remove those pairs before the provider call.
        messages = _drop_tool_pairs(messages)
    elif execution_mode == "debug":
        _insert_system_prefix(
            messages,
            "=== DEBUG MODE ===\n"
            "Diagnose before changing code: reproduce the failure, use concrete diagnostics, "
            "make the smallest relevant fix, and rerun the strongest available check.",
        )

    phase_guidance = str(configurable.get("phase_guidance") or "").strip()
    if phase_guidance and execution_mode != "ask":
        _insert_system_prefix(
            messages,
            f"=== RUNTIME EXECUTION PHASE: {configurable.get('execution_phase')} ===\n"
            + phase_guidance,
        )

    # --- CopilotKit app context (agent-app-context) + refusal guard ---
    _copilotkit_ctx = state.get("copilotkit") if isinstance(state.get("copilotkit"), dict) else {}
    _ctx_items = _copilotkit_ctx.get("context") if isinstance(_copilotkit_ctx.get("context"), list) else []
    _crusor_ctx = None
    for _item in _ctx_items:
        if isinstance(_item, dict) and _item.get("description") == "Crusor workspace context":
            _crusor_ctx = _item.get("value")
            break
    if _crusor_ctx is not None:
        _insert_system_prefix(
            messages,
            "=== CRUSOR WORKSPACE CONTEXT (shared via useAgentContext) ===\n"
            + str(_crusor_ctx)[:4000]
            + "\n\nUse this context to answer. If the user asks about an entity not in this context, refuse and name what is missing instead of inventing.",
        )
    else:
        _insert_system_prefix(
            messages,
            "=== CRUSOR CONTEXT MISSING ===\n"
            "No Crusor workspace context was shared via useAgentContext. If the user asks about files, tasks, or workspace entities, you must refuse to answer about entities the shared context does not carry, and name what is missing instead of inventing plausible entities. Ask the frontend to share context.",
        )
    # Guard unattended side effects: remind model to use clarify for destructive actions
    _insert_system_prefix(
        messages,
        "=== SAFETY GUARD ===\n"
        "Unattended side effects (file overwrites, deletions, dangerous shell commands) are guarded by SafetyGuard/clarify. For any destructive or irreversible change, call clarify to confirm before proceeding.",
    )

    # State the actual shell contract before the model guesses — through the
    # SAME detection the environment block uses (windows_bash_available), so
    # the two carriers can never contradict each other again. Field
    # 2026-09-09 @7a7111b9: this banner hardcoded "Windows cmd.exe. NEVER
    # use ls" on a git-bash host (tool receipts: /usr/bin/bash) while the
    # environment block taught POSIX; the model obeyed the banner —
    # `cd /d "..."` and `Get-ChildItem … | Select-Object` straight into bash,
    # both failed. hermes teaches the shell only via its environment block;
    # crusor keeps this banner as the trim-proof copy of the SAME text.
    from src.prompts.hermes.environment import windows_terminal_banner
    _terminal_banner = windows_terminal_banner()
    if _terminal_banner:
        _insert_system_prefix(
            messages,
            "=== ACTIVE TERMINAL PLATFORM ===\n" + _terminal_banner,
        )

    if (
        execution_mode != "ask"
        and _requires_file_delivery(state)
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
    # hermes turn_iteration_prep.py::_maybe_inject_iteration_budget_warning
    # (field 2026-09-16 audit): the hard wall gets a SOFT checkpoint first.
    # One shot, fired when the run enters its final budget slice: land
    # durable progress and head for the finish instead of hitting the wall
    # cold mid-work (a cold wall is exactly when the grace summary has the
    # least to summarize — the class behind "acting dumb after the cut").
    # Never on exhausted laps (the grace request owns that call), never in
    # ask mode (no work to checkpoint), one-shot via budget_warning_done.
    budget_warning_fired = bool(state.get("budget_warning_done", 0))
    if (
        execution_mode != "ask"
        and not budget_exhausted
        and not final_response_slot
        and not budget_warning_fired
    ):
        from src.graphs.budget import _budget_warning_threshold
        _warn_at = _budget_warning_threshold()
        if _warn_at is not None and iteration_used >= _warn_at:
            budget_warning_fired = True
            print(
                f"[budget] checkpoint warning at {iteration_used}/"
                f"{_iteration_budget()} — one-shot notice injected",
                flush=True,
            )
            _insert_system_prefix(
                messages,
                "=== ITERATION BUDGET CHECKPOINT ===\n"
                f"You have used {iteration_used} of {_iteration_budget()} "
                "iterations. Checkpoint durable progress now, then continue "
                "the task; do not stop solely because of this warning.",
            )

    steers = turn_controls.drain_steer(session_id)
    if steers:
        _inject_steers_after_newest_tool_result(session_id, messages, steers)

    call_model = model
    call_llm = llm_with_tools
    if execution_mode != "ask" and configurable.get("execution_phase") in {"deliver", "forced_delivery"}:
        # The reply ceiling is the model's own number, clamped by what the last rejection said still
        # fits -- not a constant written into this file. What used to sit here was
        # `max_tokens=max(512, min(delivery_cap, 8192))`, which throttled every delivery to 8,192 on an
        # endpoint reporting 512,000, and did so invisibly: no receipt, no setting, no way to tell that
        # the number came from anywhere other than the provider.
        bind_generation = getattr(llm_with_tools, "bind", None)
        if callable(bind_generation):
            # The reply ceiling is the model's own number, clamped by what
            # the last rejection said still fits (base 6a2717bd/a8e7dc64 via
            # src/llm/output_budget) — never a constant written here. The
            # user's CRUSORAI_DELIVERY_MAX_TOKENS stays the DESIRED amount.
            from src.llm.output_budget import requested_output_cap, take_available_output
            from src.config.reasoning_config import THINKING_BUDGET_TOKENS

            # Endpoints that bill hidden reasoning inside max_tokens (e.g.
            # velona/glm-5.3-flash @ high effort) truncate the delivery call
            # before any content unless the thinking budget is included
            # (field 2026-10-22); providers billing reasoning separately just
            # get harmless headroom.
            _think = 0
            _effort = (reasoning_config or {}).get("effort", "")
            if (reasoning_config or {}).get("enabled"):
                _think = THINKING_BUDGET_TOKENS.get(str(_effort), 0)
            allowed = requested_output_cap(model, thinking_tokens=_think)
            _room = take_available_output(model)
            if _room:
                allowed = max(512, min(allowed, _room))
            call_llm = bind_generation(max_tokens=allowed)
    # Field 2026-09-10: the plan-complete wrap cut shares the grace call's
    # shape — wrap lap 2 sets wrap_summary (gates.finish_gate_node) and this
    # lap runs toolless with the summary request, so a cut turn ALWAYS gets
    # a closing answer instead of ending on a bare tool card.
    wrap_summary = bool(state.get("wrap_summary"))
    if budget_exhausted or wrap_summary or final_response_slot:
        call_llm = llm  # closing call: NO tools (OpenCode/Hermes shape)
        if not grace_done:
            # hermes handle_max_iterations (chat_completion_helpers.py:2101):
            # the summary request rides as a USER message appended to the
            # FULL history — never a system nudge, never a stripped
            # transcript. Field 2026-09-09 @b75cd4c6: the old grace dropped
            # every tool pair, the model amnesia'd to "I'll start by
            # exploring..." + a raw text tool_call after 111s of real work,
            # and the turn finalized "completed" on that nonsense.
            grace_summary_lap1 = True
            if final_response_slot:
                print(
                    "[final-reserve] using inclusive final provider slot "
                    f"{iteration_used + 1}/{_iteration_budget()} "
                    f"(evidence_ready={completion_evidence_ready})",
                    flush=True,
                )
                messages = messages + [
                    HumanMessage(content=_FINAL_RESPONSE_RESERVE_REQUEST)
                ]
                try:
                    event_bus.emit("context.status", {
                        "thread_id": session_id,
                        "phase": "final_response_reserve",
                        "severity": "info",
                        "message": (
                            "Using the final reserved provider call for a "
                            "tool-free completion response."
                        ),
                        "iteration": iteration_used + 1,
                        "budget": _iteration_budget(),
                        "completion_evidence_ready": completion_evidence_ready,
                    })
                except Exception:
                    pass
            elif wrap_summary and not budget_exhausted:
                from src.graphs.budget import _PLAN_WRAP_SUMMARY_REQUEST
                print(
                    "[grace] Task list complete but no closing answer was "
                    "delivered — requesting the final summary (toolless).",
                    flush=True,
                )
                messages = messages + [
                    HumanMessage(content=_PLAN_WRAP_SUMMARY_REQUEST)
                ]
            else:
                from src.graphs.budget import _budget_trip_reason
                # Queue item (field 2026-09-09 x2 + 2026-09-10): the prefix
                # blamed "maximum iterations" even when the TOKEN leg tripped;
                # the bracket detail already names both legs, so the prefix
                # must stay leg-neutral.
                print(
                    f"[grace] Run budget reached "
                    f"[{_budget_trip_reason(state)}]. Requesting summary...",
                    flush=True,
                )
                # The summary request must name the leg that ACTUALLY tripped:
                # the iterations wording on a token-cap cut told the model it
                # ran out of tool-calling iterations while iterations had
                # headroom left (same mislabel class as the [grace] prefix).
                if iteration_used >= _iteration_budget():
                    _summary_request = _MAX_ITERATIONS_SUMMARY_REQUEST
                else:
                    from src.graphs.budget import _TOKEN_BUDGET_SUMMARY_REQUEST
                    _summary_request = _TOKEN_BUDGET_SUMMARY_REQUEST
                messages = messages + [
                    HumanMessage(content=_summary_request)
                ]
        else:
            # Lap 2+: hermes never sees one (handle_max_iterations RETURNS
            # the summary and the loop ends). Crusor's graph routes the
            # summary through the model once more, so this bounded lap keeps
            # the D40 pairs-drop: a clean text-only request the provider
            # accepts, no tools to act with.
            messages = _drop_tool_pairs(messages)

    # Hermes todo pipeline (tools/todo_tool.py format_for_injection): the
    # session's ACTIVE task list rides every model call, so the list survives
    # context trims and the model never re-does finished work after
    # compression. Finished/cancelled items are excluded by the store itself.
    _sid_for_todos = str(session_id or "default")
    _todo_block = inject_active_todos(_sid_for_todos)
    if _todo_block:
        messages.append(SystemMessage(content=_todo_block))

    # Hermes request shape: exactly one system message leaves the door (see
    # _fuse_system_head). The anatomy log below then reports the TRUE request.
    messages = _fuse_system_head(messages)

    # Prefill visibility (owner runs: 33s 'hi', 3:12 after a two-tool turn --
    # nobody could say whether the whale was ours or the endpoint's). One
    # line per agent call: the chars/4 estimate of the ACTUAL assembled
    # request, plus the ROLE anatomy — a bare count hid the fact that even a
    # fresh "hi" carries the whole context-layer stack (1 persona system +
    # the fitted context layers + 1 user message; tool turns add the
    # assistant/tool pairs). A number in the tens of thousands here is OUR
    # prompt; a small number with a long wait indicts the endpoint.
    try:
        _req_chars = sum(
            len(getattr(m, "content", "") or "")
            if isinstance(getattr(m, "content", ""), str)
            else len(str(getattr(m, "content", "")))
            for m in messages
        )
        _roles: dict[str, int] = {}
        for _m in messages:
            _r = str(getattr(_m, "type", "unknown"))
            _roles[_r] = _roles.get(_r, 0) + 1
        _role_label = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}
        _role_bits = " + ".join(
            f"{_count} {_role_label.get(_r, _r)}"
            for _r, _count in sorted(_roles.items(), key=lambda kv: -kv[1])
        )
        print(
            # "messages only" honesty (queue item E, field 2026-09-10: a run
            # logged ~18.5k/call yet billed 628k over 15 calls — the estimate
            # counts messages; the provider ALSO bills the bound tool schemas
            # on every call, and TokenTracker records the provider's own
            # usage when it reports one. Estimate and billing are different
            # quantities; the label must say so.)
            f"[ai_node] request ~{_req_chars // 4 / 1000:.1f}k tokens "
            f"(messages only — bound tools bill on top; "
            f"{len(messages)} messages: {_role_bits}) -> {provider}/{model}",
            flush=True,
        )
    except Exception:
        pass  # diagnostics never block the call

    # Circuit breaker: a provider that failed auth earlier in this process is
    # skipped BEFORE the doomed request (each 401 round trip cost the owner
    # seconds on every call of every turn).
    if (provider, model) in _AUTH_DEAD_PROVIDERS and (provider, model) != (base_provider, base_model):
        print(
            f"[ai_node] auth-dead provider skipped: {provider}/{model} "
            f"-> {base_provider}/{base_model} (circuit breaker)"
        )
        try:
            from src.agents.cost_router import cost_router as _cr
            _route = getattr(_cr, "_last_route", None)
            if isinstance(_route, dict):
                _cr._last_route = {**_route, "provider": base_provider, "model": base_model, "failed_over": True}
        except Exception:
            pass  # diagnostics never break the turn
        provider, model = base_provider, base_model
        llm = get_llm(provider=provider, model=model, reasoning_config=reasoning_config)
        llm_with_tools = (
            llm if execution_mode == "ask"
            else llm.bind_tools(_resolve_bound_tools(state, config))
        )
        call_llm = llm_with_tools

    # RetryLLMProxy.invoke() owns request-scoped abort registration for every
    # model path. Keep the active-session binding at the turn boundary; clearing
    # it here would make later planner/classifier requests uninterruptible.
    # The repair/cleaned-text gate needs to know whether THIS call bound
    # tools: the grace/ask path invokes the unbound `llm`, everything
    # else a tools-bound callable.
    tools_bound = call_llm is not llm
    t_llm_start = time.time()
    try:
        result = _invoke_with_token_pump(
            call_llm, messages, session_id, provider, model,
            strip_tool_blocks=tools_bound, reasoning_config=reasoning_config,
            hold_text=tools_bound,
        )
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
                    additional_kwargs={"crusor_cancelled": True},
                )],
                "iteration_used": int(state.get("iteration_used", 0)),
            }
        if grace_summary_lap1 and _is_tool_messages_rejection(exc):
            # hermes sends the iteration summary with the FULL history and no
            # tools key (its providers accept tool traffic unbound,
            # chat_completion_helpers.py:1937-2025). This provider didn't —
            # the D40 400 ("Tool messages found but no tools provided").
            # Retry ONCE text-only so the turn still ends with a real
            # summary instead of dying on its farewell call.
            print(
                "[grace] provider rejected the full-history summary request "
                f"({type(exc).__name__}); retrying text-only (D40 fallback)",
                flush=True,
            )
            result = _invoke_with_token_pump(
                call_llm, _drop_tool_pairs(messages), session_id,
                provider, model, strip_tool_blocks=tools_bound,
                reasoning_config=reasoning_config,
            )
        elif (provider, model) == (base_provider, base_model):
            raise
        else:
            print(
                f"[ai_node] provider failover {provider}/{model} -> "
                f"{base_provider}/{base_model} ({type(exc).__name__})"
            )
            if _mark_auth_dead(provider, model, exc):
                print(
                    f"[ai_node] {provider}/{model} marked AUTH-DEAD for this "
                    "process; future turns skip straight to failover"
                )
                # Hermes honesty discipline: a dead credential is the OWNER's
                # actionable fact, not console noise. One surface per process,
                # on the degraded channel the panel already renders.
                try:
                    from src.dashboard.event_bus import event_bus as _eb
                    _eb.emit("runtime.degraded", {
                        "thread_id": session_id,
                        "component": "llm_credentials",
                        "reason": (
                            f"{provider} rejected the API key "
                            f"({type(exc).__name__}) — fix the {provider.upper()}"
                            f"_API_KEY in settings; using "
                            f"{base_provider}/{base_model} for this session."
                        ),
                    })
                except Exception:
                    pass  # diagnostics never break the turn
            provider, model = base_provider, base_model
            try:
                from src.agents.cost_router import cost_router as _cr
                _route = getattr(_cr, "_last_route", None)
                if isinstance(_route, dict):
                    _cr._last_route = {**_route, "provider": provider, "model": model, "failed_over": True}
            except Exception:
                pass  # diagnostics never break the turn
            llm = get_llm(provider=provider, model=model, reasoning_config=reasoning_config)
            llm_with_tools = (
                llm if execution_mode == "ask"
                else llm.bind_tools(_resolve_bound_tools(state, config))
            )
            from src.context.cache_preservation import redecorate_for_failover
            messages, _d37_info = redecorate_for_failover(messages)
            call_model = model
            call_llm = llm_with_tools
            if execution_mode != "ask" and configurable.get("execution_phase") in {"deliver", "forced_delivery"}:
                bind_generation = getattr(llm_with_tools, "bind", None)
                if callable(bind_generation):
                    # Provider's stated ceiling (base 6a2717bd), clamped by
                    # any rejection headroom — env knob stays the desired
                    # amount; the hardcoded 8,192 is gone.
                    from src.llm.output_budget import requested_output_cap, take_available_output
                    from src.config.reasoning_config import THINKING_BUDGET_TOKENS

                    # Thinking budget inside max_tokens — same accounting as
                    # the primary delivery bind (field 2026-10-22).
                    _think = 0
                    if (reasoning_config or {}).get("enabled"):
                        _think = THINKING_BUDGET_TOKENS.get(
                            str((reasoning_config or {}).get("effort", "")), 0
                        )
                    allowed = requested_output_cap(model, thinking_tokens=_think)
                    _room = take_available_output(model)
                    if _room:
                        allowed = max(512, min(allowed, _room))
                    call_llm = bind_generation(max_tokens=allowed)
            if budget_exhausted or wrap_summary or final_response_slot or execution_mode == "ask":
                call_llm = llm
                # Failover must also be no-tools safe — strip tool pairs so
                # strict providers don't 400 on "Tool messages found but no
                # tools provided" after redecoration.
                messages = _drop_tool_pairs(messages)
            try:
                # The repair gate needs to know whether THIS call bound tools: the
                # grace/ask path invokes the unbound `llm`, everything else a
                # tools-bound callable (see repair_text_tool_calls `allow`).
                tools_bound = call_llm is not llm
                try:
                    result = _invoke_with_token_pump(
                        call_llm, messages, session_id, provider, model,
                        strip_tool_blocks=tools_bound,
                        reasoning_config=reasoning_config,
                        hold_text=tools_bound,
                    )
                except Exception as _failover_exc:
                    if _is_tool_messages_rejection(_failover_exc):
                        print(
                            f"[failover] tool rejection on failover path ({type(_failover_exc).__name__}); retrying stripped no-tools",
                            flush=True,
                        )
                        _discard_held_answer(session_id)
                        result = _invoke_with_token_pump(
                            llm, _drop_tool_pairs(messages), session_id,
                            provider, model, strip_tool_blocks=False,
                            reasoning_config=reasoning_config,
                        )
                    else:
                        raise
            except TurnCancelledError:
                return {
                    "messages": [AIMessage(
                        content="Operation cancelled by the user.",
                        additional_kwargs={"crusor_cancelled": True},
                    )],
                    "iteration_used": int(state.get("iteration_used", 0)),
                }

    # ── Post-LLM cancellation gate ──────────────────────────────
    # Check immediately after every blocking LLM invocation. If the
    # user pressed Stop while the HTTP request was in flight, the
    # result contains tool_calls that MUST NOT execute. Replace the
    # result with a cancellation message and let should_continue
    # route to finalize (crusor_cancelled=True). Preserve valid
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
                additional_kwargs={"crusor_cancelled": True},
            )],
            "iteration_used": int(state.get("iteration_used", 0)),
        }

    # Hermes-pattern repair: some models emit tool calls as TEXT
    # (<tool_call>NAME<arg_key>...<arg_value>...) instead of structured
    # tool_calls. Parse them so the loop can execute instead of stalling —
    # but ONLY when this call actually bound tools. On the grace/ask call
    # (`call_llm is llm`) the dialect text stays prose and the turn
    # finalizes: hermes' grace law (no tools bound → no actions), field
    # 2026-09-09 @7a7111b9 — post-grace phantom executions otherwise.
    from src.graphs.parallel_tools import repair_text_tool_calls
    result = repair_text_tool_calls(result, allow=tools_bound)

    # Hermes dropped tool-call recovery (conversation_loop.py:8381-8424):
    # Some providers (DeepSeek v4, Claude on Copilot) return
    # finish_reason="tool_calls" with an empty tool_calls array — the model
    # signalled it wanted to act but delivered no call. Re-prompt up to 3
    # times with a nudge so the turn doesn't waste a full provider round-trip.
    if _should_reprompt_dropped_toolcall(
        result, tools_bound, int(state.get("_dropped_toolcall_retries", 0))
    ):
        _dropped_retries = int(state.get("_dropped_toolcall_retries", 0)) + 1
        print(
            f"[ai_node] finish_reason=tool_calls with empty tool_calls "
            f"(retry {_dropped_retries}/3, model={model}) — re-prompting",
            flush=True,
        )
        _nudge = HumanMessage(content=(
            "Your previous turn indicated a tool call but none was "
            "included. Do not narrate a plan or restate intent — issue "
            "the actual tool call now to continue the task."
        ))
        messages_with_nudge = messages + [_nudge]
        # The first attempt is being DISCARDED (it signalled a tool call
        # and delivered none). Its held text dies silently; anything that
        # already streamed live is retracted by exact painted char count,
        # so the re-prompt's answer never glues onto it (field 2026-10-15:
        # 'Hello! How' + the replacement answer).
        _discard_held_answer(session_id)
        try:
            result = _invoke_with_token_pump(
                call_llm, messages_with_nudge, session_id, provider, model,
                strip_tool_blocks=tools_bound, reasoning_config=reasoning_config,
                hold_text=tools_bound,
            )
            result = repair_text_tool_calls(result, allow=tools_bound)
            # Update state for the retry count (carried via additional_kwargs)
            extra = dict(getattr(result, "additional_kwargs", {}) or {})
            extra["_dropped_toolcall_retries"] = _dropped_retries
            try:
                result = result.model_copy(update={"additional_kwargs": extra})
            except AttributeError:
                result.additional_kwargs = extra
        except Exception as _re_nudge_exc:
            print(
                f"[ai_node] dropped-toolcall re-prompt failed "
                f"({type(_re_nudge_exc).__name__}) — continuing with empty",
                flush=True,
            )
    elif tools_bound and not (getattr(result, "tool_calls", None) or []):
        if _finish_reason_is_tool_calls(result) and _result_answer_text(result).strip():
            # The velona/GLM shape: a full text answer wearing a
            # tool_calls finish_reason. Accepted as-is -- re-prompting
            # here double-bills every step (field logs 2026-10-15).
            print(
                "[ai_node] finish_reason=tool_calls with empty tool_calls "
                "but a text answer was delivered -- accepting the answer "
                "(provider mislabels finish_reason; no re-prompt)",
                flush=True,
            )
        # Reset retry counter if we got a non-empty result or gave up
        pass

    # hermes handle_max_iterations tail: the summary response is the turn's
    # FINAL answer — <think> stripped, one retry when empty, honest fallback
    # text. No tool_calls can ride it (repair is disarmed; no tools bound).
    if grace_summary_lap1:
        # For strict providers (Sarvam), the reinvoke must also be text-only.
        # The original lambda used `messages` (full history with tool pairs)
        # which would 400 again if summary text was empty (field 2026-09-12:
        # 10.7s text-only fallback succeeded, but empty summary triggered
        # reinvoke with tool history → 400 → turn FAILED). Use stripped
        # version for reinvoke as well.
        _stripped_for_reinvoke = _drop_tool_pairs(messages)
        result = _finalize_iteration_summary(
            result,
            lambda: _invoke_with_token_pump(
                call_llm, _stripped_for_reinvoke, session_id, provider, model,
                strip_tool_blocks=tools_bound, reasoning_config=reasoning_config,
            ),
        )

    # Hermes refuses to dispatch tool arguments from a token-limited response.
    # Preserve the assistant/tool pairing, but mark the message so SafeToolNode
    # returns an explicit error observation instead of mutating the workspace.
    # The next iteration can split the write or continue with a larger budget.
    completion = provider_response_info(result)
    incomplete_retries = int(state.get("incomplete_response_retries", 0))
    if completion["incomplete"]:
        incomplete_retries += 1
        extra = dict(getattr(result, "additional_kwargs", {}) or {})
        extra["crusor_incomplete_response"] = True
        extra["crusor_incomplete_reason"] = completion["finish_reason"]
        extra["crusor_raw_finish_reason"] = completion["raw_finish_reason"]
        # hermes repetition_guard (agent/repetition_guard.py, issue #86581): a
        # length-cut fragment dominated by verbatim repeats — or, Crusor's
        # documented extension, one dominating word — is a degenerate loop.
        # Discard the partial BEFORE the finish-gate continuation nudge can
        # stitch more of it (hermes incident: a 60k-char turn delivered as 31
        # Discord messages; Crusor field 2026-09-10: a multilingual salad turn
        # streamed into the panel). History keeps the notice, never the slop.
        if is_degenerate_output(str(getattr(result, "content", "") or "")):
            extra["crusor_repetition_dominated"] = True
            print(
                f"[ai_node] repetition-dominated output (finish_reason={completion['finish_reason']}) "
                "— partial discarded, turn ends",
                flush=True,
            )
            try:
                result = result.model_copy(
                    update={"content": REPETITION_DOMINATED_NOTICE, "additional_kwargs": extra}
                )
            except AttributeError:
                result.additional_kwargs = extra
                result.content = REPETITION_DOMINATED_NOTICE
        else:
            try:
                result = result.model_copy(update={"additional_kwargs": extra})
            except AttributeError:
                result.additional_kwargs = extra
    else:
        incomplete_retries = 0
        # Field instrument, no behavior change: hermes' guard scope is the
        # length-truncated path. If a STOP-ended response trips the same
        # predicate, the log says so — that is the datum which decides
        # (owner-visible, never silently) whether the guard scope must grow.
        _text = str(getattr(result, "content", "") or "")
        if len(_text) >= 1500 and is_degenerate_output(_text):
            print(
                "[ai_node] repetition-dominance observed on a stop-ended response (informational)",
                flush=True,
            )

    # =========================================================
    # TRACK TOKEN USAGE
    # =========================================================
    call_usage = TokenTracker.record_call(messages, result, call_model)

    # P3 (Hermes parity): feed the provider's ACTUAL usage back into the
    # session context engine. The engine owns the compaction decision from
    # real numbers (75% of the real window); Crusor's own counting is
    # heuristic for unlisted models, so the provider's figure is the ground
    # truth. Only the MAIN-agent call feeds the engine — the task_manager
    # classifier request is a small planner call, not window pressure.
    # Best-effort telemetry: never break the turn.
    try:
        get_context_engine(config).update_from_response(call_usage.to_dict())
    except Exception:
        pass

    # Law-1 visibility: when the provider reports prompt-cache hits, SAY so —
    # a custom tier re-bills all bound tool schemas per call unless its
    # automatic prefix caching engages; this line is how anyone can SEE
    # whether it does. Silent when the provider reports no cache data.
    if call_usage.cached_tokens > 0 and call_usage.prompt_tokens > 0:
        pct = round(100 * call_usage.cached_tokens / call_usage.prompt_tokens)
        print(
            f"[ai_node] prompt cache: {call_usage.cached_tokens:,} of "
            f"{call_usage.prompt_tokens:,} prompt tokens served from cache ({pct}%)",
            flush=True,
        )

    # Step Tracker: Record step metrics & diagnostics for local inspection
    try:
        from src.runtime.step_tracker import StepTracker
        _tracker = StepTracker.get_tracker(
            session_id,
            workspace_root=str(configurable.get("workspace") or "."),
        )
        _tracker.start_step("ai", state)
        _tracker.record_llm_metrics(
            model=call_model,
            provider=provider,
            input_tokens=call_usage.prompt_tokens,
            output_tokens=call_usage.completion_tokens,
            cached_tokens=call_usage.cached_tokens,
            duration_s=round(time.time() - t_llm_start, 3),
        )
        for _tc in (getattr(result, "tool_calls", None) or []):
            _tracker.record_tool_call(
                name=_tc.get("name", ""),
                args=_tc.get("args", {}),
                status="proposed",
            )
        _tracker.finish_step()
    except Exception:
        pass

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
    # guardrail controller. Copying only the refund into Crusor's 20-call paid
    # harness created an unbounded blind spot: Test5-6 issued four os.walk
    # execute_code inspections without advancing the counter that activates
    # forced delivery. PTC still saves round trips when it batches real work;
    # it is not free when it consumes another provider request.
    next_used = iteration_used + 1

    # Carry dropped-toolcall retry count through state for the re-prompt loop.
    _dtc_retries = int(
        (getattr(result, "additional_kwargs", None) or {}).get(
            "_dropped_toolcall_retries", 0
        )
    )

    # Doom-loop hand-off: if the permission rules would ask (or deny)
    # about a repeated loop, the drop above must not eat the repeats.
    _doom_defers = False
    try:
        from src.context.permission_config import effect_for, load_permission_rules
        _agent = "build"
        if session_id.startswith("sub-"):
            try:
                from src.runtime.subagent_store import get_store
                _row = get_store().get_by_child(session_id)
                _agent = str(getattr(_row, "mode", "") or "") if _row else ""
            except Exception:
                _agent = ""
        _doom_defers = effect_for(
            "doom_loop", ["*"],
            load_permission_rules(str(configurable.get("workspace") or "."), _agent),
        ) != "allow"
    except Exception:
        _doom_defers = False
    result = _drop_repeated_read_calls(result, state, doom_defers=_doom_defers)
    # The kept attempt's held head paints now (answers under the hold cap
    # arrive whole; longer ones already went live mid-generation).
    _release_held_answer(session_id)

    return {
        "messages": [result],
        "token_usage": token_usage,
        "turn_token_usage": turn_token_usage,
        "iteration_used": next_used,
        "incomplete_response_retries": incomplete_retries,
        "grace_done": 1 if (budget_exhausted or final_response_slot) else grace_done,
        "wrap_summary": 1 if (wrap_summary or completion_evidence_ready) else 0,
        "budget_warning_done": 1 if budget_warning_fired else int(
            state.get("budget_warning_done", 0) or 0
        ),
        "_dropped_toolcall_retries": _dtc_retries,
    }




def finalize_node(state: AgentState, config: RunnableConfig):
    # hermes turn_truncation.py: "Unanswered continue nudges made every later
    # turn re-truncate: drop the trail." Recovery nudges are REQUEST-scoped
    # rows for the turn they recover — once the turn ends they must not sit
    # in the transcript shaping every later request (each repeated imperative
    # row biases the next completion toward exactly those imperatives; field
    # 2026-09-10: the degenerate turn looped on the nudges' leading word).
    # Every nudge is tagged at creation (gates.py crusor_nudge); finalize
    # removes all of them, so nothing but real work survives the turn.
    _sweep = [
        RemoveMessage(id=m.id)
        for m in (state.get("messages") or [])
        if getattr(m, "additional_kwargs", {}).get("crusor_nudge")
        and getattr(m, "id", None)
    ]
    last = state.get("messages", [])[-1] if state.get("messages") else None
    if bool(getattr(last, "additional_kwargs", {}).get("crusor_cancelled")):
        try:
            from src.telemetry import call_ledger
            call_ledger.record_run(
                str((config.get("configurable") or {}).get("thread_id") or "default"),
                "cancelled",
            )
        except Exception:
            pass  # telemetry never breaks finalization
        return {
            "task_completed": False,
            "task_status": "cancelled",
            "messages": [AIMessage(content="Operation cancelled by the user."), *_sweep],
        }

    plan = finalize_plan(
        plan=list(state.get("plan", [])),
        task_succeeded=True,
    )

    # Store and judge the resolved interest, not whichever human message was
    # newest. A bare "ok" must not replace the objective, while a substantive
    # correction must be visible to memory, feedback, and completion gates.
    interest = interest_from_state(state)
    current_task = interest.focus_text() or str(
        state.get("current_task") or state.get("latest_instruction", "")
    )
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
    from src.graphs.gates import (
        _any_tool_activity,
        _named_deliverables_exist,
        _produced_code_deliverable,
        _verification_ran_and_passed,
        verification_status as gate_verification_status,
    )
    from src.graphs.progress_helpers import trailing_batch_failed
    # Production routes write_file never sees count too: an app generated
    # in the terminal (`flutter create`) is unverified whenever no fresh
    # passing verification receipt backs it — whether verification ran
    # and failed (field 2026-10-19 run 2) or never ran at all (hard gate,
    # founder 2026-10-20). A bounded escape (verify-nudge/iteration
    # budgets spent) may still end the turn, but it ends HERE, surfaced
    # as unverified — never stamped completed. Non-code artifacts stay
    # exempt via _produced_code_deliverable's code/app bar.
    unverified = (
        _execution_requested_by_interest(state)
        and not _verification_ran_and_passed(state)
        and _produced_code_deliverable(state)
    )
    # Zero Mutation / Empty Execution Check: if the user requested building or
    # executing a task, and the turn finalized with ZERO tool activity at all
    # and no deliverable produced (the model monologued without emitting a
    # single tool call), report as incomplete/failed.
    #
    # Audit 2026-10-12: the check used to fire on "no MUTATION tool ran",
    # which stamped legitimate read-only work incomplete — "verify the test2
    # folder" (two independent field pins) failed here even though reads and
    # commands had run. Mutation-less turns are exactly what read/verify asks
    # look like. The finish gate above already refuses to finalize an
    # execution task with no real work while budget remains; this check now
    # catches only the pure-monologue case it was written for.
    no_work_done = (
        _execution_requested_by_interest(state)
        and not _any_tool_activity(state)
        and not _wrote_code_files(state)
        and not _named_deliverables_exist(state, state.get("workspace", "."))
    )
    # hermes turn-finalizer honesty (turn_finalizer.py::_resolve_budget_fallback
    # records max_iterations_reached(N/M)): a turn that ended because the
    # budget VALVE closed is not a completed task — the grace summary is a
    # checkpoint, not a finish. Without this the terminal frame told the IDE
    # "completed" on cut runs (the ✅ on a run whose own farewell said "I
    # reached the iteration limit"). The plan-complete wrap leg is exempt:
    # that cut fires when the work IS done.
    budget_cut = (
        _budget_exhausted(state)
        and not bool(state.get("wrap_summary"))
    )
    # Hermes turn semantics (field 2026-09-05, "Ended incomplete" on a run
    # whose two tool errors were both long-recovered): failed_steps HISTORY
    # never fails a turn — tool errors are observations the model iterated
    # past. Only a failure still sitting in the trailing tool batch
    # (unrecovered — the model's final act was the failure) or D9-unverified
    # code marks the turn incomplete.
    trailing_failed = trailing_batch_failed(state.get("messages") or [])
    # Nudged-but-never-acted (field 2026-10-19): the finish gate judged an
    # early finish premature and re-prompted for work; every work-demanding
    # nudge records len(messages) at nudge time. If the transcript since
    # the last nudge contains no tool call at all, the announced next step
    # never happened — stamping "completed" lies (Flutter installed and
    # verified, model said "Creating the project now:", turn completed,
    # no project exists). Any tool executed after the nudge — a terminal
    # generator run counts, not just file writes — clears it.
    ended_mid_task = False
    _nudged_at = state.get("nudged_at_msg_count")
    if isinstance(_nudged_at, int) and _nudged_at >= 0:
        _msgs = state.get("messages") or []
        _acted_after_nudge = any(
            getattr(m, "tool_calls", None) for m in _msgs[_nudged_at:]
        )
        ended_mid_task = (
            _execution_requested_by_interest(state) and not _acted_after_nudge
        )
    # Audit 2026-10-12: the verdict is computed ONCE and used for both the
    # returned task_status and the console line. They used to disagree —
    # `no_work_done` flipped task_completed to False while the print still
    # said "done: completed", so the field log contradicted the verdict the
    # UI rendered and nobody could tell which was true.
    verdict = (
        "budget_exhausted" if budget_cut
        else "unverified" if unverified
        else "failed" if (trailing_failed or no_work_done or ended_mid_task)
        else "completed"
    )
    task_succeeded = verdict == "completed"
    try:
        from src.telemetry import call_ledger
        call_ledger.record_run(
            str((config.get("configurable") or {}).get("thread_id") or "default"),
            verdict,
        )
    except Exception:
        pass  # telemetry never breaks finalization
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
        print(
            "[turn] memory store done (degraded=no-op if backend cold)",
            flush=True,
        )
    try:
        engine = get_context_engine(config)
        if trailing_failed or unverified or budget_cut or ended_mid_task:
            engine.record_feedback(success=False, task=current_task)
        else:
            engine.record_feedback(success=True, task=current_task)
    except Exception:
        pass  # Feedback is best-effort; never block finalization


    # Finalize writes NO prose on success. Hermes appends nothing after the
    # model's answer — the streamed words ARE the turn. Our stamp block
    # ("## ✅ Finished: <task> / What I did / Need any tweaks?") was invented
    # voice: the owner called it "hardcoded text at last" (2026-09-04), and it
    # also leaked a STALE task name ("Finished: hi" on a directory-listing
    # turn). Everything it carried now rides structure: the verdict in
    # task_completed/task_status (terminal frame + receipt row), per-step
    # outcomes in the tool cards, suggestions in the `suggestions` event.
    # Only genuine DEVIATIONS keep words here — a budget-hit or
    # unrecovered trailing failure says so (hermes explainer pattern).
    # Unverified code NO LONGER injects a hard-coded stamp: hermes
    # (turn_finalizer.py, conversation_loop.py:8452) keeps the model's words
    # as the transcript and drives a bounded synthetic nudge loop instead;
    # honesty rides `task_status="unverified"` + tool-card receipts.
    lines: list[str] = []
    # Word-boundary truncation (field 2026-09-10: "don't rea" — the 70-char
    # cut landed mid-word and the stamp read like corruption).
    task_display = current_task if current_task else "Task"
    if len(task_display) > 70:
        cut = task_display[:70]
        task_display = cut[:cut.rfind(" ")] if " " in cut[20:] else cut
        task_display = task_display.rstrip(" \t-,.;:!?") + "\u2026"
    did_work = bool(steps_completed or failed_steps or unverified)
    print(
        "[turn] finalize entered: "
        f"steps={len(steps_completed)} failed={len(failed_steps)} "
        f"unverified={unverified} ended_mid_task={ended_mid_task}",
        flush=True,
    )
    if budget_cut:
        # The verdict frame must match the grace farewell: a budget-cut run
        # ends on a checkpoint, and the next user message gets a FRESH budget
        # (safety budgets are turn-scoped), so the stamp names the escape hatch.
        lines.append(f"## ⚠️ Ended on budget: {task_display}")
        lines.append("")
        lines.append(
            "**This run hit its iteration/token budget** and was concluded by "
            "the budget valve — the summary above is a checkpoint of work so "
            "far, not a finished task. Send a follow-up (e.g. \"continue\") "
            "to resume with a fresh budget and full context."
        )
        lines.append("")
    elif did_work and unverified:
        # Hermes parity (D:\hermes\hermes-agent\agent\turn_finalizer.py:546-602,
        # conversation_loop.py:8452-8509): missing verification NEVER appends a
        # hardcoded stamp to the transcript. Hermes keeps the model's own words
        # as the turn answer and, when needed, drives a synthetic
        # `verification_required` loop (max 2 nudges, stripped before persistence).
        # CrusorAI's equivalent loop is gates.finish_gate/should_continue
        # (verify_nudges). The structured verdict `task_status="unverified"` +
        # tool-card receipts carry honesty — no injected markdown.
        pass
    elif did_work and trailing_failed:
        # Only UNRECOVERED failures stamp the transcript (trailing batch):
        # recovered error history shows in the tool cards, hermes-style —
        # the stamp on a recovered run lied ("Ended incomplete" while the
        # agent was mid-work and succeeding).
        lines.append(f"## ⚠️ Ended incomplete: {task_display}")
        lines.append("")
        for failure in failed_steps[-3:]:
            # One tight line each (owner: "needs some discipline" — the old
            # bullet carried the full command AND the tool-output tail,
            # duplicating the tool card in the transcript).
            lines.append(f"- {failure.splitlines()[0][:160]}")
        lines.append("")

    # Reflection stays computed: its suggestions ride the `suggestions`
    # event (below) for UI surfacing; they are never stapled into the
    # transcript as the model's voice.
    from src.context.reflection_engine import ReflectionEngine
    reflector = ReflectionEngine()
    reflection = reflector.reflect(
        task=current_task,
        steps_completed=steps_completed,
        failed_steps=failed_steps,
        plan=plan,
    )

    # Export analytics for dashboard
    from src.agents.cost_router import cost_router
    from src.agents.skill_manager import skill_manager

    # Calculate token usage for emissions
    usage = state.get("token_usage", {})
    cost_known = bool(usage.get("cost_known", True))
    cost_usd = usage.get("estimated_cost_usd", 0) if cost_known else None
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    call_count = usage.get("calls_made", 0)

    _final_thread_id = str(config.get("configurable", {}).get("thread_id", "default"))
    event_bus.emit("analytics.update", {
        "thread_id": _final_thread_id,
        "totalCost": cost_usd,
        "costKnown": cost_known,
        "tokensIn": prompt_tokens,
        "tokensOut": completion_tokens,
        "apiCalls": call_count,
        "model": LLM_MODEL,
        "tier": (getattr(cost_router, "_last_route", None) or {}).get("tier", "standard"),
        "provider": LLM_PROVIDER,
        "skills": len(skill_manager.list_skills()),
    })

    # Floor 6: the observability receipt (env-gated, fail-closed, JSONL).
    # Same shape as the analytics.update above but durable — this is the
    # cost-per-task ledger. Best-effort: never breaks the turn.
    # model/provider come from the TURN's config (the bridge passes
    # per-session provider/model), falling back to the process defaults.
    _turn_cfg = config.get("configurable", {}) or {}
    _turn_model = str(_turn_cfg.get("model") or LLM_MODEL)
    _turn_provider = str(_turn_cfg.get("provider") or LLM_PROVIDER)
    _turn_id = str(_turn_cfg.get("turn_id") or "")
    _duration_s = 0.0
    try:
        from src.runtime.turn_control import turn_controls as _turn_controls
        _elapsed = _turn_controls.turn_elapsed(_final_thread_id)
        if _elapsed is not None:
            _duration_s = round(_elapsed, 3)
    except Exception:
        pass
    _trace = [a for a in (state.get("execution_trace") or []) if isinstance(a, dict)]
    _progress_tool_names = [str(a["tool"]) for a in _trace if a.get("tool")]
    _receipt_tool_names = [
        str(name) for name in (state.get("turn_tool_execution_names") or []) if name
    ]
    _tool_names = _receipt_tool_names or _progress_tool_names
    try:
        _state_execution_count = int(state.get("turn_tool_execution_count", 0) or 0)
    except (TypeError, ValueError):
        _state_execution_count = 0
    # Backward-compatible max: old checkpoints only have execution_trace; new
    # checkpoints retain every ToolMessage receipt, including outcomes filtered
    # from progress/recovery classification.
    _tool_execution_count = max(
        len(_trace),
        len(_receipt_tool_names),
        _state_execution_count,
    )
    try:
        from src.observability import record_turn_receipt
        record_turn_receipt(
            thread_id=_final_thread_id,
            turn_id=_turn_id,
            model=_turn_model,
            provider=_turn_provider,
            input_tokens=int(prompt_tokens or 0),
            output_tokens=int(completion_tokens or 0),
            estimated_cost_usd=float(cost_usd) if cost_usd is not None else None,
            duration_s=_duration_s,
            tool_calls=_tool_execution_count,
            tool_names=_tool_names or None,
            execution_mode=str(state.get("execution_mode") or ""),
            completed=task_succeeded,
            error="; ".join(str(s) for s in (state.get("failed_steps") or [])[:3]),
        )
    except Exception:
        pass

    event_bus.emit("suggestions", {
        "thread_id": _final_thread_id,
        "suggestions": [{"text": s} for s in reflection.get("suggestions", [])],
    })

    # Close the diagnostics report with the same authoritative interest,
    # evidence status, and verdict used by Agent Core.  Earlier reports were
    # exported only mid-step, so they could retain "hello", label proposals as
    # successes, and miss the final verification state entirely.
    try:
        from src.runtime.step_tracker import StepTracker

        _final_text = next(
            (
                str(getattr(message, "content", "") or "")
                for message in reversed(state.get("messages") or [])
                if isinstance(message, AIMessage)
                and str(getattr(message, "content", "") or "").strip()
            ),
            "",
        )
        if lines:
            _final_text = "\n".join(filter(None, [_final_text, "\n".join(lines)]))
        _final_verification = (
            "not_applicable"
            if interest.mode in {"answer", "social"}
            else gate_verification_status(state)
        )
        StepTracker.get_tracker(
            _final_thread_id,
            workspace_root=str(_turn_cfg.get("workspace") or "."),
        ).finalize_report(
            user_ask=current_task,
            final_message=_final_text,
            verification_status=_final_verification,
            receipts={
                "task_status": verdict,
                "tool_execution_count": _tool_execution_count,
                "failed_step_count": len(failed_steps),
            },
        )
    except Exception:
        pass  # diagnostics never alter finalization

    # One verdict, one voice: this line and task_status below cannot disagree.
    print(f"[turn] finalize done: {verdict}", flush=True)
    return {
        "plan": plan,
        "task_completed": task_succeeded,
        "task_status": verdict,
        "messages": ([AIMessage(content="\n".join(lines))] if lines else []) + _sweep,
    }


# ---------------------------------------------------------------------------
# Live token streaming (hermes discipline: the user watches words arrive).
# The pump is attached as a LangChain callback at the AGENT NODE's provider
# invoke ONLY -- planner/classifier/compaction calls never receive it, so
# their tokens can never leak into the transcript. Each completed invoke
# records whether IT streamed into _TURN_LAST_CALL_STREAMED, and stream_agent
# pops that flag at the ai-node boundary: a call that already delivered its
# text token-by-token must not re-emit the full content as one more fake
# chunk. Streaming off (or a provider that never fired tokens) falls back to
# the historical single end-chunk -- nothing is lost either way.
# ---------------------------------------------------------------------------
_TURN_LAST_CALL_STREAMED: dict[str, bool] = {}
# Answer chars each invoke DELIVERED to the client (streamed deltas + the
# buffered flush). When ai_node discards an attempt and re-generates (the
# dropped-toolcall re-prompt, the tool-rejection failover), those chars are
# already painted -- the retract event below is how the replacement attempt
# avoids gluing a second full answer onto the first (field 2026-10-15:
# velona/GLM returns finish_reason=tool_calls with empty tool_calls on
# nearly every reply, so the re-prompt fired constantly and users got 2-3
# concatenated answers).
_TURN_LAST_CALL_TEXT: dict[str, int] = {}


_TURN_PUMPS: dict[str, "_AgentTokenPump"] = {}


def _release_held_answer(thread_id: str) -> None:
    """ai_node kept the attempt: paint anything the pump still holds."""
    pump = _TURN_PUMPS.pop(thread_id, None)
    if pump is not None:
        pump.release_held()


def _discard_held_answer(thread_id: str) -> None:
    """ai_node is regenerating: held text dies silently; anything already
    live (over the hold cap) is retracted by exact painted char count."""
    pump = _TURN_PUMPS.get(thread_id)
    if pump is not None:
        pump.discard_held()
    _retract_streamed_answer(thread_id)


def _retract_streamed_answer(thread_id: str) -> None:
    """Withdraw the previous attempt's painted answer text (char count).

    The client truncates exactly that many chars from the tail of the
    live text, so the re-generated attempt paints into a clean tail.
    Best-effort: a dead bus must not kill the re-generation.
    """
    chars = _TURN_LAST_CALL_TEXT.pop(thread_id, 0)
    if chars <= 0:
        return
    try:
        event_bus.emit("message.agent.retract", {
            "chars": chars,
            "thread_id": thread_id,
        })
    except Exception:
        pass
# Cumulative model-request wall time per thread (hermes turn_usage
 # discipline: the turn receipt must ACCOUNT, not just total — field run
 # 2026-09-09: wall=360.0s while logged model+tool time summed to ~92s and
 # nothing on screen could say where the other 268s went).
_TURN_MODEL_WALL: dict[str, float] = {}


def turn_model_wall(thread_id: str) -> float:
    """Total seconds this thread's turn has spent inside model requests."""
    return _TURN_MODEL_WALL.get(thread_id, 0.0)


# Sub-agent model wall, attributed to the PARENT thread. Children run
# their model calls under their own thread id, so the bridge's
# per-parent read used to count every child model-second as
# "non-model" (founder field 2026-10-16: a 742.3s turn reported
# "model 42.8s, non-model 699.6s" while the child's model calls sat
# invisibly inside the delegate wait). Each settled child's wall is
# popped out of its own bucket exactly once and settled here, so the
# turn receipt can name all three numbers honestly.
_TURN_SUBAGENT_MODEL_WALL: dict[str, float] = {}


def note_subagent_model_wall(parent_thread_id: str, child_thread_id: str) -> float:
    """Settle a finished child's accumulated model wall onto its
    parent's sub-agent bucket. Pop semantics: a resumed child
    transfers each of its runs exactly once."""
    seconds = _TURN_MODEL_WALL.pop(child_thread_id, 0.0)
    if seconds > 0 and parent_thread_id:
        _TURN_SUBAGENT_MODEL_WALL[parent_thread_id] = (
            _TURN_SUBAGENT_MODEL_WALL.get(parent_thread_id, 0.0) + seconds
        )
    return seconds


def pop_turn_model_accounting(thread_id: str) -> tuple[float, float]:
    """(own model seconds, sub-agent model seconds) for the turn that
    just ended — read-and-clear, so a session's second turn is not
    charged for its first (the old cumulative read clamped every
    later turn's non-model remainder to zero)."""
    return (
        _TURN_MODEL_WALL.pop(thread_id, 0.0),
        _TURN_SUBAGENT_MODEL_WALL.pop(thread_id, 0.0),
    )

# Auth-dead providers (hermes-style circuit breaker): a 401 never heals
# mid-session, yet the router kept re-proposing the dead provider on EVERY
# call — each turn paying a doomed request + failover round trip (owner log
# 2026-09-04: three `attempt 1/5 ... 401 Invalid API Key` lines per turn).
# One strike marks the pair; routing skips it until process restart.
_AUTH_DEAD_PROVIDERS: set[tuple[str, str]] = set()


def _mark_auth_dead(provider: str, model: str, exc: BaseException) -> bool:
    """True when `exc` is an authentication failure worth breaking the
    circuit on. Type-name based so no provider SDK import is needed."""
    if f"{type(exc).__name__}" not in {"AuthenticationError", "PermissionDeniedError"}:
        return False
    _AUTH_DEAD_PROVIDERS.add((str(provider or ""), str(model or "")))
    try:
        from src.agents.cost_router import cost_router
        cost_router.mark_dead(provider, model)
    except Exception:
        pass  # diagnostics never break the turn
    return True


from langchain_core.callbacks import BaseCallbackHandler


def _result_answer_text(result: Any) -> str:
    """The answer text of an AIMessage-ish result (str content, or a content
    block list's text parts). Tolerant by design — diagnostics never raise."""
    content = getattr(result, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _result_reasoning_text(result: Any) -> str:
    """Hidden-reasoning text of a buffered response. Two carrier shapes:
    deepseek-style `reasoning_content` on the message/additional_kwargs, and
    inline `<think>…</think>` spans in the content (the shape DeepSeek-style
    routers actually send). Tolerant by design — display extraction never
    raises."""
    additional = getattr(result, "additional_kwargs", None) or {}
    raw = (
        additional.get("reasoning_content")
        or additional.get("reasoning")
        or getattr(result, "reasoning_content", None)
        or ""
    )
    if not (isinstance(raw, str) and raw.strip()):
        # Inline-think shape: pull the spans out of the content. The answer
        # side keeps them stripped via _THINK_BLOCK_RE at the final-emission
        # layer; here we surface the thought itself.
        try:
            content = getattr(result, "content", "")
            if isinstance(content, str) and _THINK_OPEN in content:
                spans = re.findall(
                    r"<think>(.*?)</think>", content, flags=re.DOTALL
                )
                if spans:
                    return "\n".join(s for s in spans).strip()
        except Exception:
            pass
        raw = raw if isinstance(raw, str) else (str(raw) if raw else "")
    return raw


def _flush_unstreamed_answer(pump: "_AgentTokenPump", result: Any, thread_id: str) -> bool:
    """Hermes transport discipline: the transcript must show the answer
    regardless of how the endpoint delivered it. An endpoint that buffered
    the whole completion (field 2026-09-06: 14s answer, zero chunks, EMPTY
    transcript) emits no token events, so the text rode no frame at all.
    Flush the full answer as ONE chunk frame on the exact streaming path —
    never when any answer text already streamed (duplication guard)."""
    if pump.text_chars > 0:
        return False
    text = _result_answer_text(result)
    if not text.strip():
        return False
    if _THINK_OPEN in text:
        # Inline-think routers: the thought rides the content. The Thinking
        # card already got it via _flush_unstreamed_reasoning — the answer
        # frame must carry the reply only (same contract as the live
        # _split_inline_think filter, and as _summary_text_from).
        text = _THINK_BLOCK_RE.sub("", text).strip()
        if not text.strip():
            return False
    if pump.strip_tool_blocks:
        # Same cleaned-text contract as the live stream: blocks the repair
        # layer will consume must not paint the transcript here either —
        # this flush reads the PRE-repair content.
        text = pump._filter_piece(text)
        if not text.strip():
            return False
    try:
        pump._emit_text(text)
        return True
    except Exception:
        return False  # a dead bus must not kill a live turn


def _flush_unstreamed_reasoning(result: Any, thread_id: str) -> bool:
    """The Thinking-card twin of _flush_unstreamed_answer: a buffered call
    carries the model's reasoning ONLY in the response object (no token
    events ever fire), so without this flush the thought is invisible —
    field 2026-09-17: reasoning cards never painted on a non-streaming
    endpoint. One whole-text `reasoning.update` frame (the desktop's
    reasoning frame REPLACES, so single-frame is the correct shape)."""
    text = _result_reasoning_text(result)
    if not text.strip():
        return False
    try:
        event_bus.emit("reasoning.update", {
            "text": text,
            "thread_id": thread_id,
        })
        return True
    except Exception:
        return False  # a dead bus must not kill a live turn


# hermes agent/acp_openai_bridge.py:20 — the taught text-dialect block that
# the repair layer consumes out of a response before display.
_TOOL_BLOCK_OPEN = "<tool_call>"
_TOOL_BLOCK_CLOSE = "</tool_call>"
# Inline-think routers (DeepSeek-style): reasoning inlined in content.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
# Unterminated-block safety valve: past this much swallowed stream text with
# no close tag, the span flushes as display text (a block that size is not a
# tool call; hermes' non-greedy regex would not match it either).
_TOOL_BLOCK_SWALLOW_LIMIT = 65_536


_PARTIAL_ARG_FIELDS = (
    "path", "file_path", "content", "new_text", "old_text",
    "command", "description", "prompt", "query", "pattern", "name", "url",
)


def _partial_json_string(raw: str, field: str) -> str | None:
    """Decode a string field's value-so-far out of half-streamed JSON.

    The arguments object is invalid JSON until the call completes, so
    this scans for `"field": "` and decodes escapes until the closing
    quote or the end of what has arrived (a trailing half-escape is
    dropped, never painted). Returns None when the field has not
    started streaming yet.
    """
    match = re.search(r'"' + re.escape(field) + r'"\s*:\s*"', raw)
    if not match:
        return None
    i = match.end()
    chars: list[str] = []
    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}
    while i < len(raw):
        c = raw[i]
        if c == "\\":
            if i + 1 >= len(raw):
                break
            esc = raw[i + 1]
            if esc == "u":
                if i + 6 > len(raw):
                    break
                try:
                    chars.append(chr(int(raw[i + 2:i + 6], 16)))
                except ValueError:
                    break
                i += 6
                continue
            chars.append(escapes.get(esc, esc))
            i += 2
            continue
        if c == '"':
            break
        chars.append(c)
        i += 1
    return "".join(chars)


def _partial_tool_args(raw: str) -> dict:
    """Lenient snapshot of a streaming tool call's arguments.

    OpenCode renders edit/write cards from the STREAMING input, so the
    card grows while the model is still writing the call. The full
    parse wins whenever the JSON happens to be complete already;
    otherwise the string fields the cards actually read are decoded
    incrementally. Deliberately lossy: the durable tool.call frame
    that follows carries the authoritative arguments.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    out: dict = {}
    for field in _PARTIAL_ARG_FIELDS:
        value = _partial_json_string(raw, field)
        if value is not None:
            out[field] = value
    return out


class _AgentTokenPump(BaseCallbackHandler):
    """Forward the agent node's tokens to the event bus as live deltas.

    REGRESSION FIX (owner desktop run at f414aa02): the pump was duck-typed,
    but LangChain's callback manager reads ``handler.run_inline`` on EVERY
    registered handler (callbacks/manager.py) -- an attribute only
    BaseCallbackHandler carries. Every agent call died with
    "'_AgentTokenPump' object has no attribute 'run_inline'" and burned all
    5 retries. Subclassing the base is the contract, not ceremony.

    ``run_inline = True`` is deliberate: without it the manager dispatches
    each event through ``run_in_executor(copy_context().run, ...)`` and token
    chunks can land OUT OF ORDER -- garbled transcript. Inline delivery keeps
    tokens strictly in provider order. Telemetry discipline: emission
    failures must NEVER break the model call.
    """

    run_inline = True

    # A tools-bound attempt's text is held back until this many chars --
    # past it the text is certainly the answer (pre-tool narration is
    # never this long) and streams live. Under it, ai_node decides the
    # attempt's fate first: kept -> released whole; discarded (re-prompt,
    # tool call, failover) -> dropped silently. Without the hold, a
    # discarded attempt visibly spawns and vanishes (field 2026-10-15).
    _HELD_TEXT_CAP = 160

    def __init__(self, thread_id: str, strip_tool_blocks: bool = False, enable_reasoning: bool = True, hold_text: bool = False):
        self._thread_id = thread_id
        self.enable_reasoning = enable_reasoning
        self.streamed = False
        self._live = not hold_text
        self._held: list[str] = []
        self._held_chars = 0
        self._reasoning_acc = ""
        # Inline-think router (field 2026-09-17: zero Thinking cards on
        # deepseek-v4-flash): DeepSeek-style routers do NOT deliver reasoning
        # as `reasoning_content` chunks — they inline it in the CONTENT as
        # `<think>…</think>` before the answer. State machine:
        self._in_think = False
        self._think_seen = False  # a <think> span was routed this call
        self._think_tag_carry = ""
        # hermes ACP display contract (field 2026-09-09 @7a7111b9, shots 1-2):
        # when the parser consumes a <tool_call> block out of a response, the
        # UI must show cleaned_text — the raw markup never renders (hermes
        # agent/acp_openai_bridge.py: extract_tool_calls_from_text returns
        # ``(tool_calls, cleaned_text)`` and only cleaned_text is displayed).
        # The repair layer runs AFTER the full response, but the pump streams
        # DURING it, so the filter lives here: complete
        # <tool_call>…</tool_call> spans are swallowed from the live chunk
        # stream. Only armed when the call bound tools (the repaired blocks
        # are really consumed); on grace/ask calls the text is the model's
        # own unbound prose and displays as-is, exactly like hermes.
        self.strip_tool_blocks = strip_tool_blocks
        self._carry = ""
        self._in_tool_block = False
        self._swallowed = 0
        # Response receipt (owner run 2026-09-04: a 2:08 "Waiting on the
        # model" spinner had NO telemetry — silence vs slow generation vs
        # tokens-arriving-but-not-rendered were indistinguishable). One
        # honest line per call settles it.
        self._t0 = time.monotonic()
        self.first_token_s: float | None = None
        self.token_count = 0
        self.char_count = 0
        # Answer-text chars only (reasoning excluded): a buffered endpoint
        # leaves this at 0, which is the flush signal in
        # _invoke_with_token_pump (field 2026-09-06: a 14s answer painted
        # NOTHING because the endpoint buffered the whole completion —
        # text reached the transcript only via streamed chunks).
        self.text_chars = 0
        # Streamed tool-call arguments (OpenCode renders edit/write cards
        # from the streaming input): per-chunk-index accumulators fed by
        # AIMessageChunk.tool_call_chunks. Keyed by chunk index; the
        # provider id is captured from whichever chunk carries it.
        self._tool_arg_acc: dict[int, dict] = {}

    def _emit_reasoning(self, piece: str) -> None:
        """Forward a reasoning delta as the ACCUMULATED text.

        The desktop's reasoning frame REPLACES the Thinking text, so each
        update carries reasoning-so-far -- streaming semantics without any
        protocol change. Only fired when the endpoint actually streams
        reasoning_content (deepseek-style) or inline <think> spans; a model
        with none stays silent, which is the honest state.
        """
        self._reasoning_acc += piece
        if not self.enable_reasoning:
            return
        self._think_seen = True  # reasoning already reached the client
        try:
            event_bus.emit("reasoning.update", {
                "text": self._reasoning_acc,
                "thread_id": self._thread_id,
            })
        except Exception:
            pass  # a dead bus must not kill a live generation

    def _mark(self, piece: str) -> None:
        """Receipt counters: first-token latency + chunk/char totals."""
        if self.first_token_s is None:
            self.first_token_s = time.monotonic() - self._t0
        self.token_count += 1
        self.char_count += len(piece)

    def _observe_tool_chunks(self, chunk) -> None:  # noqa: ANN001
        """Accumulate streamed tool-call argument fragments.

        Chat-model chunks carry tool_call_chunks (name + partial args
        JSON string per index); some routers only fill the raw
        additional_kwargs tool_calls deltas. Both shapes feed the same
        accumulator. Emission is throttled by growth — the renderer
        repaints per frame anyway. NEVER raises: a telemetry failure
        must not break the model call (class contract).
        """
        try:
            message = getattr(chunk, "message", None)
            if message is None:
                return
            fragments: list[dict] = []
            chunks = getattr(message, "tool_call_chunks", None) or []
            for entry in chunks:
                if isinstance(entry, dict):
                    fragments.append({
                        "index": entry.get("index", 0) or 0,
                        "id": entry.get("id"),
                        "name": entry.get("name"),
                        "args": entry.get("args"),
                    })
            if not fragments:
                extra = getattr(message, "additional_kwargs", None) or {}
                for entry in extra.get("tool_calls") or []:
                    if not isinstance(entry, dict):
                        continue
                    fn = entry.get("function") or {}
                    fragments.append({
                        "index": entry.get("index", 0) or 0,
                        "id": entry.get("id"),
                        "name": fn.get("name") or entry.get("name"),
                        "args": fn.get("arguments"),
                    })
            for frag in fragments:
                index = frag["index"]
                acc = self._tool_arg_acc.setdefault(
                    index, {"id": None, "name": "", "raw": "", "emitted_len": -1})
                if frag.get("id"):
                    acc["id"] = str(frag["id"])
                if frag.get("name"):
                    acc["name"] = str(frag["name"])
                if isinstance(frag.get("args"), str):
                    acc["raw"] += frag["args"]
                if acc["name"] and (
                    acc["emitted_len"] < 0
                    or len(acc["raw"]) - acc["emitted_len"] >= 96
                ):
                    self._emit_tool_args(index, acc)
        except Exception:
            pass

    def _emit_tool_args(self, index: int, acc: dict) -> None:
        acc["emitted_len"] = len(acc["raw"])
        self.streamed = True
        try:
            event_bus.emit("tool.args", {
                "tool_id": f"{self._thread_id}-{acc['id'] or f'stream-{index}'}",
                "tool_name": acc["name"],
                "tool_args": _partial_tool_args(acc["raw"]),
                "thread_id": self._thread_id,
            })
        except Exception:
            pass

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001, ANN003
        # Flush the final fragments so the card paints the complete
        # input just before the durable tool.call frame lands.
        try:
            for index, acc in self._tool_arg_acc.items():
                if acc["name"] and len(acc["raw"]) != acc["emitted_len"]:
                    self._emit_tool_args(index, acc)
        except Exception:
            pass
        self._tool_arg_acc.clear()

    def on_llm_error(self, error, **kwargs) -> None:  # noqa: ANN001, ANN003
        self._tool_arg_acc.clear()

    def on_llm_new_token(self, token, **kwargs) -> None:  # noqa: ANN001, ANN003
        # Chat models may deliver the chunk payload as the positional string
        # OR as a GenerationChunk on the token/kwarg -- take .text when the
        # positional argument is not itself text.
        # Reasoning deltas ride the chunk's additional_kwargs (reasoning_content
        # on the message or the chunk) -- forward them as live Thinking BEFORE
        # the answer, exactly as hermes' desktop separates thought from reply.
        chunk = kwargs.get("chunk")
        if chunk is not None:
            self._observe_tool_chunks(chunk)
        reasoning_piece = ""
        if chunk is not None:
            extra = getattr(chunk, "additional_kwargs", None) or {}
            raw = extra.get("reasoning_content") or extra.get("reasoning")
            if isinstance(raw, str) and raw and len(raw) > len(self._reasoning_acc) \
                    and raw.startswith(self._reasoning_acc):
                # cumulative payload: take only the new tail
                reasoning_piece = raw[len(self._reasoning_acc):]
            elif isinstance(raw, str) and raw:
                reasoning_piece = raw
            else:
                message = getattr(chunk, "message", None)
                message_extra = getattr(message, "additional_kwargs", None) or {}
                raw = message_extra.get("reasoning_content") or message_extra.get("reasoning")
                if isinstance(raw, str) and raw and len(raw) > len(self._reasoning_acc) \
                        and raw.startswith(self._reasoning_acc):
                    reasoning_piece = raw[len(self._reasoning_acc):]
                elif isinstance(raw, str) and raw:
                    reasoning_piece = raw
        if reasoning_piece:
            self.streamed = True
            self._mark(reasoning_piece)
            self._emit_reasoning(reasoning_piece)

        piece = getattr(token, "text", None)
        if not isinstance(piece, str):
            piece = str(token or "")
        if not piece:
            return
        self.streamed = True
        self._mark(piece)
        if self.strip_tool_blocks:
            piece = self._filter_piece(piece)
        if not piece:
            return
        # Inline-think routers (DeepSeek-style) carry the reasoning INSIDE
        # the content stream. Route it to the Thinking card — the answer
        # must start when the model's reply starts, not with its thoughts.
        piece = self._split_inline_think(piece)
        if piece:
            self._emit_text(piece)

    # Holdback covers any split of the LONGER tag ("</think>" is 8 chars;
    # "<think>" 7). Same discipline as the <tool_call> filter below.
    _THINK_HOLD = 7  # len("</think>") - 1

    def _split_inline_think(self, piece: str) -> str:
        """Route inline <think>…</think> spans to the Thinking card.

        Returns the ANSWER portion of `piece` (may be empty); reasoning is
        accumulated and emitted as reasoning.update frames directly. An
        UNTERMINATED <think> at end-of-stream is flushed by flush_tail() as
        reasoning (a thought that never closed still shows as thought, never
        as answer text).
        """
        carry = self._think_tag_carry + piece
        self._think_tag_carry = ""
        out: list[str] = []
        while True:
            if self._in_think:
                end = carry.find(_THINK_CLOSE)
                if end != -1:
                    self._emit_think(carry[:end])
                    # Same contract as the buffered _THINK_BLOCK_RE
                    # (`</think>\s*`): whitespace after the thought is
                    # router layout, not the answer's leading text.
                    carry = carry[end + len(_THINK_CLOSE):].lstrip()
                    self._in_think = False
                    continue
                # Stay inside the thought; hold back a possible split tag.
                if len(carry) > self._THINK_HOLD:
                    keep = carry[-self._THINK_HOLD:]
                    self._emit_think(carry[:-len(keep)])
                    self._think_tag_carry = keep
                else:
                    self._think_tag_carry = carry
                break
            start = carry.find(_THINK_OPEN)
            if start != -1:
                out.append(carry[:start])
                self._in_think = True
                self._think_seen = True
                carry = carry[start + len(_THINK_OPEN):]
                # Leading newline right after the open tag is layout, not thought.
                carry = carry.lstrip("\r\n") if carry.startswith("\r") or carry.startswith("\n") else carry
                continue
            # No open tag in the free portion. Hold back a tail that could
            # be a split "<think>" tag prefix — SHORT carries can be prefixes
            # too ("<th" + "ink>…" as separate chunks). Bounded holdback:
            # flush_tail releases it as answer text if the tag never closes.
            if "<" in carry:
                keep = carry[-self._THINK_HOLD:] if len(carry) > self._THINK_HOLD else carry
                if len(carry) > len(keep):
                    out.append(carry[:-len(keep)])
                self._think_tag_carry = keep
            else:
                out.append(carry)
            break
        return "".join(out)

    def _emit_think(self, piece: str) -> None:
        """Accumulate + forward one inline-think delta (accumulated text —
        the desktop's reasoning frame REPLACES)."""
        if not piece:
            return
        self.streamed = True
        self._mark(piece)
        self._emit_reasoning(piece)

    def _filter_piece(self, piece: str) -> str:
        """Swallow complete <tool_call>…</tool_call> spans from the stream,
        holding back only possible partial-tag tails at piece boundaries
        (`<tool_call>` is 11 chars, `</tool_call>` is 12 — a 10-char holdback
        covers any split). An UNTERMINATED block is not consumable (hermes'
        block regex would not match it either), so past a bounded swallow
        limit it flushes as ordinary text."""
        self._carry += piece
        out: list[str] = []
        while True:
            if self._in_tool_block:
                end = self._carry.find(_TOOL_BLOCK_CLOSE)
                if end != -1:
                    self._carry = self._carry[end + len(_TOOL_BLOCK_CLOSE):]
                    self._in_tool_block = False
                    self._swallowed = 0
                    continue
                hold = len(_TOOL_BLOCK_CLOSE) - 1
                if len(self._carry) > hold:
                    self._swallowed += len(self._carry) - hold
                    if self._swallowed > _TOOL_BLOCK_SWALLOW_LIMIT:
                        # unterminated: re-emit the open tag we swallowed so
                        # the display shows the stream as it arrived.
                        out.append(_TOOL_BLOCK_OPEN + self._carry)
                        self._carry = ""
                        self._in_tool_block = False
                        self._swallowed = 0
                        break
                    self._carry = self._carry[-hold:]
                break
            start = self._carry.find(_TOOL_BLOCK_OPEN)
            if start != -1:
                out.append(self._carry[:start])
                self._carry = self._carry[start + len(_TOOL_BLOCK_OPEN):]
                self._in_tool_block = True
                self._swallowed = 0
                continue
            hold = len(_TOOL_BLOCK_OPEN) - 1
            if len(self._carry) > hold:
                out.append(self._carry[:-hold])
                self._carry = self._carry[-hold:]
            break
        return "".join(out)

    def flush_tail(self) -> str:
        """End-of-stream: anything still held was NOT a consumed block (an
        unclosed <tool_call> is not parseable — the repair layer ignores it,
        hermes' block regex would not match it either), so it displays as
        text. Bounded: the holdback is at most one partial-tag length.
        Returns what was flushed (tests assert on it; callers ignore).

        Inline-think discipline: a held-back answer tail flushes as answer
        text; a thought that never closed flushes as REASONING (never
        answer), matching the model's own production order. The THINK
        filter sits DOWNSTREAM of the TOOL filter, so the tool holdback
        releases THROUGH the think filter — tag-split spans still route."""
        flushed = ""
        tool_tail, self._carry = self._carry, ""
        if tool_tail:
            routed = self._split_inline_think(tool_tail)
            if routed:
                self._emit_text(routed)
                flushed += routed
        think_tail, self._think_tag_carry = self._think_tag_carry, ""
        if self._in_think:
            # Unterminated <think>: everything still held is thought.
            self._in_think = False
            self._emit_think(think_tail)
        elif think_tail:
            flushed += think_tail
            self._emit_text(think_tail)
        self._in_tool_block = False
        return flushed

    def _emit_text(self, piece: str) -> None:
        self.text_chars += len(piece)
        if not self._live:
            self._held.append(piece)
            self._held_chars += len(piece)
            if self._held_chars >= self._HELD_TEXT_CAP:
                self.release_held()
            return
        try:
            event_bus.emit("message.agent.chunk", {
                "chunk": piece,
                "thread_id": self._thread_id,
            })
        except Exception:
            pass  # a dead bus must not kill a live generation

    @property
    def painted_chars(self) -> int:
        """Chars that actually reached the client (held text has not)."""
        return self.text_chars - self._held_chars

    def release_held(self) -> None:
        """The attempt is the answer: paint the held head, stream the rest."""
        self._live = True
        if not self._held:
            return
        text = "".join(self._held)
        self._held = []
        self._held_chars = 0
        try:
            event_bus.emit("message.agent.chunk", {
                "chunk": text,
                "thread_id": self._thread_id,
            })
        except Exception:
            pass

    def discard_held(self) -> None:
        """The attempt is being regenerated: its held text never paints."""
        self._held = []
        self._held_chars = 0


def _est_tokens(text: str) -> int:
    """chars//4 token estimate — the house heuristic (context_breakdown)."""
    return (len(text) + 3) // 4


def _request_anatomy(messages, call_llm) -> dict:
    """What one model request is MADE OF (Phase 1 diet measurement).

    Buckets by message role; the bound tool schemas ride the llm binding,
    not the messages — introspected defensively (RunnableBinding kwargs),
    None -> omitted rather than guessed. Estimates, labelled as such;
    provider-reported input_tokens on the same ledger line is the billed
    truth the diet is judged against.
    """
    import json as _json

    buckets = {"sys_tokens": 0, "user_tokens": 0, "ai_tokens": 0, "tool_result_tokens": 0}
    total = 0
    for message in messages or []:
        role = getattr(message, "type", "") or ""
        content = getattr(message, "content", "")
        text = content if isinstance(content, str) else str(content)
        size = _est_tokens(text)
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            try:
                size += _est_tokens(_json.dumps(calls, ensure_ascii=False, default=str))
            except Exception:
                pass
        total += size
        if role == "system":
            buckets["sys_tokens"] += size
        elif role == "human":
            buckets["user_tokens"] += size
        elif role == "ai":
            buckets["ai_tokens"] += size
        elif role == "tool":
            buckets["tool_result_tokens"] += size
        else:
            buckets["user_tokens"] += size
    buckets["req_tokens_est"] = total
    try:
        # Walk proxy/binding layers (RetryLLMProxy -> RunnableBinding) the
        # way llm.factory._nested_runnable_attr does until the binding
        # that carries the tools shows up.
        current, seen = call_llm, set()
        for _ in range(8):
            if current is None or id(current) in seen:
                break
            seen.add(id(current))
            bound = getattr(current, "kwargs", None) or {}
            tools = bound.get("tools") if isinstance(bound, dict) else None
            if tools:
                buckets["tools_schema_tokens"] = _est_tokens(
                    _json.dumps(tools, ensure_ascii=False, default=str)
                )
                break
            current = getattr(current, "bound", None) or getattr(current, "_llm", None)
    except Exception:
        pass
    return buckets


def _invoke_with_token_pump(
    call_llm, messages, thread_id: str, provider: str = "", model: str = "",
    strip_tool_blocks: bool = False, reasoning_config: dict | None = None,
    hold_text: bool = False,
):
    """Agent-node invoke with the live token pump attached (best-effort).

    The pump rides in `config.callbacks`, which LangChain forwards to the
    underlying provider client -- through RetryLLMProxy's **kwargs pass-
    through -- so only THIS call streams. Providers that reject the config
    kwarg (defensive) fall back to a plain invoke with no pump.

    `strip_tool_blocks` arms the pump's cleaned-text filter for calls whose
    <tool_call> text blocks the repair layer will consume (tools bound);
    hermes' ACP bridge displays cleaned_text, never the raw markup.

    On completion, one receipt line: total wall time, first-token latency
    and whether anything actually streamed. The owner's "Waiting on the
    model 2:08" (2026-09-04) was unattributable — this line makes the next
    one self-diagnosing: first token ~0.x s = endpoint fine, renderer blind;
    first token ~120 s = endpoint slow/silent (stall budget owns it);
    "non-streaming" = streaming got disabled upstream.
    """
    enable_reasoning = bool(reasoning_config and reasoning_config.get("enabled", False))
    pump = _AgentTokenPump(
        thread_id,
        strip_tool_blocks=strip_tool_blocks,
        enable_reasoning=enable_reasoning,
        hold_text=hold_text,
    )
    _TURN_PUMPS[thread_id] = pump
    _model_t0 = time.monotonic()
    try:
        result = call_llm.invoke(messages, config={"callbacks": [pump]})
    except TypeError:
        result = call_llm.invoke(messages)
    except Exception as _call_exc:
        _TURN_LAST_CALL_STREAMED[thread_id] = pump.streamed
        _TURN_LAST_CALL_TEXT[thread_id] = pump.painted_chars
        # Failed requests cost wall time too — account before re-raising.
        _TURN_MODEL_WALL[thread_id] = _TURN_MODEL_WALL.get(thread_id, 0.0) + (
            time.monotonic() - _model_t0
        )
        try:
            from src.telemetry import call_ledger
            call_ledger.record_call(
                thread_id, provider, model,
                time.monotonic() - _model_t0,
                streamed=pump.streamed, error=type(_call_exc).__name__,
            )
        except Exception:
            pass  # telemetry never breaks the call
        raise
    _TURN_LAST_CALL_STREAMED[thread_id] = pump.streamed
    _TURN_MODEL_WALL[thread_id] = _TURN_MODEL_WALL.get(thread_id, 0.0) + (
        time.monotonic() - _model_t0
    )
    try:
        from src.telemetry import call_ledger
        _usage = provider_response_info(result)
        call_ledger.record_call(
            thread_id, provider, model,
            time.monotonic() - _model_t0,
            input_tokens=_usage.get("input_tokens"),
            output_tokens=_usage.get("output_tokens"),
            total_tokens=_usage.get("total_tokens"),
            reasoning_chars=int(_usage.get("reasoning_chars") or 0),
            streamed=pump.streamed,
            provider_cost=_usage.get("reported_cost"),
            anatomy=_request_anatomy(messages, call_llm),
            tool_names=_usage.get("tool_names"),
        )
    except Exception:
        pass  # telemetry never breaks the call
    if enable_reasoning and not pump._think_seen:
        # Streamed but thought-less: some routers carry reasoning only on the
        # AGGREGATED response (reasoning_content), never on chunks. Flush it
        # FIRST (thought precedes the reply) so the Thinking card paints even
        # on this shape; when the pump DID route inline think, this is a
        # no-op (no duplicate card).
        _flush_unstreamed_reasoning(result, thread_id)
    # Any held-back display text (partial-tag tail, or an unterminated block
    # that repair will NOT consume) flushes before the receipt line.
    pump.flush_tail()
    _TURN_LAST_CALL_TEXT[thread_id] = pump.painted_chars
    try:
        route = f"{provider}/{model}" if provider else "llm"
        total = time.monotonic() - pump._t0
        if pump.streamed:
            ft = pump.first_token_s if pump.first_token_s is not None else total
            shape = ""
            # Pseudo-stream detection: a real stream lands many small chunks;
            # an endpoint that buffers the whole generation and emits one SSE
            # event shows up as a tiny chunk count with real text volume
            # (owner run 2026-09-04: "first token 8.1s, 1 chunks streamed").
            # Name it — the fix lives on the endpoint, not in the panel.
            if pump.token_count <= 2 and pump.char_count >= 200:
                shape = " [buffered: endpoint sent the whole answer as one chunk]"
            _reasoned = len(pump._reasoning_acc)
            _rshape = (
                f", reasoning streamed live ({_reasoned} chars)"
                if _reasoned and pump._think_seen
                else ", no live reasoning deltas (aggregated-only or none)"
            )
            print(
                f"[ai_node] {route} answered in {total:.1f}s "
                f"(first token {ft:.1f}s, {pump.token_count} chunks streamed)"
                f"{shape}{_rshape}",
                flush=True,
            )
        else:
            # A genuinely buffered call (streaming disabled upstream, or the
            # endpoint answered stream:true with one body — the receipt's
            # [buffered] marker names that shape). NO speculative retry here:
            # a second generation double-bills every call on a lane that
            # never streams (field 2026-09-17 v.txt: the probe fired a hidden
            # ChatGroq request inside test fakes) and violates the hermes
            # single-retry-owner discipline — RetryLLMProxy owns retries.
            # Words-arrive-as-words is the factory's job (streaming defaults
            # per provider); the transport contract here is only that the
            # answer PAINTS regardless of delivery mode.
            # The buffered reasoning flushes BEFORE the answer: thought
            # precedes the reply in the model's own production order, and the
            # desktop closes the Thinking card the moment the answer starts.
            _flush_unstreamed_reasoning(result, thread_id)
            flushed = _flush_unstreamed_answer(pump, result, thread_id)
            if flushed:
                _TURN_LAST_CALL_TEXT[thread_id] = pump.painted_chars
                # The flag means "this call's text already reached the client"
                # — the stream-loop fallback (final_response emission) must
                # not re-emit the same answer (double paint).
                _TURN_LAST_CALL_STREAMED[thread_id] = True
            note = " — answer flushed to the UI as one frame" if flushed else ""
            print(
                f"[ai_node] {route} answered in {total:.1f}s "
                f"(non-streaming response{note})",
                flush=True,
            )
    except Exception:
        pass  # telemetry never breaks the call
    return result


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
_CLASSIFIER_ROUTE_LOGGED = threading.Event()


def _task_manager_llm(provider: str, model: str):
    """Task classification is MANAGEMENT-class work (short structured
    output, not user-facing prose): route it to the auxiliary client
    (D21) under an env-driven LATENCY BUDGET -- the hermes auxiliary
    discipline (issue #54465: hidden retries silently multiply wall time
    on slow endpoints; their answer was owned retries + deadlines, never
    a message-text shortcut). Resolution and budget are read PER CALL:
      - route: AUX_LLM_PROVIDER/AUX_LLM_MODEL env -> per-provider cheap
        table -> main-model fallback (hermes' own documented fallback:
        "a blocked pick is refused, let the caller keep the main model")
      - CRUSORAI_CLASSIFIER_ATTEMPTS  (default 1, clamp 1..5)
      - CRUSORAI_CLASSIFIER_TIMEOUT_S (default 10, clamp 2..120)
    The resolved route + budget print ONCE per process: a deployment whose
    classifier is silently riding the heavyweight main model sees it in
    one boot line instead of paying it invisibly every turn."""
    from src.config.settings import resolve_aux_llm

    import os as _os

    def _clamp(name: str, default: int, lo: int, hi: int) -> int:
        try:
            raw = _os.getenv(name)
            if raw is None or not str(raw).strip():
                return default
            return max(lo, min(hi, int(str(raw).strip())))
        except Exception:
            return default

    attempts = _clamp("CRUSORAI_CLASSIFIER_ATTEMPTS", 1, 1, 5)
    timeout_s = float(_clamp("CRUSORAI_CLASSIFIER_TIMEOUT_S", 10, 2, 120))

    try:
        aux_provider, aux_model = resolve_aux_llm()
    except Exception:
        aux_provider, aux_model = provider, model

    if not _CLASSIFIER_ROUTE_LOGGED.is_set():
        _CLASSIFIER_ROUTE_LOGGED.set()
        if _os.getenv("AUX_LLM_MODEL"):
            source = "env"
        elif aux_model != model:
            source = "cheap-table"
        else:
            source = "main-fallback (set AUX_LLM_MODEL for a fast route)"
        print(
            f"[task_classifier] route {aux_provider}/{aux_model} "
            f"(source: {source}); budget {attempts} attempt(s) x {timeout_s:.0f}s",
            flush=True,
        )

    try:
        return get_llm(
            provider=aux_provider, model=aux_model,
            max_attempts=attempts, request_timeout=timeout_s,
        )
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
# CRUSORAI_TASK_CLASSIFIER=llm restores always-LLM behavior.

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
    LLM exactly like before. Kill-switch: CRUSORAI_TASK_CLASSIFIER=llm.
    """
    if os.environ.get("CRUSORAI_TASK_CLASSIFIER", "").strip().lower() == "llm":
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


def _cfg(configurable: dict, key: str, default=None):
    """Read a graph-configurable value with a fallback.

    The CLI/bridge entrypoints populate ``config.configurable`` with
    ``provider``, ``model``, ``workspace`` and friends. The AG-UI endpoint
    (``src/server.py``) is driven by a frontend and carries only LangGraph's
    own keys, so hard indexing raises ``KeyError`` there. Every read of a
    non-required configurable goes through this helper so both entrypoints
    behave identically.
    """
    value = (configurable or {}).get(key)
    return default if value is None else value


def _latest_instruction_from_messages(messages: list) -> str:
    """Derive the current instruction from the trailing HumanMessage.

    The CLI and bridge entrypoints set ``latest_instruction`` explicitly when
    they invoke the graph. The AG-UI endpoint (``src/server.py``) is driven by
    a frontend that sends only ``messages``, so the field is absent there and
    ``task_manager_node`` must derive it instead of raising KeyError.
    """
    for message in reversed(list(messages or ())):
        if getattr(message, "type", None) == "human":
            content = getattr(message, "content", "")
            if isinstance(content, list):
                # Multimodal content blocks: keep the text parts only.
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(str(block.get("text", "")))
                    else:
                        parts.append(str(block))
                content = " ".join(parts)
            return (content or "").strip()
    return ""


def _salvage_task_decision(text: str) -> "TaskDecision | None":
    """Parse a TaskDecision out of whatever the model ACTUALLY said.

    Owner desktop run: `auto/best-chat` answered the classification prompt
    with the literal word `unrelated` -- semantically PERFECT, syntactically
    not JSON -- and with_structured_output raised, burning 5 proxy retries on
    a permanently-failing parse before the turn died. The router's whole job
    is one of three words; accept them in ANY wrapper: bare prose, JSON, or
    JSON fenced inside chatter. Returns None only when nothing salvageable
    is present.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    import json as _json
    import re as _re

    # direct JSON or an embedded {...} block
    candidates = [raw]
    match = _re.search(r"\{.*\}", raw, _re.S)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = _json.loads(candidate)
            if isinstance(data, dict):
                action = str(data.get("action") or data.get("classification")
                             or data.get("type") or data.get("status") or "").strip().lower()
                if action in {"new", "continue", "unrelated"}:
                    return TaskDecision(
                        action=action,  # type: ignore[arg-type]
                        updated_task=data.get("updated_task") or None,
                    )
        except Exception:
            continue

    # bare action word (the owner's exact case), case/punctuation tolerant
    word = _re.sub(r"[^a-z]", "", raw.lower())
    if word in {"new", "continue", "unrelated"}:
        return TaskDecision(action=word)  # type: ignore[arg-type]
    # the action named anywhere in a short prose answer ("This is unrelated
    # to the current task") -- only trusted for SHORT replies so a chatty
    # essay mentioning 'new' cannot hijack the task
    if len(raw) <= 200:
        for action in ("unrelated", "continue", "new"):
            if _re.search(rf"\b{action}\b", raw.lower()):
                return TaskDecision(action=action)  # type: ignore[arg-type]
    return None


def _invoke_task_decision(llm, task_messages) -> "TaskDecision":
    """Classifier invoke that can NEVER fail the turn on a parse.

    The strict with_structured_output path couples a prose-obedient model's
    normal answer to a JSON ValidationError, which RetryLLMProxy then
    faithfully retries 5x (a permanently failing call) before the graph
    crashes. This lane invokes RAW (transport retries still cover real
    network faults), salvages the answer, and -- only when nothing is
    salvageable -- falls back to the SAFE default: 'continue' preserves the
    active task, which is exactly what a mis-routed conversational message
    should do. One honest line on the true fallback; never silent.
    """
    try:
        result = llm.invoke(task_messages)
    except Exception as exc:
        # Budget exhaustion / transport death on the ROUTER must never kill
        # the MISSION (hermes: aux failure degrades that side task, the turn
        # proceeds). Cancellation still propagates -- a Stop is not a fault.
        from src.llm.factory import TurnCancelledError

        if isinstance(exc, TurnCancelledError):
            raise
        print(
            "[task_classifier] route unavailable "
            f"({type(exc).__name__}); defaulting to 'continue' "
            "(active task preserved)"
        )
        return TaskDecision(action="continue")
    content = getattr(result, "content", "")
    if not isinstance(content, str):
        content = "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict)
        ) if isinstance(content, list) else str(content)
    salvaged = _salvage_task_decision(content)
    if salvaged is not None:
        return salvaged
    print(
        "[task_classifier] unparseable classification answer; "
        "defaulting to 'continue' (active task preserved)"
    )
    return TaskDecision(action="continue")


def task_manager_node(
    state: AgentState,
    config: RunnableConfig,
):
    configurable = config.get("configurable", {}) or {}

    from src.config.settings import LLM_PROVIDER as _DF_PROVIDER, LLM_MODEL as _DF_MODEL
    provider = configurable.get("provider") or _DF_PROVIDER
    model = configurable.get("model") or _DF_MODEL

    current_task = state.get("current_task", "")
    # AG-UI entrypoints supply only `messages`; derive the instruction instead
    # of KeyError-ing (the CLI/bridge still set it explicitly).
    latest_instruction = state.get("latest_instruction") or _latest_instruction_from_messages(
        state.get("messages") or []
    )

    def _interest(objective: str, relationship: str) -> dict[str, Any]:
        """Resolve schema-v1 intent state without another provider call."""
        return resolve_user_interest(
            previous=state.get("user_interest"),
            objective=objective,
            latest_instruction=latest_instruction,
            relationship=relationship,  # type: ignore[arg-type]
        ).to_state()

    if (
        is_plan_cancellation(latest_instruction)
        and state.get("plan_created")
        and state.get("plan")
    ):
        return {
            "current_task": "",
            "latest_instruction": latest_instruction,
            "user_interest": _interest("", "cancelled"),
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
            **_turn_scoped_resets(),
            "workspace": config["configurable"].get("workspace", "."),
        }

    if (
        is_plan_approval(latest_instruction)
        and state.get("plan_created")
        and state.get("plan")
    ):
        approved_task = state.get(
            "plan_goal",
            state.get("current_task", ""),
        )
        return {
            "execution_mode": "agent",
            "plan_approved": True,
            "task_action": "execute_approved_plan",
            "current_task": approved_task,
            "latest_instruction": latest_instruction,
            "user_interest": _interest(approved_task, "continue"),
            "token_usage": state.get("token_usage", _zero_token_usage()),
            **_turn_scoped_resets(),
            "workspace": config["configurable"].get("workspace", "."),
        }

    if is_plan_approval(latest_instruction):
        return {
            "task_action": "approval_without_plan",
            "task_status": "idle",
            "plan_approved": False,
            "latest_instruction": latest_instruction,
            "user_interest": _interest(current_task, "continue"),
            "token_usage": state.get("token_usage", _zero_token_usage()),
            **_turn_scoped_resets(),
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
            "user_interest": _interest(current_task, "corrects"),
            "token_usage": state.get("token_usage", _zero_token_usage()),
            **_turn_scoped_resets(),
        }

    # First turn: there is no previous active task.
    if not current_task:
        return {
            "current_task": latest_instruction,
            "latest_instruction": latest_instruction,
            "user_interest": _interest(latest_instruction, "new"),
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
            **_turn_scoped_resets(),
            "workspace": config["configurable"].get("workspace", "."),
        }

    # D30 (§46): slam-dunk messages classified for free — ack => continue
    # (task text unchanged), explicit reset => new. Only these two shapes;
    # everything else pays the aux LLM below, exactly like before. (Note:
    # the aux client is constructed AFTER this check — a quick-path turn
    # costs zero LLM anything, not even client setup.)
    quick = _quick_task_decision(current_task, latest_instruction)
    if quick is None:
        # The central interest resolver has one more deterministic reset that
        # the text-only D30 helper cannot see: a substantive instruction after
        # a social/phatic objective (for example, `hello` then `Create ...`).
        # Treat that resolved replacement as a genuinely new task so stale
        # steps, failures, plans, and receipts from the greeting are reset too.
        # This remains zero-provider-call and also covers explicit multi-line
        # `New task:` messages that the conservative one-line quick path skips.
        resolved = _interest(current_task, "undetermined")
        if resolved.get("relationship") == "replaces":
            quick = (
                "new",
                str(resolved.get("objective") or latest_instruction),
            )
    if quick is not None:
        action, updated_task = quick
        if action == "new":
            return {
                "current_task": updated_task,
                "latest_instruction": latest_instruction,
                "user_interest": _interest(updated_task, "replaces"),
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
                # Every retry/nudge valve is turn-scoped. Without this reset,
                # a resumed task inherits whichever channels the prior turn
                # spent and behaves differently for the same instruction.
                **_turn_scoped_resets(),
                "workspace": config["configurable"].get("workspace", "."),
            }
        # A normal acknowledgement changes no user-interest field. LangGraph
        # preserves the existing contract from state, and keeping this return
        # minimal retains the zero-cost D30 fast-path API. The one exception is
        # resuming after an unrelated turn: restore the active objective's mode
        # so the unrelated answer cannot strand the session in read-only state.
        quick_update = {
            "current_task": updated_task,
            "task_action": action,
            "token_usage": state.get("token_usage", _zero_token_usage()),
            # A bare ack/continue gets every turn-local valve back, not only
            # the token-iteration budget.
            **_turn_scoped_resets(),
            "workspace": config["configurable"].get("workspace", "."),
        }
        prior_interest = _stored_user_interest(state)
        if prior_interest is not None and prior_interest.relationship == "unrelated":
            quick_update["latest_instruction"] = latest_instruction
            quick_update["user_interest"] = _interest(updated_task, "continue")
        return quick_update

    # ── Pre-LLM cancellation gate (task_manager) ──────────────
    session_id_tm = str(configurable.get("thread_id") or "default")
    from src.runtime.turn_control import turn_controls as _tc_tm
    if _tc_tm.cancelled(session_id_tm):
        return {
            "current_task": current_task,
            "latest_instruction": latest_instruction,
            "user_interest": _interest(current_task, "continue"),
            "task_action": "cancelled",
            "task_status": "cancelled",
            "task_completed": False,
            "token_usage": state.get("token_usage", _zero_token_usage()),
            **_turn_scoped_resets(),
            "workspace": config["configurable"].get("workspace", "."),
        }

    # Hermes pipeline parity (run_conversation): ZERO model calls before the
    # main one — in EVERY mode, unless the owner opts back in with
    # CRUSORAI_TASK_CLASSIFIER=on (read per call). Field proof (agent-mode
    # run): "hello" paid a classifier round-trip that returned an
    # UNPARSEABLE answer and would have been used only as "continue" anyway;
    # the free D30 quick decision above already owns acks and explicit
    # resets. A new-task instruction still lands: the main model sees it and
    # acts; only the task label may lag, which recovery/finalize reconcile.
    classifier_mode = os.environ.get("CRUSORAI_TASK_CLASSIFIER", "").strip().lower()
    if classifier_mode != "on":
        return {
            "current_task": current_task,
            "latest_instruction": latest_instruction,
            # The optional relationship classifier is disabled, so report
            # that uncertainty honestly while still preserving this steering
            # for the main model.  No extra provider round trip is introduced.
            "user_interest": _interest(current_task, "undetermined"),
            "task_action": "continue",
            "task_status": "in_progress",
            "task_completed": False,
            "token_usage": state.get("token_usage", _zero_token_usage()),
            **_turn_scoped_resets(),
            "workspace": config["configurable"].get("workspace", "."),
        }

    llm = _task_manager_llm(provider, model)

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

    decision = _invoke_task_decision(llm, task_messages)

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
            "latest_instruction": latest_instruction,
            "user_interest": _interest(updated_task, "replaces"),
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
            **_turn_scoped_resets(),
            # Preserve the classifier call in this turn's metering after the
            # generic zeroed reset above.
            "turn_token_usage": _merge_token_usage({}, [call_usage]),
            "workspace": config["configurable"].get("workspace", "."),
        }

    return {
        "current_task": updated_task,
        "latest_instruction": latest_instruction,
        "user_interest": _interest(updated_task, decision.action),
        "task_action": decision.action,
        "task_status": "in_progress",
        "task_completed": False,
        "token_usage": token_usage,
        **_turn_scoped_resets(),
        "turn_token_usage": _merge_token_usage({}, [call_usage]),
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
    plan_created = bool(state.get("plan_created", False))
    steps_completed = list(state.get("steps_completed", []))
    failed_steps = list(state.get("failed_steps", []))
    execution_trace = list(state.get("execution_trace", []))
    recovery_attempts = state.get("recovery_attempts", 0)
    recovery_mode = state.get("recovery_mode", False)
    tool_failures = state.get("tool_failures", 0)
    recovery_command = state.get("recovery_command")
    replan_needed = False  # hermes: no engine re-plan consult exists
    env_failures = state.get("env_failures", 0)
    total_usage = TokenUsage.from_dict(state.get("token_usage", {}))
    command_retries = dict(state.get("command_retries", {}))
    turn_tool_execution_count = int(state.get("turn_tool_execution_count", 0) or 0)
    # _turn_scoped_resets deliberately keeps its exact historical return shape.
    # Its existing execution counter is the turn epoch: zero means any guard
    # carried by a resumed checkpoint belongs to the prior user turn and must
    # be discarded before the first new tool outcome is sampled.
    tool_cycle_guard = (
        dict(state.get("tool_cycle_guard") or {})
        if turn_tool_execution_count > 0
        else {}
    )
    tool_cycle_history = list(tool_cycle_guard.get("history") or [])
    turn_tool_execution_names = [
        str(name) for name in (state.get("turn_tool_execution_names") or [])
    ]

    latest_tools = ph.latest_tool_messages(messages)
    injected: list = []
    processed_tools = 0

    for message in latest_tools:
        tool_name = message.name or "unknown_tool"
        result = str(message.content)
        tool_args = ph.find_tool_args(messages, message.tool_call_id)

        # Receipt accounting is broader than progress accounting.  B/E desktop
        # evidence at 1e05cc02 exposed the distinction: informational and
        # unavailable tools really executed but classify_tool_outcome correctly
        # omits them from execution_trace so they do not arm recovery.  Keep a
        # separate turn-scoped ledger for final reports/observability.
        turn_tool_execution_count += 1
        turn_tool_execution_names.append(tool_name)

        outcome = ph.classify_tool_outcome(tool_name, result)
        if outcome == ph.OUTCOME_SKIP:
            continue  # no success/failure progress row

        processed_tools += 1
        failed = outcome == ph.OUTCOME_FAILED

        # Trace comes before memory/failure/success handling (pre-D9 order).
        execution_trace.append(
            ph.make_trace_entry(tool_name, tool_args, result, failed)
        )
        tool_cycle_history = ph.append_tool_cycle_sample(
            tool_cycle_history,
            ph.tool_cycle_sample(
                tool_name,
                tool_args,
                result,
                failed=failed,
            ),
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
                _active_interest_text(state),
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
            # Hermes pipeline shape (verified: hermes has NO replanner
            # component and no plan-LLM consult anywhere in the loop — the
            # model adapts from the failure receipt in context, exactly as
            # it adapts to every other tool result). Crusor's should_replan
            # LLM consult is REMOVED with this round: a failure is just an
            # observation handed back to the model.
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

        if tool_name == "plan_update":
            # The model's own list wins outright -- Hermes' todo tool replaces the list rather than
            # inferring progress from receipts. Parsing is tolerant by construction (steps_to_dicts),
            # so a bare-text step can never repeat the crash that ate a 42s turn.
            written = steps_to_dicts(_plan_tool_steps(tool_args))
            if written:
                plan = written
                plan_created = True
                event_bus.emit(
                    "plan_updated",
                    {
                        "session_id": str(
                            config.get("configurable", {}).get("thread_id") or "default"
                        ),
                        "plan": plan,
                    },
                )
        if plan and tool_name != "plan_update":
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

    # Gemini-style trajectory cycles + Cline-style soft/hard escalation.
    # This runs after outcomes are known, unlike a name-only pre-tool guard:
    # a changed test result or changed edit is real debugging progress and
    # therefore has a different fingerprint. Only identical trailing action
    # AND outcome cycles trigger.
    cycle = ph.detect_tool_cycle(tool_cycle_history)
    previous_warning = str(tool_cycle_guard.get("warned_signature") or "")
    guard_update: dict[str, Any] = {
        "history": tool_cycle_history,
        "warned_signature": previous_warning,
        "hard_stop": False,
        "detail": {},
    }
    if cycle is None:
        # Let a genuinely broken trajectory earn a fresh warning if it later
        # falls into another cycle; keep only the bounded hashed history.
        guard_update["warned_signature"] = ""
    else:
        detail = {
            "signature": cycle["signature"],
            "length": cycle["length"],
            "repetitions": cycle["repetitions"],
            "tools": list(cycle["tools"]),
        }
        guard_update["detail"] = detail
        tools_display = " → ".join(detail["tools"])
        severity = "error" if cycle["hard_stop"] else "warning"
        if cycle["hard_stop"]:
            guard_update["hard_stop"] = True
            failure = (
                "Unproductive tool trajectory stopped: "
                f"{tools_display} repeated {cycle['repetitions']} times "
                "with identical arguments and outcomes."
            )
            if failure not in failed_steps:
                failed_steps.append(failure)
            print(f"[ToolCycleGuard] HARD STOP: {failure}", flush=True)
        elif cycle["signature"] != previous_warning:
            guard_update["warned_signature"] = cycle["signature"]
            injected.append(SystemMessage(content=ph.TOOL_CYCLE_NUDGE.format(
                length=cycle["length"],
                repetitions=cycle["repetitions"],
                tools=tools_display,
            )))
            print(
                "[ToolCycleGuard] strategy-change warning: "
                f"length={cycle['length']} repeats={cycle['repetitions']} "
                f"tools={tools_display}",
                flush=True,
            )
        if cycle["hard_stop"] or cycle["signature"] != previous_warning:
            event_bus.emit("context.status", {
                "thread_id": str(
                    config.get("configurable", {}).get("thread_id") or "default"
                ),
                "phase": "tool_cycle_guard",
                "severity": severity,
                "message": (
                    f"Repeated tool trajectory detected: {tools_display} "
                    f"({cycle['repetitions']} identical cycles)."
                ),
                "cycle_length": cycle["length"],
                "repetitions": cycle["repetitions"],
                "tools": list(cycle["tools"]),
            })

    result = {
        "steps_completed": steps_completed,
        "failed_steps": failed_steps,
        "tool_failures": tool_failures,
        "recovery_mode": recovery_mode,
        "recovery_command": recovery_command,
        "recovery_attempts": recovery_attempts,
        "plan": plan,
        "plan_created": plan_created,
        "replan_needed": replan_needed,
        "execution_trace": execution_trace,
        "turn_tool_execution_count": turn_tool_execution_count,
        "turn_tool_execution_names": turn_tool_execution_names,
        "tool_cycle_guard": guard_update,
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
    # A hard trajectory loop is not a normal tool failure and must not consume
    # another provider call. End through its truthful, dedicated boundary while
    # preserving the workspace/checkpoint for a later user-steered recovery.
    if bool((state.get("tool_cycle_guard") or {}).get("hard_stop")):
        return "tool_cycle_limit"

    # Hermes question discipline (field run 2026-09-05, "asked question
    # but"): the legacy ask_user returned its echo to the MODEL, which kept
    # working — ask_user is no longer bound (clarify replaced it), but old
    # checkpointed sessions can still replay its messages:
    # asked AND ran a command in the same turn, then died "Ended
    # incomplete". In hermes a clarifying question is a TURN END: the user
    # answers in the chat, the next turn proceeds with the reply. An
    # ask_user-only tool batch therefore finalizes right here; the
    # question card is the answer surface and the end is CLEAN (no steps,
    # no failures -> no "Ended incomplete" stamp).
    _msgs = state.get("messages") or []
    if _msgs and isinstance(_msgs[-1], ToolMessage) and getattr(_msgs[-1], "name", "") == "ask_user":
        for _m in reversed(_msgs[:-1]):
            if getattr(_m, "type", "") == "ai":
                _calls = getattr(_m, "tool_calls", None) or []
                if _calls and all(c.get("name") == "ask_user" for c in _calls):
                    return "finalize"
                break
    route = ph.next_after_progress(
        recovery_mode=state.get("recovery_mode", False),
        recovery_attempts=state.get("recovery_attempts", 0),
        plan_complete=is_plan_complete(state),
        env_failures=state.get("env_failures", 0),
        pivot_count=state.get("pivot_count", 0),
        plan_wrap_nudges=state.get("plan_wrap_nudges", 0),
    )
    if route == "finalize" and (
        _verify_unsatisfied(state)
        or _deliverables_missing_on_disk(state, state.get("workspace", "."))
    ):
        return "finish_gate"
    return route

def tool_cycle_limit_node(state: AgentState, config: RunnableConfig):
    """Truthful terminal boundary for a repeated no-progress trajectory."""
    detail = dict((state.get("tool_cycle_guard") or {}).get("detail") or {})
    tools = [str(name) for name in detail.get("tools", []) if str(name)]
    tools_display = " → ".join(tools) or "unknown tool sequence"
    repetitions = int(detail.get("repetitions", 0) or 0)
    length = int(detail.get("length", 0) or len(tools))

    # The cycle is a failed outcome for feedback attribution, but feedback is
    # best-effort and must never interfere with the stop boundary.
    try:
        get_context_engine(config).record_feedback(
            success=False, task=_active_interest_text(state)
        )
    except Exception:
        pass

    return {
        "messages": [AIMessage(content=(
            "I stopped an unproductive tool loop before spending more turns. "
            f"The same {length}-action sequence ({tools_display}) produced "
            f"identical outcomes {repetitions} times. The workspace and session "
            "state are preserved. Please provide guidance for a different "
            "approach, or resume after changing the blocker."
        ))],
        "task_status": "failed",
        "task_completed": False,
    }


def recovery_limit_node(state: AgentState, config: RunnableConfig):
    failed_steps = state.get("failed_steps", [])

    # Record failure feedback: recovery was exhausted — the layer combination
    # used for this task correlated with failure.
    try:
        get_context_engine(config).record_feedback(
            success=False, task=_active_interest_text(state)
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
    # The advisory planning chain is gone (plan mode is a prompt, not an
    # engine), so this node no longer pays for a model call -- the gate
    # stays because a Stop must still short-circuit the node outright.
    session_id_pl = str(configurable.get("thread_id") or "default")
    from src.runtime.turn_control import turn_controls as _tc_pl
    if _tc_pl.cancelled(session_id_pl):
        return {
            "messages": [AIMessage(
                content="Operation cancelled by the user.",
                additional_kwargs={"crusor_cancelled": True},
            )],
        }

    interest = interest_from_state(state)
    current_task = interest.focus_text() or str(state.get("current_task", "") or "")
    plan_created = state.get("plan_created", False)

    provider = _cfg(configurable, "provider", LLM_PROVIDER)
    model = _cfg(configurable, "model", LLM_MODEL)

    # Keep the existing plan for the active task.
    if plan_created:
        return {}

    # Nothing meaningful to plan.
    if not current_task:
        return {}

    # The autonomous workspace request is already a complete task contract and
    # has a finite provider budget. Crusor previously spent multiple provider
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

    # plan_update writes state["plan"] mid-turn, and "plan" has no reducer: returning _no_plan()
    # here would replace it with [] and erase the model's own list on the next pass.
    if state.get("plan"):
        return {}

    # Hermes parity, and the fix for "hi" costing two provider calls: planning is model reasoning
    # inside the loop, so no mode except an explicit PLAN request pays for it up front. The model
    # reaches the list through plan_update; the UI reads the same plan state either way.
    if state.get("execution_mode", "agent") != "plan":
        return _no_plan()

    # PLAN MODE is a prompt, not an engine (agent/plan_prompt.py: "There is no engine and no
    # model-tool footprint"). Feed the live agent Hermes' ground rules as a normal turn.
    from src.prompts.hermes.plan_learn import build_plan_prompt

    plan_goal = interest.objective or current_task
    # Keep Hermes' one-argument prompt path while making that argument the
    # complete versioned contract rather than a stale task label.
    current_task = render_user_interest(interest)
    return {
        "plan": [],
        "plan_goal": plan_goal,
        "plan_created": False,
        "messages": [SystemMessage(content=build_plan_prompt(current_task))],
        "token_usage": _merge_token_usage(state.get("token_usage", {}), usages),
    }

def _plan_tool_steps(tool_args: dict) -> list:
    """Steps as the model passed them: a list, or a JSON string it could not be bothered to type."""

    raw = (tool_args or {}).get("steps")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = [line for line in raw.splitlines() if line.strip()]
    return raw if isinstance(raw, list) else []


def after_task_manager(state: AgentState) -> str:
    """Route conversational Ask directly; other new tasks may use planning."""

    if state.get("execution_mode") == "ask":
        return "ai"

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
        # The plan-mode prompt above already replaced the advisory chain, so there is no generated
        # list to preview: the agent writes the plan file and answers. Hermes does the same.
        return "ai"

    return "ai"


def plan_preview_node(state: AgentState):
    """Return the generated plan without executing it."""
    # A cancelled planner/plan_reviser must surface the cancellation message
    # instead of the (possibly stale) plan preview.
    last = state.get("messages", [])[-1] if state.get("messages") else None
    if bool(getattr(last, "additional_kwargs", {}).get("crusor_cancelled")):
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
                additional_kwargs={"crusor_cancelled": True},
            )],
        }

    current_plan = state.get("plan", [])

    if not current_plan:
        return {}

    usages: list[TokenUsage] = []

    try:
        revised = revise_plan(
            task=render_user_interest(interest_from_state(state)),
            plan=current_plan,
            revision=state.get("latest_instruction", ""),
            provider=_cfg(configurable, "provider", LLM_PROVIDER),
            model=_cfg(configurable, "model", LLM_MODEL),
            usage_list=usages,
        )
    except ValueError:
        # A revision the parser cannot read is an observation, not a crash
        # (field 2026-09-08: "Planner did not return a valid numbered plan."
        # ended the run as "Run failed"). The current plan stands unchanged;
        # the model adapts from what is on the floor, exactly as hermes does
        # with every other unparseable plan-shaped answer.
        return {
            "messages": [AIMessage(content=(
                "The plan revision didn't come back as a usable step list, "
                "so the current plan stands unchanged. Re-state the change "
                "against a specific step, or proceed and adjust the plan "
                "yourself as you work."
            ))],
            "token_usage": _merge_token_usage(
                state.get("token_usage", {}),
                usages,
            ),
        }

    token_usage = _merge_token_usage(
        state.get("token_usage", {}),
        usages,
    )

    revised_plan = steps_to_dicts(revised.steps)

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





def _denied_command(tc) -> str:
    """Compact command echo for denial ToolMessages — the model adapts by
    seeing WHAT was denied, not just a policy adjective (hermes denial
    receipts carry the command)."""
    args = tc.get("args") or {}
    command = args.get("command") if isinstance(args, dict) else None
    return f"\nDenied command: {command}" if command else ""


def _extract_exit_code(content: str) -> int | None:
    """Read the final explicit process exit receipt from tool output."""
    matches = re.findall(
        r"(?i)\b(?:exit\s+code|exited|exit)\s*(?::|=|with)?\s*(-?\d+)",
        str(content or ""),
    )
    # Terminal receipts put the authoritative process code at the end; earlier
    # stdout can discuss an expected exit code without being the process result.
    return int(matches[-1]) if matches else None


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
    for batch/cron-style runs: CRUSORAI_SUBAGENT_AUTO_APPROVE=1 (their
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

    def _repair_tool_call_names(self, tool_calls: list[dict]) -> tuple[list[dict], bool]:
        """hermes validate_tool_calls: "Repair mismatched tool names before
        validating (model hallucinations)" — each unknown name goes through
        parallel_tools.repair_tool_call_name; the receipt is hermes' own
        ('Auto-repaired tool name'). Returns (calls, changed)."""
        from src.graphs.parallel_tools import repair_tool_call_name
        changed = False
        out: list[dict] = []
        for tc in tool_calls:
            name = str(tc.get("name", "") or "")
            if name and name not in self._tools_by_name:
                repaired = repair_tool_call_name(name, set(self._tools_by_name))
                if repaired:
                    print(
                        f"[SafeToolNode] 🔧 Auto-repaired tool name: "
                        f"'{name}' -> '{repaired}'",
                        flush=True,
                    )
                    out.append({**tc, "name": repaired})
                    changed = True
                    continue
            out.append(tc)
        return (out, True) if changed else (tool_calls, False)

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
        # Seam observability (owner field runs: the log went silent between
        # a finished tool and the next "[ai_node] request" line, and nobody
        # could tell WHICH side owned the hang). One line at the exact
        # tool->model handoff: if the tool PASSED in the UI but this line
        # never prints, the hang is inside the durable transaction; if it
        # prints but "[ai_node] request" doesn't, the hang is graph-side.
        import time as _time
        _t0 = _time.monotonic()
        results = run_durable_batch_sequential(
            tool_calls, self._tools_by_name, config
        )
        print(
            f"[tool_node] {len(results)} tool result(s) ready in "
            f"{_time.monotonic() - _t0:.1f}s -> handing back to the model",
            flush=True,
        )
        return results

    def _diff_payload(self, tool_call: dict, workspace: str) -> dict | None:
        name = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        if name in {"run_terminal", "start_terminal", "terminal", "execute_code"}:
            cmd = str(args.get("command") or args.get("code") or "")
            from src.context.approval_detection import detect_dangerous_command
            risk = detect_dangerous_command(cmd) if cmd else None
            return {
                "kind": "shell",
                "command": cmd,
                "risk": risk or "Approval required before execution",
            }
        if name not in {"write_file", "edit_file", "copy_file"}:
            return None
        try:
            import difflib
            from src.tools.file_tools import resolve_workspace_path
            path_arg = args.get("path") or args.get("dst") or ""
            path = resolve_workspace_path(workspace, str(path_arg))
            old = path.read_text(encoding="utf-8") if path.is_file() else None
            action = "modify" if old is not None else "create"
            if name == "write_file":
                new = str(args.get("content", ""))
            elif name == "edit_file":
                needle = str(args.get("old_text", ""))
                replacement = str(args.get("new_text", ""))
                new = old.replace(needle, replacement, 1) if old is not None and needle in old else replacement
            else:
                action = "copy"
                src = resolve_workspace_path(workspace, str(args.get("src", "")))
                new = src.read_text(encoding="utf-8", errors="replace") if src.is_file() else ""

            old_str = old if old is not None else ""
            old_lines = old_str.splitlines(keepends=True)
            new_lines = new.splitlines(keepends=True)
            diff_lines = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f"a/{path_arg}",
                tofile=f"b/{path_arg}",
            ))
            diff_text = "".join(diff_lines)
            added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

            return {
                "kind": "file",
                "path": str(path),
                "relative_path": str(path_arg),
                "action": action,
                "old_text": old,
                "new_text": new,
                "diff": diff_text,
                "stats": {"added": added, "removed": removed},
            }
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
        _t_tool_start = time.time()
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
            # Pairing invariant (field 2026-09-10: a write batch returned ZERO
            # ToolMessages for a non-empty tool_calls list — the graph kept
            # flowing on an unpaired call while the UI card showed an error).
            # hermes' pairing law: EVERY proposed call gets a terminal result.
            # Any path whose result count misses a call id is a BUG: name it
            # in the log and fabricate the paired error so the model and the
            # transcript both see the truth.
            expected = [str(tc.get("id") or "") for tc in (tool_calls or [])]
            got = {str(getattr(m, "tool_call_id", "") or "") for m in (msg_list or [])}
            missing = [tc for tc, tid in zip(tool_calls or [], expected) if tid and tid not in got]
            if missing:
                print(
                    f"[SafeToolNode] PAIRING BUG: {len(missing)} of {len(expected)} "
                    "tool call(s) got NO result from this path ("
                    + ", ".join(str(tc.get('name', '?')) for tc in missing)
                    + ") — fabricating paired error result(s); the batch path is "
                    "losing results and must be fixed.",
                    flush=True,
                )
                for tc in missing:
                    msg_list = list(msg_list) + [self._durable_denial(
                        tc,
                        f"Error: `{tc.get('name', '')}` produced NO terminal result "
                        "(internal pairing bug); the call did NOT verifiably execute. "
                        "Re-check the effect (e.g. read the file) before relying on it.",
                        config,
                    )]

            # Step Tracker: Record executed tool outputs for diagnostics
            try:
                from src.runtime.step_tracker import StepTracker
                _trk = StepTracker.get_tracker(
                    _cfg_sid,
                    workspace_root=str(_cfg_ws or "."),
                )
                _trk.start_step("tools", state)
                _tool_dur = round(time.time() - _t_tool_start, 3)
                if _trk._current_step:
                    _trk._current_step.tool_duration_s = _tool_dur
                    _trk._current_step.duration_s = _tool_dur
                _calls_by_id = {
                    str(tc.get("id") or ""): tc
                    for tc in (tool_calls or [])
                    if tc.get("id")
                }
                _calls_by_name: dict[str, list[dict]] = {}
                for _tc in (tool_calls or []):
                    _calls_by_name.setdefault(str(_tc.get("name") or "tool"), []).append(_tc)
                _used_calls: set[int] = set()
                for _m in (msg_list or []):
                    _tname = getattr(_m, "name", "") or getattr(_m, "tool", "") or "tool"
                    _tcontent = str(getattr(_m, "content", "") or "")
                    _call = _calls_by_id.get(str(getattr(_m, "tool_call_id", "") or ""))
                    if _call is None:
                        _call = next(
                            (
                                candidate
                                for candidate in _calls_by_name.get(str(_tname), [])
                                if id(candidate) not in _used_calls
                            ),
                            None,
                        )
                    if _call is not None:
                        _used_calls.add(id(_call))
                    _safe_args = (_call or {}).get("args", {})
                    _exit_code = _extract_exit_code(_tcontent)
                    _is_err = getattr(_m, "status", None) == "error" or getattr(_m, "is_error", False)
                    if _exit_code not in (None, 0):
                        _is_err = True
                    if not _is_err:
                        _low = _tcontent.lower()
                        if _tname in ("read_file", "search_files", "list_files", "write_file", "edit_file"):
                            _is_err = _low.startswith("error:") or _low.startswith("file not found:") or _low.startswith("permission denied:")
                        elif _tname in ("terminal", "run_terminal", "start_terminal"):
                            _is_err = "command failed" in _low or ("exit code " in _low and "exit code 0" not in _low)
                        elif _tname == "execute_code":
                            _is_err = "traceback (most recent call last):" in _low or _low.startswith("error in execute_code:")
                        else:
                            _is_err = _low.startswith("error:") or "traceback (most recent call last):" in _low
                    _trk.record_tool_call(
                        name=_tname,
                        args=_safe_args if isinstance(_safe_args, dict) else {},
                        output=_tcontent,
                        status="failed" if _is_err else "success",
                        exit_code=_exit_code,
                        error=_tcontent if _is_err else None,
                    )
                _trk.finish_step()
            except Exception:
                pass

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
                "crusor_incomplete_response"
            )
        )
        if incomplete:
            reason = str(
                getattr(last_msg, "additional_kwargs", {}).get(
                    "crusor_incomplete_reason", "provider token limit"
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

        # OpenCode permission config (ask/allow/deny rule table) over
        # the guard: {tool_call_id: {effect, warning, action}} for
        # every call the config does not simply allow. Each channel
        # below consumes it its own way — the dock asks, deny-only
        # channels (sub-agents, autonomous runs) refuse.
        perm_decisions = _permission_decisions(
            tool_calls, workspace=workspace, thread_id=thread_id,
            state=state, guard=guard,
        )

        # --- D20: sub-agent threads auto-deny instead of prompting -------
        if thread_id.startswith("sub-") and os.environ.get(
            "CRUSORAI_SUBAGENT_AUTO_APPROVE", ""
        ).strip() != "1":
            verdicts = [
                (tc, *guard.check_tool_call(tc.get("name", ""), tc.get("args", {})))
                for tc in tool_calls
            ]
            unsafe = [v for v in verdicts if not v[1]]
            # Permission config: a child cannot ask, so an ask is a
            # denial here too (per-agent rules govern children).
            unsafe_ids_here = {str(v[0].get("id") or "") for v in unsafe}
            for tc in tool_calls:
                decision = perm_decisions.get(str(tc.get("id") or ""))
                if decision and str(tc.get("id") or "") not in unsafe_ids_here:
                    verdicts.append((tc, False, decision["warning"] or "Permission required by the permission config."))
                    unsafe.append(verdicts[-1])
            if not unsafe:
                return _with_repaired(self._execute_durable(tool_calls, config))

            import logging
            _log = logging.getLogger("crusorai.safety")

            def _content(tc, first_line):
                return (
                    f"⛔ AUTO-DENIED (sub-agent safety policy): "
                    f"`{tc.get('name', '')}` was blocked. {first_line}"
                f"{_denied_command(tc)}\n"
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
            logging.getLogger("crusorai.safety").warning(
                "sub-agent %s AUTO-APPROVED %d tool call(s) unchecked "
                "(CRUSORAI_SUBAGENT_AUTO_APPROVE=1): %s",
                thread_id, len(tool_calls),
                [tc.get("name", "") for tc in tool_calls],
            )
            return _with_repaired(self._execute_durable(tool_calls, config))

        verdicts = [
            (tc, *guard.check_tool_call(tc.get("name", ""), tc.get("args", {})))
            for tc in tool_calls
        ]
        unsafe = [v for v in verdicts if not v[1]]
        autonomous = os.environ.get("CRUSORAI_AUTO_APPROVE_WRITES", "").strip() == "1"
        if autonomous:
            # No human can answer on this path: config asks and
            # denials refuse alongside guard-unsafe calls.
            unsafe_ids_here = {str(v[0].get("id") or "") for v in unsafe}
            for tc in tool_calls:
                decision = perm_decisions.get(str(tc.get("id") or ""))
                if decision and str(tc.get("id") or "") not in unsafe_ids_here:
                    verdicts.append((tc, False, decision["warning"] or "Permission required by the permission config."))
                    unsafe.append(verdicts[-1])
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
            _log = logging.getLogger("crusorai.safety")

            def _content(tc, first_line):
                return (
                    f"⛔ BLOCKED (safety policy): `{tc.get('name', '')}` was not "
                    f"executed. {first_line}"
                    f"{_denied_command(tc)}\n"
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
        mutation_names = {
            "write_file", "edit_file", "copy_file",
        }

        def _approval_grant_key(tc) -> str:
            # OpenCode's "always" grants the RESOURCES the dock showed
            # (the file, the command) — not the whole tool. The key is
            # the tool plus its primary resource string.
            args = tc.get("args", {}) or {}
            resource = ""
            for arg_key in ("path", "file_path", "dst", "command", "cmd", "code"):
                value = args.get(arg_key)
                if isinstance(value, str) and value.strip():
                    resource = value.strip()
                    break
            return f"{tc.get('name', '')}\n{resource}"

        def _external_paths_covered(session_id: str, judged_paths) -> bool:
            """True when every judged outside path is inside a path an
            earlier "Allow always" granted for this session.

            The grant scope is the judged path the dock named (upstream
            suggested-pattern shape), NOT the exact command string:
            keyed on the full command, "always" could never cover the
            next, different command — e.g. every flutter invocation via
            an absolute SDK path re-asked forever (field 2026-10-20)."""
            if not judged_paths:
                return False
            from src.dashboard.event_bus import approval_queue as _q
            granted = [
                key.split("\n", 1)[1]
                for key in _q.grants_for(session_id)
                if key.startswith("external_directory\n")
            ]
            if not granted:
                return False

            def _covers(granted_path: str, path: str) -> bool:
                g, pth = granted_path, path
                if "\\" in g or "\\" in pth:
                    g, pth = g.replace("/", "\\"), pth.replace("/", "\\")
                    sep = "\\"
                    g, pth = g.casefold(), pth.casefold()
                else:
                    sep = "/"
                return pth == g or pth.startswith(g.rstrip(sep) + sep)

            return all(
                any(_covers(g, str(path)) for g in granted)
                for path in judged_paths
            )

        from src.context.safety_guard import session_grant_vetoed

        approval_candidates = []
        preapproved_ids: set[str] = set()
        denied_ids = {
            tc_id for tc_id, d in perm_decisions.items() if d["effect"] == "deny"
        }
        if approval_channel:
            # A prior "Allow always" verdict for this exact tool +
            # resource skips the queue (OpenCode's session ruleset).
            # Veto-class warnings never consult the grant store: the
            # guard re-asks secrets and git-ignored paths every time.
            from src.dashboard.event_bus import approval_queue as _queue_peek
            for tc in tool_calls:
                warning = unsafe_by_id.get(tc.get("id"), "")
                is_mutation = tc.get("name") in mutation_names
                auto_safe_mutation = (
                    is_mutation
                    and approval_policy in {"workspace_session", "session"}
                    and tc.get("id") not in unsafe_by_id
                )
                decision = perm_decisions.get(str(tc.get("id") or ""))
                if decision and decision["effect"] == "deny":
                    # A config denial never reaches the dock — it is
                    # refused outright (upstream's BlockedError).
                    denied_ids.add(str(tc.get("id") or ""))
                    continue
                config_ask = bool(decision and decision["effect"] == "ask")
                if tc.get("id") in unsafe_by_id or (is_mutation and not auto_safe_mutation) or config_ask:
                    ask_warning = warning or (decision["warning"] if decision else "")
                    if (
                        not session_grant_vetoed(ask_warning)
                        and (
                            _queue_peek.is_granted(
                                thread_id or "default", _approval_grant_key(tc)
                            )
                            or (
                                bool(decision and decision.get("external_ask"))
                                and _external_paths_covered(
                                    thread_id or "default",
                                    (decision or {}).get("grant_paths") or [],
                                )
                            )
                        )
                    ):
                        preapproved_ids.add(str(tc.get("id") or ""))
                        continue
                    approval_candidates.append((tc, False, ask_warning))
        if approval_channel and (approval_candidates or preapproved_ids or denied_ids):
            # Real pre-execution UI approval: publish the proposed diff, wait
            # on this session's request for the human's verdict (no timeout —
            # founder 2026-10-20 removed it; Stop cancels the wait), then
            # execute only approved + originally-safe calls through the
            # durable path. The wait heartbeats, so the bridge's stall
            # watchdog — which counts approval waits as liveness — never
            # mistakes a pending dock for a dead turn.
            from src.dashboard.event_bus import approval_queue
            unsafe_ids = {tc.get("id") for tc, _, _ in approval_candidates}
            approved_ids: set[str] = set(preapproved_ids)
            denials: dict[str, ToolMessage] = {}
            for tc in tool_calls:
                tc_id_str = str(tc.get("id") or "")
                if tc_id_str in denied_ids:
                    denials[tc_id_str] = self._durable_denial(
                        tc, perm_decisions[tc_id_str]["warning"], config,
                    )
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
                # Testimony (field run-3, build c54ccebf: two `flutter
                # create` calls waited out the full 300s dock timeout and
                # the engine log showed only "[tool_node] 0 tool result(s)
                # ready" — an unanswered dock was indistinguishable from
                # a swallowed tool call). Every dock wait now speaks in
                # the engine log: asked, still waiting, answered, or
                # cancelled. The ask names the judged resource, so a
                # false ask is recognizable at a glance.
                _ask_reason = (
                    (warning or "permission ask").strip().splitlines()[0][:160]
                )
                print(
                    f"[approval] {tc.get('name', '')} needs approval — "
                    f"waiting for human: {_ask_reason}",
                    flush=True,
                )

                # Stop must wake an approval wait immediately rather than
                # leave the turn blocked on an unanswered dock.
                def _cancel_approval(
                    pending_tool_id=tool_id,
                    pending_session=thread_id or "default",
                ):
                    approval_queue.resolve(
                        pending_tool_id, False, session_id=pending_session
                    )

                def _approval_heartbeat(elapsed_s: float) -> None:
                    # The wait is alive and says so: a log line for the
                    # human reading along, and an event the bridge
                    # forwarder relays — relayed approval-wait output is
                    # liveness, so the stall watchdog never fires on a
                    # dock the human simply hasn't reached yet. The
                    # event has no Protocol v2 projection; it never
                    # reaches the panel as a frame.
                    print(
                        f"[approval] still waiting for human "
                        f"({elapsed_s:.0f}s): {tc.get('name', '')}",
                        flush=True,
                    )
                    event_bus.emit("tool.approval.waiting", {
                        "tool_id": tool_id,
                        "tool_name": tc.get("name", ""),
                        "thread_id": thread_id or "default",
                        "elapsed_s": round(elapsed_s, 1),
                    })

                _tc.register_abort(_cfg_sid, _cancel_approval)
                _wait_started = time.monotonic()
                try:
                    decision = approval_queue.wait_for_decision(
                        tool_id, heartbeat=_approval_heartbeat
                    )
                finally:
                    _tc.unregister_abort(_cfg_sid, _cancel_approval)
                _waited_s = time.monotonic() - _wait_started
                if decision and decision.get("decision") is True:
                    print(
                        f"[approval] {tc.get('name', '')} allowed after "
                        f"{_waited_s:.1f}s"
                        + (
                            " (always — granted for this session)"
                            if decision.get("always_allow")
                            else ""
                        ),
                        flush=True,
                    )
                    approved_ids.add(tool_id)
                    # "Allow always": remember (session, tool, resource)
                    # so the same ask is not repeated THIS session —
                    # and only this session. Nothing is written to
                    # disk; a fresh session asks again (founder
                    # 2026-10-17: permission handling is session-only).
                    # Veto classes (secrets, git-ignored paths) are
                    # never remembered.
                    if decision.get("always_allow") and not session_grant_vetoed(warning):
                        _pdecision = perm_decisions.get(tool_id) or {}
                        _grant_paths = (
                            _pdecision.get("grant_paths") or []
                            if _pdecision.get("external_ask") else []
                        )
                        if _grant_paths:
                            # Scope the session grant to the judged
                            # outside path(s) the human just approved —
                            # never to the full command string, which no
                            # future command would ever match again.
                            for _gp in _grant_paths:
                                approval_queue.grant(
                                    thread_id or "default",
                                    f"external_directory\n{_gp}",
                                )
                        else:
                            approval_queue.grant(
                                thread_id or "default", _approval_grant_key(tc)
                            )
                else:
                    reason = (
                        "cancelled" if _tc.cancelled(_cfg_sid) else "denied"
                    )
                    print(
                        f"[approval] {tc.get('name', '')} {reason} after "
                        f"{_waited_s:.1f}s — call denied before execution",
                        flush=True,
                    )
                    denials[tool_id] = self._durable_denial(
                        tc,
                        f"⛔ Tool `{tc.get('name', '')}` {reason} before execution.",
                        config,
                    )
            runnable = [
                tc for tc in tool_calls
                if str(tc.get("id") or "") not in denied_ids
                and (tc.get("id") not in unsafe_ids or tc.get("id") in approved_ids)
            ]
            results = {m.tool_call_id: m for m in self._execute_durable(runnable, config)}
            results.update(denials)
            ordered = [results[tc["id"]] for tc in tool_calls if tc.get("id") in results]
            return _with_repaired(ordered)

        if denied_ids and not unsafe:
            # Permission-config denials on a channel with no dock to
            # ask through: refuse those calls, execute the rest.
            runnable = [
                tc for tc in tool_calls if str(tc.get("id") or "") not in denied_ids
            ]
            results = {m.tool_call_id: m for m in self._execute_durable(runnable, config)}
            for tc in tool_calls:
                tc_id_str = str(tc.get("id") or "")
                if tc_id_str in denied_ids:
                    results[tc_id_str] = self._durable_denial(
                        tc, perm_decisions[tc_id_str]["warning"], config,
                    )
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
        # canonical). CRUSORAI_PARALLEL_TOOLS=off => true legacy below.
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
        if os.environ.get("CRUSORAI_PARALLEL_TOOLS", "").strip().lower() == "off":
            # Explicit compatibility kill-switch: restore ToolNode's historical
            # execution semantics (including its concurrent batch behavior).
            if _repaired_ai is not None:
                state = dict(state)
                state["messages"] = messages[:-1] + [_repaired_ai]
            if not _tc.admit_action(_cfg_sid):
                return _cancelled_result()
            return _with_repaired(self._node.invoke(state, config)["messages"])
        # ── hermes turn_tool_validation (agent/turn_tool_validation.py +
        # agent_runtime_helpers.repair_tool_call #33007): repair model-emitted
        # tool names BEFORE validating, then answer unrepairable names with
        # tool-role error results carrying the catalog. Field receipt (owner
        # log 2026-09-08): the model called `terminal` — hermes' own shell
        # tool name (terminal_tool.py name="terminal") — and `Bash`; both
        # fell through unknown, the model flailed (dir -R, ls /d/...), and
        # the turn died "Ended unverified".
        tool_calls, _names_changed = self._repair_tool_call_names(tool_calls)
        if _names_changed:
            _repaired_ai = AIMessage(
                content=last_msg.content,
                tool_calls=tool_calls,
                id=getattr(last_msg, "id", None),
            )
        if all(tc.get("name", "") in self._tools_by_name for tc in tool_calls):
            return _with_repaired(self._execute_durable(tool_calls, config))

        # Mixed/unknown batch: KNOWN calls keep the durable chokepoint; an
        # UNKNOWN name answers with hermes' invalid-tool-name error content
        # (_invalid_tool_name_error_content: the catalog so the model can
        # self-correct; a BLANK name gets the terse anti-priming text —
        # dumping the catalog feeds the echo loop, #47967). The "Error: "
        # prefix is hermes' own recovery-result convention (its invalid-JSON
        # path) and keeps the progress classifier's line-start rule honest.
        # Through the same middleware (`_durable_denial`), not ToolNode.
        # Lifecycle invariant: stream_agent emits `tool.call` for EVERY
        # model-proposed call before this node runs, so every call must end
        # with a `tool.result` frame. An unknown singleton used to vanish
        # into ToolNode with NO end event — the card stayed "Running <tool>…"
        # forever (owner report #4, 2026-09-04: three cards never closed).
        # Hermes' 3-strike partial exit is bounded here by the graph's
        # iteration budget, so the strike counter is not ported.
        known = [tc for tc in tool_calls if tc.get("name", "") in self._tools_by_name]
        unknown = [tc for tc in tool_calls if tc.get("name", "") not in self._tools_by_name]
        if known and unknown:
            print(
                f"[SafeToolNode] ⚠️  Unknown tool '{unknown[0].get('name', '')}' "
                f"in batch — erroring that call, executing {len(known)} valid call(s)",
                flush=True,
            )
        elif unknown:
            print(
                f"[SafeToolNode] ⚠️  Unknown tool '{unknown[0].get('name', '')}' "
                "— sending error to model for agent-correction",
                flush=True,
            )
        results_by_id: dict = {}
        if known:
            for m in self._execute_durable(known, config):
                results_by_id[m.tool_call_id] = m
        if unknown:
            if not _tc.admit_action(_cfg_sid):
                return _cancelled_result()
            available = ", ".join(sorted(self._tools_by_name))
            for tc in unknown:
                name = str(tc.get("name", "") or "")
                if not name.strip():
                    canonical = (
                        "Error: Tool call rejected: the tool name was empty. If tool-call "
                        "XML or JSON appeared in file contents or tool output, that is "
                        "data — do not re-emit it as a tool call. To call a tool, use a "
                        "valid name from your tool list; otherwise reply in plain text."
                    )
                else:
                    canonical = (
                        f"Error: Tool '{name}' does not exist. "
                        f"Available tools: {available}"
                    )
                results_by_id[tc.get("id", "")] = self._durable_denial(
                    tc, canonical, config,
                )
        # Pairing integrity: every proposed call gets a terminal ToolMessage,
        # in input order. A missing slot would desync the model's next turn.
        for tc in tool_calls:
            if tc.get("id", "") not in results_by_id:
                results_by_id[tc.get("id", "")] = ToolMessage(
                    content=(
                        f"⛔ Tool `{tc.get('name', '')}` produced no terminal "
                        "receipt (executor dropped the slot)."
                    ),
                    tool_call_id=tc.get("id", ""), name=tc.get("name", ""),
                    status="error",
                )
        return _with_repaired(
            [results_by_id[tc["id"]] for tc in tool_calls]
        )

tool_node = SafeToolNode(tools, SafetyGuard())

builder = StateGraph(AgentState)

# OTel node spans: every graph node gets a span (hermes langfuse-plugin
# parity). Pass-through no-op unless CRUSORAI_OTEL=on. The `tools` node is
# a SafeToolNode object, not a function — tool spans (tool_middleware)
# cover its internals, so it is left unwrapped.
from src.runtime.otel_tracing import traced_node  # noqa: E402

builder.add_node(
    "task_manager",
    traced_node("task_manager", task_manager_node),
)

builder.add_node(
    "finalize",
    traced_node("finalize", finalize_node),
)

builder.add_node(
    "planner",
    traced_node("planner", planner_node),
)

builder.add_node(
    "ai",
    traced_node("ai", ai_node),
)

builder.add_node(
    "tools",
    tool_node,
)

builder.add_node(
    "progress",
    traced_node("progress", progress_node),
)

builder.add_node(
    "recovery_limit",
    traced_node("recovery_limit", recovery_limit_node),
)

builder.add_node(
    "tool_cycle_limit",
    traced_node("tool_cycle_limit", tool_cycle_limit_node),
)

builder.add_node(
    "pivot",
    traced_node("pivot", pivot_node),
)

builder.add_node(
    "plan_preview",
    traced_node("plan_preview", plan_preview_node),
)

builder.add_node(
    "plan_reviser",
    traced_node("plan_reviser", plan_reviser_node),
)

builder.add_node(
    "plan_cancelled",
    traced_node("plan_cancelled", plan_cancelled_node),
)

builder.add_node(
    "approval_without_plan",
    traced_node("approval_without_plan", approval_without_plan_node),
)

builder.add_node(
    "finish_gate",
    traced_node("finish_gate", finish_gate_node),
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
        "recovery_limit": "recovery_limit",
        "tool_cycle_limit": "tool_cycle_limit",
        "finalize": "finalize",
        "pivot": "pivot",
        "finish_gate": "finish_gate",
    },
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

builder.add_edge(
    "tool_cycle_limit",
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
if os.environ.get("CRUSORAI_DISABLE_LONG_TERM_MEMORY", "").strip().lower() in {
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
    # Only a model the caller EXPLICITLY pins (a present, non-empty "model"
    # in a config dict) is allowed to change a session's engine. A raw key
    # string (tests / tools / nodes that carry only thread_id) and a config
    # with no "model" express NO model choice — they must reuse whatever
    # engine the session already holds instead of silently rebuilding it
    # against the process-default LLM_MODEL. (The old code defaulted every
    # implicit call to LLM_MODEL, so a node passing the full config
    # {"thread_id": t, "model": <session model>} created engine A, then a
    # caller passing bare key "t" rebuilt engine B — two engines for one
    # thread_id, splitting the layer cache / feedback history / weights.)
    explicit_model: "str | None" = None
    if isinstance(config_or_key, dict):
        pinned = config_or_key.get("configurable", {}).get("model")
        if pinned:
            explicit_model = str(pinned)
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
        # actually receive this session's requests. When THIS call explicitly
        # pins a different model than the one the session engine was built for,
        # re-point THAT engine in place (model + budget) — never evict it. The
        # engine is session identity (layer cache, _last_layers_sent snapshot,
        # feedback history, learned weights); a model switch must not split a
        # thread into two engines. Implicit calls (raw key / no "model") never
        # touch the model — they express no preference.
        if (
            engine is not None
            and explicit_model is not None
            and explicit_model != str(getattr(engine, "model", ""))
        ):
            engine.reconfigure_model(explicit_model)
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
            # First engine for the thread: an explicit pin wins, otherwise
            # fall back to the process default. Once built, implicit callers
            # reuse it (guarded above); only a later, differing explicit pin
            # rebuilds.
            engine = ContextEngine(
                model=explicit_model or LLM_MODEL,
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
_CHECKPOINT_DB = os.path.join(os.path.expanduser("~"), ".crusorai", "sessions.db")
os.makedirs(os.path.dirname(_CHECKPOINT_DB), exist_ok=True)
_checkpoint_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
# Windows field failure (2026-09-04): the turn died BETWEEN finalize's return
# and the stream generator ending - the state commit / post-loop checkpoint
# reads. Default rollback-journal SQLite lets one writer EXCLUDE all readers
# during a commit and vice versa; with several threads on this one shared
# connection that is a stall class, not a crash. WAL makes readers and the
# writer concurrent; an explicit busy_timeout turns any residual contention
# into a bounded wait instead of an instant error.
try:
    _checkpoint_conn.execute("PRAGMA journal_mode=WAL")
    _checkpoint_conn.execute("PRAGMA busy_timeout=10000")
    _checkpoint_conn.execute("PRAGMA synchronous=NORMAL")
except Exception:
    pass  # an unhardened checkpointer still works; never block graph compile
memory = SqliteSaver(_checkpoint_conn)
memory.setup()

graph = builder.compile(
    checkpointer=memory
)


# =========================================================
# NORMAL INVOCATION
# =========================================================
def _begin_diagnostic_turn(thread_id: str, workspace: str, message: str) -> None:
    """Invalidate the previous turn's terminal report before graph work.

    Diagnostics are best-effort and can never block a user turn.
    """
    try:
        from src.runtime.step_tracker import StepTracker

        StepTracker.get_tracker(
            thread_id,
            workspace_root=workspace,
        ).begin_turn(user_ask=message)
    except Exception:
        pass


def invoke_agent(
    message: str,
    thread_id: str = "default",
    provider: str = LLM_PROVIDER,
    model: str = LLM_MODEL,
    workspace: str = ".",
    execution_mode: ExecutionMode = "agent",
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

        _begin_diagnostic_turn(thread_id, workspace, message)
        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(content=message)
                ],
                "latest_instruction": message,
                "execution_mode": execution_mode,
                # Safety/gate budgets are turn-scoped even when checkpoint
                # state is resumed (all channels, not only token iteration).
                **_turn_scoped_resets(),
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
    execution_mode: ExecutionMode = "agent",
    approval_channel: bool = False,
    approval_policy: str = "ask",
    turn_id: str | None = None,
    initial_plan: list[dict[str, Any]] | None = None,
    reasoning_effort: str | None = None,
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
                "approval_policy": approval_policy,
                "turn_id": turn_id,
                "reasoning_effort": reasoning_effort,
            },
            "recursion_limit": _recursion_limit(),
        }

        _begin_diagnostic_turn(thread_id, workspace, message)
        final_response = ""
        turn_completed: bool | None = None
        current_step = 0
        total_steps = 0

        initial_state = {
            "messages": [HumanMessage(content=message)],
            "latest_instruction": message,
            "execution_mode": execution_mode,
            # Safety/gate budgets are turn-scoped even when checkpoint
            # state is resumed (all channels, not only token iteration).
            **_turn_scoped_resets(),
        }
        if initial_plan is not None:
            initial_state.update({
                "plan": list(initial_plan),
                "plan_goal": message,
                "plan_created": bool(initial_plan),
                "plan_approved": bool(initial_plan),
            })

        # Fresh-label printing state: the progress event carries the
        # CUMULATIVE lists, so printing steps_completed[-1] re-printed a
        # STALE label whenever the newest batch earned nothing new (a
        # check_terminal on a running process classifies SKIP and records
        # nothing; a repeated start command dedups out of the list) and
        # swallowed all but the last label of a multi-call batch. Field
        # log 2026-09-08: start_terminal #2 printed stop's receipt, and
        # check_terminal printed start's. Print the labels EARNED since
        # the previous event; a batch that earned nothing prints nothing.
        printed_step_labels: set[str] = set()
        printed_failed_labels: set[str] = set()
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
                    try:
                        print(f"\n{route_info}")
                    except UnicodeEncodeError:
                        print(f"\n{route_info.encode('ascii', 'replace').decode()}")

                # AI requested tools
                if last_message.tool_calls:
                    event_bus.emit("message.agent.start", {"thread_id": thread_id})
                    for tool_call in last_message.tool_calls:
                        tool_name = tool_call["name"]
                        tool_args = tool_call["args"]

                        tool_id = f"{thread_id}-{tool_call.get('id', '')}"

                        # Field 2026-09-27: custom OpenAI-compatible endpoints
                        # (velona.in/deepseek) intermittently stream tool calls
                        # with EMPTY names (args intact). The request sanitizer
                        # drops them from the NEXT request's history, but this
                        # frame still reached the UI, which painted a "Unknown"
                        # card with raw JSON args. Skip the ghost here — the
                        # sanitizer will drop the pairing on the next turn.
                        if not str(tool_name or "").strip():
                            print("[ui] skipped nameless tool-call frame (endpoint glitch)", flush=True)
                            continue

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
                    # Normalize content (str or content-block list) to clean
                    # text: this feeds the fallback chunk AND turn_done's
                    # authoritative message (hermes message.complete shape —
                    # the wire never carries a list).
                    final_response = _result_answer_text(last_message)
                    # Live tokens already carried THIS call's text to the
                    # client piece by piece (_invoke_with_token_pump recorded
                    # that in _TURN_LAST_CALL_STREAMED); re-emitting the whole
                    # content here would print the answer twice. A call that
                    # did not stream (streaming off, provider without token
                    # callbacks, pump rejected) falls back to this single
                    # historical chunk -- either way the text appears once.
                    if final_response and not _TURN_LAST_CALL_STREAMED.pop(thread_id, False):
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

                for label in steps_completed:
                    if label in printed_step_labels:
                        continue
                    printed_step_labels.add(label)
                    print(f"  ✅ {label}")
                    event_bus.emit("plan.step.complete", {
                        "step": label,
                        "thread_id": thread_id,
                    })

                for label in failed_steps:
                    if label in printed_failed_labels:
                        continue
                    printed_failed_labels.add(label)
                    print(f"  ❌ {label}")

            # ---------------------------------------------
            # REPLANNER NODE
            # ---------------------------------------------

            # ---------------------------------------------
            # RECOVERY LIMIT
            # ---------------------------------------------
            if "recovery_limit" in event:
                print("\n⛔ Recovery limit reached. Pausing for user input.")

            # FINALIZE NODE — its verdict, not mere transport closure, owns
            # turn completion. Attempt 11 discarded this state and returned
            # the preceding "I will inspect" text as completed=true.
            if "finalize" in event:
                print("[turn] stream: finalize update received", flush=True)
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
                        # The ai-node branch above already emitted (or
                        # deliberately skipped) the assistant text for THIS
                        # turn; a finalize copy that is byte-identical is a
                        # duplicate paint, not new information. Deviation
                        # stamps ("Ended incomplete/...") differ from the
                        # answer and still go out.
                        if str(content) != str(final_response or ""):
                            final_response = str(content)
                            event_bus.emit("message.agent.chunk", {
                                "chunk": final_response,
                                "thread_id": thread_id,
                            })

        print("[turn] stream loop ended", flush=True)
        # Idle reaches the desktop BEFORE the best-effort browser teardown:
        # on the interrupt path every ms spent before this emit is perceived
        # Stop-latency, and teardown must never gate the ack again.
        event_bus.emit("session.status", {"status": "idle", "thread_id": thread_id})
        # hermes saves the browser recording in cleanup_browser ("saves the
        # file before close"); the turn end is crusor's closest equivalent —
        # the .webm is the visible-testing artifact (owner 2026-09-07,
        # Antigravity-style walkthroughs). Best-effort: never blocks idle.
        try:
            from src.tools.browser_tools import stop_browser_recording_for_thread
            _saved = stop_browser_recording_for_thread(thread_id)
            if _saved:
                print(f"[turn] browser recording saved: {_saved}", flush=True)
        except Exception as _rec_exc:
            print(f"[turn] browser recording save skipped: {type(_rec_exc).__name__}: {_rec_exc}", flush=True)
        # Second half of hermes cleanup_browser: CLOSE the browser after the
        # recording is saved. A testing turn used to leave the headed window
        # and every navigation tab open on the user's desktop; the test is
        # over, the .webm is the artifact — the window is not. Best effort,
        # bounded: this must never block or fail the turn end.
        try:
            from src.tools.browser_tools import close_browser_for_thread
            if close_browser_for_thread(thread_id):
                print("[turn] browser closed (tab/window cleanup)", flush=True)
        except Exception as _close_exc:
            print(f"[turn] browser close skipped: {type(_close_exc).__name__}: {_close_exc}", flush=True)
        # D38: post-run bounded background self-curation (memory review on the
        # aux model). Never blocks the response — state is snapshotted from the
        # checkpointer and reviewed on a daemon thread.
        from src.context.self_curation import maybe_spawn_memory_review
        try:
            spawned = maybe_spawn_memory_review(thread_id)
            if spawned:
                print("[turn] post-run review spawned", flush=True)
        except Exception:
            pass

        # Read the persisted verdict even when an earlier ai event supplied
        # text. Transport completion and task completion are different facts.
        # Keep the string return API compatible while carrying the verdict for
        # the bridge's terminal frame.
        snap_values: dict[str, Any] = {}
        try:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(graph.get_state, config)
                try:
                    snap = _fut.result(timeout=1.5)
                    snap_values = dict(snap.values or {}) if snap else {}
                    print("[turn] state snapshot ok", flush=True)
                except _cf.TimeoutError:
                    print("[turn] state snapshot timeout — returning without snapshot", flush=True)
                    try:
                        _fut.cancel()
                    except Exception:
                        pass
                except Exception as _e:
                    print(f"[turn] state snapshot error: {_e}", flush=True)
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

    analytics_path = Path.home() / ".crusorai" / "session_analytics.json"

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

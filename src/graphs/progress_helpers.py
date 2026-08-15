# src/graphs/progress_helpers.py
"""
Progress-node helpers — D9 (§40)
=================================

Extracted from the ~340-line progress_node god-block so every fork of the
tool-progress bookkeeping is unit-testable in isolation. progress_node in
chat_graph.py is now a thin orchestrator over these helpers.

Behavior contract (every rule preserved verbatim from the pre-D9 code,
pinned in src/tests/test_progress_helpers.py):

- a check_terminal message reporting "status: running" is SKIPPED ENTIRELY
  (tri-state "skip") — no trace, no memory, no outcome handling;
- every other latest tool message appends a trace entry (result tail 1000)
  BEFORE memory/failure/success handling;
- tool memory: only for non-empty results and tool != "think"; anchor
  precedence path > command > query > process_id; failures store the
  result TAIL (300), successes the HEAD (300), full_output the head 2000;
  storage is best-effort (never raises);
- failures: tool_failures increments for ANY failed tool;
  recovery_attempts increments for run_terminal/check_terminal failures,
  and for other tools ONLY while already in recovery_mode;
  recovery_mode/recovery_command are set by the FIRST run/check failure
  (later failures do not steal the command slot);
- success on run_terminal clears recovery ONLY when the command equals
  the stored recovery_command (same-operation rule);
- write_file successes emit diff.show + files.changed; edit_file emits
  files.changed; no other tool emits events;
- step labels are deduped by exact string before appending;
- replan is consulted only on failure AND a non-empty plan.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from langchain_core.messages import ToolMessage

from src.agents.planner import should_replan, update_plan_from_tool

# Shown to the model after any tool result (kept byte-identical to the
# pre-D9 inline string).
PROGRESS_REFLECTION_PROMPT = (
    "You just received a tool result. Take a moment to evaluate it:\n"
    "- Did the tool succeed or fail?\n"
    "- Does the output match what you expected?\n"
    "- Should you proceed, fix something, ask the user, or replan?\n\n"
    "Use verify() when the result needs explicit validation. "
    "Don't verify meta-tools like think(), verify(), or ask_user()."
)

OUTCOME_SUCCESS = "success"
OUTCOME_FAILED = "failed"
OUTCOME_SKIP = "skip"      # check_terminal still running: record NOTHING

# =====================================================================
# STRATEGY PIVOT (lab finding, run 10)
# =====================================================================
# When tool failures are ENVIRONMENT-level (missing binary, PATH/shim or
# permission problems — e.g. `npx create-vite` failing with "not recognized
# as an internal or external command" on Windows), retrying the same class
# of command fails identically forever and the old recovery loop burned all
# 3 attempts and paused for user input instead of switching strategy.
# These markers classify that class so the graph can pivot (see
# next_after_progress / pivot_node) instead of retry-until-dead.
_ENV_FAILURE_MARKERS = (
    "not recognized as an internal or external command",
    "is not recognized",
    "the syntax of the command is incorrect",  # cmd.exe parses '/' as a switch

    "command not found",
    "no such file or directory",
    "cannot find the path specified",
    "not found in path",
    "permission denied",
    "exit code: 127",
)

RECOVERY_LIMIT = 3      # terminal failures before recovery_limit / pivot
MAX_PIVOTS = 2          # bounded strategy pivots before giving up


# Shown to the model when environment-level failures force a strategy pivot.
PIVOT_GUIDANCE_PROMPT = (
    "Environment-level failure detected: the commands you keep running cannot "
    "execute in this environment (missing binary, PATH/shim or permission "
    "problem), so retrying them will keep failing identically. STOP running "
    "this class of command. PIVOT YOUR STRATEGY:\n"
    "- Create or edit files directly with write_file/edit_file — do not "
    "scaffold projects or install packages through the terminal if the "
    "command fails.\n"
    "- If the task asks for setup/install steps or instructions, deliver them "
    "as text in your final answer instead of executing them.\n"
    "- Inspect the workspace with read_file/list_files; never re-run the "
    "failing command.\n"
    "Make concrete progress now with a different approach."
)


def classify_env_failure(result: str) -> bool:
    """True when a tool failure is environmental (missing binary, PATH/shim
    breakage, permissions) rather than a bug in the agent's own strategy.

    These failures repeat identically on retry and need a strategy pivot,
    not another attempt (and not a replan — the plan isn't wrong, the
    environment is)."""
    r = result.lower()
    return any(marker in r for marker in _ENV_FAILURE_MARKERS)


def next_after_progress(
    recovery_mode: bool,
    recovery_attempts: int,
    replan_needed: bool,
    plan_complete: bool,
    env_failures: int,
    pivot_count: int,
) -> str:
    """Pure routing decision for after_progress (unit-testable).

    Old behavior: 3 terminal failures -> recovery_limit (pause for user)
    even when the failures were environmental and a different strategy
    existed. New behavior: repeated environment-level failures route to a
    bounded strategy pivot (MAX_PIVOTS) before giving up."""
    if recovery_mode and recovery_attempts >= RECOVERY_LIMIT:
        if env_failures >= 2 and pivot_count < MAX_PIVOTS:
            return "pivot"
        return "recovery_limit"
    if replan_needed:
        return "replanner"
    if plan_complete:
        return "finalize"
    return "ai"

_TRACE_RESULT_TAIL = 1000
_MEMORY_SNIPPET = 300
_MEMORY_FULL_OUTPUT = 2000
_FAILURE_RESULT_TAIL = 3000


def latest_tool_messages(messages: list) -> list[ToolMessage]:
    """The trailing run of ToolMessages at the end of the conversation."""
    latest: list[ToolMessage] = []
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            latest.append(message)
        else:
            break
    latest.reverse()
    return latest


def find_tool_args(messages: list, tool_call_id: str) -> dict:
    """Locate the arguments of the tool call that produced this result."""
    for previous_message in reversed(messages):
        if not hasattr(previous_message, "tool_calls"):
            continue
        for tool_call in previous_message.tool_calls:
            if tool_call.get("id") == tool_call_id:
                return tool_call.get("args", {})
    return {}


# Generic error markers that indicate a FAILED tool execution. Matched at
# LINE STARTS (MULTILINE), never as substrings: real file content routinely
# carries mid-line "error:" — `except ValueError:`, a test named
# `test_..._raises_value_error:` — which previously misclassified successful
# read_file/think results as failures and burned recovery attempts (lab
# finding, run 5). Genuine failures open a line: langchain's
# ToolNode(handle_tool_errors=True) emits "Error: ...", tracebacks open
# with "Traceback (most recent call last):", and the engine's own error
# strings ("unknown process id", "path escapes workspace") are standalone
# lines.
_ERROR_MARKER_RE = re.compile(
    r"^(?:error:|traceback|unknown process id|path escapes workspace)",
    re.IGNORECASE | re.MULTILINE,
)


def classify_tool_outcome(tool_name: str, result: str) -> str:
    """The success/failure/skip verdict, preserving every legacy fork.

    Generic markers (Error:, traceback, ...) count only at LINE STARTS;
    a mid-line "error:" inside file content or reasoning text is data,
    not a failed tool (see _ERROR_MARKER_RE). run_terminal/check_terminal
    keep their exit-code rules.
    """
    result_lower = result.lower()
    failed = bool(_ERROR_MARKER_RE.search(result))

    if tool_name == "typecheck_workspace":
        # Compiler invocation is evidence only when it explicitly returns the
        # green receipt. Unicode status markers are part of the tool contract.
        failed = not result.lstrip().startswith("✅")
    elif tool_name in {"verify_ui_workspace", "verify_ui_routes"}:
        failed = not result.lstrip().startswith("✅")
    elif tool_name == "run_terminal":
        if "exit code: 0" not in result_lower:
            failed = True
    elif tool_name == "check_terminal":
        if "status: running" in result_lower:
            return OUTCOME_SKIP
        if "status: completed" in result_lower:
            if "exit code: 0" not in result_lower:
                failed = True

    return OUTCOME_FAILED if failed else OUTCOME_SUCCESS


def make_trace_entry(tool_name: str, tool_args: dict, result: str, failed: bool) -> dict:
    return {
        "type": "tool",
        "tool": tool_name,
        "args": dict(tool_args),
        "status": "failed" if failed else "success",
        "result": result[-_TRACE_RESULT_TAIL:],
    }


def tool_memory_anchor(tool_args: dict) -> str:
    """First present anchor in the legacy precedence order."""
    for key in ("path", "command", "query", "process_id"):
        val = tool_args.get(key)
        if val:
            return f"{key}={val}"
    return ""


def record_tool_memory(memory_manager: Any, tool_name: str, task: str,
                       result: str, tool_args: dict, failed: bool) -> None:
    """Store tool output for the semantic-retrieval layer. Best-effort:
    never raises, never stores empty results or think() internals."""
    if not result.strip() or tool_name == "think" or memory_manager is None:
        return
    try:
        anchor = tool_memory_anchor(tool_args)
        # Failures: the error lives at the tail of the output.
        # Successes: the useful content starts at the head.
        summary = (result[-_MEMORY_SNIPPET:] if failed
                   else result[:_MEMORY_SNIPPET]).replace("\n", " ")
        memory_manager.store_tool_memory(
            tool_name=tool_name,
            query=task,
            summary=f"{'FAILED' if failed else 'OK'} {anchor} | {summary}",
            full_output=result[:_MEMORY_FULL_OUTPUT],
        )
    except Exception:
        pass  # Tool memory is best-effort; never block execution


def build_failure(tool_name: str, result: str, tool_args: dict,
                  recovery_mode: bool, recovery_command: Optional[str]):
    """Failure bookkeeping for one failed tool message.

    Returns (failure_text, updates) where updates carries the deltas/state
    the node applies:
        tool_failures_inc / recovery_attempts_inc (ints)
        recovery_mode / recovery_command (new state)
    """
    updates = {
        "tool_failures_inc": 1,
        "recovery_attempts_inc": 0,
        "recovery_mode": recovery_mode,
        "recovery_command": recovery_command,
        "env_failure": classify_env_failure(result),
    }

    if tool_name == "run_terminal":
        command = tool_args.get("command", "unknown command")
        updates["recovery_attempts_inc"] = 1
        if not recovery_mode:
            updates["recovery_mode"] = True
            updates["recovery_command"] = command
        failure = (
            f"Command failed: {command}\n"
            f"Actual tool output:\n{result[-_FAILURE_RESULT_TAIL:]}"
        )
    elif tool_name == "check_terminal":
        process_id = tool_args.get("process_id", "unknown")
        updates["recovery_attempts_inc"] = 1
        if not recovery_mode:
            updates["recovery_mode"] = True
            updates["recovery_command"] = f"process:{process_id}"
        failure = (
            f"Terminal process failed: {process_id}\n"
            f"Actual tool output:\n{result[-_FAILURE_RESULT_TAIL:]}"
        )
    else:
        if recovery_mode:
            updates["recovery_attempts_inc"] = 1
        failure = f"Tool failed: {tool_name}"

    return failure, updates


def command_fingerprint(tool_name: str, tool_args: dict) -> Optional[str]:
    """R3-1: stable fingerprint of a (presumed to be failing, retried)
    command so progress_node can cap identical retries.

    Terminal.execute_code both take a `command` arg (execute_code on some
    providers uses `code` instead). Crawls the dict for the first string
    arg keyed `command`/`code`/`cmd`, normalizes incidental whitespace, and
    returns the lower-cased marker. Returns None when there is nothing
    command-like (call can never be capped because it has no retry-able
    identity).
    """
    candidate: Optional[str] = None
    for key in ("command", "code", "cmd", "script"):
        if tool_args.get(key):
            candidate = tool_args.get(key)
            break
    if not candidate:
        return None
    return re.sub(r"\s+", " ", str(candidate)).strip().lower()


IDENTICAL_FAILURE_NUDGE = (
    "You have now failed the same {tool_name} command {count} times in a "
    "row. Retrying it a fourth time is very likely to fail identically. "
    "Stop this loop NOW: pick a different command, a different tool, a "
    "different approach, or ask a human."
)


def read_fingerprint(tool_name: str, tool_args: dict, result: str) -> Optional[str]:
    """Stable identity for a successful read-only observation.

    A repeated successful read can still be a no-progress loop: the tool keeps
    returning the same fact while the model misinterprets it. Include the
    result digest so a changed file/listing is a genuinely new observation.
    """
    if tool_name not in {"list_files", "read_file", "search_code"}:
        return None
    import hashlib
    import json
    args = json.dumps(tool_args or {}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(str(result).encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"read:{tool_name}:{args}:{digest}"


IDENTICAL_READ_NUDGE = (
    "NO-PROGRESS GUARD: {tool_name} has returned the same successful result "
    "{count} times. Do NOT call it again. Trust the result already in context "
    "and perform the next mutating deliverable, verification step, replan, or "
    "ask the user if the result is genuinely ambiguous."
)


def maybe_replan(task: str, plan: list, failure: str,
                 provider: str, model: str):
    """Consult the replanner (failure + non-empty plan only).

    Returns (replan_needed, usages) — usages for token accounting; the
    empty-plan case short-circuits without touching the LLM path.
    """
    if not plan:
        return False, []
    usages: list = []
    needed = should_replan(
        task=task,
        plan=plan,
        failure=failure,
        provider=provider,
        model=model,
        usage_list=usages,
    )
    return needed, usages


def success_step_label(tool_name: str, tool_args: dict,
                       tool_call_id: str):
    """The human label for a successful tool, plus the events the node
    must emit (returned as data so helpers stay side-effect-free).

    Returns (label, events) where events is a list of (name, payload).
    """
    events: list[tuple[str, dict]] = []

    if tool_name == "read_file":
        label = f"Read file: {tool_args.get('path', 'unknown')}"
    elif tool_name == "write_file":
        path = tool_args.get("path", "unknown")
        label = f"Wrote file: {path}"
        content = tool_args.get("content", "")
        events.append(("diff.show", {
            "file": path,
            "lines": content.split("\n")[:20],
        }))
        events.append(("files.changed", {
            "messageId": tool_call_id,
            "files": [path],
        }))
    elif tool_name == "edit_file":
        path = tool_args.get("path", "unknown")
        label = f"Edited file: {path}"
        events.append(("files.changed", {
            "messageId": tool_call_id,
            "files": [path],
        }))
    elif tool_name == "copy_file":
        dest = tool_args.get("destination", tool_args.get("dest", "unknown"))
        src = tool_args.get("source", tool_args.get("src", "unknown"))
        label = f"Copied file: {dest}"
        events.append(("files.changed", {
            "messageId": tool_call_id,
            "files": [dest],
        }))
    elif tool_name == "search_code":
        label = (f"Searched for '{tool_args.get('query', '')}'"
                 f" inside {tool_args.get('path', '.')}")
    elif tool_name == "list_files":
        label = f"Listed files: {tool_args.get('path', '.')}"
    elif tool_name == "run_terminal":
        label = (f"Ran command successfully: "
                 f"{tool_args.get('command', 'unknown command')}")
    elif tool_name == "start_terminal":
        label = (f"Started background command: "
                 f"{tool_args.get('command', 'unknown command')}")
    elif tool_name == "check_terminal":
        label = (f"Terminal process completed successfully: "
                 f"{tool_args.get('process_id', 'unknown')}")
    elif tool_name == "stop_terminal":
        label = (f"Stopped terminal process: "
                 f"{tool_args.get('process_id', 'unknown')}")
    else:
        label = f"Completed tool: {tool_name}"

    return label, events


def resolve_recovery_on_success(tool_name: str, tool_args: dict,
                                recovery_mode: bool,
                                recovery_command: Optional[str]):
    """Same-operation rule: a run_terminal success clears recovery only
    when its command IS the stored recovery_command."""
    if (
        tool_name == "run_terminal"
        and recovery_mode
        and recovery_command is not None
        and tool_args.get("command", "unknown command") == recovery_command
    ):
        return False, None
    return recovery_mode, recovery_command

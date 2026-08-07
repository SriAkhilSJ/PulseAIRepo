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


def classify_tool_outcome(tool_name: str, result: str) -> str:
    """The success/failure/skip verdict, preserving every legacy fork."""
    result_lower = result.lower()

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

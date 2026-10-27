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
  recovery_attempts increments for terminal/run_terminal/check_terminal
  failures, and for other tools ONLY while already in recovery_mode;
  recovery_mode/recovery_command are set by the FIRST run/check failure
  (later failures do not steal the command slot);
- success on terminal/run_terminal clears recovery ONLY when the command
  equals the stored recovery_command (same-operation rule);
- write_file successes emit diff.show + files.changed; edit_file emits
  files.changed; no other tool emits events;
- step labels are deduped by exact string before appending;
- replan is consulted only on failure AND a non-empty plan.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from langchain_core.messages import ToolMessage

from src.agents.planner import update_plan_from_tool

# Shown to the model after any tool result (kept byte-identical to the
# pre-D9 inline string).
PROGRESS_REFLECTION_PROMPT = (
    "You just received a tool result. Take a moment to evaluate it:\n"
    "- Did the tool succeed or fail?\n"
    "- Does the output match what you expected?\n"
    "- Should you proceed, fix something, ask the user, or replan?\n\n"
    "Use verify() when the result needs explicit validation. "
    "Don't verify meta-tools like think(), verify(), or clarify()."
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
    plan_complete: bool,
    env_failures: int,
    pivot_count: int,
    plan_wrap_nudges: int = 0,
) -> str:
    """Pure routing decision for after_progress (unit-testable).

    Old behavior: 3 terminal failures -> recovery_limit (pause for user)
    even when the failures were environmental and a different strategy
    existed. New behavior: repeated environment-level failures route to a
    bounded strategy pivot (MAX_PIVOTS) before giving up.

    Hermes loop law (field 2026-09-05, "Ended incomplete: verify test2
    folder"): the MODEL ends its turn by stopping tool calls — the graph
    never finalizes underneath a live tool batch. The old plan-complete
    shortcut decapitated the model right after it emitted `npm install`
    (the tool result was never fed back), then the finalize stamp called
    the cut "Ended incomplete". Now plan completion gets ONE bounded
    wrap nudge (the grace-call shape hermes uses at budget exhaustion):
    the model is told to deliver its final answer, and only if it keeps
    tooling past that does the shortcut finalize."""
    if recovery_mode and recovery_attempts >= RECOVERY_LIMIT:
        if env_failures >= 2 and pivot_count < MAX_PIVOTS:
            return "pivot"
        return "recovery_limit"
    # (replanner route REMOVED with the engine re-plan consult — hermes has
    # no re-planning component; the model adapts from failure receipts.)
    if plan_complete:
        # Field 2026-09-10: the model KEPT TOOLING past wrap lap 1 (the law's
        # own "only if it keeps tooling past that" clause) and the shortcut
        # then finalized with its last act a tool call — no closing answer
        # ever streamed. Wrap lap 2 is the hermes handle_max_iterations
        # shape: one toolless summary call (ai_node's wrap_summary path),
        # then the shortcut may end the turn.
        return "finalize" if plan_wrap_nudges >= 2 else "finish_gate"
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


def trailing_batch_failed(messages: list) -> bool:
    """True when the model's FINAL tool batch contains an error result.

    Hermes turn semantics: per-tool failures are observations the model
    iterates on — they never by themselves fail the turn. Only a failure
    the model never got past (it is still in the trailing batch at
    finalize time, i.e. unrecovered) marks the turn incomplete. Field
    2026-09-05: a run with two LONG-recovered failures (a mis-typed
    read_file path, a bad CLI flag — both retried successfully) was
    stamped "Ended incomplete" by the failed_steps history alone, while
    the actual last action (npm install) was cut mid-flight by routing.
    """
    latest = latest_tool_messages(messages)
    return any(
        _ERROR_MARKER_RE.search(str(getattr(m, "content", "") or ""))
        for m in latest
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
        # "No tsconfig" / "typescript missing" is an unavailable check, not
        # a failed implementation. Test5-5 classified this no-op as failure
        # three times and paid a KEEP/REPLAN model call after each one. Keep it
        # out of failure/replan accounting; the tool's own message already
        # tells the main model what prerequisite is absent.
        if result.lstrip().startswith("ℹ️"):
            return OUTCOME_SKIP
        # Compiler invocation is evidence only when it explicitly returns the
        # green receipt. Unicode status markers are part of the tool contract.
        failed = not result.lstrip().startswith("✅")
    elif tool_name in {"verify_ui_workspace", "verify_ui_routes"}:
        failed = not result.lstrip().startswith("✅")
    elif tool_name in {"verify_target_app", "build_target"}:
        # Target receipts carry their own verdict prefixes (✅ passed, ❌ failed,
        # ⛔ unavailable toolchain/host, 🧭 plan preview). An unavailable or
        # preview receipt is an operator/tooling fact, NOT a failed repair loop:
        # counting it as failure arms recovery and burns a REPLAN call per turn.
        stripped = result.lstrip()
        if stripped.startswith(("⛔", "🧭")):
            return OUTCOME_SKIP
        failed = not stripped.startswith("✅")
    elif tool_name in {"device_action", "device_screenshot", "device_logs", "device_ui"}:
        failed = result.lstrip().startswith("❌")
    elif tool_name in {"detect_targets", "check_target_toolchains"}:
        # Informational: never a failure, whatever the report says.
        return OUTCOME_SKIP
    elif tool_name in ("run_terminal", "terminal"):
        # A promoted foreground call (over-cap timeout) returns the tracked-
        # background spawn receipt: no verdict exists yet — the process is
        # running under a process id and check_terminal is the verdict
        # channel. Same law as check_terminal's "status: running" below.
        # Field 2026-09-08: `npm run build` with timeout 120000 promoted and
        # printed "Process started. / Process ID: …", and this branch painted
        # it ❌ failed 0.0s in — arming recovery for a live process.
        if (result.lstrip().startswith("Process started.")
                and "process id:" in result_lower
                and "exit code:" not in result_lower):
            return OUTCOME_SKIP
        # `terminal` is bound as the verbatim alias of run_terminal (hermes
        # tool-name parity) — same tool, so the SAME verdict rules. Field
        # 2026-09-08 (44ed3687): the guard refused the alias's `npm run dev`
        # and the receipt printed "✅ Ran command successfully" — a refusal
        # carried no "exit code: 0" envelope, and the alias name missed the
        # run_terminal branch. The refusal is NOT a success.
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
    for key in ("path", "command", "query", "process_id", "url"):
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

    if tool_name in {"run_terminal", "terminal"}:
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
    if tool_name not in {"list_files", "read_file", "search_files", "search_code"}:
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


# ---------------------------------------------------------------------
# TURN-SCOPED TOOL-CYCLE GUARD
# ---------------------------------------------------------------------
# Source-backed thresholds and shape:
# - Cline warns after 3 identical calls and hard-stops at 5.
# - Gemini CLI recognizes repeating tool patterns of length 1..5.
# PulseAI adds the observed outcome to the fingerprint: an edit/test cycle is
# blocked only when names, arguments, statuses, AND results repeat. A changed
# edit or changed test output is debugging progress, not a loop.
TOOL_CYCLE_SOFT_REPETITIONS = 3
TOOL_CYCLE_HARD_REPETITIONS = 5
TOOL_CYCLE_MAX_LENGTH = 5
TOOL_CYCLE_HISTORY_LIMIT = TOOL_CYCLE_HARD_REPETITIONS * TOOL_CYCLE_MAX_LENGTH

TOOL_CYCLE_NUDGE = (
    "TRAJECTORY LOOP GUARD: the same {length}-action sequence has produced "
    "the same outcomes {repetitions} times ({tools}). Stop repeating this "
    "sequence. Use the observations already in context and choose a materially "
    "different action or strategy. If no different safe action exists, explain "
    "the blocker and ask the user instead of retrying."
)


def tool_cycle_sample(
    tool_name: str,
    tool_args: dict,
    result: str,
    *,
    failed: bool,
) -> dict[str, str]:
    """Return a privacy-safe identity for one completed tool action.

    The sample retains only the non-secret tool name and a SHA-256 digest. The
    digest covers canonical arguments plus the complete observed result and
    outcome, so reordered dict keys compare equal while changed evidence breaks
    a candidate cycle immediately.
    """
    tool = str(tool_name)
    status = "failed" if failed else "success"
    canonical_args = json.dumps(
        tool_args or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    # Feed each field incrementally. In particular, do not embed a potentially
    # large result in another JSON string (which would allocate/escape a second
    # full copy merely to hash it). Retained state is still one fixed digest.
    digest = hashlib.sha256()
    for value in (tool, canonical_args, status, str(result)):
        encoded = value.encode("utf-8", errors="replace")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return {
        "tool": tool,
        "fingerprint": digest.hexdigest(),
    }


def append_tool_cycle_sample(
    history: list[dict[str, str]],
    sample: dict[str, str],
) -> list[dict[str, str]]:
    """Append one sample under the same 5 cycles × 5 actions hard bound."""
    bounded = [
        {
            "tool": str(item.get("tool", "")),
            "fingerprint": str(item.get("fingerprint", "")),
        }
        for item in history
        if isinstance(item, dict) and item.get("fingerprint")
    ]
    if sample.get("fingerprint"):
        bounded.append({
            "tool": str(sample.get("tool", "")),
            "fingerprint": str(sample["fingerprint"]),
        })
    return bounded[-TOOL_CYCLE_HISTORY_LIMIT:]


def detect_tool_cycle(
    history: list[dict[str, str]],
    *,
    minimum_repetitions: int = TOOL_CYCLE_SOFT_REPETITIONS,
) -> dict[str, Any] | None:
    """Detect a repeated trailing cycle of one to five completed actions.

    Shortest cycles win, so A/A/A reports length 1 and A/B/A/B/A/B reports
    length 2. Only the trailing trajectory matters: any different action or
    outcome breaks the run naturally without a special reset heuristic.
    """
    samples = [
        item for item in history
        if isinstance(item, dict) and str(item.get("fingerprint", ""))
    ][-TOOL_CYCLE_HISTORY_LIMIT:]
    fingerprints = [str(item["fingerprint"]) for item in samples]
    total = len(fingerprints)
    minimum = max(2, int(minimum_repetitions))

    for length in range(1, TOOL_CYCLE_MAX_LENGTH + 1):
        if total < length * minimum:
            continue
        cycle = fingerprints[-length:]
        repetitions = 1
        cursor = total - (2 * length)
        while cursor >= 0 and fingerprints[cursor:cursor + length] == cycle:
            repetitions += 1
            cursor -= length
        if repetitions < minimum:
            continue
        tools = [str(item.get("tool", "unknown")) for item in samples[-length:]]
        signature = hashlib.sha256("|".join(cycle).encode("ascii")).hexdigest()[:16]
        return {
            "signature": signature,
            "length": length,
            "repetitions": repetitions,
            "tools": tools,
            "hard_stop": repetitions >= TOOL_CYCLE_HARD_REPETITIONS,
        }
    return None


_DETERMINISTIC_KEEP_MARKERS = (
    "blocked (safety policy)",
    "phase policy denied",
    "posix-only shell",
    "does not exist on this windows environment",
    "nothing to typecheck",
    "no tsconfig.json",
)


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
    elif tool_name in ("search_files", "search_code"):
        label = (f"Searched for '{tool_args.get('pattern') or tool_args.get('query', '')}'"
                 f" inside {tool_args.get('path', '.')}")
    elif tool_name == "list_files":
        label = f"Listed files: {tool_args.get('path', '.')}"
    elif tool_name in ("run_terminal", "terminal"):
        # `terminal` is bound as the verbatim alias of run_terminal (hermes
        # tool-name parity) — its receipt gets the same human label.
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
        # Distinguish repeats: a bare tool name dedupes identical labels
        # (field 2026-09-08: the second read_terminal_output's receipt
        # vanished under the first). Anchor with the call's distinguishing
        # argument — path/command/query/process_id/url.
        anchor = tool_memory_anchor(tool_args)
        label = f"Completed tool: {tool_name}"
        if anchor:
            label = f"{label} ({anchor})"

    return label, events


def resolve_recovery_on_success(tool_name: str, tool_args: dict,
                                recovery_mode: bool,
                                recovery_command: Optional[str]):
    """Same-operation rule: a terminal-equivalent success clears recovery
    only when its command IS the stored recovery_command."""
    if (
        tool_name in {"run_terminal", "terminal"}
        and recovery_mode
        and recovery_command is not None
        and tool_args.get("command", "unknown command") == recovery_command
    ):
        return False, None
    return recovery_mode, recovery_command

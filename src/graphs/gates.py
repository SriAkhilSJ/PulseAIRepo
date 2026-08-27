# src/graphs/gates.py
"""
Routing + verification gate machinery (P0-D extraction from chat_graph.py).

This is the densest pure-logic cluster in the graph: should_continue (the ai
node's exit router), the bounded finish/verify nudges, and finish_gate_node.
Every function here is a pure (state -> decision | state-dict) transform — no
singletons, no LLM calls, no side effects — which is exactly why it was the
first cluster worth pulling out of the 2,900-line god-file (it is now
navigable and unit-testable in isolation).

Layering: gates <- state, budget (budget provides _budget_exhausted).
"""
from __future__ import annotations

import re

import os
import re
from pathlib import Path

from langchain_core.messages import SystemMessage, ToolMessage

from src.graphs.state import AgentState
from src.graphs.budget import _budget_exhausted


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
_INCOMPLETE_RESPONSE_RETRY_BUDGET = 3

_INCOMPLETE_RESPONSE_NUDGE = (
    "[System: The provider hit its output limit before returning a complete "
    "response. Continue from a clean boundary without repeating prior work. "
    "Keep the next response small. If a tool action was intended, reissue one "
    "complete, valid tool call; no partial tool call was executed.]"
)

_FINISH_NUDGE = (
    "[System: You declared the task finished, but almost no real work has "
    "been done — few or no tool calls have executed and the deliverable does "
    "not exist yet. This is an execution task: do not summarize, do not ask "
    "questions, do not repeat this finish message. Make the tool call you "
    "were planning right now (write the file, run the command, build the "
    "artifact) and keep going until the deliverable actually exists.]"
)

# E2-specific finish nudge: a copy/compose task names its deliverable files
# (e.g. "Copy-paste this component to /components/ui ... hero-futuristic.tsx
# and demo.tsx"). When the task carries that shape and nothing was written/
# copied, the nudge must NAME the copy operation and the provided source —
# the E2 model ignored a generic instruction but a specific one
# ("use copy_file _provided/hero-futuristic.tsx -> src/components/ui/") is
# a step it cannot mistake for something else.
_COPY_TASK_MARKERS = (
    "copy-paste", "copy paste", "copy_file", "copy ",
    "/components/ui", "components/ui", "place this file",
)
_COPY_NUDGE = (
    "[System: This task is a copy/compose task — its deliverable is one or "
    "more EXISTING files to be placed at a specific path, and none of them "
    "has been written or copied yet. Do NOT retry scaffold/init commands "
    "and do NOT reinstall dependencies; those are done. If the file is "
    "provided in the workspace (e.g. under _provided/), place it with the "
    "copy_file tool (copy_file src=<provided path> dst=<target path>) so "
    "the content is byte-for-byte. If no source is provided, write_file the "
    "named component at the target path. Then run typecheck_workspace and "
    "finish only when the files exist on disk.]"
)

_ARTIFACT_NUDGE = (
    "[System: The user requested a named deliverable, but that artifact does "
    "not exist on disk yet. Scope is a general IDE agent: produce the actual "
    "file, not a description or a code block. Use the appropriate workspace "
    "tool or execute_code/terminal workflow for its format, then verify that "
    "the exact requested path exists and is non-empty before finishing. If "
    "the format cannot be produced in this environment, report the concrete "
    "blocker instead of claiming completion.]"
)


def _looks_like_copy_task(task: str) -> bool:
    t = (task or "").lower()
    return any(marker in t for marker in _COPY_TASK_MARKERS)


_NAMED_DELIVERABLE_EXTENSIONS = (
    # Code and project text
    "tsx", "ts", "jsx", "js", "py", "css", "html", "json", "md", "mdx",
    "yaml", "yml", "toml", "xml", "sql", "sh", "ps1",
    # Scope IDE's non-coding artifact surface
    "txt", "csv", "tsv", "svg", "png", "jpg", "jpeg", "webp",
    "pdf", "docx", "xlsx", "pptx", "mp3", "wav", "mp4",
)
_NAMED_DELIVERABLE_RE = re.compile(
    r"[A-Za-z0-9_./\\-]+\.(?:" + "|".join(_NAMED_DELIVERABLE_EXTENSIONS) + r")\b",
    re.IGNORECASE,
)
_NON_CODE_ARTIFACT_EXTENSIONS = frozenset({
    ".txt", ".csv", ".tsv", ".svg", ".png", ".jpg", ".jpeg", ".webp",
    ".pdf", ".docx", ".xlsx", ".pptx", ".mp3", ".wav", ".mp4",
})


def _deliverable_targets(task: str) -> list[str]:
    """Explicit named outputs for code *and* general IDE artifact tasks."""
    targets: list[str] = []
    for m in _NAMED_DELIVERABLE_RE.finditer(task or ""):
        name = m.group(0).strip().strip("/\\")
        if name not in targets:
            targets.append(name)
    return targets

# Verify gate (Test-2 fix): an execution task that WROTE code files but
# never ran a verification tool must not finalize. Test 2 shipped ~15
# syntax/type bugs because writes were blind — nothing forced a check
# before the agent declared itself done.
_VERIFY_NUDGE_BUDGET = 2

_VERIFY_TOOL_NAMES = frozenset({
    "typecheck_workspace", "verify_ui_workspace", "verify_ui_routes", "run_terminal",
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_click", "browser_type",
})

# UI/frontend deliverables: for these, typecheck alone proves nothing at
# runtime (Test-2 retest D5: tsc passed while the app 500'd on a missing
# "use client"). The agent must have DRIVEN A REAL BROWSER. Matching is
# word-based on purpose: a naive substring "ui" also hits inside "build".
_UI_TASK_PHRASES = (
    "web app", "web application", "webapp", "chat app", "chatbot",
    "user interface", "frontend app", "front-end app", "next.js app",
    "nextjs app", "react app", "single page app", "build ui", "create ui",
    "ui/ux", "render in browser", "visual proof",
)
# Runtime proof is mandatory only when the task asks for a rendered surface.
# Merely copying or refactoring a React *component* is a static integration task
# unless the user also asks to render/preview/screenshot it.
_UI_TASK_WORDS = {
    "app", "browser", "dashboard", "page", "website", "screenshot", "preview",
}

_VERIFY_NUDGE = (
    "[System: You wrote code files but never verified them. You must not "
    "finish an execution task with unverified code — run a verification "
    "tool right now. For TypeScript/JS projects run typecheck_workspace "
    "(tsc --noEmit). For a UI/frontend deliverable that is NOT enough: prefer "
    "ONE verify_ui_workspace call, which deterministically typechecks, starts "
    "the app, navigates, snapshots, captures a screenshot, rejects near-blank "
    "proof, and cleans up. Use individual browser tools only for interactive "
    "flows that need browser_type/browser_click. Fix any errors BEFORE "
    "finishing, then re-verify until it passes.]"
)

# Test-2 hardening: a verification tool that RAN but FAILED is not
# verification. The gate accepts only a passing (✅) or skip (ℹ️ — no
# tsconfig / typescript not installed) typecheck result. Failure markers
# cover the ❌ errors-found shape AND the ⚠️ timeout/unparsed shapes (a
# check that cannot prove a clean build proves nothing). For UI tasks a
# browser check that returns NO rendered content is the same class of
# failure (D6: snapshot came back {"title":"","text":""}, screenshot
# timed out, yet the agent declared Finished on a page that 500'd).
_VERIFY_FAILED_NUDGE = (
    "[System: Your verification did NOT pass — fix it before finishing. "
    "If typecheck_workspace reported errors, fix EVERY error and re-run "
    "it until it returns the ✅ pass message. If this is a UI/frontend "
    "task: a page that 500s, a browser_snapshot that returns empty "
    "content, or a screenshot that times out means the app has NOT "
    "rendered — wait for the dev server to finish compiling (the first "
    "Next.js compile can take 30s+), re-navigate, and re-snapshot until "
    "you see the actual UI text. Only then finalize.]"
)

_VERIFY_FAIL_MARKERS = ("❌ typecheck_workspace:", "⚠️ typecheck_workspace:")

# browser_navigate results that prove the page FAILED to serve — a tsc pass
# does not cancel these out; a 500 page is unverified UI regardless of
# static analysis (Test-2 retest D5 shipped exactly this bug: tsc clean,
# GET / = 500, missing "use client").
_BROWSER_FAIL_MARKERS = (
    "net::ERR", "failed to navigate", "page crashed", "http 500",
    "status of 500", "internal server error", "application error",
    "error occurred", "server responded with a status of 500",
)

_CODE_EXT_MARKERS = (".tsx", ".ts", ".jsx", ".js", ".py", ".json", ".css", ".html")


def _looks_like_execution_task(task: str) -> bool:
    t = (task or "").lower()
    return any(marker in t for marker in _EXECUTION_TASK_MARKERS)


# Tools that produce the DELIVERABLE — the finish gate's "real work" bar.
# The bar is deliberately NARROW: only calls that create or mutate the
# artifact count. Introspection/scratchpad calls (think, list_files,
# read_file, search_code, session_search) do NOT count, and crucially
# neither do run_terminal / execute_code — E2 (Test-3 retest) burned 13
# shadcn-CLI iterations through run_terminal and wrote ZERO component
# files, then declared Finished. Shell/proof calls are handled by the
# verify gate below; the finish gate exists to catch "ran stuff, delivered
# nothing" (the D4 bypass, still open through the non-file tools).
_WORK_TOOLS = frozenset({
    "write_file", "edit_file", "copy_file",
})

# R3-4: the evidence ledger classifies the task as
#   unverified — no verification ran, or the last result failed;
#   stale     — verification PASSED but code was edited afterwards;
#   passed    — verification passed and nothing was edited after it.
UNVERIFIED = "unverified"
STALE = "stale"
PASSED = "passed"


def _tool_call_count(state: AgentState) -> int:
    return sum(
        1 for m in state.get("messages", [])
        if any(tc.get("name") in _WORK_TOOLS
               for tc in (getattr(m, "tool_calls", None) or []))
    )


# =========================================================
# R3-4 EVIDENCE LEDGER — stop semantics
# =========================================================
# Minimal DNA of verification_evidence.py (Hermes evidence ledger):
# the ledger is a state-carried map from named deliverable targets to
# their verification classification, keyed by how the deliverable was
# produced:
#   mark_edited(paths)      on write/edit/copy — evidence goes stale;
#   verification_result()   on a tool result that proves soundness —
#   evidence becomes passed for any file that exists on disk.
# verification_status exposes one of {unverified, stale, passed}; the
# finalize gate below requires passed or nudge-bound, so "✅ Finished"
# with zero on-disk deliverables is structurally impossible even on the
# budget-exhausted grace path.

def _marked_edited(state: AgentState) -> list[str]:
    """Paths the run has written/edited/copied (mark_edited).
    Grows monotonically; order is insertion order."""
    return list(state.get("marked_edits", []))


def _evidence_for(state: AgentState, path: str) -> str:
    """Classification for ONE deliverable on the ledger:
    passed if a passing verification result exists, else unverified
    (stale is computed at the gate level: any edit after a pass
    downgrades the WHOLE ledger, matching the copy-task shape where the
    two files are delivered together)."""
    if _verification_ran_and_passed(state):
        return PASSED
    return UNVERIFIED


def _verification_ran_and_passed(state: AgentState) -> bool:
    """True only when every task-required verification receipt is fresh.

    A lone passing typecheck cannot prove a UI task, and invoking a browser
    tool is not evidence unless navigate, non-empty snapshot, and a meaningful
    saved screenshot all succeeded after the last mutation.
    """
    return _verification_receipt_status(state)["passed"]


def _edits_after_last_pass(state: AgentState) -> bool:
    """R3-4 staleness: a pass followed by any edit/copy invalidates the
    evidence — the passing result described a DIFFERENT file state.
    Scans execution_trace (ordered, always appended pre-outcome) for the
    newest work-tool entry that succeeded; if it postdates the newest
    passing verification message, the ledger is stale."""
    last_pass_index = -1
    for i, m in reversed(list(enumerate(state.get("messages", [])))):
        if not isinstance(m, ToolMessage):
            continue
        name = getattr(m, "name", "")
        content = str(getattr(m, "content", "") or "")
        if name == "typecheck_workspace":
            if content.startswith(_VERIFY_FAIL_MARKERS) or content.startswith("ℹ️"):
                return False  # newest verification result failing stops scan
            last_pass_index = i
            break
    if last_pass_index == -1:
        return False
    for m in state.get("messages", [])[last_pass_index + 1:]:
        if isinstance(m, ToolMessage) and getattr(m, "name", "") in _WORK_TOOLS:
            return True
    return False


def verification_status(state: AgentState) -> str:
    """Exposed ledger status for the gating decision (R3-4)."""
    if not _wrote_code_files(state):
        return UNVERIFIED
    if _edits_after_last_pass(state):
        return STALE
    if _verification_ran_and_passed(state):
        return PASSED
    return UNVERIFIED


# =========================================================
# E2-1 NAMED DELIVERABLE ON-DISK CHECK
# =========================================================
# Test-3 E2 named explicit deliverable paths in the task
# ("src/components/ui/hero-futuristic.tsx", "demo.tsx") and still
# ""Finished" with zero files. The verify gate only proves the code that
# WAS written sound; it proves nothing about a named file that was never
# created. Before finalize, when the task names deliverable targets and
# NONE exist on disk, redirect to finish_gate with the E2 copy nudge
# (extended from copy-only to any named-file deliverable, MDX-style
# tasks).
_WRITE_EXT_MARKERS = _CODE_EXT_MARKERS  # reuse: .tsx/.ts/... from verify gate


def _deliverables_missing_on_disk(state: AgentState, workspace: str = ".") -> list[str]:
    """The named deliverable targets from the task that do NOT exist on
    disk under `workspace`. Empty list = no named targets or all present.

    Deliberately conservative to avoid false positives: a bare filename
    in prose ("build a chat app with Next.js" would otherwise match
    "Next.js") only counts as a named deliverable for COPY tasks — where
    the whole point is placing one specific file. Non-copy (MDX-style)
    tasks must name a PATH containing a slash, e.g.
    "src/components/ui/hero-futuristic.tsx".

    Disk I/O is the outcome-checking exception to gates' purity: E2's
    failure was a run that proudly finished with 0 files — the only way
    to detect that is to look. Read-only, never raises (an unreadable
    workspace treats targets as missing rather than crashing the gate).
    """
    task = state.get("current_task", "")
    is_copy = _looks_like_copy_task(task)
    missing: list[str] = []
    for target in _deliverable_targets(task):
        if not target:
            continue
        if not is_copy and "/" not in target and "\\" not in target:
            # A bare code-ish filename in prose can be a library/version token
            # (the historical `Next.js` false positive), so keep requiring a
            # path for code. A requested non-code artifact such as report.pdf,
            # analysis.xlsx, or slides.pptx is unambiguously a deliverable and
            # should be protected even at the workspace root.
            if Path(target).suffix.lower() not in _NON_CODE_ARTIFACT_EXTENSIONS:
                continue
        exists = False
        for cand in _deliverable_candidates(workspace, target):
            try:
                if cand.is_file():
                    exists = True
                    break
            except OSError:
                continue
        if not exists:
            missing.append(target)
    return missing


def _named_deliverables_exist(state: AgentState, workspace: str = ".") -> bool:
    """True when the task names eligible outputs and every one exists.

    This lets a general Scope task create a binary artifact through
    execute_code/terminal without being falsely treated as "no work" merely
    because the delivery-only work counter intentionally excludes shell calls.
    """
    task = state.get("current_task", "")
    is_copy = _looks_like_copy_task(task)
    eligible: list[str] = []
    for target in _deliverable_targets(task):
        has_dir = "/" in target or "\\" in target
        if not is_copy and not has_dir:
            if Path(target).suffix.lower() not in _NON_CODE_ARTIFACT_EXTENSIONS:
                continue
        eligible.append(target)
    if not eligible:
        return False
    for target in eligible:
        if not any(candidate.is_file() for candidate in _deliverable_candidates(workspace, target)):
            return False
    return True


def _deliverable_candidates(workspace: str, target: str):
    """The workspace-relative paths a named target could live at. A
    bare filename in the task may appear at the workspace root or under
    a few common source dirs; a path-like target is checked verbatim."""
    import os as _os

    ws = Path(workspace)
    candidates = [
        ws / target,
        Path(str(ws), target.lstrip("/\\").replace("\\", "/")),
    ]
    bare = Path(target).name
    _has_dir = ("/" in target) or ("\\" in target)
    if bare and not _has_dir:
        # Bare filename (no directory). A copy/compose task often names its
        # deliverable only by filename (e.g. "demo.tsx") while the
        # instruction places it under a known output dir. Check those dirs
        # too, otherwise the on-disk check reports a placed file as
        # forever-missing and either deadlocks or lets the run finalize with
        # the artifact unverified (R3-2 / Test-3 retest).
        for sub in (
            "src", "components", "app", "lib",
            "src/components/ui", "components/ui",
            "src/components", "components",
            "src/app", "app/components", "src/ui", "ui",
        ):
            candidates.append(ws / sub / bare)
    return candidates


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if bool(getattr(last_message, "additional_kwargs", {}).get("pulse_cancelled")):
        return "finalize"

    # A token-limited text response is not a final answer. Tool-bearing
    # incomplete responses route through SafeToolNode for paired rejection;
    # text-only responses receive the bounded finish-gate continuation nudge.
    if (
        bool(getattr(last_message, "additional_kwargs", {}).get(
            "pulse_incomplete_response"
        ))
        and not getattr(last_message, "tool_calls", None)
        and not _budget_exhausted(state)
    ):
        if state.get("incomplete_response_retries", 0) <= _INCOMPLETE_RESPONSE_RETRY_BUDGET:
            return "finish_gate"
        return "finalize"

    # Ask mode never binds tools. Its first complete text response is the
    # answer; execution and verification nudges must not turn it into Agent.
    if state.get("execution_mode") == "ask":
        return "finalize"

    # ── Hermes loop law (ported, behavior-based) ─────────────────────────
    # Two mechanical guards that no intent classifier can misroute around:
    #
    # 1. NO-PROGRESS TURN END: a model that keeps replying WITHOUT tool
    #    calls is answering, not working. The bounded finish/verify nudges
    #    below still get their shot, but after NO_TOOL_TURN_LIMIT
    #    consecutive no-tool assistant replies the turn CONCLUDES — the
    #    measured 20-lap turn ($0.12 for one question) came from a plan
    #    loop no intent gate could see; this cap makes the class
    #    structurally impossible.
    # 2. REPETITION CONTENT-SANITY: a degenerate model echoing one fragment
    #    (hermes #86581: a 60k-char turn of repeated text) must never be
    #    fed back for another lap — conclude with what exists.
    from src.graphs.loop_guards import (
        NO_TOOL_TURN_LIMIT,
        consecutive_no_tool_ai_messages,
        is_repetition_dominated,
    )
    if not getattr(last_message, "tool_calls", None):
        _no_tool_streak = consecutive_no_tool_ai_messages(state.get("messages", []))
        _repetition = is_repetition_dominated(
            str(getattr(last_message, "content", "") or "")
        )
        if _repetition or _no_tool_streak >= NO_TOOL_TURN_LIMIT:
            return "finalize"

    # D40: once the ai iteration budget is spent, this run must conclude.
    # The grace call produced a text answer (or a tool_call the no-tools
    # binding prevented) — finalize it instead of re-entering gates that
    # would push the model to work it can no longer do.
    # R3-4: even on the budget-exhausted grace route, "Finished" with a
    # NAMED deliverable that does not exist (or code that was never
    # verified) is blocked once — bounded by the nudge budgets so the
    # run still concludes rather than looping on a grace path that has
    # no tools to do the work.
    if _budget_exhausted(state):
        if (state.get("finish_nudges", 0) < _FINISH_NUDGE_BUDGET
                and _deliverables_missing_on_disk(state, state.get("workspace", "."))):
            return "finish_gate"
        if (_wrote_code_files(state)
                and state.get("verify_nudges", 0) < _VERIFY_NUDGE_BUDGET
                and verification_status(state) != PASSED):
            return "finish_gate"
        return "finalize"

    if getattr(last_message, "tool_calls", None):
        return "tools"

    # Finish gate: an execution task that ends with NO deliverable-producing
    # tool call is an early stop, not completion (probe/scratchpad calls like
    # think/list_files don't count as work). Nudge once (bounded via
    # finish_nudges) so the model actually acts; after the budget, allow
    # finalize.
    if state.get("finish_nudges", 0) < _FINISH_NUDGE_BUDGET:
        if _looks_like_execution_task(state.get("current_task", "")):
            if (
                _tool_call_count(state) < 1
                and not _named_deliverables_exist(
                    state, state.get("workspace", ".")
                )
            ):
                return "finish_gate"

    # Verify gate: code files were written but the code is NOT proven
    # sound — either no verification tool ran, or the last verification
    # result reported failure. A check that ran and failed is as
    # unsatisfied as no check at all (Test-2 hardening).
    # (Bounded via verify_nudges; both gates share the finish_gate node,
    # which picks the right nudge + counter.)
    if _verify_unsatisfied(state):
        return "finish_gate"

    # E2-1: the task NAMES deliverable files that must exist on disk before
    # finalize. Writes that typecheck but never produce the named artifact
    # are not a working deliverable.
    #
    # For COPY/COMPOSE tasks the deliverable is a trivial copy_file away, so
    # "✅ Finished" with zero named files is made STRUCTURALLY impossible:
    # route to finish_gate every turn until the files exist — independent of
    # the finish-nudge budget (the iteration budget's grace path still
    # force-finalizes, so this cannot loop forever). This closes the hole
    # that let the Test-3 retest escape with an empty deliverable: after two
    # generic finish nudges the old code allowed finalize even though the
    # named components were never placed.
    #
    # Non-copy named-deliverable tasks keep the bounded nudge so a
    # legitimately unplaceable file cannot deadlock the run.
    _missing = _deliverables_missing_on_disk(state, state.get("workspace", "."))
    if _missing:
        _is_copy = _looks_like_copy_task(state.get("current_task", ""))
        if _is_copy or state.get("finish_nudges", 0) < _FINISH_NUDGE_BUDGET:
            return "finish_gate"

    return "finalize"


def _verify_unsatisfied(state: AgentState) -> bool:
    """True when the bounded verify gate must fire: an execution task
    where code was written but not proven sound.

    Shared by should_continue (ai -> finish_gate) AND after_progress
    (plan-complete shortcut, D7). Without the after_progress check a
    model can self-mark every plan step complete — including
    "verify in browser" it never did — and the plan-complete route goes
    STRAIGHT to finalize, bypassing should_continue entirely (D7:
    typecheck ran once and failed 57 errors, zero browser calls, no dev
    server, yet 8/8 plan steps self-marked and the run finalized clean).
    """
    if state.get("verify_nudges", 0) >= _VERIFY_NUDGE_BUDGET:
        return False
    if not _looks_like_execution_task(state.get("current_task", "")):
        return False
    if not _wrote_code_files(state):
        return False
    return not _ran_verification(state) or _verification_failed(state)


def _wrote_code_files(state: AgentState) -> bool:
    """True when a success step indicates a code file was written/edited."""
    for step in state.get("steps_completed", []):
        low = str(step).lower()
        if (
            "wrote file:" in low
            or "edited file:" in low
            or "copied file:" in low
            or "file written" in low
        ) and any(ext in low for ext in _CODE_EXT_MARKERS):
            return True
    return False


def _fresh_verification_messages(state: AgentState) -> list[ToolMessage]:
    """Verification results after the newest successful workspace mutation."""
    messages = list(state.get("messages", []))
    last_edit = -1
    for i, message in enumerate(messages):
        if isinstance(message, ToolMessage) and getattr(message, "name", "") in _WORK_TOOLS:
            content = str(getattr(message, "content", "") or "").lower()
            if not content.startswith(("error:", "❌")):
                last_edit = i
    return [
        m for m in messages[last_edit + 1:]
        if isinstance(m, ToolMessage) and getattr(m, "name", "") in _VERIFY_TOOL_NAMES
    ]


def _verification_receipt_status(state: AgentState) -> dict[str, object]:
    """Aggregate evidence by domain instead of trusting the newest check.

    This is the stop-semantics analogue of Hermes' passive evidence ledger:
    every required domain must have a fresh successful receipt. Later receipts
    supersede earlier receipts only within their own domain.
    """
    ui_task = _looks_like_ui_task(state.get("current_task", ""))
    receipts = _fresh_verification_messages(state)
    status = {
        "static": False,
        "typecheck": False,
        "integrity": False,
        "navigate": False,
        "snapshot": False,
        "screenshot": False,
    }
    seen: set[str] = set()
    all_messages = list(state.get("messages", []))

    def tool_args(message: ToolMessage) -> dict:
        call_id = getattr(message, "tool_call_id", "")
        for prior in reversed(all_messages):
            for call in getattr(prior, "tool_calls", None) or []:
                if call.get("id") == call_id:
                    return call.get("args") or {}
        return {}

    for message in receipts:
        name = getattr(message, "name", "")
        content = str(getattr(message, "content", "") or "")
        low = content.lower()
        seen.add(name)
        if name in {"verify_ui_workspace", "verify_ui_routes"}:
            passed = content.startswith((
                "✅ UI VERIFICATION PASSED", "✅ UI ROUTE VERIFICATION PASSED"
            ))
            status["static"] = passed
            status["typecheck"] = passed
            status["navigate"] = passed
            status["snapshot"] = passed
            status["screenshot"] = passed
        elif name == "typecheck_workspace":
            passed = content.startswith("✅") and "0 errors" in low
            status["typecheck"] = passed
            status["static"] = passed
        elif name == "run_terminal":
            command = str(tool_args(message).get("command", "")).lower()
            is_check = any(token in command for token in (
                "pytest", " test", "npm test", "typecheck", "tsc ",
                " lint", " build", "cargo check", "go test",
            ))
            if is_check:
                status["static"] = "exit code: 0" in low
        elif name == "browser_navigate":
            status["navigate"] = not any(marker.lower() in low for marker in _BROWSER_FAIL_MARKERS) \
                and ("navigated" in low or "http" in low)
        elif name == "browser_snapshot":
            status["snapshot"] = _snapshot_shows_content(content)
        elif name == "browser_screenshot":
            status["screenshot"] = (
                "screenshot saved" in low
                and "visual quality failed" not in low
                and "timed out" not in low
                and "could not save" not in low
            )

    # A successful command only proves the source tree it actually checked.
    # Catch unresolved workspace-local imports/dependencies (and conservative
    # embedded-shader constants) before that receipt can authorize completion.
    # This read-only audit is intentionally additive: it never substitutes for
    # the executable/static/browser receipts above.
    from src.context.workspace_integrity import audit_workspace
    workspace = state.get("workspace")
    integrity_issues = audit_workspace(workspace) if workspace else []
    status["integrity"] = not integrity_issues

    required = ["static", "integrity"]
    if ui_task:
        required.extend(["navigate", "snapshot", "screenshot"])
    missing = [name for name in required if not bool(status[name])]
    return {
        **status,
        "ui_task": ui_task,
        "required": required,
        "missing": missing,
        "integrity_issues": [issue.describe() for issue in integrity_issues[:20]],
        "ran_any": bool(seen),
        "passed": not missing,
    }


def _ran_verification(state: AgentState) -> bool:
    """Whether any fresh verification receipt exists (quality is separate)."""
    return bool(_verification_receipt_status(state)["ran_any"])


def _looks_like_ui_task(task: str) -> bool:
    t = (task or "").lower()
    if any(p in t for p in _UI_TASK_PHRASES):
        return True
    words = set(re.findall(r"[a-z0-9]+", t))
    return bool(words & _UI_TASK_WORDS)


def _snapshot_shows_content(content: str) -> bool:
    """True when a browser_snapshot result proves the page rendered.

    Snapshot results are JSON; the ToolMessage wraps them with escaped
    quotes, so normalize \\" first. D6's unrendered page came back as
    {"url":..., "title":"", "text":""} — empty title AND empty text
    means the page never painted. Anything else (non-empty title or
    text) is rendering proof.
    """
    norm = content.replace('\\"', '"')
    if '"title":""' in norm and '"text":""' in norm:
        return False
    return bool(re.search(r'"(title|text)":\s*"[^"\n]+', norm))


def _verification_failed(state: AgentState) -> bool:
    """True when one or more required fresh evidence domains are missing."""
    return not bool(_verification_receipt_status(state)["passed"])


def finish_gate_node(state: AgentState) -> dict:
    """Push the model back to work after an early finish declaration.

    Distinguishes the three nudge cases, in priority order:
    - E2-1: the task NAMES deliverable files that don't exist on disk —
      use the E2-specific copy/placement nudge (extends beyond copy tasks
      to any named-file deliverable, MDX-style); the model must produce
      the artifact, not just re-work what exists;
    - verify gate (code written, nothing verified) — prove the code;
    - finish gate (no real work at all) — do some work.
    Each has its own bounded counter so one can never starve the other.
    """
    # Output-limit recovery is mechanical, not an early-finish judgment. It
    # has its own retry counter and does not spend the generic finish budget.
    last = state.get("messages", [])[-1] if state.get("messages") else None
    if bool(getattr(last, "additional_kwargs", {}).get("pulse_incomplete_response")):
        return {"messages": [SystemMessage(content=_INCOMPLETE_RESPONSE_NUDGE)]}

    # E2-1 first: a named deliverable missing on disk is the dominant
    # signal. Even when OTHER code files were written, the task's own
    # target files must exist before finalize.
    missing = _deliverables_missing_on_disk(state, state.get("workspace", "."))
    if missing:
        artifact_only = all(
            Path(path).suffix.lower() in _NON_CODE_ARTIFACT_EXTENSIONS
            for path in missing
        )
        nudge = _ARTIFACT_NUDGE if artifact_only else _COPY_NUDGE
        return {
            "messages": [SystemMessage(content=nudge)],
            "finish_nudges": state.get("finish_nudges", 0) + 1,
        }
    if _wrote_code_files(state) and (
        not _ran_verification(state) or _verification_failed(state)
    ):
        nudge = _VERIFY_FAILED_NUDGE if _verification_failed(state) else _VERIFY_NUDGE
        receipt = _verification_receipt_status(state)
        issues = list(receipt.get("integrity_issues") or [])
        if issues:
            nudge += (
                "\n\n[Deterministic dependency/source audit found unresolved "
                "references. Repair these before re-running verification:\n- "
                + "\n- ".join(issues[:10])
                + "]"
            )
        return {
            "messages": [SystemMessage(content=nudge)],
            "verify_nudges": state.get("verify_nudges", 0) + 1,
        }
    nudge = _FINISH_NUDGE
    if _looks_like_copy_task(state.get("current_task", "")) and not _wrote_code_files(state):
        nudge = _COPY_NUDGE
    return {
        "messages": [SystemMessage(content=nudge)],
        "finish_nudges": state.get("finish_nudges", 0) + 1,
    }

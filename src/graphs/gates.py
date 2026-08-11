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

_FINISH_NUDGE = (
    "[System: You declared the task finished, but almost no real work has "
    "been done — few or no tool calls have executed and the deliverable does "
    "not exist yet. This is an execution task: do not summarize, do not ask "
    "questions, do not repeat this finish message. Make the tool call you "
    "were planning right now (write the file, run the command, build the "
    "artifact) and keep going until the deliverable actually exists.]"
)

# Verify gate (Test-2 fix): an execution task that WROTE code files but
# never ran a verification tool must not finalize. Test 2 shipped ~15
# syntax/type bugs because writes were blind — nothing forced a check
# before the agent declared itself done.
_VERIFY_NUDGE_BUDGET = 2

_VERIFY_TOOL_NAMES = frozenset({
    "typecheck_workspace",
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_click", "browser_type",
})

# UI/frontend deliverables: for these, typecheck alone proves nothing at
# runtime (Test-2 retest D5: tsc passed while the app 500'd on a missing
# "use client"). The agent must have DRIVEN A REAL BROWSER. Matching is
# word-based on purpose: a naive substring "ui" also hits inside "build".
_UI_TASK_PHRASES = (
    "web app", "web application", "webapp", "chat app", "chatbot",
    "user interface", "frontend app", "front-end app", "next.js",
    "nextjs", "react app", "single page app",
)
_UI_TASK_WORDS = {
    "app", "ui", "web", "chat", "frontend", "front-end", "browser",
    "dashboard", "component", "page", "website", "interface", "react",
    "vue", "screenshot",
}

_VERIFY_NUDGE = (
    "[System: You wrote code files but never verified them. You must not "
    "finish an execution task with unverified code — run a verification "
    "tool right now. For TypeScript/JS projects run typecheck_workspace "
    "(tsc --noEmit). For a UI/frontend deliverable that is NOT enough: "
    "start the app (start_terminal, read_terminal_output for the port), "
    "then prove it with the browser tools — browser_navigate to the URL, "
    "browser_snapshot to read what rendered, browser_screenshot for visual "
    "proof, and for chat/forms use browser_type + browser_click. Fix any "
    "errors BEFORE finishing, then re-verify until it passes.]"
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


# Tools that produce or prove the deliverable — the finish gate's "real
# work" bar. Introspection/scratchpad calls (think, list_files, read_file,
# search_code, session_search, check_terminal) do NOT count: a model that
# burns two of those and then declares "Finished" has still delivered
# nothing (Test-2 retest on workspace_d proved exactly this bypass).
_WORK_TOOLS = frozenset({
    "write_file", "edit_file", "run_terminal", "execute_code",
    "typecheck_workspace",
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_click", "browser_type", "browser_select", "browser_hover",
    "browser_evaluate",
    "web_search", "web_fetch",
})


def _tool_call_count(state: AgentState) -> int:
    return sum(
        1 for m in state.get("messages", [])
        if any(tc.get("name") in _WORK_TOOLS
               for tc in (getattr(m, "tool_calls", None) or []))
    )


def should_continue(state: AgentState):
    last_message = state["messages"][-1]

    # D40: once the ai iteration budget is spent, this run must conclude.
    # The grace call produced a text answer (or a tool_call the no-tools
    # binding prevented) — finalize it instead of re-entering gates that
    # would push the model to work it can no longer do.
    if _budget_exhausted(state):
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
            if _tool_call_count(state) < 1:
                return "finish_gate"

    # Verify gate: code files were written but the code is NOT proven
    # sound — either no verification tool ran, or the last verification
    # result reported failure. A check that ran and failed is as
    # unsatisfied as no check at all (Test-2 hardening).
    # (Bounded via verify_nudges; both gates share the finish_gate node,
    # which picks the right nudge + counter.)
    if _verify_unsatisfied(state):
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
        if ("wrote file:" in low or "edited" in low or "file written" in low) and any(
            ext in low for ext in _CODE_EXT_MARKERS
        ):
            return True
    return False


def _ran_verification(state: AgentState) -> bool:
    """True when the agent already called a verification tool this turn.

    Policy-only (hermes verification_stop: "intentionally policy-only...
    requires fresh evidence when the model tries to finish after editing
    code"). The loop never dictates WHICH tool proves the work — the
    persona teaches commensurate choice (typecheck for static soundness;
    a real browser for UI/frontend runtime proof, because a tsc-pass can
    hide a runtime 500 — D5's missing "use client"). The QUALITY of the
    evidence is judged separately by _verification_failed (a ❌ typecheck,
    a 500 navigate, an empty snapshot, or a timed-out screenshot is not
    evidence).
    """
    for m in state.get("messages", []):
        for tc in getattr(m, "tool_calls", None) or []:
            if (tc.get("name") or "") in _VERIFY_TOOL_NAMES:
                return True
    return False


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
    """True when the LAST verification RESULT reported a failure.

    Scans ToolMessages (results) in reverse so a later result supersedes
    an earlier one — the agent fixed things and re-verified. Failures:
    - typecheck_workspace ❌ errors-found / ⚠️ timeout-unparsed shapes;
    - a browser_navigate that failed to serve the page (HTTP 500 / load
      error) — a page that 500s is unverified even if tsc passed; and,
      UI tasks only:
    - a browser_snapshot that returned NO rendered content — the page
      never painted (D6: dev server still compiling, snapshot came back
      {"title":"","text":""} and the agent declared Finished on a
      page that 500'd at runtime);
    - a browser_screenshot that timed out — visual proof never captured.
    A snapshot that shows real content supersedes earlier failures.
    """
    ui_task = _looks_like_ui_task(state.get("current_task", ""))
    for m in reversed(state.get("messages", [])):
        if not isinstance(m, ToolMessage):
            continue
        name = getattr(m, "name", "")
        content = str(getattr(m, "content", "") or "")
        if name == "typecheck_workspace":
            # The LAST typecheck result decides (later ✅ supersedes
            # an earlier ❌ — the agent fixed and re-verified).
            # ℹ️ "typescript is not installed — skipped" also counts as
            # unsatisfied: no compiler ran, so no evidence exists (D9
            # shipped this hole — typecheck_workspace returned ℹ️-skip,
            # then npx tsc via run_terminal FAILED with TS2688/TS5107 in
            # raw STDOUT, and the gate let the broken app finalize).
            return (
                content.startswith(_VERIFY_FAIL_MARKERS)
                or content.startswith("ℹ️")
            )
        if name == "run_terminal":
            # Raw tsc failure through the terminal is the SAME failure
            # class as a ❌ typecheck_workspace result (D9: the model ran
            # `npx tsc --noEmit` directly and the tool returned
            # "error TS2688: ..." in plain STDOUT — the marker scan
            # never saw it). Detect the compiler's own error shape.
            # `error TS<digits>` is the TypeScript compiler's own error
            # shape — no other output form produces it, so it is a safe
            # failure signal even in plain STDOUT.
            if re.search(r"\berror TS\d+", content):
                return True
            continue
        if name == "browser_navigate":
            low = content.lower()
            if any(marker in low for marker in _BROWSER_FAIL_MARKERS):
                return True
            continue
        if ui_task and name == "browser_snapshot":
            return not _snapshot_shows_content(content)
        if ui_task and name == "browser_screenshot":
            if "timed out" in content.lower():
                return True
            continue
    return False


def finish_gate_node(state: AgentState) -> dict:
    """Push the model back to work after an early finish declaration.

    Distinguishes the two nudge cases: verify gate (code written, nothing
    verified) vs finish gate (no real work at all) — each has its own
    bounded counter so one can never starve the other.
    """
    if _wrote_code_files(state) and (
        not _ran_verification(state) or _verification_failed(state)
    ):
        nudge = _VERIFY_FAILED_NUDGE if _verification_failed(state) else _VERIFY_NUDGE
        return {
            "messages": [SystemMessage(content=nudge)],
            "verify_nudges": state.get("verify_nudges", 0) + 1,
        }
    return {
        "messages": [SystemMessage(content=_FINISH_NUDGE)],
        "finish_nudges": state.get("finish_nudges", 0) + 1,
    }

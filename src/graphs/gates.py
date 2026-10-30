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

import hashlib
import json
import re
from pathlib import Path

from langchain_core.messages import SystemMessage, ToolMessage

from src.context.user_interest import UserInterest, interest_from_state
from src.graphs.state import AgentState
from src.graphs.budget import _budget_exhausted
from src.graphs.verification_helpers import (
    classify_env_failure,
    classify_flaky_failure,
    command_fingerprint,
)


# =========================================================
# ROUTING
# =========================================================

# Execution-flavored task markers: on these, a plain-text finish with no
# real tool work is treated as an early stop and nudged once (hermes
# _CODEX_INCOMPLETE_NUDGE pattern, conversation_loop.py).
#
# Matching is WORD-BOUNDARED, not substring (audit 2026-10-12): the old
# `marker in task` test matched "test" inside "test2", so a read-only ask
# like "verify the test2 folder" classified as an execution task and
# finalize stamped the turn incomplete (two independent field pins caught
# it). Single verbs match whole tokens with the ordinary inflections
# (build/builds/building/built is NOT covered — see _EXECUTION_VERB_FORMS);
# two-word markers stay phrases with real boundaries so "rewrite all files"
# no longer matches "write a".
_EXECUTION_TASK_VERBS = (
    "build", "create", "implement", "integrate", "install", "fix",
    "refactor", "debug", "test", "scaffold", "develop", "deploy",
    "configure", "add", "migrate", "upgrade",
)
_EXECUTION_TASK_PHRASES = ("write a", "make a")
# Kept for importers/tests that read the marker tuple; the regexes below are
# what actually match.
_EXECUTION_TASK_MARKERS = _EXECUTION_TASK_VERBS + _EXECUTION_TASK_PHRASES

_EXECUTION_VERB_RE = re.compile(
    r"\b(?:" + "|".join(_EXECUTION_TASK_VERBS) + r")(?:s|es|ed|ing)?\b"
)
_EXECUTION_PHRASE_RE = re.compile(
    r"\b(?:" + "|".join(_EXECUTION_TASK_PHRASES) + r")\b"
)

_FINISH_NUDGE_BUDGET = 2  # max early-finish nudges before finalize is allowed
_STALL_CONTINUATION_BUDGET = 2  # hermes stall guard: codex_ack_continuations < 2
_INCOMPLETE_RESPONSE_RETRY_BUDGET = 3

_INCOMPLETE_RESPONSE_NUDGE = (
    "[System: The provider hit its output limit before returning a complete "
    "response. Continue from a clean boundary without repeating prior work. "
    "Keep the next response small. If a tool action was intended, reissue one "
    "complete, valid tool call; no partial tool call was executed.]"
)

# hermes conversation_loop.py::_CODEX_ACK_CONTINUATION_NUDGE, verbatim — the
# stall guard's re-prompt row.
_STALL_CONTINUATION_NUDGE = (
    "[System: Continue now. Execute the required tool calls and only send your "
    "final answer after completing the task.]"
)
_ANSWER_CONTINUATION_NUDGE = (
    "[System: Continue and complete the answer now. This is an answer/read-only "
    "turn: do not make workspace changes or call side-effecting tools.]"
)

_FINISH_NUDGE = (
    "[System: You declared the task finished, but almost no real work has "
    "been done — few or no tool calls have executed and the deliverable does "
    "not exist yet. This is an execution task: do not summarize, do not ask "
    "questions, do not repeat this finish message. Make the tool call you "
    "were planning right now (write the file, run the command, build the "
    "artifact) and keep going until the deliverable actually exists.]"
)

# Hermes grace-call shape (budget.py's _GRACE_NUDGE, for plan completion):
# every plan step is marked complete — the model must deliver its final
# answer instead of starting new work. The ROUTER, not this nudge, ends the
# turn if the model keeps tooling past it.
_PLAN_WRAP_NUDGE = (
    "[System: Every step in the plan is now marked complete. Do not start "
    "new work and do not call more tools. Give your final answer now: "
    "report what was done, what the results are, and anything the user "
    "still needs to do themselves.]"
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


def _interest_text(state: AgentState) -> str:
    """Source-faithful task focus used by every completion/evidence gate."""
    focus = interest_from_state(state).focus_text()
    return focus or str(state.get("current_task", "") or "")


def _deliverable_source_text(state: AgentState) -> str:
    """Active task text with line structure retained for file-ledger syntax.

    ``UserInterest.focus_text()`` intentionally normalizes whitespace. That is
    useful for semantic routing but destroys whether ``server.py`` appeared as
    an exact bullet or merely in prose. The raw state fields retain that syntax.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for key in ("current_task", "latest_instruction"):
        value = str(state.get(key, "") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        parts.append(value)
    return "\n".join(parts) if parts else _interest_text(state)


def _execution_requested(state: AgentState) -> bool:
    """Whether completion should require execution rather than an answer."""
    interest = UserInterest.from_state(state.get("user_interest"))
    if interest is not None:
        if (
            interest.mode in {"answer", "social"}
            or interest.relationship == "cancelled"
        ):
            return False
        if interest.mode == "act":
            return True
    return _looks_like_execution_task(_interest_text(state))


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
# A bare code filename is ambiguous in prose (``Next.js`` is a framework),
# but not when the user puts the filename itself in a markdown/numbered file
# ledger. Preserve that provenance rather than weakening the conservative
# bare-name rule globally.
_LISTED_DELIVERABLE_RE = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])\s+[`'\"]?"
    r"(?P<target>[A-Za-z0-9_./\\-]+\.(?:"
    + "|".join(_NAMED_DELIVERABLE_EXTENSIONS)
    + r"))[`'\"]?\s*(?:(?:—|–|:)\s+.+|[.,;])?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DELIVERABLE_LEDGER_HEADER_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:deliverables?|artifacts?|output\s+files?|required\s+files?)\b|"
    r"\b(?:file|project)\s+(?:list|structure|layout)\b|"
    r"\bfiles?\s*(?:to\s+(?:create|write|deliver|produce|include)|:)|"
    r"\b(?:create|deliver|write|produce|include|return|save)\b.{0,100}\bfiles?\b"
    r")"
)
_NON_DELIVERY_LEDGER_HEADER_RE = re.compile(
    r"(?i)\b(?:technology|tech\s+stack|frameworks?|dependencies|"
    r"ignore|exclude|do\s+not\s+create)\b"
)

_NAMED_APP_RE = re.compile(
    r"\b(?:app|application|project|package|folder|directory|module|service"
    r"|website|site)\s+(?:called|named)\s+([A-Za-z][A-Za-z0-9_-]{1,63})",
    re.IGNORECASE,
)


def _app_named_targets(task: str) -> list[str]:
    """'Create a Flutter app called flutterdemo' names a deliverable
    DIRECTORY — the generated project folder. The extension-based regex
    above cannot see it (no dot), so the finish gate used to be blind to
    the one artifact app-creation tasks exist to produce (field
    2026-10-19: SDK install verified, model announced 'Creating the
    project now:', turn stamped completed, no folder ever created)."""
    out: list[str] = []
    for m in _NAMED_APP_RE.finditer(task or ""):
        name = m.group(1)
        if name not in out:
            out.append(name)
    return out
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


def _listed_deliverable_targets(task: str) -> list[str]:
    """Path entries in a list explicitly introduced as files/deliverables.

    Requiring the nearby heading is what distinguishes ``- server.py`` under
    "Required files" from ``- Next.js`` under "Technology stack".
    """
    targets: list[str] = []
    seen: set[str] = set()
    ledger_context = False
    in_ledger = False
    for line in str(task or "").replace("\r\n", "\n").split("\n"):
        match = _LISTED_DELIVERABLE_RE.fullmatch(line)
        if match is not None:
            if not (ledger_context or in_ledger):
                continue
            in_ledger = True
            name = match.group("target").replace("\\", "/").lstrip("./")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                targets.append(name)
            continue
        if not line.strip():
            # Markdown commonly separates a heading and its list by one blank
            # line; do not lose the explicit context there.
            continue
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            ledger_context = False
            in_ledger = False
            continue
        ledger_context = bool(
            _DELIVERABLE_LEDGER_HEADER_RE.search(line)
            and not _NON_DELIVERY_LEDGER_HEADER_RE.search(line)
        )
        in_ledger = False
    return targets


# Verify gate (Test-2 fix): an execution task that WROTE code files but
# never ran a verification tool must not finalize. Test 2 shipped ~15
# syntax/type bugs because writes were blind — nothing forced a check
# before the agent declared itself done.
_VERIFY_NUDGE_BUDGET = 2

_VERIFY_TOOL_NAMES = frozenset({
    "typecheck_workspace", "verify_ui_workspace", "verify_ui_routes",
    # The desktop shell is bound as `terminal` (hermes parity rename);
    # `run_terminal` is the legacy alias of the same tool. Both report
    # checks — a set that names only the alias is blind on the desktop.
    "run_terminal", "terminal", "execute_code",
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_click", "browser_type",
    # Multi-platform receipts (src/targets/): a target build/verify receipt is
    # the native analogue of the UI pipeline above.
    "build_target", "verify_target_app", "device_ui", "device_screenshot", "device_logs",
})
_VERIFICATION_COMMAND_TOKENS = (
    "pytest", "unittest", " test", "npm test", "typecheck", "tsc ",
    " lint", " build", "cargo check", "go test", " analyze",
    "curl", "health",
)
_FAILED_CHECK_TOOLS = frozenset({
    "typecheck_workspace", "verify_ui_workspace", "verify_ui_routes",
    "build_target", "verify_target_app",
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "run_terminal", "terminal",
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

# Audit 2026-10-12: when the user asks for VISUAL proof, a DOM snapshot is
# not that proof. The gate used to accept `navigate + (snapshot OR
# screenshot)`, so a UI task that explicitly asked for a screenshot could
# pass with no screenshot receipt at all — the weaker evidence authorizing
# completion on the stronger ask. These phrases make the screenshot domain
# mandatory; the composite verify_ui_workspace tool satisfies it (it
# typechecks, navigates, snapshots, screenshots, rejects near-blank proof).
_VISUAL_PROOF_RE = re.compile(
    r"\b(?:screenshot|visual proof|visual quality|capture the (?:page|screen|ui))\b"
)


def _task_asks_visual_proof(task: str) -> bool:
    return bool(_VISUAL_PROOF_RE.search((task or "").lower()))

_VERIFY_NUDGE = (
    "[System: You wrote code files but never verified them. You must not "
    "finish an execution task with unverified code — run a verification "
    "tool right now. For TypeScript/JS projects run typecheck_workspace "
    "(tsc --noEmit). For a UI/frontend deliverable that is NOT enough: prefer "
    "ONE verify_ui_workspace call, which deterministically typechecks, starts "
    "the app, navigates, snapshots, captures a screenshot, rejects near-blank "
    "proof, and cleans up. Use individual browser tools only for interactive "
    "flows that need browser_type/browser_click. For a Flutter/native "
    "deliverable run verify_target_app — a device/emulator receipt is its "
    "runtime proof (flutter analyze/flutter test via the terminal prove the "
    "code statically, not that it renders). Fix any errors BEFORE "
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

_CODE_EXT_MARKERS = (
    ".tsx", ".ts", ".jsx", ".js", ".py", ".json", ".css", ".html",
    # Native/mobile stacks the targets system ships (Flutter/Android/
    # iOS/Rust): a written .dart file is authored code exactly like
    # .ts — before this, `flutter create` + a hand-written main.dart
    # registered as "no code written" in every verify gate.
    ".dart", ".kt", ".kts", ".swift", ".java", ".rs",
)


def _looks_like_execution_task(task: str) -> bool:
    """True when the task asks for work, not for an answer.

    Word-boundary matching only: `"test"` must never match inside `"test2"`
    (audit 2026-10-12 — that substring trap stamped read-only verification
    turns incomplete), and `"add"` must never match inside `"address"`.
    """
    t = (task or "").lower()
    if not t:
        return False
    return bool(_EXECUTION_VERB_RE.search(t) or _EXECUTION_PHRASE_RE.search(t))


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


def _verification_trace_key(item: dict) -> tuple[str, str] | None:
    """Stable identity for a concrete executable verification obligation."""
    tool_name = str(item.get("tool") or "")
    if tool_name not in _FAILED_CHECK_TOOLS:
        return None
    args = item.get("args") if isinstance(item.get("args"), dict) else {}
    canonical_tool = "terminal" if tool_name in {"terminal", "run_terminal"} else tool_name
    if canonical_tool == "terminal":
        command = command_fingerprint(tool_name, args) or ""
        if not command or not any(token in command for token in _VERIFICATION_COMMAND_TOKENS):
            return None
        identity = command
    else:
        identity = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()[:20]
    return f"{canonical_tool}:{digest}", canonical_tool


def _unresolved_failed_verification_checks(state: AgentState) -> list[dict[str, object]]:
    """Failed checks that have not passed again with the same identity.

    A mutation marks repair as landed but deliberately does not erase the debt:
    only a successful rerun of the exact failed check can do that. A different,
    weaker green command therefore cannot overwrite a stronger red receipt.
    Environmental failures are excluded because source mutation is not their
    valid recovery path.
    """
    debts: dict[str, dict[str, object]] = {}
    for index, item in enumerate(state.get("execution_trace", []) or []):
        if not isinstance(item, dict):
            continue
        if (
            item.get("tool") in _WORK_TOOLS
            and item.get("status") == "success"
        ):
            for debt in debts.values():
                debt["repair_landed"] = True
            continue
        identity = _verification_trace_key(item)
        if identity is None:
            continue
        fingerprint, canonical_tool = identity
        status = str(item.get("status") or "").lower()
        result = str(item.get("result") or "")
        if status in {"failed", "error", "failure"}:
            if classify_env_failure(result):
                continue
            if classify_flaky_failure(result):
                flaky_attempts = int(item.get("flaky_attempts", 0) or 0)
                if flaky_attempts < 2:
                    continue
            debts[fingerprint] = {
                "fingerprint": fingerprint,
                "tool": canonical_tool,
                "failed_at": index,
                "repair_landed": False,
            }
        elif status in {"success", "succeeded", "completed"}:
            debts.pop(fingerprint, None)
    return sorted(debts.values(), key=lambda item: int(item["failed_at"]))


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


def _any_tool_activity(state: AgentState) -> bool:
    """True when the turn ran ANY tool — reads/terminal/search included.

    `_tool_call_count` answers "did the turn deliver work?" (mutation tools
    only, deliberately narrow). This answers the different question the
    finalize honesty check needs: "did the model act at all?". A read-only
    ask ("verify the test2 folder", "what does this file do") legitimately
    ends with zero mutations; only a turn with no tool activity whatsoever
    is a pure monologue. An emitted tool call counts even if the result was
    an error — the failure then rides `trailing_batch_failed`, which is the
    honest signal, instead of being double-counted as "did nothing".
    """
    for m in state.get("messages", []):
        if isinstance(m, ToolMessage):
            return True
        if getattr(m, "tool_calls", None):
            return True
    return False


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
    mentioned in prose ("build a chat app with Next.js" would otherwise
    match "Next.js") is ignored unless the task is a COPY task, the suffix
    names a non-code artifact, or the filename is an exact entry in a
    markdown/numbered file ledger. Path-shaped targets remain explicit.

    Disk I/O is the outcome-checking exception to gates' purity: E2's
    failure was a run that proudly finished with 0 files — the only way
    to detect that is to look. Read-only, never raises (an unreadable
    workspace treats targets as missing rather than crashing the gate).
    """
    interest = UserInterest.from_state(state.get("user_interest"))
    if interest is not None and (
        not _execution_requested(state) or interest.change_policy == "no_changes"
    ):
        return []
    task = _deliverable_source_text(state)
    is_copy = _looks_like_copy_task(task)
    app_named = _app_named_targets(task)
    listed = {name.lower() for name in _listed_deliverable_targets(task)}
    targets = _deliverable_targets(task)
    for name in app_named:
        if name not in targets:
            targets.append(name)
    missing: list[str] = []
    for target in targets:
        if not target:
            continue
        target_key = target.replace("\\", "/").lstrip("./").lower()
        if not is_copy and "/" not in target and "\\" not in target:
            # A bare code-ish filename in prose can be a library/version token
            # (the historical `Next.js` false positive), so keep requiring a
            # path unless the user made it an exact ledger entry. A requested
            # non-code artifact such as report.pdf or slides.pptx is already
            # unambiguous. An app-named target is a project directory.
            if (
                Path(target).suffix.lower() not in _NON_CODE_ARTIFACT_EXTENSIONS
                and target not in app_named
                and target_key not in listed
            ):
                continue
        exists = False
        for cand in _deliverable_candidates(workspace, target):
            try:
                if cand.is_file() or (target in app_named and cand.is_dir()):
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
    task = _deliverable_source_text(state)
    is_copy = _looks_like_copy_task(task)
    listed = {name.lower() for name in _listed_deliverable_targets(task)}
    eligible: list[str] = []
    for target in _deliverable_targets(task):
        has_dir = "/" in target or "\\" in target
        target_key = target.replace("\\", "/").lstrip("./").lower()
        if not is_copy and not has_dir:
            if (
                Path(target).suffix.lower() not in _NON_CODE_ARTIFACT_EXTENSIONS
                and target_key not in listed
            ):
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
        Path(target),
    ]
    t_parts = Path(target).parts
    if t_parts:
        ws_parts = ws.parts
        for i in range(len(t_parts), 0, -1):
            if len(ws_parts) >= i and tuple(p.lower() for p in ws_parts[-i:]) == tuple(p.lower() for p in t_parts[:i]):
                candidates.append(ws.joinpath(*t_parts[i:]))
                break
        if len(t_parts) > 1:
            for i in range(1, len(t_parts)):
                candidates.append(ws.joinpath(*t_parts[i:]))
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


def _completion_activity_missing(state: AgentState) -> bool:
    """Whether an action turn still owes its first concrete action.

    Mutation-capable delivery tasks keep the deliberately strict work-tool /
    on-disk-artifact bar.  A ``no_changes`` action cannot satisfy that bar by
    design: mutation tools are not bound.  For those turns, any executed tool
    receipt is the honest progress boundary (terminal checks, target
    inspection, reads, searches, and verification all qualify).

    Desktop evidence bd057959 exposed the mismatch: ``python --version`` ran
    successfully with exit 0, then the mutation-only gate issued two
    impossible work nudges and finalization falsely returned ``failed``.
    """
    interest = UserInterest.from_state(state.get("user_interest"))
    if interest is not None and interest.change_policy == "no_changes":
        return not _any_tool_activity(state)
    return (
        _tool_call_count(state) < 1
        and not _named_deliverables_exist(
            state, state.get("workspace", ".")
        )
    )


def _completion_evidence_ready(state: AgentState) -> bool:
    """Whether a reserved final response may carry a completed verdict.

    This is deliberately stricter than a model saying "done". Execution tasks
    need concrete activity, every named deliverable, fresh required
    verification, no unrecovered trailing failure, and no open plan step. The
    result only controls budget-cut attribution; it never skips the final model
    response itself.
    """
    if state.get("execution_mode") == "ask":
        return True
    if not _execution_requested(state):
        return True
    if not _any_tool_activity(state):
        return False
    if _deliverables_missing_on_disk(state, state.get("workspace", ".")):
        return False
    # The reserve is not a shortcut around the verification gate. Technical
    # execution earns a clean wrap only from a fresh, recognized passing
    # receipt; unlike _verify_unsatisfied, this has no nudge-budget escape.
    if not _verification_ran_and_passed(state):
        return False
    plan = state.get("plan") or []
    if plan and any(step.get("status") != "completed" for step in plan):
        return False
    from src.graphs.progress_helpers import trailing_batch_failed

    if trailing_batch_failed(state.get("messages") or []):
        return False
    nudged_at = state.get("nudged_at_msg_count")
    if isinstance(nudged_at, int) and nudged_at >= 0:
        messages = state.get("messages") or []
        if not any(
            getattr(message, "tool_calls", None)
            for message in messages[nudged_at:]
        ):
            return False
    return True


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if bool(getattr(last_message, "additional_kwargs", {}).get("crusor_cancelled")):
        return "finalize"

    # hermes repetition_guard (#86581): a discarded degenerate fragment ends
    # the turn — a continuation nudge would only stitch more repeated text.
    # This check owns the verdict before the incomplete-recovery routing
    # below can send the fragment back through finish_gate.
    if bool(getattr(last_message, "additional_kwargs", {}).get(
        "crusor_repetition_dominated"
    )):
        return "finalize"

    # A token-limited text response is not a final answer. Tool-bearing
    # incomplete responses route through SafeToolNode for paired rejection;
    # text-only responses receive the bounded finish-gate continuation nudge.
    if (
        bool(getattr(last_message, "additional_kwargs", {}).get(
            "crusor_incomplete_response"
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

    # F close (wrap leg): the plan-complete wrap lap produced the closing
    # answer — the turn ends on it (same law as the grace summary: ONE
    # toolless summary call, then RETURN; wrap_summary stays set until the
    # turn teardown).
    #
    # Audit 2026-10-12: this check used to sit BELOW the no-tool Hard Gate,
    # so the guaranteed closing lap could be answered under the Hard Gate's
    # "no mutation tools ran" condition and get routed back to finish_gate —
    # burning paid laps against a law this module's own comment states. The
    # wrap lap is terminal; it owns the verdict ABOVE the Hard Gate.
    if state.get("wrap_summary") and not getattr(last_message, "tool_calls", None):
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
        trailing_continue_intent,
    )
    if not getattr(last_message, "tool_calls", None):
        _no_tool_streak = consecutive_no_tool_ai_messages(state.get("messages", []))
        _repetition = is_repetition_dominated(
            str(getattr(last_message, "content", "") or "")
        )
        if _repetition:
            return "finalize"

        # Hard Gate: If this is an execution/creation task and NO eligible
        # action has executed, do NOT let the turn finalize prematurely on
        # no_tool_streak while finish nudges remain. Delivery tasks still owe
        # mutation/on-disk evidence; explicitly no-change tasks owe a real
        # read/check/terminal receipt instead (their mutation tools are
        # intentionally unavailable).
        if (
            _execution_requested(state)
            and _completion_activity_missing(state)
            and state.get("finish_nudges", 0) < _FINISH_NUDGE_BUDGET
            and not _budget_exhausted(state)
        ):
            return "finish_gate"

        if _no_tool_streak >= NO_TOOL_TURN_LIMIT:
            return "finalize"
        # ── Hermes stall guard (agent/turn_final_response.py, verbatim) ──
        # "Said-continue-but-stopped": no tool calls, but the short reply
        # TAILS with an announced next action — the model announced work
        # and stopped. Hermes re-prompts it to ACT, bounded 2/turn
        # (codex_ack_continuations < 2). Field 2026-09-10: after 13
        # read-only observations the model announced its next step in text
        # and the turn finalized mid-plan. Off on budget-exhausted laps:
        # the grace lap runs UNBOUND — no tools left to act with (same
        # condition as the incomplete-response gate above).
        if (
            state.get("stall_continuations", 0) < _STALL_CONTINUATION_BUDGET
            and not _budget_exhausted(state)
            and trailing_continue_intent(str(getattr(last_message, "content", "") or ""))
        ):
            return "finish_gate"

    # ── Hermes loop law: pending tool calls execute, even at the cap ──
    # Hermes IterationBudget.consume() (agent/iteration_budget.py) gates the
    # NEXT MODEL CALL, never the execution of tool calls the model already
    # emitted; turn_iteration_prep.py:108 states it verbatim: "Fires at the
    # top of the NEXT iteration, so the budget-crossing request completes
    # first." Field receipt (owner log 2026-09-08, engine 9dc843ef): the ai
    # call entered with tools bound one request under the budget, its own
    # result pushed iteration_used to the cap, and THIS router finalized —
    # the model's bound start_terminal call (the dev server the whole task
    # was for) was dropped un-executed: no spawn, no receipt, the card stuck
    # "Running" forever, and the final text promised a browser check that
    # never ran. Dispatch FIRST; the budget then concludes the turn the
    # designed way — ai_node re-enters unbound, the grace nudge fires, the
    # text answer finalizes. One bounded grace lap; the valve is intact.
    if getattr(last_message, "tool_calls", None):
        return "tools"

    # D40: once the ai iteration budget is spent, this run must conclude.
    # The grace call produced a text answer — finalize it instead of
    # re-entering gates that would push the model to work it can no longer
    # do. (Pending tool calls never reach this point: they were dispatched
    # above, hermes-style.)
    # F close (field 2026-09-09→10): the grace summary already ran when
    # grace_done is set — hermes _handle_max_iterations RETURNS the summary
    # and the loop ends there. R3-4's post-grace nudges ordered work from a
    # TOOLLESS lap (no tools can place deliverables or run checks), so they
    # could only burn paid toolless laps until their budgets expired. The
    # closing answer is the turn's LAST model call. The same law closes the
    # plan-complete wrap lap: wrap_summary's toolless answer ends the turn.
    if _budget_exhausted(state):
        if state.get("grace_done", 0):
            return "finalize"
        if (state.get("finish_nudges", 0) < _FINISH_NUDGE_BUDGET
                and _deliverables_missing_on_disk(state, state.get("workspace", "."))):
            return "finish_gate"
        if (_execution_requested(state)
                and _produced_code_deliverable(state)
                and state.get("verify_nudges", 0) < _VERIFY_NUDGE_BUDGET
                and not _verification_ran_and_passed(state)):
            return "finish_gate"
        return "finalize"

    # Finish gate: an execution task that ends with NO eligible action is an
    # early stop, not completion. Mutation-capable delivery tasks owe a work
    # tool or named on-disk artifact. Explicit no-change actions instead owe
    # one real tool receipt; requiring a mutation there is impossible and
    # caused successful inspection/command turns to fail after extra laps.
    if state.get("finish_nudges", 0) < _FINISH_NUDGE_BUDGET:
        if (
            _execution_requested(state)
            and _completion_activity_missing(state)
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
        _is_copy = _looks_like_copy_task(_interest_text(state))
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
    if not _execution_requested(state):
        return False
    # Hard gate (founder 2026-10-20): a produced code deliverable owes at
    # least one real verification pass before the turn may close, however
    # it was produced. Scaffold tools are deleted, so `flutter create`
    # writes no write_file steps; gating only write_file output (or only
    # verification that already ran and failed) let a terminal-created app
    # finish with zero checks. Non-code artifacts (PDF/docs/data) carry no
    # runtime to verify and stay on the existence contract via
    # _produced_code_deliverable's code-extension/app-name bar.
    if not _produced_code_deliverable(state):
        return False
    return not _ran_verification(state) or _verification_failed(state)


def _produced_code_deliverable(state: AgentState) -> bool:
    """True when the turn produced a code/app deliverable that can be
    verified — by ANY production route.

    `_wrote_code_files` alone was the old bar, but the sanctioned
    app-creation path is the terminal (scaffold tools are deleted):
    `flutter create flutterdemo` writes 93 files without a single
    write_file call, so the verify gate and the finalize verdict were
    both blind to the one deliverable the task existed to produce
    (field 2026-10-19 run 2: verification failed, model chattered,
    turn stamped completed). A named target counts when it is an
    app-named project directory or carries a code extension (the
    `_CODE_EXT_MARKERS` set — docs and data artifacts carry no
    runtime to verify and stay on the existence contract)."""
    if _wrote_code_files(state):
        return True
    task = _deliverable_source_text(state)
    app_named = _app_named_targets(task)
    targets = [
        t for t in _deliverable_targets(task)
        if Path(t).suffix.lower() in _CODE_EXT_MARKERS
    ]
    for name in app_named:
        if name not in targets:
            targets.append(name)
    if not targets:
        return False
    workspace = state.get("workspace", ".")
    for target in targets:
        try:
            exists = any(
                cand.is_file() or (target in app_named and cand.is_dir())
                for cand in _deliverable_candidates(workspace, target)
            )
        except OSError:
            exists = False
        if not exists:
            return False
    return True


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
    task_focus = _interest_text(state)
    ui_task = _looks_like_ui_task(task_focus)
    receipts = _fresh_verification_messages(state)
    failed_check_debts = _unresolved_failed_verification_checks(state)
    status = {
        "static": False,
        "typecheck": False,
        "integrity": False,
        "navigate": False,
        "snapshot": False,
        "screenshot": False,
        "failed_checks": not failed_check_debts,
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
            # The pipeline's stages are sequential: a failure AT the
            # static stage condemns static, but a failure AFTER it
            # (server never ready, screenshot quality) must not zero
            # the static proof that same call already earned — zeroing
            # it made a later manual browser proof unable to pass
            # (field 2026-10-19 run 3: one-shot verify failed at the
            # server stage, agent then proved the app in a live
            # browser, turn still stamped unverified).
            static_ok = passed or "at static source checks" not in content
            status["static"] = static_ok
            status["typecheck"] = static_ok
            status["navigate"] = passed
            status["snapshot"] = passed
            status["screenshot"] = passed
        elif name in {"verify_target_app", "build_target"}:
            passed = content.startswith("✅ TARGET VERIFICATION PASSED")
            status["static"] = passed
            status["typecheck"] = passed
            if name == "verify_target_app" and passed and _target_receipt_proves_render(content):
                # A device/emulator/simulator/window receipt IS runtime proof:
                # the app was launched and produced a UI dump/screenshot there.
                status["navigate"] = True
                status["snapshot"] = True
                status["screenshot"] = True
        elif name == "typecheck_workspace":
            passed = content.startswith("✅") and "0 errors" in low
            status["typecheck"] = passed
            status["static"] = passed
        elif name in {"run_terminal", "terminal"}:
            command = str(tool_args(message).get("command", "")).lower()
            is_check = any(
                token in command for token in _VERIFICATION_COMMAND_TOKENS
            )
            if is_check:
                status["static"] = "exit code: 0" in low
        elif name == "execute_code":
            code = str(tool_args(message).get("code", "")).lower()
            is_check = any(
                token in code for token in _VERIFICATION_COMMAND_TOKENS
            ) or any(
                token in low for token in _VERIFICATION_COMMAND_TOKENS
            )
            if is_check:
                status["static"] = ("exit code: 0" in low or "ok" in low or "passed" in low or "ran " in low) and "failed" not in low and "error" not in low
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

    # If the user specifically instructs verification via automated test suite / terminal tests,
    # static test execution is the required verification domain.
    test_suite_ask = bool(re.search(r"(?i)(?:automated test|run (?:the )?(?:automated )?tests?)", task_focus))
    required = ["static", "integrity", "failed_checks"]
    if ui_task and not test_suite_ask:
        # UI verification: requires successful navigation AND at least one of
        # DOM snapshot or visual screenshot (either proves page rendered).
        ui_rendered = bool(status.get("snapshot") or status.get("screenshot"))
        status["rendered"] = ui_rendered
        required.extend(["navigate", "rendered"])
        # ...but when the task ASKS for a screenshot/visual proof, the
        # snapshot cannot stand in for it (audit 2026-10-12): the requested
        # artifact is the receipt, so the screenshot domain is required too.
        visual_proof = _task_asks_visual_proof(task_focus)
        status["visual_proof_required"] = visual_proof
        if visual_proof:
            required.append("screenshot")
    missing = [name for name in required if not bool(status.get(name))]
    return {
        **status,
        "ui_task": ui_task,
        "required": required,
        "missing": missing,
        "integrity_issues": [issue.describe() for issue in integrity_issues[:20]],
        "failed_check_debts": failed_check_debts,
        "ran_any": bool(seen),
        "passed": not missing,
    }


def derive_4state_verification_receipt(state: AgentState) -> dict[str, object]:
    """Authoritative task-adaptive 4-state verification receipt (Pillar 5).

    States:
    - 'verified': All required checks executed and passed.
    - 'partially_verified': Core checks passed, but secondary checks skipped.
    - 'failed': One or more required checks failed or debts exist.
    - 'blocked': Execution obstructed by environment failures.
    - 'not_applicable': Non-execution or read-only task.
    - 'unverified': Code produced but verification was never executed.
    """
    if not _execution_requested(state) or (not _wrote_code_files(state) and not _produced_code_deliverable(state)):
        return {
            "state": "not_applicable",
            "passed": True,
            "checks": {},
            "required": [],
            "missing": [],
            "details": "Non-execution or mutation-free task: verification not applicable.",
        }

    raw = _verification_receipt_status(state)
    if not raw["ran_any"]:
        return {
            "state": "unverified",
            "passed": False,
            "checks": {k: "skipped" for k in raw["required"]},
            "required": raw["required"],
            "missing": raw["missing"],
            "details": "Deliverables were created but no verification command or tool was executed.",
        }

    # Environment failure check
    env_failure = False
    for debt in raw.get("failed_check_debts") or []:
        if classify_env_failure(str(debt)):
            env_failure = True
            break
    if env_failure:
        return {
            "state": "blocked",
            "passed": False,
            "checks": {k: ("passed" if raw.get(k) else "blocked") for k in raw["required"]},
            "required": raw["required"],
            "missing": raw["missing"],
            "details": "Verification execution was obstructed by environment configuration or missing runtime dependencies.",
        }

    # Check for failed debts or static check failure
    missing_items = list(raw.get("missing") or [])
    if raw.get("failed_check_debts") or ("static" in missing_items and raw.get("ran_any") and not raw.get("static")):
        return {
            "state": "failed",
            "passed": False,
            "checks": {k: ("passed" if raw.get(k) else "failed") for k in raw["required"]},
            "required": raw["required"],
            "missing": missing_items,
            "details": f"Verification checks failed: {', '.join(missing_items)}.",
        }

    if raw.get("passed"):
        return {
            "state": "verified",
            "passed": True,
            "checks": {k: "passed" for k in raw["required"]},
            "required": raw["required"],
            "missing": [],
            "details": f"All {len(raw['required'])} required verification domains verified and passed.",
        }

    if raw.get("static") and raw.get("failed_checks"):
        return {
            "state": "partially_verified",
            "passed": True,
            "checks": {k: ("passed" if raw.get(k) else "skipped") for k in raw["required"]},
            "required": raw["required"],
            "missing": missing_items,
            "details": f"Core code verification passed, but secondary checks skipped: {', '.join(missing_items)}.",
        }

    return {
        "state": "failed",
        "passed": False,
        "checks": {k: ("passed" if raw.get(k) else "failed") for k in raw["required"]},
        "required": raw["required"],
        "missing": missing_items,
        "details": f"Verification incomplete: missing {', '.join(missing_items)}.",
    }



#: Target ids whose ✅ receipt implies a rendered surface (a device, emulator,
#: simulator or desktop window actually displayed the app). The web target is
#: deliberately absent: an HTTP-ready dev server proves nothing about rendering,
#: so web tasks keep owing the browser pipeline its navigate/snapshot proof.
_RENDER_PROVING_TARGETS = ("android", "ios", "desktop", "flutter", "react-native")


def _target_receipt_proves_render(content: str) -> bool:
    return any(
        f"TARGET: {target}" in content or f"PROVIDER: {target}" in content
        for target in _RENDER_PROVING_TARGETS
    )


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
    # hermes repetition_guard: a discarded degenerate fragment gets NO
    # continuation nudge — continuing would only produce more repeated text;
    # the router already ends the turn on this flag.
    last = state.get("messages", [])[-1] if state.get("messages", []) else None
    if bool(getattr(last, "additional_kwargs", {}).get("crusor_repetition_dominated")):
        return {}
    if bool(getattr(last, "additional_kwargs", {}).get("crusor_incomplete_response")):
        return {"messages": [SystemMessage(content=_INCOMPLETE_RESPONSE_NUDGE, additional_kwargs={"crusor_nudge": True})], "nudged_at_msg_count": len(state.get("messages") or [])}

    # Hermes stall guard (turn_final_response.py): the toolless reply ended on
    # an announced next action. The assistant reply already sits in the
    # transcript as interim (ai_node returned it); the nudge is hermes'
    # _CODEX_ACK_CONTINUATION_NUDGE verbatim. Bounded by the router's
    # stall_continuations check (hermes codex_ack_continuations < 2).
    from src.graphs.loop_guards import trailing_continue_intent

    if (
        not getattr(last, "tool_calls", None)
        and state.get("stall_continuations", 0) < _STALL_CONTINUATION_BUDGET
        and trailing_continue_intent(str(getattr(last, "content", "") or ""))
    ):
        print(
            "[StallGuard] turn ending on trailing continue-intent with no tool "
            f"calls — re-prompting to act ({state.get('stall_continuations', 0) + 1}/2)",
            flush=True,
        )
        nudge = (
            _STALL_CONTINUATION_NUDGE
            if _execution_requested(state)
            else _ANSWER_CONTINUATION_NUDGE
        )
        return {
            "messages": [SystemMessage(content=nudge, additional_kwargs={"crusor_nudge": True})],
            "stall_continuations": state.get("stall_continuations", 0) + 1,
            "nudged_at_msg_count": len(state.get("messages") or []),
        }

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
        # Name the missing deliverables: the gate KNOWS what does not
        # exist, and a generic "produce the file" does not move a model
        # that believes it already did (field 2026-10-19: two unnamed
        # nudges answered with words, zero tool calls).
        nudge += (
            "\n\n[Missing deliverable(s): " + ", ".join(missing[:5])
            + " — these do not exist on disk yet. Create exactly these now "
            "with the appropriate tool or generator command, then confirm "
            "each one exists before finishing. A text-only reply does not "
            "count as progress.]"
        )
        return {
            "messages": [SystemMessage(content=nudge, additional_kwargs={"crusor_nudge": True})],
            "finish_nudges": state.get("finish_nudges", 0) + 1,
            "nudged_at_msg_count": len(state.get("messages") or []),
        }
    # The verify branch MUST honor the same budget the router checks
    # (_VERIFY_NUDGE_BUDGET): field 2026-10-21 (build ca4a5b0d) looped
    # forever here — the router stopped routing on the verify gate at
    # budget, re-entered via the finish gate (whose budget this branch
    # never spends), and this branch kept re-emitting the verify nudge
    # while verify_nudges grew unbounded past every limit.
    if (
        _execution_requested(state)
        and _produced_code_deliverable(state)
        and state.get("verify_nudges", 0) < _VERIFY_NUDGE_BUDGET
        and (not _ran_verification(state) or _verification_failed(state))
    ):
        # _verification_failed means "required receipts are not all
        # passing", which is also true when nothing ever ran — that
        # never-ran case owes the first-check nudge, not the failure one.
        nudge = (
            _VERIFY_FAILED_NUDGE
            if _ran_verification(state) and _verification_failed(state)
            else _VERIFY_NUDGE
        )
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
            "messages": [SystemMessage(content=nudge, additional_kwargs={"crusor_nudge": True})],
            "verify_nudges": state.get("verify_nudges", 0) + 1,
        }
    # Hermes loop law (field 2026-09-05): the plan completed but the model
    # is mid-work (progress runs right after a tool batch). Tell it to
    # deliver the final answer — the model, not the router, ends the turn.
    # Bounded: after_progress finalizes the second time plan-complete hits.
    plan = state.get("plan") or []
    if plan and all(step.get("status") == "completed" for step in plan):
        nudges = state.get("plan_wrap_nudges", 0)
        if nudges >= 1:
            # Field 2026-09-10: the model tooling past lap 1 used to be
            # decapitated by the shortcut (last act a tool call, no closing
            # answer). Lap 2 is hermes handle_max_iterations' shape: ai_node
            # hides the tools and appends the summary request — a guaranteed
            # closing text lap. No second nudge here; the flag carries it.
            return {
                "plan_wrap_nudges": nudges + 1,
                "wrap_summary": 1,
            }
        return {
            "messages": [SystemMessage(content=_PLAN_WRAP_NUDGE, additional_kwargs={"crusor_nudge": True})],
            "plan_wrap_nudges": nudges + 1,
        }
    nudge = _FINISH_NUDGE
    if _looks_like_copy_task(_interest_text(state)) and not _wrote_code_files(state):
        nudge = _COPY_NUDGE
    return {
        "messages": [SystemMessage(content=nudge, additional_kwargs={"crusor_nudge": True})],
        "finish_nudges": state.get("finish_nudges", 0) + 1,
        "nudged_at_msg_count": len(state.get("messages") or []),
    }

"""Receipt-driven execution phases: guidance and budgets, NEVER amputation.

Hermes keeps hard loop guardrails pure and lets runtime code project decisions
— and its 288-run core_tool_deferral battery (PR #97979) is the standing
evidence that HIDING tools from the model is a loss, not focus: tools stay
registered and the model decides. Field proof 2026-09-07 (build 9756690d): a
"do browser testing" turn died because a plan step reading "Run the build to
ensure no errors" tripped the static_verify keyword phase, which stripped every
browser tool AND todo_list AND think from the binding mid-turn. The model
honestly reported "we cannot actually launch a browser" (they were amputated
from its context) and the owner saw no plan either — the planning tool was
gone. This module's former capability filters were a lexicon gate on plan-step
WORDS, exactly the class of behavior pulse banned.

So this module now derives a phase NAME, compact GUIDANCE (steering words flow
into the system prompt via phase_guidance — hermes' nudge-not-amputate shape),
and mutation BUDGETS. Keyword phases carry ``allowed=None``: no tool hiding,
anywhere downstream (binding and the tool node's execution-time check both
treat None as no policy). Pulse's only state-driven allowlists — forced
delivery on an empty autonomous workspace, and the verification reserve — are
constructed in chat_graph, which owns them; they key on workspace/budget
STATE, not on step wording. This module never hardcodes benchmark paths or
component names.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionPhase:
    name: str
    # None = no tool hiding (hermes discipline). Only chat_graph's
    # state-driven phases ever construct a non-None allowlist.
    allowed: frozenset[str] | None
    max_file_mutations_per_turn: int = 0
    guidance: str = ""


def _active_step(state: dict[str, Any]) -> dict[str, Any] | None:
    for step in state.get("plan", []) or []:
        if step.get("status") == "in_progress":
            return step
    return None


def derive_execution_phase(state: dict[str, Any]) -> ExecutionPhase:
    """Phase name + guidance + budgets from the active plan receipt.

    ``allowed`` is ALWAYS None here: a plan step's wording must never remove
    capabilities the turn's task granted (field 2026-09-07). Steering happens
    through ``guidance``; the tool waist lives in the per-turn capability
    resolver (toolsets.resolve_runtime_tool_names), exactly one narrowing.
    """
    if os.environ.get("PULSEAI_PHASE_GUIDANCE", "on").strip().lower() in {
        "0", "off", "false", "no", "disabled",
    }:
        return ExecutionPhase("general", None)

    step = _active_step(state)
    if not step:
        return ExecutionPhase("general", None)
    description = str(step.get("description", "")).lower()

    if any(word in description for word in (
        "browser", "screenshot", "visual", "rendered page", "verify_ui",
    )):
        return ExecutionPhase(
            "visual_verify", None,
            max_file_mutations_per_turn=2,
            guidance=(
                "VISUAL VERIFY step. Prove it in the browser: navigate, act by "
                "ref, screenshot — the composite verify_ui receipts or the "
                "individual browser tools. If proof fails, make at most two "
                "targeted file repairs, then repeat the proof once."
            ),
        )

    if any(word in description for word in (
        "typecheck", "type check", "test", "lint", "build", "static verify",
    )):
        return ExecutionPhase(
            "static_verify", None,
            max_file_mutations_per_turn=2,
            guidance=(
                "STATIC VERIFY step. Run the named check now. On failure, use "
                "its exact diagnostics for at most two targeted repairs; do "
                "not re-inspect unrelated files or rerun unchanged checks. "
                "This does not remove the browser tools: a browser-testing "
                "task builds first, then proves in the browser."
            ),
        )

    if any(word in description for word in (
        "scaffold", "install", "bootstrap", "initialize project", "setup project",
    )):
        return ExecutionPhase(
            "setup", None,
            guidance=(
                "SETUP step. Execute the planned scaffold/install directly and "
                "move on; the next step owns verification."
            ),
        )

    if any(word in description for word in (
        "create", "write", "implement", "copy", "edit", "modify", "update",
        "route", "component", "deliver",
    )):
        return ExecutionPhase(
            "deliver", None,
            max_file_mutations_per_turn=2,
            guidance=(
                "DELIVER step. Make the source mutations now — every named "
                "file needs its own landed receipt; batch at most two file "
                "mutations per response."
            ),
        )

    return ExecutionPhase("general", None)

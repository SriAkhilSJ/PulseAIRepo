"""Receipt-driven execution phases and phase-specific capability filters.

Hermes keeps hard loop guardrails pure and lets runtime code project decisions.
This module does the same for workflow progress: derive a phase from the active
plan receipt, expose only useful tools, and provide compact execution guidance.
It never hardcodes benchmark paths or component names.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ExecutionPhase:
    name: str
    allowed: frozenset[str] | None
    max_file_mutations_per_turn: int = 0
    guidance: str = ""


_ALWAYS = frozenset({"ask_user"})
_FILE_MUTATIONS = frozenset({"write_file", "edit_file", "copy_file"})
_READS = frozenset({
    "read_file", "list_files", "search_code", "session_search",
    "discover_host_capabilities", "invoke_host_capability",
})
_TERMINAL = frozenset({
    "run_terminal", "start_terminal", "check_terminal", "read_terminal_output",
    "stop_terminal", "list_terminal_processes", "cleanup_terminal_processes",
})
_BROWSER = frozenset({
    "browser_navigate", "browser_snapshot", "browser_screenshot",
    "browser_click", "browser_type", "browser_select", "browser_hover",
    "browser_evaluate", "verify_ui_workspace", "verify_ui_routes",
})


def _active_step(state: dict[str, Any]) -> dict[str, Any] | None:
    for step in state.get("plan", []) or []:
        if step.get("status") == "in_progress":
            return step
    return None


def derive_execution_phase(state: dict[str, Any]) -> ExecutionPhase:
    if os.environ.get("PULSEAI_PHASE_GUARD", "on").strip().lower() in {
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
            "visual_verify",
            _ALWAYS | _BROWSER | _TERMINAL | _READS | _FILE_MUTATIONS |
            frozenset({"typecheck_workspace", "verify"}),
            max_file_mutations_per_turn=2,
            guidance=(
                "VISUAL VERIFY phase. Prefer one verify_ui_workspace or "
                "verify_ui_routes receipt. Use individual browser tools only "
                "for interactions. If proof fails, make at most two targeted "
                "file repairs, then repeat the composite receipt once."
            ),
        )

    if any(word in description for word in (
        "typecheck", "type check", "test", "lint", "build", "static verify",
    )):
        return ExecutionPhase(
            "static_verify",
            _ALWAYS | _READS | _FILE_MUTATIONS |
            frozenset({"typecheck_workspace", "run_terminal", "verify"}),
            max_file_mutations_per_turn=2,
            guidance=(
                "STATIC VERIFY phase. Run the named check now. On failure, "
                "use its exact diagnostics for at most two targeted repairs; "
                "do not re-inspect unrelated files or rerun unchanged checks."
            ),
        )

    if any(word in description for word in (
        "scaffold", "install", "bootstrap", "initialize project", "setup project",
    )):
        return ExecutionPhase(
            "setup",
            _ALWAYS | frozenset({"scaffold_nextjs", "run_terminal", "copy_file"}),
            guidance=(
                "SETUP phase. Execute the planned scaffold/install directly. "
                "Do not inspect generated boilerplate or package metadata; the "
                "next plan phase owns delivery."
            ),
        )

    if any(word in description for word in (
        "create", "write", "implement", "copy", "edit", "modify", "update",
        "route", "component", "deliver",
    )):
        return ExecutionPhase(
            "deliver",
            _ALWAYS | _FILE_MUTATIONS,
            max_file_mutations_per_turn=2,
            guidance=(
                "DELIVER phase. Make source mutations now—no think/read/list/"
                "search/terminal calls. Emit at most two file mutation calls "
                "this response and keep their combined content concise (about "
                "8,000 characters). Continue in the next turn for remaining "
                "files; every named file needs its own landed receipt."
            ),
        )

    return ExecutionPhase("general", None)


def filter_tool_names(names: Iterable[str], phase: ExecutionPhase) -> list[str]:
    ordered = list(dict.fromkeys(names))
    if phase.allowed is None:
        return ordered
    return [name for name in ordered if name in phase.allowed]


def phase_allows(tool_name: str, allowed_names: Iterable[str] | None) -> bool:
    if allowed_names is None:
        return True
    return tool_name in set(allowed_names)

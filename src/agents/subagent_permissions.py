"""Permission derivation for subagents — port of OpenCode's deriveSubagentSessionPermission.

OpenCode logic:
- Inherit parent's deny rules + external_directory rules
- Add todowrite deny if subagent doesn't allow todowrite
- Add task deny if subagent doesn't allow task

Crusor adaptation:
- Crusor uses tuple of allowed capabilities + path-based safety_guard
- We keep both: capability check (existing KNOWN_CAPABILITIES subset) + file permission deny inheritance
- For file permissions, we treat parent's deny list as ruleset similar to OpenCode's PermissionV1.Ruleset

This module provides pure functions, no side effects, easy to test.
"""

from __future__ import annotations

from typing import Any

# Canonical per-mode capability scopes for sub-agent children. These speak
# the COARSE capability vocabulary (runtime_profile.KNOWN_CAPABILITIES) --
# the only vocabulary the toolset waist (tools.toolsets.resolve_runtime_
# tool_names) and the strict binder understand. Mode->tool-name maps are
# forbidden here: filtering tool names through KNOWN_CAPABILITIES silently
# collapses every child's scope to () (found 2026-10-15: children then ran
# strict-empty and paid for / received the full parent schema surface).
MODE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "research": ("research", "workspace_read"),
    "code": ("workspace_read", "workspace_write", "execution", "verification"),
    "test": ("workspace_read", "execution", "verification"),
    "review": ("workspace_read",),
}
_DEFAULT_MODE_CAPABILITIES = (
    "workspace_read", "workspace_write", "execution", "verification",
)


def default_capabilities_for_mode(mode: str) -> tuple[str, ...]:
    """Coarse capabilities a sub-agent mode runs with when nothing stricter
    was derived from the parent."""
    return MODE_CAPABILITIES.get((mode or "").strip().lower(), _DEFAULT_MODE_CAPABILITIES)


def derive_subagent_session_permission(
    parent_permission: list[dict[str, Any]] | None,
    subagent_permission: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """
    Derive child permission from parent.

    parent_permission: list of {permission, pattern, action}
    subagent_permission: list of same for subagent's own rules

    Returns merged ruleset:
    - parent deny + external_directory
    - plus todowrite/task deny if subagent doesn't have allow
    """
    parent = parent_permission or []
    subagent = subagent_permission or []

    # Keep parent deny + external_directory
    inherited = [
        r for r in parent
        if r.get("action") == "deny" or r.get("permission") == "external_directory"
    ]

    # Check if subagent allows todowrite / task
    def allows(perm_name: str) -> bool:
        for r in subagent:
            if r.get("permission") == perm_name and r.get("action") in ("allow", "ask"):
                return True
        return False

    # If subagent doesn't explicitly allow todowrite, deny it
    if not allows("todowrite"):
        # avoid duplicate if already denied
        if not any(r.get("permission") == "todowrite" and r.get("action") == "deny" for r in inherited):
            inherited.append({"permission": "todowrite", "pattern": "*", "action": "deny"})

    if not allows("task"):
        if not any(r.get("permission") == "task" and r.get("action") == "deny" for r in inherited):
            inherited.append({"permission": "task", "pattern": "*", "action": "deny"})

    # Deduplicate by (permission, pattern, action)
    seen = set()
    out = []
    for r in inherited:
        key = (r.get("permission"), r.get("pattern"), r.get("action"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out

def derive_subagent_capabilities(
    parent_capabilities: tuple[str, ...],
    requested_capabilities: tuple[str, ...],
) -> tuple[str, ...]:
    """
    Ensure child capabilities are subset of parent.
    Returns filtered tuple that is subset, or raises if broadening.
    """
    if not parent_capabilities:
        return requested_capabilities
    parent_set = set(parent_capabilities)
    requested_set = set(requested_capabilities)
    if not requested_set.issubset(parent_set):
        # Filter to subset instead of raising — caller can decide
        # But for safety, we return intersection and let caller check
        return tuple(sorted(requested_set & parent_set))
    return requested_capabilities

# OpenCode's tool-output limits (packages/core tool-output:
# MAX_LINES = 2000, MAX_BYTES = 50 KiB). A child's result used to be
# cut at 2,000 CHARACTERS, head-first — but a final answer's
# conclusion sits at its end, so the parent received research with
# its verdict amputated and had to re-ask the user things the child
# had already settled (founder field 2026-10-16, the parent's own
# words: "its conclusion was truncated in the summary and I can't
# verify from it whether your preference question was actually
# asked and answered"). Upstream's limits, and when they do bite
# the marker says so and points at the child's session, where the
# full answer durably lives.
_DELEGATE_RESULT_MAX_LINES = 2000
_DELEGATE_RESULT_MAX_CHARS = 50 * 1024


def truncate_delegate_result(text: str, session_id: str) -> str:
    """One result, delivered whole up to OpenCode's tool-output
    limits; past them, cut with an explicit marker (never silently,
    and never duplicated under two wrappers)."""
    truncated = False
    lines = text.split("\n")
    if len(lines) > _DELEGATE_RESULT_MAX_LINES:
        text = "\n".join(lines[:_DELEGATE_RESULT_MAX_LINES])
        truncated = True
    if len(text) > _DELEGATE_RESULT_MAX_CHARS:
        text = text[:_DELEGATE_RESULT_MAX_CHARS]
        truncated = True
    if truncated:
        text += (
            f"\n\n[Result truncated — the child's full answer is in "
            f"its session (session_id: {session_id}); open or resume "
            f"that session to read the rest.]"
        )
    return text


def format_task_output(
    session_id: str,
    state: str,
    text: str,
    summary: str | None = None,
) -> str:
    """
    Render OpenCode-style <task> XML output for parent LLM.

    state: running|completed|error
    """
    tag = "task_error" if state == "error" else "task_result"
    parts = [f'<task id="{session_id}" state="{state}">']
    if summary:
        # escape summary minimal
        safe_summary = summary.replace("<", "&lt;").replace(">", "&gt;")[:200]
        parts.append(f"<summary>{safe_summary}</summary>")
    parts.append(f"<{tag}>")
    parts.append(truncate_delegate_result(text, session_id) if state != "running" else text[:500])
    parts.append(f"</{tag}>")
    parts.append("</task>")
    return "\n".join(parts)

BACKGROUND_STARTED = (
    "The task is working in the background. You will be notified automatically when it finishes. "
    "DO NOT sleep, poll for progress, ask the task for status, or duplicate this task's work — "
    "avoid working with the same files or topics it is using. Work on non-overlapping tasks, or "
    "briefly tell the user what you launched and end your response."
)

BACKGROUND_UPDATED = (
    "Additional context sent to the running background task. "
    "The task is still working in the background. You will be notified automatically when it finishes. "
    "DO NOT sleep, poll for progress, ask the task for status, or duplicate this task's work."
)

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
    parts.append(text[:2000] if state != "running" else text[:500])
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

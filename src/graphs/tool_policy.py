"""Explicit graph tool side-effect classification (Increment 2).

Every tool the graph can invoke is classified here. The canonical runtime
fails closed for unknown names, and only tools with a proven broker-mediated
mutation path are allowed to change the workspace.

Categories
----------
read_only        no workspace write; existing authorization still applies.
state_only       mutates graph/session state, not the workspace.
external         interacts with an external system (browser/device/web).
delegation       spawns a child turn; the child re-enters this same policy.
workspace_write  mutates workspace files; must use WorkspaceMutationBroker
                 with an approval token bound to the proposed content digest.
shell / unknown  potentially mutating or unclassifiable; fail closed.
"""
from __future__ import annotations

READ_ONLY = frozenset({
    "read_file", "list_files", "search_files", "search_code",
    "session_search", "web_search", "web_fetch", "web_extract", "media_search",
    "browser_navigate", "browser_snapshot", "browser_scroll", "browser_back",
    "browser_console", "browser_get_images", "browser_screenshot",
    "skills_list", "skill_view", "hub_search", "hub_list",
    "discover_host_capabilities", "mcp_servers", "mcp_tools",
    "think", "verify", "clarify", "check_terminal", "read_terminal_output",
    "list_terminal_processes", "check_target_toolchains", "detect_targets",
    "device_screenshot", "device_ui", "device_logs", "device_preview",
    "open_preview",
})

STATE_ONLY = frozenset({
    "todo_list", "plan_update", "display_crusor_task",
})

EXTERNAL = frozenset({
    "hub_install", "hub_remove", "hub_update",
    "browser_click", "browser_type", "browser_press",
    "device_action", "invoke_host_capability", "mcp_call",
    "install_toolchain", "skill_manage",
})

DELEGATION = frozenset({
    "delegate_to_subagent", "delegate_to_subagent_batch",
})

# Workspace writes with a proven broker path (enabled in Increment 2).
WORKSPACE_WRITE_ENABLED = frozenset({
    "write_file", "edit_file",
})

# Workspace writes that remain fail-closed until they prove the same
# path/operation/digest/approval contract (or have no broker implementation).
WORKSPACE_WRITE_DISABLED = frozenset({
    "copy_file", "delete_file", "move_file", "rename_file", "apply_patch",
    "create_file", "bulk_write", "generate_image", "media_download",
    "build_target",
})

SHELL = frozenset({
    "run_terminal", "start_terminal", "terminal", "execute_code", "code_exec",
    "stop_terminal", "cleanup_terminal_processes",
})

# Verification tools execute toolchain commands; they do not write source and
# remain available under their existing controls.
READ_ONLY_EXECUTION = frozenset({
    "typecheck_workspace", "verify_ui_workspace", "verify_ui_routes",
    "verify_target_app",
})

_ALL_CLASSIFIED = (
    READ_ONLY
    | STATE_ONLY
    | EXTERNAL
    | DELEGATION
    | WORKSPACE_WRITE_ENABLED
    | WORKSPACE_WRITE_DISABLED
    | SHELL
    | READ_ONLY_EXECUTION
)


def classify_tool(name: str) -> str:
    """Return the side-effect class for a tool name (``unknown`` if absent)."""
    normalized = str(name or "").strip().lower()
    if normalized in READ_ONLY:
        return "read_only"
    if normalized in READ_ONLY_EXECUTION:
        return "read_only_execution"
    if normalized in STATE_ONLY:
        return "state_only"
    if normalized in WORKSPACE_WRITE_ENABLED:
        return "workspace_write"
    if normalized in WORKSPACE_WRITE_DISABLED:
        return "workspace_write_disabled"
    if normalized in SHELL:
        return "shell"
    if normalized in EXTERNAL:
        return "external"
    if normalized in DELEGATION:
        return "delegation"
    return "unknown"


def is_known(name: str) -> bool:
    return str(name or "").strip().lower() in _ALL_CLASSIFIED


def is_enabled_workspace_write(name: str) -> bool:
    return str(name or "").strip().lower() in WORKSPACE_WRITE_ENABLED


def requires_mutation_token(name: str) -> bool:
    return is_enabled_workspace_write(name)


def tool_inventory() -> dict[str, str]:
    """Deterministic name -> class map (evidence/reporting helper)."""
    return {name: classify_tool(name) for name in sorted(_ALL_CLASSIFIED)}

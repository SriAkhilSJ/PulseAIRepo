"""Deterministic tool waist for the broad Scope IDE agent.

Scope can code, research, create documents/data artifacts, operate processes,
and use a browser.  It does not expose every capability on every request.
`runtime_profile.resolve_runtime_profile()` is the single posture resolver;
this module only maps its immutable capabilities to real tool names.
"""
from __future__ import annotations

import os
from typing import Any

from src.agents.runtime_profile import (
    CAP_BROWSER,
    CAP_DELEGATION,
    CAP_DESKTOP_APP,
    CAP_EXECUTION,
    CAP_MOBILE_APP,
    CAP_RESEARCH,
    CAP_VERIFICATION,
    CAP_WORKSPACE_READ,
    CAP_WORKSPACE_WRITE,
    RuntimeProfile,
    resolve_runtime_profile,
)

# Paid on every turn. Keep this truly universal and action-neutral.
# todo_list + clarify are hermes' always-available pair (todo_tool.py
# check_todo_requirements -> True; clarify_tool.py check_clarify_requirements
# -> True): the task list and the ask-the-user tool are never posture-gated.
_CORE_TOOLS: tuple[str, ...] = (
    "think", "verify", "session_search", "todo_list", "clarify",
)

_WORKSPACE_READ_TOOLS: tuple[str, ...] = (
    "read_file", "list_files", "search_files", "search_code",
    "discover_host_capabilities", "invoke_host_capability", "open_preview",
)
_WORKSPACE_WRITE_TOOLS: tuple[str, ...] = (
    "write_file", "edit_file", "copy_file",
)
_EXECUTION_TOOLS: tuple[str, ...] = (
    "run_terminal", "terminal", "execute_code",
    "start_terminal", "check_terminal", "read_terminal_output",
    "stop_terminal", "list_terminal_processes", "cleanup_terminal_processes",
)
_VERIFICATION_TOOLS: tuple[str, ...] = ("typecheck_workspace",)
_UI_SCAFFOLD_TOOLS: tuple[str, ...] = (
    "verify_ui_workspace", "verify_ui_routes",
)
# Multi-platform delivery (src/targets/): detect the target, check the
# toolchain, build it, then prove it on a device/emulator/simulator/window.
# `verify_target_app` is the composite receipt — the multi-platform peer of
# verify_ui_workspace — so it is bound in one call, not as a chain of steps.
_TARGET_TOOLS: tuple[str, ...] = (
    "detect_targets", "check_target_toolchains", "install_toolchain",
    "build_target", "verify_target_app",
)
_MOBILE_DEVICE_TOOLS: tuple[str, ...] = (
    "device_action", "device_screenshot", "device_ui", "device_logs",
    # Mirror the device into the IDE's preview window (src/preview/device.py):
    # the human watches and pokes the same device the agent is driving.
    "device_preview",
)
_RESEARCH_TOOLS: tuple[str, ...] = ("web_search", "web_fetch", "web_extract")
_MEDIA_TOOLS: tuple[str, ...] = ("media_search", "media_download", "generate_image")
# Skills are always in context (index + eager injection), so the pull tools
# that load a skill body on demand are always bound — Agent Skills parity.
# The hub tools are the INSTALL side of the same story and ride the same
# always-on waist (discovery -> install -> skill_view pull).
_SKILL_TOOLS: tuple[str, ...] = (
    "skills_list", "skill_view", "skill_manage",
    "hub_search", "hub_install", "hub_update", "hub_list", "hub_remove",
)
_DELEGATION_TOOLS: tuple[str, ...] = (
    "delegate_to_subagent", "delegate_to_subagent_batch",
)


def web_available(config: Any = None) -> bool:
    """Web is bundled through ddgs; an explicit operator opt-out wins."""
    val = os.environ.get("CRUSORAI_WEB_TOOLS", "").strip().lower()
    return val not in ("off", "0", "false", "no", "disabled")


def _browser_tool_names() -> tuple[str, ...]:
    """Registered browser tools, loaded lazily because the agent-browser CLI
    is resolved per call (hermes backend; browser_mcp is retired)."""
    try:
        from src.tools.browser_tools import BROWSER_TOOLS
        return tuple(t.name for t in BROWSER_TOOLS)
    except Exception:
        return ()


def resolve_runtime_tool_names(profile: RuntimeProfile, config: Any = None) -> list[str]:
    """Map one immutable profile to ordered, de-duplicated real tool names."""
    names: list[str] = list(_CORE_TOOLS)
    names.extend(_SKILL_TOOLS)
    caps = set(profile.capabilities)

    if CAP_WORKSPACE_READ in caps:
        names.extend(_WORKSPACE_READ_TOOLS)
    if CAP_WORKSPACE_WRITE in caps:
        names.extend(_WORKSPACE_WRITE_TOOLS)
    if CAP_EXECUTION in caps:
        names.extend(_EXECUTION_TOOLS)
    if CAP_VERIFICATION in caps:
        names.extend(_VERIFICATION_TOOLS)
    if CAP_RESEARCH in caps and web_available(config):
        names.extend(_RESEARCH_TOOLS)
        names.extend(_MEDIA_TOOLS)
    if CAP_BROWSER in caps:
        names.extend(_browser_tool_names())
        if CAP_VERIFICATION in caps:
            names.extend(_UI_SCAFFOLD_TOOLS)
    if CAP_MOBILE_APP in caps or CAP_DESKTOP_APP in caps:
        names.extend(_TARGET_TOOLS)
        if CAP_MOBILE_APP in caps:
            names.extend(_MOBILE_DEVICE_TOOLS)
    if CAP_DELEGATION in caps:
        names.extend(_DELEGATION_TOOLS)

    return list(dict.fromkeys(names))


def resolve_toolset_names(task: str, config: Any = None) -> list[str]:
    """Compatibility entry point used by the graph."""
    return resolve_runtime_tool_names(resolve_runtime_profile(task, config), config)


def looks_like_ui_task(task: str) -> bool:
    """Compatibility predicate backed by the canonical profile resolver."""
    return resolve_runtime_profile(task).has(CAP_BROWSER)


def looks_like_execution_task(task: str) -> bool:
    """Compatibility predicate backed by the canonical profile resolver."""
    return resolve_runtime_profile(task).has(CAP_EXECUTION)


def all_known_tool_names() -> list[str]:
    """Every name this resolver can return, in canonical group order."""
    names = [
        *_CORE_TOOLS,
        *_SKILL_TOOLS,
        *_WORKSPACE_READ_TOOLS,
        *_WORKSPACE_WRITE_TOOLS,
        *_EXECUTION_TOOLS,
        *_VERIFICATION_TOOLS,
        *_RESEARCH_TOOLS,
        *_MEDIA_TOOLS,
        *_browser_tool_names(),
        *_UI_SCAFFOLD_TOOLS,
        *_TARGET_TOOLS,
        *_MOBILE_DEVICE_TOOLS,
        *_DELEGATION_TOOLS,
    ]
    return list(dict.fromkeys(names))


__all__ = [
    "resolve_toolset_names",
    "resolve_runtime_tool_names",
    "resolve_runtime_profile",
    "all_known_tool_names",
    "looks_like_ui_task",
    "looks_like_execution_task",
    "web_available",
]

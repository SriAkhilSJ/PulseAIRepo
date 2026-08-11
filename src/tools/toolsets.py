# src/tools/toolsets.py
"""
Toolset waist — Hermes Law #2 (narrow core, capability at the edges).

Every bound tool DEFINITION ships on EVERY api call, so the set of tools the
model SEES must be the smallest set that can do the work. This mirrors
hermes-agent/toolsets.py: a narrow CORE + named toolsets + check_fn gating
(a tool only enters the schema when its prerequisite is configured or the
task needs it).

``resolve_toolset_names`` returns the ordered, de-duplicated tool NAMES for a
turn, picked from ``(task, config)``. ``chat_graph`` maps names -> objects
from its tool registry and binds ONLY those. The SafeToolNode still holds the
FULL registry so it can execute whatever is bound; the model simply never
sees the gated tools, so it never calls them.

Cache-safe (Hermes Law #1): within one task the inputs (task text, config
gates) are stable, so ``resolve_toolset_names`` is deterministic per task —
the tools block in the request is byte-identical turn over turn, so prompt
caches survive. The set only changes across a NEW task (a new user turn),
where the cache legitimately resets anyway.

Conservative by design: this only CUTS clearly task-irrelevant tools. It
never silently adds a tool that was not in the original registry, and a
kill-switch (``PULSEAI_TOOLSETS=off``) restores the full all-tools binding.

Measured lever: the chat-app lab run sent ~5,686 tool-def tokens every call
across 30 bound tools. Gating the 8 browser tools off for non-UI tasks (the
common coding case) drops that to 22 tools — the single biggest per-call
static-token cut available, and it is pure code (Hermes Law #2 alignment).
"""
from __future__ import annotations

import os
import re
from typing import Any

# --------------------------------------------------------------------------- #
# The narrow waist: every coding turn needs these. Kept minimal on purpose —  #
# every entry here is paid for on every call.                                 #
# --------------------------------------------------------------------------- #
_CORE_TOOLS: tuple[str, ...] = (
    "think", "verify", "ask_user",
    "read_file", "list_files", "search_code",
    "write_file", "edit_file", "copy_file",
    "run_terminal", "execute_code",
)

# Small, broadly useful, always on (parallelization + cross-session recall).
_ALWAYS_TOOLS: tuple[str, ...] = (
    "delegate_to_subagent",
    "delegate_to_subagent_batch",
    "session_search",
)

# Execution extras: static verification (can't ship unverified code) +
# long-lived process control (dev servers, long builds). run_terminal (in
# CORE) already covers one-shot commands.
_EXECUTION_TOOLS: tuple[str, ...] = (
    "typecheck_workspace",
    "start_terminal", "check_terminal", "read_terminal_output",
    "stop_terminal", "list_terminal_processes", "cleanup_terminal_processes",
)

# Web search/fetch. ddgs (the default web_search backend) is bundled + free,
# so these are on by default; ``PULSEAI_WEB_TOOLS=off`` opts out.
_WEB_TOOLS: tuple[str, ...] = ("web_search", "web_fetch")


# --------------------------------------------------------------------------- #
# check_fn gates                                                              #
# --------------------------------------------------------------------------- #
def web_available(config: Any = None) -> bool:
    """Is the web toolset configured? ddgs is free + bundled, so default ON;
    an explicit opt-out (``PULSEAI_WEB_TOOLS=off``) is the only way off."""
    val = os.environ.get("PULSEAI_WEB_TOOLS", "").strip().lower()
    if val in ("off", "0", "false", "no", "disabled"):
        return False
    return True


def _browser_tool_names() -> tuple[str, ...]:
    """The registered browser tool names. Imported lazily so this module
    stays import-cheap and never requires the (optional) MCP stack."""
    try:
        from src.tools.browser_mcp import BROWSER_TOOLS
        return tuple(t.name for t in BROWSER_TOOLS)
    except Exception:
        return ()


# --------------------------------------------------------------------------- #
# Task-type detection (self-contained so the resolver is unit-testable with   #
# no LLM / embedding deps — a behavior contract, per Hermes test discipline). #
# --------------------------------------------------------------------------- #
_UI_TASK_PHRASES = (
    "web app", "web application", "webapp", "chat app", "chatbot",
    "user interface", "frontend app", "front-end app", "next.js",
    "nextjs", "react app", "single page app",
)
_UI_TASK_WORDS = frozenset({
    "app", "ui", "web", "chat", "frontend", "front-end", "browser",
    "dashboard", "component", "page", "website", "interface", "react",
    "vue", "screenshot",
})
_EXEC_MARKERS = (
    "build", "create", "implement", "integrate", "install", "fix",
    "refactor", "debug", "test", "scaffold", "develop", "deploy",
    "configure", "write a", "make a", "add ", "migrate", "upgrade",
)


def looks_like_ui_task(task: str) -> bool:
    """True when the task produces a UI deliverable that needs a browser to
    prove it renders. Word-based on purpose (a naive substring 'ui' would
    also hit inside 'build')."""
    t = (task or "").lower()
    if any(p in t for p in _UI_TASK_PHRASES):
        return True
    words = set(re.findall(r"[a-z0-9]+", t))
    return bool(words & _UI_TASK_WORDS)


def looks_like_execution_task(task: str) -> bool:
    """True when the task produces/changes a deliverable (vs. a pure
    chat/explain). Execution tasks get the verification + process tools."""
    t = (task or "").lower()
    return any(marker in t for marker in _EXEC_MARKERS)


# --------------------------------------------------------------------------- #
# The resolver                                                                #
# --------------------------------------------------------------------------- #
def resolve_toolset_names(task: str, config: Any = None) -> list[str]:
    """Return the ordered, de-duplicated tool NAMES to bind for this turn.

    Conservative: only CUTS clearly task-irrelevant tools (browser for non-UI
    tasks; web when explicitly opted out; execution tools for pure chat).
    Never adds a tool outside the original registry.
    """
    names: list[str] = list(_CORE_TOOLS) + list(_ALWAYS_TOOLS)

    # No task text yet (first turn) => assume execution-capable (the safe,
    # superset choice; the model can still just chat if it wants).
    if looks_like_execution_task(task) or not task:
        names.extend(_EXECUTION_TOOLS)

    if web_available(config):
        names.extend(_WEB_TOOLS)

    if looks_like_ui_task(task):
        names.extend(_browser_tool_names())

    # de-dupe, preserve first-seen order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# The full superset, for the kill-switch path and for tests that need to
# assert "every resolved tool is a real tool". Built from the named groups.
def all_known_tool_names() -> list[str]:
    """Every tool name the resolver can ever return (browser included)."""
    names: list[str] = (
        list(_CORE_TOOLS)
        + list(_ALWAYS_TOOLS)
        + list(_EXECUTION_TOOLS)
        + list(_WEB_TOOLS)
        + list(_browser_tool_names())
    )
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out

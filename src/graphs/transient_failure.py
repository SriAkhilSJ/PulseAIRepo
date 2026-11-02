"""Bounded advisory retention for recent, uncorrected startup tracebacks.

This is not verification evidence or a completion gate. We inspect the real
checkpointed receipts, stop at possible workspace mutations, and extract only
structured exception facts rather than promoting arbitrary tool output into a
system instruction. Shell classification here is conservative and advisory.
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

_READ_ONLY_TOOLS = frozenset({
    "read_file", "list_files", "search_files", "search_code", "think",
    "todo_list", "plan_update", "discover_tools", "web_search", "web_fetch",
    "web_extract", "browser_snapshot", "browser_screenshot", "session_search",
})
_EXC = re.compile(r"^(NameError|ModuleNotFoundError|ImportError|SyntaxError|IndentationError|AttributeError):[^\n]*$", re.MULTILINE)
_MISSING_NAME = re.compile(r"^NameError: name ['\"]([A-Za-z_][A-Za-z_0-9]{0,63})['\"] is not defined$")
_EXIT_NONZERO = re.compile(r"\bexit code:\s*(-?\d+)", re.IGNORECASE)


def recent_startup_failure(messages: list[Any], limit: int = 12) -> str:
    """Return a concise recent traceback observation, or nothing after a barrier."""
    from src.runtime.tool_middleware import _progress_read_only_command

    turn = []
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            break
        turn.append(msg)
    turn.reverse()
    args_by_id = {}
    for msg in turn:
        for call in getattr(msg, "tool_calls", None) or []:
            if isinstance(call, dict):
                args_by_id[call.get("id")] = call.get("args") or {}

    checked = 0
    for msg in reversed(turn):
        if not isinstance(msg, ToolMessage):
            continue
        checked += 1
        if checked > limit:
            break
        name = msg.name or ""
        text = str(msg.content or "")
        args = args_by_id.get(msg.tool_call_id) or {}
        if name in {"terminal", "run_terminal"}:
            codes = _EXIT_NONZERO.findall(text)
            match = _EXC.search(text) if "Traceback (most recent call last):" in text else None
            if codes and int(codes[-1]) != 0 and match:
                exception = match.group(1)
                missing = _MISSING_NAME.fullmatch(match.group(0).strip())
                detail = f" (undefined name: {missing.group(1)})" if missing else ""
                return f"Recent terminal traceback: {exception}{detail}."
            # Unknown commands (even failures) may have changed the workspace.
            if not _progress_read_only_command(str(args.get("command") or "")):
                break
        elif name not in _READ_ONLY_TOOLS:
            break
    return ""

"""Small, permission-neutral catalog for continuous parent tool discovery.

Discovery only advertises capabilities already selected by the graph. Actual
execution remains subject to the bound-surface, phase, permission and safety
checks in SafeToolNode. Activations live in the durable tool-result history.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# A stable task-neutral baseline; all other eligible tools remain discoverable.
CORE = frozenset({
    "think", "verify", "todo_list", "clarify", "plan_update",
    "read_file", "list_files", "search_files", "search_code",
    "write_file", "edit_file", "copy_file", "terminal", "run_terminal",
    "start_terminal", "check_terminal", "read_terminal_output", "stop_terminal",
    "web_search", "web_fetch", "web_extract", "browser_navigate",
    "browser_snapshot", "browser_screenshot", "browser_click", "browser_type",
    "typecheck_workspace", "verify_ui_workspace", "verify_ui_routes",
    "discover_tools",
})


@tool
def discover_tools(query: str = "", names: list[str] | None = None,
                   config: RunnableConfig = None) -> str:
    """Find and activate additional tools by name or keyword.

    Some available capabilities are not listed as direct tools until activated:
    use this for images, delegation, plugins/MCP, skills, device operations,
    advanced browser actions, or any other capability you need. Search with
    query (empty lists all names); activate by supplying exact names in names.
    Activated tools bind on the next model turn, not in this same batch.
    Discovery grants no permissions; actual calls remain subject to safety approval.
    """
    catalog = ((config or {}).get("configurable") or {}).get("progressive_tool_catalog") or []
    entries = [entry for entry in catalog if isinstance(entry, dict) and entry.get("name")]
    available = {str(entry["name"]): entry for entry in entries}
    requested = list(dict.fromkeys(str(n).strip() for n in (names or []) if str(n).strip()))[:30]
    activated = [name for name in requested if name in available]
    unknown = [name for name in requested if name not in available]
    q = query.strip().lower()[:120]
    matches = [entry for entry in entries if (
        (not q and (not requested or entry["name"] in requested))
        or (q and q in (str(entry["name"]) + " " + str(entry.get("description", ""))).lower())
    )]
    return json.dumps({
        "activated": activated,
        "unavailable": unknown,
        "matches": matches[:60],
        "remaining": max(0, len(matches) - 60),
        "note": "Activated tools bind on the next turn; permissions still apply.",
    }, ensure_ascii=False)


def activated_tools(messages: list[Any]) -> set[str]:
    """Recover current-turn activations from actual successful tool receipts."""
    activated: set[str] = set()
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if not isinstance(message, ToolMessage) or message.name != "discover_tools":
            continue
        if getattr(message, "status", "success") == "error":
            continue
        try:
            data = json.loads(str(message.content))
            names = data.get("activated") if isinstance(data, dict) else None
            if isinstance(names, list):
                activated.update(name for name in names if isinstance(name, str))
        except (ValueError, TypeError):
            continue
    return activated

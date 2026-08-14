"""Single durable execution chokepoint for direct, parallel, and PTC tools.

Callers own scope and approval because those depend on their surface, then enter
this pipeline. The invoked tool owns its pre-mutation checkpoint. This function
owns durable intent/result ordering and result projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    status: str
    result_seq: int | None = None


def execute_tool_transaction(
    *, name: str, args: dict[str, Any], tool_call_id: str, config,
    invoke: Callable[[], Any], project: bool = True,
) -> ToolOutcome:
    configurable = (config or {}).get("configurable", {})
    session_id = str(configurable.get("thread_id") or "default")
    turn_id = str(configurable.get("turn_id") or "") or None
    workspace = str(configurable.get("workspace") or ".")
    from src.runtime.factory import get_runtime_services
    from src.runtime.identity import workspace_id
    services = get_runtime_services()
    services.journal.append(
        "tool.intent", {"tool_name": name, "args": args},
        session_id=session_id, turn_id=turn_id,
        workspace_id=workspace_id(workspace), tool_call_id=tool_call_id,
    )

    status = "ok"
    try:
        raw = invoke()
        content = raw if isinstance(raw, str) else str(raw)
        import re
        if (
            re.search(r"(?:^|\n)Exit code:\s*[1-9]\d*", content)
            or content.lstrip().startswith(("⛔", "❌", "Error:"))
        ):
            status = "error"
    except Exception as exc:
        status = "error"
        content = f"Error: {name}() failed: {type(exc).__name__}: {exc}"

    persisted = services.journal.append(
        "tool.result", {"tool_name": name, "status": status, "content": content},
        session_id=session_id, turn_id=turn_id,
        workspace_id=workspace_id(workspace), tool_call_id=tool_call_id,
    )
    if project:
        from src.dashboard.event_bus import event_bus
        event_bus.emit("tool.result", {
            "thread_id": session_id, "turn_id": turn_id,
            "tool_id": tool_call_id, "tool_name": name,
            "result": content, "status": status,
            "journal_seq": persisted["seq"],
        })
    return ToolOutcome(content, status, persisted["seq"])

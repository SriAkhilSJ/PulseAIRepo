"""Lazy tools for read-only capabilities supplied by the Code OSS workbench."""
from __future__ import annotations

import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


@tool
def discover_host_capabilities(query: str, config: RunnableConfig) -> str:
    """Discover relevant read-only native editor capabilities.

    Returns compact availability metadata only. Use before invoking native
    diagnostics, symbols, references, editor context, search, SCM, or trust.
    An empty query lists all currently published read-only capabilities.
    """
    from src.runtime.host_capabilities import host_capability_broker

    session_id = str(config["configurable"].get("thread_id") or "default")
    items = host_capability_broker.discover(session_id, query)
    if not items:
        return "No matching native workbench capabilities are currently published."
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


@tool
def invoke_host_capability(
    capability_id: str, arguments: dict, config: RunnableConfig,
) -> str:
    """Invoke one published read-only native Code OSS capability.

    Allowed first-stage capabilities are workspace trust, active editor/dirty
    context, diagnostics, symbols, definitions, references, bounded workspace
    search, and SCM state. Mutation, execution, secrets, extension tools, and
    MCP tools are intentionally unavailable through this operation.
    """
    from src.runtime.host_capabilities import host_capability_broker

    configurable = config["configurable"]
    receipt = host_capability_broker.request(
        session_id=str(configurable.get("thread_id") or "default"),
        workspace=str(configurable.get("workspace") or "."),
        capability_id=capability_id,
        arguments=dict(arguments or {}),
    )
    return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), default=str)


HOST_TOOLS = [discover_host_capabilities, invoke_host_capability]

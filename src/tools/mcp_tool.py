"""MCP meta-tools — third-party capability at a flat token cost.

Wiring every MCP tool into the registry is the obvious thing and the wrong one:
`chat_graph._resolve_bound_tools` binds the whole registry every turn, so a
GitHub server (~90 tools) plus a browser server would put tens of thousands of
schema tokens into turns that never touch them. GitHub's own MCP server ships
`--toolsets` for that reason: *"help the LLM with tool choice and reduce the
context size."*

So the waist is three fixed tools (~300 tokens, whatever the workspace holds):

    mcp_servers()                 which servers exist, alive, tool counts
    mcp_tools(server?, query?)    the catalog; schemas only for what is asked
    mcp_call(server, tool, args)  run it, approval-gated, receipted

That is the honest version of the skills story: skills are zero-call because we
own them; MCP is one call because we do not.

Safety: third-party code has arbitrary side effects, so a call only proceeds
without a human if the server *itself* declares the tool read-only
(spec `annotations.readOnlyHint`). Everything else returns an approval request
naming exactly what would run; the model re-issues with `confirm=True` and the
transcript shows both halves. Results are wrapped as untrusted data by the tool
middleware (`mcp_` prefix), same as every other external source.
"""
from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.tools.mcp_client import (
    _POOL,
    _TOOLS_CACHE,
    call_mcp_tool,
    close_all,          # re-exported for tests/shutdown
    invalidate_mcp_cache,
    mcp_config_path,
    server_tools,
)

_MAX_DESC = 120
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 60


def _workspace(config: RunnableConfig | None) -> str:
    try:
        return str((config or {}).get("configurable", {}).get("workspace") or ".")  # type: ignore[union-attr]
    except Exception:
        return "."


def _configured(workspace: str) -> dict[str, dict]:
    """Servers named in .crusorai/mcp.json, enabled only. Never spawns."""
    path = mcp_config_path(workspace)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    servers = raw.get("servers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        return {}
    return {name: spec for name, spec in servers.items()
            if isinstance(spec, dict) and spec.get("enabled") is not False}


def _cached_tools(workspace: str, server: str) -> list[dict] | None:
    """The catalog only if it is already cached — a listing must not spawn."""
    import os
    hit = _TOOLS_CACHE.get((os.path.abspath(workspace or "."), server))
    return hit[1] if hit else None


def _trim(text: str, limit: int = _MAX_DESC) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@tool
def mcp_servers(config: RunnableConfig) -> str:
    """List the MCP servers configured for this workspace.

    Reports each server's name, whether a session is already live, and how many
    tools it exposes (only if the catalog has been loaded — listing never starts
    a server). Use mcp_tools(server) to load a catalog, then mcp_call to run a
    tool. Servers are configured in .crusorai/mcp.json.
    """
    workspace = _workspace(config)
    servers = _configured(workspace)
    if not servers:
        return ("No MCP servers configured. Add one to .crusorai/mcp.json, e.g. "
                '{"servers": {"files": {"command": "npx", "args": ["-y", '
                '"@modelcontextprotocol/server-filesystem", "/tmp"], "enabled": true}}}')
    import os
    lines = ["=== MCP SERVERS ==="]
    for name in servers:
        session = _POOL.get((os.path.abspath(workspace or "."), name))
        alive = "live" if (session is not None and session.is_alive()) else "not started"
        cached = _cached_tools(workspace, name)
        count = f"{len(cached)} tools cached" if cached is not None else "catalog not loaded"
        lines.append(f"- {name}: {alive}, {count}")
    lines.append("Next: mcp_tools(server) for names, mcp_tools(server, query) for a schema, "
                 "mcp_call(server, tool, arguments) to run one.")
    return "\n".join(lines)


@tool
def mcp_tools(server: str = "", query: str = "", limit: int = _DEFAULT_LIMIT,
              config: RunnableConfig = None) -> str:
    """List an MCP server's tools, or show one tool's exact input schema.

    Call with only `server` to see what it offers. Add `query` (a word from the
    tool name or description) to get the matching tools **with their input
    schemas** — that is what you need before mcp_call. Leave `server` empty to
    see every configured server at once.

    Schemas are only printed for what you ask about: a server with 90 tools must
    not cost 90 schemas per turn.
    """
    workspace = _workspace(config)
    servers = _configured(workspace)
    if not servers:
        return "No MCP servers configured (see .crusorai/mcp.json)."
    limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    q = (query or "").strip().lower()

    wanted = [server] if server else list(servers)
    unknown = [s for s in wanted if s not in servers]
    if unknown:
        return (f"No such server: {', '.join(unknown)}. Configured: "
                f"{', '.join(servers) or 'none'}")

    out: list[str] = []
    for name in wanted:
        tools = server_tools(workspace, name)  # cached, or one spawn to learn it
        if not tools:
            out.append(f"=== {name}: no tools (server did not start or exposes none) ===")
            continue
        matches = [t for t in tools
                   if not q or q in str(t.get("name", "")).lower()
                   or q in str(t.get("description", "")).lower()]
        header = f"=== {name}: {len(tools)} tool(s)"
        header += f", {len(matches)} matching {q!r}" if q else ""
        out.append(header + " ===")
        if not q:
            for t in tools[:limit]:
                ro = " [read-only]" if (t.get("annotations") or {}).get("readOnlyHint") else ""
                out.append(f"- {t.get('name')}{ro}: {_trim(t.get('description') or '')}")
            if len(tools) > limit:
                out.append(f"… {len(tools) - limit} more — narrow with query= or raise limit=")
        else:
            for t in matches[:limit]:
                ro = " [read-only]" if (t.get("annotations") or {}).get("readOnlyHint") else ""
                schema = json.dumps(t.get("inputSchema") or {"type": "object"}, ensure_ascii=False)
                if len(schema) > 1500:
                    schema = schema[:1500] + "…(truncated)"
                out.append(f"- {t.get('name')}{ro}: {_trim(t.get('description') or '')}\n"
                           f"  input_schema: {schema}")
            if not matches:
                out.append("  (nothing matched — call again without query to see the list)")
    return "\n".join(out)


@tool
def mcp_call(server: str, tool: str, arguments: dict | None = None,
             confirm: bool = False, config: RunnableConfig = None) -> str:
    """Run one tool on an MCP server.

    Arguments:
        server: the server name from mcp_servers.
        tool: the tool name from mcp_tools (exact, un-namespaced).
        arguments: the tool's input object, matching its input_schema.
        confirm: set only after the human has approved a non-read-only call.

    A tool the server declares read-only runs directly. Anything else is
    third-party code with arbitrary side effects: the first call returns an
    approval request instead of running, so the human sees what would happen.
    """
    workspace = _workspace(config)
    servers = _configured(workspace)
    if server not in servers:
        return (f"No such server: {server!r}. Configured: {', '.join(servers) or 'none'}")
    catalog = {str(t.get("name")): t for t in server_tools(workspace, server)}
    if not catalog:
        return (f"{server!r} exposes no tools (it did not start, or exposes none). "
                "Check the command in .crusorai/mcp.json.")
    meta = catalog.get(str(tool))
    if meta is None:
        near = [n for n in catalog if str(tool).lower() in n.lower()][:5]
        hint = f" Did you mean: {', '.join(near)}?" if near else ""
        return f"{server!r} has no tool {tool!r}.{hint} Call mcp_tools({server!r}) to list them."

    read_only = bool((meta.get("annotations") or {}).get("readOnlyHint"))
    if not read_only and not confirm:
        preview = json.dumps(arguments or {}, ensure_ascii=False)
        if len(preview) > 400:
            preview = preview[:400] + "…"
        return (
            f"APPROVAL REQUIRED — {server}/{tool} is not declared read-only by the "
            f"server, so it may have side effects.\n"
            f"  arguments: {preview}\n"
            f"If the user approves, call mcp_call({server!r}, {tool!r}, <same arguments>, "
            f"confirm=True). If they do not, do something else."
        )

    started = time.monotonic()
    result = call_mcp_tool(workspace, server, str(tool), arguments or {})
    elapsed = (time.monotonic() - started) * 1000
    return f"[mcp {server}/{tool} · {elapsed:.0f} ms]\n{result}"


MCP_TOOLS = (mcp_servers, mcp_tools, mcp_call)

"""Generic MCP (Model Context Protocol) client — Floor 5, right-sized.

hermes ships a 9,404-line ``mcp_tool.py`` (OAuth managers, dashboards,
schema caches, death supervisors). Crusor gets the CORE of the value in one
module: connect to user-configured MCP servers over stdio (newline-delimited
JSON-RPC 2.0 per the MCP spec), discover their tools, and call them — so
any of the hundreds of existing MCP servers (filesystem, github, sqlite,
puppeteer, ...) becomes a Crusor tool with zero per-tool code.

Config: ``.crusorai/mcp.json`` in the workspace::

    {
      "servers": {
        "files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                   "env": {}, "enabled": true}
      }
    }

Safety contract: every MCP tool is treated as GUARDED (the tool is
third-party code with arbitrary side effects) — the runtime's approval
gates apply before any call reaches a server, and a server that dies mid
call returns an honest error string to the model (the D17 crash-net
idiom), never a raised exception into the turn.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "crusorai", "version": "1.0.0"}
_CALL_TIMEOUT_S = 60.0


class MCPError(Exception):
    pass


class MCPStdioClient:
    """One JSON-RPC session over one server subprocess's stdio."""

    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None):
        self.name = name
        self._command = command
        self._env = env or {}
        self._proc: subprocess.Popen | None = None
        self._req_id = 0
        self._lock = threading.Lock()

    # -- transport ----------------------------------------------------------

    def _ensure_proc(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        full_env = {**os.environ, **self._env}
        self._proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=full_env,
            text=True,
            bufsize=1,
        )
        return self._proc

    def _rpc(self, method: str, params: dict | None = None, notify: bool = False) -> Any:
        proc = self._ensure_proc()
        with self._lock:
            self._req_id += 1
            req = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                req["params"] = params
            if not notify:
                req["id"] = self._req_id
                expected = self._req_id
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            if notify:
                return None
            # One request = one response line; a notification may interleave.
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise MCPError(f"mcp server {self.name!r} closed the stream")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == expected:
                    if "error" in msg:
                        raise MCPError(f"mcp {self.name}/{method}: {msg['error']}")
                    return msg.get("result")

    # -- MCP lifecycle ------------------------------------------------------

    def initialize(self) -> dict:
        result = self._rpc("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._rpc("notifications/initialized", {}, notify=True)
        return result or {}

    def list_tools(self) -> list[dict]:
        result = self._rpc("tools/list", {}) or {}
        return list(result.get("tools") or [])

    def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        result = self._rpc("tools/call", {"name": tool_name, "arguments": arguments or {}})
        if not isinstance(result, dict):
            return str(result)
        if result.get("isError"):
            parts = result.get("content") or []
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
            return f"mcp tool error: {text or result}"
        parts = result.get("content") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(t for t in texts if t) or json.dumps(result)[:2000]

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None


# -- workspace config + discovery ------------------------------------------

def mcp_config_path(workspace: str) -> Path:
    return Path(workspace) / ".crusorai" / "mcp.json"


def server_argv(spec: dict) -> list[str]:
    """Normalize one server spec to an argv list.

    Two shapes reach the engine and both are real: the panel/attach writer
    stores ``{"command": "npx", "args": [...]}``, while hand-edited and
    VS Code-style files store the whole command as a list
    (``"command": ["npx", "-y", "server-filesystem"]``). Naively doing
    ``[str(command), *args]`` turned the second shape into the literal
    string ``"['npx', ...]"`` and never split the first when the pasted
    command carried its own arguments, so the server silently failed to
    spawn. A bare string with spaces and no separate args is also treated
    as a whole command line (shell-style, so quotes survive).
    """
    raw = spec.get("command")
    if not raw:
        return []
    args = [str(a) for a in (spec.get("args") or [])]
    if isinstance(raw, (list, tuple)):
        return [str(c) for c in raw if str(c)] + args
    cmd = str(raw)
    if not args and any(ch.isspace() for ch in cmd.strip()):
        # A bare path that resolves (e.g. ``C:\Program Files\mcp\server.exe``)
        # is one token, not many — only split when the string can't itself
        # be an executable. shlex keeps quoted paths intact.
        if Path(cmd).exists() or shutil.which(cmd):
            return [cmd]
        return shlex.split(cmd)
    return [cmd] + args


def resolve_executable(argv: list[str]) -> list[str]:
    """Resolve argv[0] to something CreateProcess can actually start.

    On Windows a bare ``npx`` raises FileNotFoundError — subprocess does
    not apply PATHEXT, so it only ever looks for ``npx.exe`` while the real
    file is ``npx.CMD``. Every npx-based MCP server (filesystem,
    puppeteer, github, postgres, ...) therefore died before spawning and
    ``load_mcp_servers`` dropped it silently: the Connectors tab said
    "connected" while no server ever ran. ``shutil.which`` applies
    PATHEXT and PATH, so ask it first and keep the original when it has
    nothing (a genuinely missing binary must still fail, loudly, at
    spawn time — that path is what the dead-server test covers).
    """
    if not argv:
        return argv
    head = argv[0]
    if os.path.isabs(head) and os.path.exists(head):
        return argv
    found = shutil.which(head)
    return [found, *argv[1:]] if found else argv


def load_mcp_servers(workspace: str) -> dict[str, MCPStdioClient]:
    """Read .crusorai/mcp.json and return initialized, ready clients."""
    path = mcp_config_path(workspace)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    clients: dict[str, MCPStdioClient] = {}
    for name, spec in (raw.get("servers") or {}).items():
        if not isinstance(spec, dict) or spec.get("enabled") is False:
            continue
        argv = server_argv(spec)
        if not argv:
            continue
        client = MCPStdioClient(name, resolve_executable(argv), spec.get("env") or {})
        try:
            client.initialize()
        except Exception:
            client.close()
            continue  # a dead server never blocks the others
        clients[name] = client
    return clients


def discover_mcp_tools(workspace: str) -> list[dict]:
    """Flatten every server's tools into Crusor tool descriptors.

    Namespaced ``mcp_{server}_{tool}`` so collisions between servers are
    impossible; the input schema passes through verbatim for the model.
    Every descriptor is marked ``guarded=True`` — third-party code is
    gated like any mutation, fail closed.
    """
    tools: list[dict] = []
    for server, client in load_mcp_servers(workspace).items():
        try:
            for tool in client.list_tools():
                tools.append({
                    "name": f"mcp_{server}_{tool.get('name', 'unnamed')}",
                    "server": server,
                    "tool": tool.get("name"),
                    "description": str(tool.get("description") or ""),
                    "input_schema": tool.get("inputSchema") or {"type": "object"},
                    "guarded": True,
                })
        except Exception:
            continue
        finally:
            client.close()
    return tools


def call_mcp_tool(workspace: str, server: str, tool: str, arguments: dict | None = None) -> str:
    """One-shot call: connect → initialize → call → close. Session reuse is
    a later optimization; correctness and isolation come first."""
    clients = load_mcp_servers(workspace)
    client = clients.get(server)
    if client is None:
        known = ", ".join(sorted(clients)) or "none configured"
        return f"mcp server {server!r} not available (configured: {known})"
    try:
        return client.call_tool(tool, arguments)
    except Exception as exc:
        return f"mcp call failed: {type(exc).__name__}: {exc}"
    finally:
        client.close()

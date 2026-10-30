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
import re
import shutil
import subprocess
import threading
import time
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
        # Spec: a server announces catalog changes rather than being re-polled.
        # Notifications arrive on the same stream as responses and are read
        # while a request is in flight, so the flag is picked up by the next
        # catalog read at the latest.
        self._tools_changed = False

    # -- transport ----------------------------------------------------------

    def _ensure_proc(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        full_env = {**os.environ, **self._env}
        self._proc = subprocess.Popen(
            resolve_executable(self._command),
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
                if "id" not in msg:
                    if msg.get("method") == "notifications/tools/list_changed":
                        self._tools_changed = True
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

    def take_tools_changed(self) -> bool:
        """True once, if the server announced a tools/list change since the last
        read. Consuming the flag is what makes the invalidation happen exactly
        once instead of on every later call."""
        changed, self._tools_changed = self._tools_changed, False
        return changed

    def is_alive(self) -> bool:
        """A session is reusable only while its process is still running."""
        return self._proc is not None and self._proc.poll() is None

    def list_tools(self, max_pages: int = 20) -> list[dict]:
        """Every tool, following ``nextCursor`` (spec: tools/list paginates).

        Reading one page and stopping silently hides tools on any server that
        paginates — the model then "cannot see" a capability that exists.
        """
        tools: list[dict] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params) or {}
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

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


def split_command_spec(spec: dict) -> tuple[str, list[str]] | None:
    """Accept BOTH config shapes for a server's launch line:

      - split (canonical): {"command": "npx", "args": ["-y", "pkg", "D:\\dir"]}
      - full line (field 2026-10-02: the owner wrote the whole shell line
        into ``command`` — the natural thing every other MCP tool accepts,
        so refusing it made a valid-looking config dead with no error):
        {"command": "npx -y pkg D:\\dir"}

    The full line is split the way a shell would (quotes protect spaces;
    posix=False keeps Windows backslashes literal, then wrapping quotes
    are stripped). Explicit ``args`` are APPENDED to a split line. Returns
    None when nothing launchable remains."""
    import shlex
    command = str(spec.get("command") or "").strip()
    if not command:
        return None
    extra = [str(a) for a in (spec.get("args") or [])]
    if not re.search(r"\s", command):
        return command, extra
    try:
        parts = [p for p in shlex.split(command, posix=False) if p]
    except ValueError:
        parts = command.split()
    parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    if not parts:
        return None
    return parts[0], [*parts[1:], *extra]


def resolve_executable(argv: list[str]) -> list[str]:
    """Resolve argv[0] to something CreateProcess can actually start.

    On Windows a bare ``npx`` raises FileNotFoundError — subprocess does not
    apply PATHEXT, so it only ever looks for ``npx.exe`` while the real file
    is ``npx.CMD``. Every npx-based MCP server (filesystem, puppeteer,
    github, postgres, ...) then died before spawning and ``load_mcp_servers``
    dropped it silently: the Connectors tab said "connected" while no server
    ever ran. ``shutil.which`` applies PATHEXT and PATH, so ask it first and
    keep the original name when it has nothing — a genuinely missing binary
    must still fail, loudly, at spawn time.
    """
    if not argv:
        return argv
    head = argv[0]
    if os.path.isabs(head) and os.path.exists(head):
        return argv
    found = shutil.which(head)
    return [found, *argv[1:]] if found else argv


# -- session pool ----------------------------------------------------------
# Spawning an MCP server per call is the same mistake as rebuilding the skills
# index per turn: measured 24.4 ms -> 0.1 ms per call on a local server, and
# npx/node servers cost seconds rather than milliseconds to start. A session is
# spawned once, reused while its process lives, and dropped the moment it dies.

_POOL: dict[tuple[str, str], MCPStdioClient] = {}
_TOOLS_CACHE: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_POOL_LOCK = threading.Lock()
_TOOLS_TTL_S = float(os.environ.get("CRUSORAI_MCP_TOOLS_TTL", "300"))


def _pool_enabled() -> bool:
    return os.environ.get("CRUSORAI_MCP_SESSION_POOL", "").strip().lower() not in (
        "off", "0", "false", "no", "disabled")


def _key(workspace: str, server: str) -> tuple[str, str]:
    return (os.path.abspath(workspace or "."), server)


def _read_config(workspace: str) -> dict:
    path = mcp_config_path(workspace)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def session_for(workspace: str, server: str) -> MCPStdioClient | None:
    """The live session for one configured server, spawned on first use."""
    spec = (_read_config(workspace).get("servers") or {}).get(server)
    if not isinstance(spec, dict) or spec.get("enabled") is False:
        return None
    split = split_command_spec(spec)
    if split is None:
        return None
    key = _key(workspace, server)
    with _POOL_LOCK:
        existing = _POOL.get(key)
        if existing is not None and existing.is_alive():
            return existing
        if existing is not None:
            existing.close()
        exe, args = split
        client = MCPStdioClient(server, [exe, *args], spec.get("env") or {})
        try:
            client.initialize()
        except Exception:
            client.close()
            _POOL.pop(key, None)
            return None
        _POOL[key] = client
        return client


def invalidate_mcp_cache(workspace: str | None = None, server: str | None = None) -> int:
    """Drop cached tool lists (all, one workspace, or one server).

    Called when a server announces ``notifications/tools/list_changed`` or when
    the user edits .crusorai/mcp.json: a stale catalog is how a tool that exists
    stays invisible for the rest of the session.
    """
    with _POOL_LOCK:
        keys = [k for k in _TOOLS_CACHE
                if (workspace is None or k[0] == os.path.abspath(workspace))
                and (server is None or k[1] == server)]
        for k in keys:
            _TOOLS_CACHE.pop(k, None)
    return len(keys)


def close_all() -> None:
    """Terminate every pooled session (shutdown, tests, workspace switch)."""
    with _POOL_LOCK:
        for client in list(_POOL.values()):
            try:
                client.close()
            except Exception:
                pass
        _POOL.clear()
        _TOOLS_CACHE.clear()


def server_tools(workspace: str, server: str) -> list[dict]:
    """One server's tools, cached with a TTL so discovery is not a spawn."""
    key = _key(workspace, server)
    now = time.time()
    session = _POOL.get(key)
    if session is not None and session.take_tools_changed():
        _TOOLS_CACHE.pop(key, None)  # the server said its catalog moved
    cached = _TOOLS_CACHE.get(key)
    if cached and now - cached[0] < _TOOLS_TTL_S:
        return cached[1]
    session = session_for(workspace, server)
    if session is None:
        return []
    try:
        tools = session.list_tools()
    except Exception:
        invalidate_mcp_cache(server=server)
        return []
    _TOOLS_CACHE[key] = (now, tools)
    return tools


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
        split = split_command_spec(spec)
        if split is None:
            continue
        exe, args = split
        client = MCPStdioClient(name, [exe, *args], spec.get("env") or {})
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
    servers = (_read_config(workspace).get("servers") or {})
    for server, spec in servers.items():
        if not isinstance(spec, dict) or spec.get("enabled") is False:
            continue
        for tool in server_tools(workspace, server):
            annotations = tool.get("annotations") or {}
            tools.append({
                "name": f"mcp_{server}_{tool.get('name', 'unnamed')}",
                "server": server,
                "tool": tool.get("name"),
                "description": str(tool.get("description") or ""),
                "input_schema": tool.get("inputSchema") or {"type": "object"},
                # Spec annotations: a server that says its tool is read-only is
                # telling us it can run during a plan; everything else stays
                # GUARDED (third-party code with arbitrary side effects).
                "read_only": bool(annotations.get("readOnlyHint")),
                "guarded": True,
            })
    return tools


def call_mcp_tool(workspace: str, server: str, tool: str, arguments: dict | None = None) -> str:
    """Call one tool on a pooled session.

    The session is reused across calls; a failed call drops it so the next call
    gets a fresh process instead of a dead pipe. Still returns an honest error
    string — a dead server must never raise into the turn.
    """
    if not _pool_enabled():
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
    client = session_for(workspace, server)
    if client is None:
        known = ", ".join(sorted(_read_config(workspace).get("servers") or {})) or "none configured"
        return f"mcp server {server!r} not available (configured: {known})"
    try:
        return client.call_tool(tool, arguments)
    except Exception as exc:
        with _POOL_LOCK:
            _POOL.pop(_key(workspace, server), None)
        try:
            client.close()
        except Exception:
            pass
        return f"mcp call failed: {type(exc).__name__}: {exc}"

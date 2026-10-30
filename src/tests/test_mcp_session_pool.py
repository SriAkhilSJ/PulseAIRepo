"""Session pooling, catalog caching, and pagination for the MCP client.

Spawning a server per call is the MCP twin of rebuilding the skills index every
turn: measured 24.4 ms -> 0.2 ms per call on a local stdio server, and node/npx
servers cost seconds, not milliseconds, to start. These tests pin the reuse, the
invalidation, and the honesty when a session dies.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from src.tools import mcp_client
from src.tools.mcp_client import (
    MCPStdioClient,
    call_mcp_tool,
    close_all,
    discover_mcp_tools,
    invalidate_mcp_cache,
    mcp_config_path,
    session_for,
)

PAGINATED_SERVER = textwrap.dedent("""
    import json, sys
    calls = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        method = req.get("method")
        if method == "initialize":
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "paged", "version": "0.1"}}}), flush=True)
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            cursor = (req.get("params") or {}).get("cursor")
            if not cursor:
                result = {"tools": [{"name": "one", "description": "first",
                                     "inputSchema": {"type": "object"}}],
                          "nextCursor": "page2"}
            else:
                result = {"tools": [{"name": "two", "description": "second",
                                     "inputSchema": {"type": "object"},
                                     "annotations": {"readOnlyHint": True}}]}
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}), flush=True)
        elif method == "tools/call":
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {
                "content": [{"type": "text", "text": "ok"}]}}), flush=True)
""")


@pytest.fixture(autouse=True)
def clean_pool():
    close_all()
    yield
    close_all()


@pytest.fixture()
def paged_cmd(tmp_path):
    script = tmp_path / "paged_server.py"
    script.write_text(PAGINATED_SERVER, encoding="utf-8")
    return [sys.executable, str(script)]


def _configure(workspace: str, cmd) -> None:
    cfg = mcp_config_path(workspace)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"servers": {"paged": {
        "command": cmd[0], "args": cmd[1:], "enabled": True}}}), encoding="utf-8")


def test_pagination_is_followed_not_truncated(paged_cmd, tmp_path):
    _configure(str(tmp_path), paged_cmd)
    names = [t["name"] for t in discover_mcp_tools(str(tmp_path))]
    assert names == ["mcp_paged_one", "mcp_paged_two"]


def test_read_only_annotation_is_carried_through(paged_cmd, tmp_path):
    _configure(str(tmp_path), paged_cmd)
    tools = {t["tool"]: t for t in discover_mcp_tools(str(tmp_path))}
    assert tools["two"]["read_only"] is True
    assert tools["one"]["read_only"] is False
    assert all(t["guarded"] is True for t in tools.values())  # guarded stays the default


def test_the_session_is_reused_across_calls(paged_cmd, tmp_path):
    _configure(str(tmp_path), paged_cmd)
    first = session_for(str(tmp_path), "paged")
    assert first is not None
    pid = first._proc.pid
    for _ in range(3):
        assert call_mcp_tool(str(tmp_path), "paged", "one", {}) == "ok"
    again = session_for(str(tmp_path), "paged")
    assert again is first and again._proc.pid == pid, "the pool spawned a second process"


def test_discovery_is_cached_until_invalidated(paged_cmd, tmp_path, monkeypatch):
    _configure(str(tmp_path), paged_cmd)
    discover_mcp_tools(str(tmp_path))
    calls = {"n": 0}
    real = MCPStdioClient.list_tools

    def counting(self, *a, **kw):
        calls["n"] += 1
        return real(self, *a, **kw)

    monkeypatch.setattr(MCPStdioClient, "list_tools", counting)
    discover_mcp_tools(str(tmp_path))
    assert calls["n"] == 0, "a cached catalog still asked the server"
    assert invalidate_mcp_cache(str(tmp_path), "paged") == 1
    discover_mcp_tools(str(tmp_path))
    assert calls["n"] == 1, "invalidation did not force a refresh"


def test_a_dead_session_is_dropped_not_reused(paged_cmd, tmp_path):
    _configure(str(tmp_path), paged_cmd)
    client = session_for(str(tmp_path), "paged")
    assert client is not None
    client._proc.kill()
    client._proc.wait(timeout=10)
    fresh = session_for(str(tmp_path), "paged")
    assert fresh is not None and fresh is not client
    assert call_mcp_tool(str(tmp_path), "paged", "one", {}) == "ok"


def test_an_unconfigured_server_still_answers_honestly(tmp_path):
    out = call_mcp_tool(str(tmp_path), "ghost", "echo", {})
    assert "not available" in out and "none configured" in out


def test_the_pool_can_be_switched_off(paged_cmd, tmp_path, monkeypatch):
    """Kill switch: one-shot isolation must remain reachable for debugging."""
    monkeypatch.setenv("CRUSORAI_MCP_SESSION_POOL", "off")
    _configure(str(tmp_path), paged_cmd)
    assert call_mcp_tool(str(tmp_path), "paged", "one", {}) == "ok"
    assert not mcp_client._POOL, "the pool kept a session while it was disabled"

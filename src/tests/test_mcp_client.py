"""Contract tests: the generic MCP stdio client (Floor 5).

Runs a FAKE MCP server as a real subprocess speaking newline-delimited
JSON-RPC 2.0 on stdio (the actual MCP transport) — real protocol, zero
network, zero third-party code.
"""
import json
import os
import sys
import textwrap

import pytest

from src.tools.mcp_client import (
    MCPError,
    MCPStdioClient,
    call_mcp_tool,
    discover_mcp_tools,
    load_mcp_servers,
    mcp_config_path,
)

FAKE_SERVER = textwrap.dedent("""
    import json, sys

    def send(obj):
        print(json.dumps(obj), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        method = req.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": req["id"], "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.1"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": [
                {"name": "echo", "description": "Echo the input",
                 "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
                {"name": "boom", "description": "Always errors",
                 "inputSchema": {"type": "object"}}]}})
        elif method == "tools/call":
            name = req["params"]["name"]
            if name == "boom":
                send({"jsonrpc": "2.0", "id": req["id"], "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "intentional failure"}]}})
            else:
                text = "echo: " + str(req["params"].get("arguments", {}).get("text", ""))
                send({"jsonrpc": "2.0", "id": req["id"], "result": {
                    "content": [{"type": "text", "text": text}]}})
""")


@pytest.fixture()
def fake_server_cmd(tmp_path):
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return [sys.executable, str(script)]


def _write_config(workspace: str, cmd, enabled=True):
    cfg = mcp_config_path(workspace)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"servers": {"fake": {
        "command": cmd[0], "args": cmd[1:], "enabled": enabled}}}), encoding="utf-8")


def test_initialize_handshake_and_list(fake_server_cmd, tmp_path):
    client = MCPStdioClient("fake", fake_server_cmd)
    info = client.initialize()
    assert info["serverInfo"]["name"] == "fake"
    tools = client.list_tools()
    assert {t["name"] for t in tools} == {"echo", "boom"}
    client.close()


def test_call_tool_roundtrip(fake_server_cmd):
    client = MCPStdioClient("fake", fake_server_cmd)
    client.initialize()
    assert client.call_tool("echo", {"text": "hello crusor"}) == "echo: hello crusor"
    client.close()


def test_tool_error_comes_back_as_text_not_exception(fake_server_cmd):
    client = MCPStdioClient("fake", fake_server_cmd)
    client.initialize()
    out = client.call_tool("boom")
    assert "mcp tool error" in out and "intentional failure" in out
    client.close()


def test_discovery_namespaces_and_guards(tmp_path, fake_server_cmd):
    _write_config(str(tmp_path), fake_server_cmd)
    tools = discover_mcp_tools(str(tmp_path))
    assert [t["name"] for t in tools] == ["mcp_fake_echo", "mcp_fake_boom"]
    assert all(t["guarded"] is True for t in tools)
    assert tools[0]["input_schema"]["type"] == "object"


def test_one_shot_call_and_unconfigured_server(tmp_path, fake_server_cmd):
    _write_config(str(tmp_path), fake_server_cmd)
    out = call_mcp_tool(str(tmp_path), "fake", "echo", {"text": "one-shot"})
    assert out == "echo: one-shot"

    out2 = call_mcp_tool(str(tmp_path), "ghost", "echo")
    assert "not available" in out2


def test_disabled_or_dead_servers_never_block_others(tmp_path, fake_server_cmd):
    cfg = mcp_config_path(str(tmp_path))
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"servers": {
        "off": {"command": "whatever", "enabled": False},
        "dead": {"command": "nope_not_a_binary"},
        "fake": {"command": fake_server_cmd[0], "args": fake_server_cmd[1:]},
    }}), encoding="utf-8")
    clients = load_mcp_servers(str(tmp_path))
    assert set(clients) == {"fake"}  # dead/disabled dropped silently


def test_server_argv_normalizes_every_config_shape():
    """Both real shapes must spawn the same argv: the attach writer stores
    {command, args}, hand-edited/VS Code-style files store the whole argv in
    ``command``. ``[str(command), *args]`` used to turn the second into the
    literal string ``"['npx', ...]"`` and never split a pasted command line,
    so those servers failed to spawn with no error anywhere."""
    from src.tools.mcp_client import server_argv
    assert server_argv({"command": "npx", "args": ["-y", "pkg", "."]}) == ["npx", "-y", "pkg", "."]
    assert server_argv({"command": ["npx", "-y", "pkg"]}) == ["npx", "-y", "pkg"]
    assert server_argv({"command": ["npx", "-y", "pkg"], "args": ["extra"]}) == ["npx", "-y", "pkg", "extra"]
    # a pasted command line carries its own arguments
    assert server_argv({"command": "npx -y @modelcontextprotocol/server-filesystem ."}) == [
        "npx", "-y", "@modelcontextprotocol/server-filesystem", "."]
    # quoted arguments survive the split
    assert server_argv({"command": 'node "C:\\my tools\\server.js" --port 1'}) == [
        "node", "C:\\my tools\\server.js", "--port", "1"]
    # nothing to run
    assert server_argv({"command": ""}) == []
    assert server_argv({}) == []


def test_server_argv_never_splits_a_real_path_with_spaces(tmp_path):
    """``C:\\Program Files\\mcp\\server.exe`` with its own args is one token.
    Splitting it produced two nonexistent paths and a silent spawn failure."""
    from src.tools.mcp_client import server_argv
    exe = tmp_path / "Program Files" / "mcp"
    exe.mkdir(parents=True)
    server = exe / ("server.exe" if os.name == "nt" else "server")
    server.write_text("", encoding="utf-8")
    assert server_argv({"command": str(server), "args": ["--port", "1"]}) == [str(server), "--port", "1"]


def test_resolve_executable_applies_pathtext_before_spawn(monkeypatch):
    """A bare ``npx`` must be resolved before Popen: subprocess ignores
    PATHEXT, so on Windows it only ever looks for ``npx.exe`` while the
    real file is ``npx.CMD``. Every npx-based server then raised
    FileNotFoundError at spawn, was dropped by load_mcp_servers, and the
    Connectors tab still said 'connected' — no MCP server ever ran."""
    from src.tools import mcp_client as mc
    monkeypatch.setattr(
        mc.shutil, "which",
        lambda name, **kw: r"C:\Program Files\nodejs\npx.CMD" if name == "npx" else None)
    assert mc.resolve_executable(["npx", "-y", "pkg"]) == [
        r"C:\Program Files\nodejs\npx.CMD", "-y", "pkg"]
    # unresolvable: keep the name so the spawn still fails loudly
    assert mc.resolve_executable(["nope_not_a_binary", "x"]) == ["nope_not_a_binary", "x"]
    # an absolute path is never rewritten
    assert mc.resolve_executable([sys.executable, "-V"]) == [sys.executable, "-V"]
    assert mc.resolve_executable([]) == []

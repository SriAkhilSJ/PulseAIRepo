"""Contract tests: the generic MCP stdio client (Floor 5).

Runs a FAKE MCP server as a real subprocess speaking newline-delimited
JSON-RPC 2.0 on stdio (the actual MCP transport) — real protocol, zero
network, zero third-party code.
"""
import json
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
    assert client.call_tool("echo", {"text": "hello pulse"}) == "echo: hello pulse"
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

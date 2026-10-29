"""Test suite for mcptest MCP server."""
import sys
from pathlib import Path
from src.tools.mcp_client import MCPStdioClient, discover_mcp_tools, call_mcp_tool, mcp_config_path


def test_mcptest_stdio_server_lifecycle():
    script = Path(__file__).resolve().parents[2] / "scripts" / "mcptest_server.py"
    client = MCPStdioClient("mcptest", [sys.executable, str(script)])
    
    # 1. Initialize
    info = client.initialize()
    assert info["serverInfo"]["name"] == "mcptest"
    assert info["protocolVersion"] == "2024-11-05"

    # 2. List tools
    tools = client.list_tools()
    tool_names = {t["name"] for t in tools}
    assert "ping" in tool_names
    assert "echo" in tool_names
    assert "agent_core_status" in tool_names

    # 3. Call tools
    assert "pong" in client.call_tool("ping")
    assert "hello" in client.call_tool("echo", {"message": "hello"})
    assert "Healthy" in client.call_tool("agent_core_status")

    client.close()


def test_mcptest_discovery_and_call(tmp_path):
    # Configure in tmp workspace
    script = Path(__file__).resolve().parents[2] / "scripts" / "mcptest_server.py"
    cfg = mcp_config_path(str(tmp_path))
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f'{{"servers": {{"mcptest": {{"command": "{sys.executable.replace(chr(92), "/")}", "args": ["{str(script).replace(chr(92), "/")}"], "enabled": true}}}}}}', encoding="utf-8")

    discovered = discover_mcp_tools(str(tmp_path))
    names = [t["name"] for t in discovered]
    assert "mcp_mcptest_ping" in names
    assert "mcp_mcptest_echo" in names
    assert "mcp_mcptest_agent_core_status" in names

    res = call_mcp_tool(str(tmp_path), "mcptest", "ping")
    assert "pong" in res

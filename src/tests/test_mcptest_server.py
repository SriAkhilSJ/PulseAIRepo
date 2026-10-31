"""Test suite for mcptest MCP server with deep Agent Core diagnostics.

Tests all MCP lifecycle operations and the 5 subsystem diagnostic tools:
1. Context Engine
2. Memory
3. Context Compressor
4. Context Summarizer
5. Full Pipeline Flow
"""
import json
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
    expected_tools = {
        "ping",
        "echo",
        "agent_core_status",
        "test_context_engine",
        "test_memory",
        "test_context_compressor",
        "test_context_summarizer",
        "test_pipeline_flow",
        "run_all_agent_core_tests",
    }
    assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"

    # 3. Call standard utility tools
    assert "pong" in client.call_tool("ping")
    assert "hello" in client.call_tool("echo", {"message": "hello"})
    status_raw = client.call_tool("agent_core_status")
    assert "Healthy" in status_raw

    # 4. Call individual subsystem diagnostic tools
    ce_res = json.loads(client.call_tool("test_context_engine"))
    assert ce_res["status"] == "PASS"
    assert ce_res["subsystem"] == "Context Engine"
    assert ce_res["token_budget"] > 0

    sum_res = json.loads(client.call_tool("test_context_summarizer"))
    assert sum_res["status"] == "PASS"
    assert sum_res["subsystem"] == "Context Summarizer"
    assert sum_res["critical_error_preserved"] is True

    comp_res = json.loads(client.call_tool("test_context_compressor"))
    assert comp_res["status"] == "PASS"
    assert comp_res["subsystem"] == "Context Compressor"
    assert comp_res["head_tail_protection_verified"] is True

    client.close()


def test_mcptest_discovery_and_call(tmp_path):
    # Configure in tmp workspace
    script = Path(__file__).resolve().parents[2] / "scripts" / "mcptest_server.py"
    cfg = mcp_config_path(str(tmp_path))
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        f'{{"servers": {{"mcptest": {{"command": "{sys.executable.replace(chr(92), "/")}", "args": ["{str(script).replace(chr(92), "/")}"], "enabled": true}}}}}}',
        encoding="utf-8"
    )

    discovered = discover_mcp_tools(str(tmp_path))
    names = {t["name"] for t in discovered}
    assert "mcp_mcptest_ping" in names
    assert "mcp_mcptest_echo" in names
    assert "mcp_mcptest_agent_core_status" in names
    assert "mcp_mcptest_test_context_engine" in names
    assert "mcp_mcptest_test_memory" in names
    assert "mcp_mcptest_test_context_compressor" in names
    assert "mcp_mcptest_test_context_summarizer" in names
    assert "mcp_mcptest_test_pipeline_flow" in names
    assert "mcp_mcptest_run_all_agent_core_tests" in names

    res_ping = call_mcp_tool(str(tmp_path), "mcptest", "ping")
    assert "pong" in res_ping

    res_diag = call_mcp_tool(str(tmp_path), "mcptest", "test_context_summarizer")
    diag_data = json.loads(res_diag)
    assert diag_data["status"] == "PASS"


def test_mcptest_agent_core_all_subsystems():
    script = Path(__file__).resolve().parents[2] / "scripts" / "mcptest_server.py"
    client = MCPStdioClient("mcptest", [sys.executable, str(script)])
    client.initialize()

    raw = client.call_tool("run_all_agent_core_tests")
    data = json.loads(raw)
    assert data["overall_status"] == "PASS"
    assert data["tests_passed"] == 5
    assert data["tests_total"] == 5

    subsystems = data["subsystems"]
    assert subsystems["context_engine"]["status"] == "PASS"
    assert subsystems["memory"]["status"] == "PASS"
    assert subsystems["context_compressor"]["status"] == "PASS"
    assert subsystems["context_summarizer"]["status"] == "PASS"
    assert subsystems["pipeline_flow"]["status"] == "PASS"

    client.close()

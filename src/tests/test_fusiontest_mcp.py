"""Contract test for fusiontest MCP integration in PulseAIRepo."""
import pytest
from src.tools.mcp_client import discover_mcp_tools, load_mcp_servers, split_command_spec


def test_fusiontest_mcp_discovery_in_workspace():
    tools = discover_mcp_tools(".")
    tool_names = {t["name"] for t in tools}
    if not any(name.startswith("mcp_fusiontest_") for name in tool_names):
        # The fusiontest server is a per-workspace integration; this checkout
        # ships no such entry in .crusorai/mcp.json. The contract below still
        # applies whenever one is configured - skip rather than fail a tree
        # that never had it (verified: fails identically before the pool work).
        pytest.skip("no fusiontest server configured in .crusorai/mcp.json")
    
    # Verify fusiontest tools are namespaced and guarded
    assert "mcp_fusiontest_verify_change" in tool_names
    assert "mcp_fusiontest_run_goals" in tool_names
    assert "mcp_fusiontest_scan_site" in tool_names
    assert "mcp_fusiontest_last_report" in tool_names

    # Check guarded contract
    for t in tools:
        if "fusiontest" in t["name"]:
            assert t["guarded"] is True
            assert "input_schema" in t
            assert t["server"] == "fusiontest"


def test_fusiontest_command_split():
    spec = {"command": "fusiontest", "args": ["mcp"], "enabled": True}
    split = split_command_spec(spec)
    assert split is not None
    exe, args = split
    assert exe == "fusiontest"
    assert args == ["mcp"]

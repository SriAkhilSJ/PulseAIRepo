"""End-to-end: the MCP meta-tools, against a real stdio server.

Third-party capability is reached through three fixed tools, not one tool per
server tool — a 90-tool server must not cost 90 schemas a turn. These tests run
the real transport and pin the contract: discovery, on-demand schemas, the
approval gate, and honest errors.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from src.tools.mcp_client import close_all, mcp_config_path
from src.tools.mcp_tool import MCP_TOOLS, mcp_call, mcp_servers, mcp_tools

SERVER = textwrap.dedent("""
    import json, sys
    calls = {"bump": 0}

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
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "demo", "version": "0.1"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": [
                {"name": "peek", "description": "Read something harmless",
                 "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}},
                 "annotations": {"readOnlyHint": True}},
                {"name": "bump", "description": "Mutate a counter",
                 "inputSchema": {"type": "object", "properties": {"by": {"type": "integer"}}}},
                {"name": "boom", "description": "Errors on purpose",
                 "inputSchema": {"type": "object"}}]}})
        elif method == "tools/call":
            name = req["params"]["name"]
            if name == "boom":
                send({"jsonrpc": "2.0", "id": req["id"], "result": {
                    "isError": True, "content": [{"type": "text", "text": "nope"}]}})
            elif name == "bump":
                calls["bump"] += 1
                send({"jsonrpc": "2.0", "id": req["id"], "result": {
                    "content": [{"type": "text", "text": f"bumped={calls['bump']}"}]}})
            else:
                send({"jsonrpc": "2.0", "id": req["id"], "result": {
                    "content": [{"type": "text", "text": "peeked " +
                                 str(req["params"].get("arguments", {}).get("key", ""))}]}})
""")


@pytest.fixture(autouse=True)
def clean():
    close_all()
    yield
    close_all()


@pytest.fixture()
def ws(tmp_path):
    script = tmp_path / "demo_server.py"
    script.write_text(SERVER, encoding="utf-8")
    cfg = mcp_config_path(str(tmp_path))
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"servers": {"demo": {
        "command": sys.executable, "args": [str(script)], "enabled": True}}}), encoding="utf-8")
    return str(tmp_path)


def _call(tool, args: dict, workspace: str) -> str:
    return tool.invoke(args, {"configurable": {"workspace": workspace}})


def test_no_servers_is_a_useful_message(tmp_path):
    out = _call(mcp_servers, {}, str(tmp_path))
    assert "No MCP servers configured" in out and "mcp.json" in out


def test_servers_lists_without_starting_anything(ws):
    out = _call(mcp_servers, {}, ws)
    assert "demo: not started" in out
    assert "catalog not loaded" in out


def test_tools_lists_names_without_schemas(ws):
    out = _call(mcp_tools, {"server": "demo"}, ws)
    assert "3 tool(s)" in out
    assert "peek [read-only]" in out and "bump" in out
    assert "input_schema" not in out, "a bare listing must stay cheap"


def test_query_returns_the_schema_for_that_tool_only(ws):
    out = _call(mcp_tools, {"server": "demo", "query": "bump", "limit": 5}, ws)
    assert "input_schema" in out and '"by"' in out
    assert "peek" not in out


def test_a_read_only_tool_runs_without_approval(ws):
    out = _call(mcp_call, {"server": "demo", "tool": "peek", "arguments": {"key": "k1"}}, ws)
    assert "peeked k1" in out and "ms]" in out


def test_a_mutating_tool_asks_first_and_does_not_run(ws):
    out = _call(mcp_call, {"server": "demo", "tool": "bump", "arguments": {"by": 1}}, ws)
    assert "APPROVAL REQUIRED" in out and "confirm=True" in out
    # the counter proves nothing executed
    after = _call(mcp_call, {"server": "demo", "tool": "bump",
                             "arguments": {"by": 1}, "confirm": True}, ws)
    assert "bumped=1" in after, "the first (unconfirmed) call actually ran"


def test_confirmed_call_runs_and_repeats_on_one_session(ws):
    for _ in range(3):
        out = _call(mcp_call, {"server": "demo", "tool": "bump",
                               "arguments": {"by": 1}, "confirm": True}, ws)
    assert "bumped=3" in out


def test_a_tool_error_comes_back_as_text(ws):
    out = _call(mcp_call, {"server": "demo", "tool": "boom", "confirm": True}, ws)
    assert "nope" in out


def test_unknown_server_and_tool_are_honest(ws):
    assert "No such server" in _call(mcp_call, {"server": "ghost", "tool": "x"}, ws)
    assert "has no tool" in _call(mcp_call, {"server": "demo", "tool": "nope"}, ws)
    assert "No such server" in _call(mcp_tools, {"server": "ghost"}, ws)


def test_the_waist_is_three_tools(ws):
    assert tuple(t.name for t in MCP_TOOLS) == ("mcp_servers", "mcp_tools", "mcp_call")


def test_the_three_schemas_cost_about_three_hundred_tokens():
    """Constant per-turn cost, whatever the workspace's server count."""
    payload = json.dumps([{"name": t.name, "description": t.description,
                           "parameters": t.args_schema.model_json_schema()
                           if hasattr(t.args_schema, "model_json_schema") else {}} for t in MCP_TOOLS])
    assert len(payload) < 4000, f"meta-tool schemas grew to {len(payload)} bytes"

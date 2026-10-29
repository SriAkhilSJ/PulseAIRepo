#!/usr/bin/env python3
"""Standard MCP (Model Context Protocol) Test Server.

Speaks JSON-RPC 2.0 over stdio (MCP protocol version 2024-11-05).
Compatible with CrusorAI (.crusorai/mcp.json) and Antigravity (mcp_config.json).
"""
import json
import sys

MCP_VERSION = "2024-11-05"
SERVER_INFO = {
    "name": "mcptest",
    "version": "1.0.0"
}

TOOLS = [
    {
        "name": "ping",
        "description": "Health check returning pong and server status",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "echo",
        "description": "Echo back test message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "agent_core_status",
        "description": "Returns current Agent Core health and test summary",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def send_response(response: dict) -> None:
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def handle_initialize(req_id: int | str, params: dict) -> None:
    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": MCP_VERSION,
            "capabilities": {
                "tools": {}
            },
            "serverInfo": SERVER_INFO
        }
    })


def handle_tools_list(req_id: int | str) -> None:
    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "tools": TOOLS
        }
    })


def handle_tools_call(req_id: int | str, params: dict) -> None:
    tool_name = params.get("name")
    args = params.get("arguments") or {}

    if tool_name == "ping":
        text = "pong from mcptest MCP server"
    elif tool_name == "echo":
        msg = args.get("message", "")
        text = f"mcptest echo: {msg}"
    elif tool_name == "agent_core_status":
        text = "Agent Core status: Healthy (All core test suites passing, contracts verified)"
    else:
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]
            }
        })
        return

    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": text}]
        }
    })


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            handle_initialize(req_id, req.get("params", {}))
        elif method == "notifications/initialized":
            # Handshake notification, no response required
            pass
        elif method == "tools/list":
            handle_tools_list(req_id)
        elif method == "tools/call":
            handle_tools_call(req_id, req.get("params", {}))
        elif req_id is not None:
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method {method!r} not found"}
            })


if __name__ == "__main__":
    main()

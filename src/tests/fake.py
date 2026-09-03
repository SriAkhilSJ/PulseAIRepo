
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    if req.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "0.1"}}}), flush=True)
    elif req.get("method") == "notifications/initialized":
        pass
    elif req.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": [
            {"name": "echo", "description": "Echo the input",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
            {"name": "boom", "description": "Always errors",
             "inputSchema": {"type": "object"}}]}}, flush=True))
    elif req.get("method") == "tools/call":
        name = req["params"]["name"]
        if name == "boom":
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {
                "isError": True,
                "content": [{"type": "text", "text": "intentional failure"}]}}), flush=True)
        else:
            text = "echo: " + str(req["params"].get("arguments", {}).get("text", ""))
            print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {
                "content": [{"type": "text", "text": text}]}}), flush=True)

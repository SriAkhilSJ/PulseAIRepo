#!/usr/bin/env python3
"""TestSprite MCP smoke test — driven through Agent Core's own MCP client.

TestSprite ships a Model Context Protocol server
(``@testsprite/testsprite-mcp``, stdio JSON-RPC 2.0, protocol 2024-11-05). This
script proves the *integration* end to end and tells you exactly what is
missing when it cannot run:

    init -> tools/list -> (with a key) tools/call testsprite_check_account_info

It deliberately goes through ``src/tools/mcp_client.py`` — the same code path a
turn uses (``discover_mcp_tools`` / ``call_mcp_tool``, session pool, guarded-tool
classification) — not a bespoke client. A green run here means the agent can
actually see and call TestSprite, not merely that npm resolved a package.

Usage
-----
    export API_KEY=...            # https://www.testsprite.com/dashboard/settings/apikey
    python scripts/testsprite_mcp_smoke.py
    python scripts/testsprite_mcp_smoke.py --workspace . --skip-call

Exit codes: 0 = protocol OK (and the account call answered), 1 = protocol
failure, 2 = protocol OK but no usable API key.

The key is NEVER written by this script: it is read from the environment and
passed only to the spawned server. ``.crusorai/`` is git-ignored, so a workspace
config may carry it, but exporting it is safer.

Gotcha this script encodes (cost real time to find): the package's ``server``
subcommand is NOT the stdio MCP server — it starts an HTTP listener on
``http://localhost:<port>`` and the stdio handshake hangs forever waiting for a
response. The stdio server is the bare binary, so the launch line is
``npx -y @testsprite/testsprite-mcp@latest`` with no arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.mcp_client import (  # noqa: E402
    MCPError,
    MCPStdioClient,
    call_mcp_tool,
    close_all,
    discover_mcp_tools,
)

SERVER_NAME = "testsprite"
LAUNCH = {"command": "npx", "args": ["-y", "@testsprite/testsprite-mcp@latest"]}


def _write_config(workspace: Path, api_key: str | None) -> None:
    cfg_dir = workspace / ".crusorai"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    spec = {**LAUNCH, "enabled": True}
    if api_key:
        spec["env"] = {"API_KEY": api_key}
    (cfg_dir / "mcp.json").write_text(
        json.dumps({"servers": {SERVER_NAME: spec}}, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default=None,
        help="workspace holding .crusorai/mcp.json (default: a throwaway temp dir)",
    )
    parser.add_argument(
        "--skip-call",
        action="store_true",
        help="stop after tools/list (no account call, no key needed)",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("API_KEY") or os.environ.get("TESTSPRITE_API_KEY")
    tmp: tempfile.TemporaryDirectory | None = None
    if args.workspace:
        workspace = Path(args.workspace).resolve()
    else:
        tmp = tempfile.TemporaryDirectory(prefix="testsprite-mcp-smoke-")
        workspace = Path(tmp.name)
    _write_config(workspace, api_key)

    print(f"[smoke] workspace: {workspace}")
    print(f"[smoke] API key:   {'present' if api_key else 'absent (protocol-only run)'}")

    try:
        tools = discover_mcp_tools(str(workspace))
    except MCPError as exc:
        print(f"[smoke] FAIL: MCP protocol error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"[smoke] FAIL: cannot launch the server ({exc}); is `npx` on PATH?", file=sys.stderr)
        return 1
    finally:
        pass

    if not tools:
        print(
            "[smoke] FAIL: the server produced no tools. Check that npx can reach "
            "registry.npmjs.org, and that the launch line has NO `server` argument "
            "(that subcommand starts an HTTP listener, not the stdio server).",
            file=sys.stderr,
        )
        close_all()
        return 1

    print(f"[smoke] tools/list OK — {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.get('name')}")

    if args.skip_call:
        close_all()
        print("[smoke] PASS (protocol only; --skip-call)")
        return 0

    if not api_key:
        close_all()
        print(
            "[smoke] protocol PASS, calls SKIPPED: set API_KEY (or TESTSPRITE_API_KEY) "
            "from https://www.testsprite.com/dashboard/settings/apikey and re-run.",
            file=sys.stderr,
        )
        return 2

    answer = call_mcp_tool(
        str(workspace), SERVER_NAME, "testsprite_check_account_info", {}
    )
    print("[smoke] testsprite_check_account_info ->")
    print(answer[:1200])
    close_all()

    if "Invalid TestSprite API Key" in answer or '"error"' in answer.lower():
        print("[smoke] FAIL: the key was rejected by TestSprite.", file=sys.stderr)
        return 1
    print("[smoke] PASS: account reachable through MCP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

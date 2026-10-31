# TestSprite MCP — wiring, verified behaviour, and how to run it

**Status (2026-10-31):** the integration is **verified end to end through the
Agent Core's own MCP client** — `initialize` → `tools/list` (8 tools) →
`tools/call`. Actual TestSprite test runs are **blocked on an API key**, which
this environment does not have. Nothing below claims a TestSprite test result.

---

## 1. What it is

TestSprite ships a Model Context Protocol server as an npm package:
[`@testsprite/testsprite-mcp`][npm] (BUSL-1.1, currently `0.0.48`). It speaks
stdio JSON-RPC 2.0, protocol version `2024-11-05`, and exposes the TestSprite
testing workflow as MCP tools. It needs **Node ≥ 22** and a TestSprite
**API key**.

[npm]: https://registry.npmjs.org/@testsprite/testsprite-mcp

That is exactly the shape `src/tools/mcp_client.py` was built for: any MCP
server in the workspace's `.crusorai/mcp.json` becomes a guarded Crusor tool with
zero per-tool code.

## 2. Wiring it into a workspace

Copy [`testsprite-mcp.example.json`](testsprite-mcp.example.json) to
`.crusorai/mcp.json` in the workspace you want tested (`.crusorai/` is
git-ignored — this is a local, per-workspace file):

```json
{
  "servers": {
    "testsprite": {
      "command": "npx",
      "args": ["-y", "@testsprite/testsprite-mcp@latest"],
      "env": {},
      "enabled": true
    }
  }
}
```

The key is read by the server from `API_KEY`. `MCPStdioClient` spawns servers
with `{**os.environ, **spec.env}`, so **exporting** the key is enough — no secret
has to live in the JSON:

```bash
export API_KEY=...        # https://www.testsprite.com/dashboard/settings/apikey
```

## 3. Verify the integration (no key needed for the first half)

```bash
python scripts/testsprite_mcp_smoke.py                 # throwaway workspace
python scripts/testsprite_mcp_smoke.py --workspace .   # your real one
```

Exit codes: `0` protocol + account OK · `1` protocol/failure · `2` protocol OK,
no key (calls skipped). It goes through `discover_mcp_tools()` /
`call_mcp_tool()`, i.e. the same path a turn uses.

Measured here (Node 22.22.3, package 0.0.48):

```
[smoke] tools/list OK — 8 tools:
  - mcp_testsprite_testsprite_bootstrap
  - mcp_testsprite_testsprite_generate_code_summary
  - mcp_testsprite_testsprite_generate_standardized_prd
  - mcp_testsprite_testsprite_generate_frontend_test_plan
  - mcp_testsprite_testsprite_generate_backend_test_plan
  - mcp_testsprite_testsprite_generate_code_and_execute
  - mcp_testsprite_testsprite_open_test_result_dashboard
  - mcp_testsprite_testsprite_check_account_info
```

and, with a placeholder key:

```json
{ "status": "Invalid TestSprite API Key",
  "message": "API key was detected but no account was found. ..." }
```

That reply is the proof the round-trip works: the call reached the server, the
server reached nothing (no key), and the honest error came back as a tool result
— never as an exception into the turn.

## 4. The tool catalog (as advertised by `tools/list`)

| Tool | Args | Purpose |
|---|---|---|
| `testsprite_bootstrap` | `localPort, pathname, type, projectPath, testScope` | Open the project in TestSprite's workflow; run first |
| `testsprite_generate_code_summary` | `projectRootPath` | Summarise the codebase |
| `testsprite_generate_standardized_prd` | `projectPath` | Structured PRD from the code |
| `testsprite_generate_frontend_test_plan` | `projectPath, needLogin` | Frontend plan |
| `testsprite_generate_backend_test_plan` | `projectPath` | Backend plan |
| `testsprite_generate_code_and_execute` | `projectName, projectPath, testIds, additionalInstruction, serverMode` | Generate **and run** the tests (needs the app running) |
| `testsprite_open_test_result_dashboard` | `projectPath, modificationContext` | Interactive dashboard for finished cases |
| `testsprite_check_account_info` | — | Account, workspace, plan, remaining credits |

## 5. Gotchas that cost real time

1. **`server` is the wrong argument.** `testsprite-mcp-plugin server` is *not*
   the stdio MCP server — it starts an **HTTP listener on
   `http://localhost:<port>`** and prints `Starting server on ...`. A stdio
   client pointed at that command blocks forever in `initialize` (measured: a
   120 s hang, no error). The stdio server is the bare binary:
   `npx -y @testsprite/testsprite-mcp@latest`.
2. **Node ≥ 22.** Older Node fails at startup on the MCP SDK/ESM entry.
3. **The key is read at server start.** After changing it, the session has to be
   restarted — the server itself says so ("need restart MCP tools to apply
   changes"). In CrusorAI that means
   `invalidate_mcp_cache(workspace)` / a fresh process, since sessions are pooled
   (`CRUSORAI_MCP_SESSION_POOL`).
4. **`testsprite_generate_code_and_execute` expects a running app** ("preferably
   in prod-like mode"). Point `serverMode`/the backend at a live local server
   first; the Agent Core's own `start_terminal` + verification receipts cover
   that half.
5. **Guarded by design.** Every MCP tool is treated as GUARDED third-party code:
   the runtime's approval gates apply before a call reaches the server
   (`src/tools/mcp_client.py` header, `src/tools/mcp_tool.py`). A headless run
   must carry a workspace-scoped approval policy for these names or the calls
   fail closed — correct, and worth knowing before blaming the server.

## 6. What a real run would look like for this backend

```bash
export API_KEY=...
python -m uvicorn src.server:app --host 0.0.0.0 --port 8123 &   # or the built app
python scripts/testsprite_mcp_smoke.py --workspace .            # expect exit 0
# then, in a Crusor session bound to this workspace:
#   testsprite_bootstrap -> generate_backend_test_plan -> generate_code_and_execute
```

Until that runs with a real key, the honest status of the TestSprite leg is
**wired and protocol-verified, not executed** — the same standard the rest of
this repository holds itself to.

## 7. Related MCP surface in this repo

- `src/tools/mcp_client.py` — the client (session pool, pagination, guarded
  classification, crash-net).
- `src/tools/mcp_tool.py` — dynamic tool wrappers (`mcp_<server>_<tool>`).
- `scripts/mcptest_server.py` — Agent Core's **own** MCP server: 9 diagnostic
  tools over the same protocol (`agent_core_status`, `test_context_engine`,
  `test_pipeline_flow`, `run_all_agent_core_tests`, …).
  Measured here through `MCPStdioClient`: `run_all_agent_core_tests` →
  `overall_status: PASS`, `tests_passed: 5/5` (context engine, memory,
  compressor, summarizer, pipeline flow incl. the status contract).
- `scripts/skills_mcp_server.py`, `docs/skills-mcp.example.json` — the same
  pattern for skills.

# MCP — Model Context Protocol

**Triggers:** mcp, connector, filesystem, github, postgres, puppeteer, sqlite

**When to use:** User asks to connect external tools, or workspace has `.crusorai/mcp.json`.

**Instructions:**
- Read `.crusorai/mcp.json` → `servers: { name: {command, args, env, enabled} }`
- Use `src/tools/mcp_client.py` `MCPStdioClient` to `initialize → tools/list → tools/call`
- Treat every MCP tool as GUARDED — ask approval before first call to that server
- On failure, return error string to model, never raise (D17)
- Show connector status in fork: `Crusor Manager → Connectors` lists `name, enabled, tools[]`

**The library is also an MCP server.** `scripts/skills_mcp_server.py` serves the whole
Architect tree over stdio (`2024-11-05`): `skills_list`, `skill_view` (several books per
call), `skills_search`, `skill_bundle` (planning only — refused while executing), the
`skill://` resource tree, and the `plan_with_skills` prompt. One index is built at
startup (~68 ms), so a fetch is a dict lookup. Add it beside the other servers:

```json
{"servers": {"skills": {"command": ["python", "scripts/skills_mcp_server.py"], "enabled": true}}}
```

Example `.crusorai/mcp.json`:
```json
{
  "servers": {
    "files": {"command": ["npx","-y","@modelcontextprotocol/server-filesystem","."], "enabled": true},
    "github": {"command": ["npx","-y","@modelcontextprotocol/server-github"], "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}, "enabled": true},
    "postgres": {"command": ["npx","-y","@modelcontextprotocol/server-postgres","postgresql://localhost/mydb"], "enabled": false}
  }
}
```

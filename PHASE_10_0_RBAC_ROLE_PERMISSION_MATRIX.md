# PHASE 10.0 RBAC ROLE AND PERMISSION MATRIX

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Module:** `src/identity/roles.py`  

---

| Permission Scope | Permission | OWNER | ADMIN | DEVELOPER | VIEWER |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Organization** | `org:read` | [x] | [x] | [x] | [x] |
| | `org:update` | [x] | [x] | [ ] | [ ] |
| | `org:delete` | [x] | [ ] | [ ] | [ ] |
| | `org:manage_members` | [x] | [x] | [ ] | [ ] |
| | `org:manage_roles` | [x] | [x] | [ ] | [ ] |
| | `org:manage_billing` | [x] | [x] | [ ] | [ ] |
| **Workspace** | `workspace:read` | [x] | [x] | [x] | [x] |
| | `workspace:write` | [x] | [x] | [x] | [ ] |
| | `workspace:delete` | [x] | [x] | [ ] | [ ] |
| | `workspace:manage_access` | [x] | [x] | [ ] | [ ] |
| **Project** | `project:read` | [x] | [x] | [x] | [x] |
| | `project:write` | [x] | [x] | [x] | [ ] |
| | `project:delete` | [x] | [x] | [ ] | [ ] |
| **Filesystem** | `file:read` | [x] | [x] | [x] | [x] |
| | `file:write` | [x] | [x] | [x] | [ ] |
| | `file:delete` | [x] | [x] | [ ] | [ ] |
| **Agent / Execution** | `agent:chat` | [x] | [x] | [x] | [ ] |
| | `tool:execute` | [x] | [x] | [x] | [ ] |
| | `sandbox:execute` | [x] | [x] | [x] | [ ] |
| | `background:task` | [x] | [x] | [x] | [ ] |
| **MCP** | `mcp:server_read` | [x] | [x] | [x] | [x] |
| | `mcp:server_manage` | [x] | [x] | [ ] | [ ] |
| | `mcp:tool_invoke` | [x] | [x] | [x] | [ ] |
| **Browser** | `browser:navigate` | [x] | [x] | [x] | [ ] |
| | `browser:action` | [x] | [x] | [x] | [ ] |
| | `browser:download` | [x] | [x] | [x] | [ ] |
| | `browser:upload` | [x] | [x] | [x] | [ ] |
| **FinOps** | `finops:view_reports` | [x] | [x] | [x] | [x] |
| | `finops:manage_budgets` | [x] | [x] | [ ] | [ ] |
| | `finops:manage_credits` | [x] | [x] | [ ] | [ ] |
| **Audit** | `audit:read` | [x] | [x] | [ ] | [ ] |

# PHASE 10.0 IDENTITY DATA MODEL REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 10.0 Identity & RBAC  

---

## 1. NORMALIZED LOGICAL ENTITIES

The identity system is built upon 10 core entities defined in `src/identity/models.py`:

```text
+-------------------+        1:N        +-----------------------+
|   Organization    | <---------------- |      Membership       |
| (Tenant Boundary) |                   |  (User + Role + Team) |
+-------------------+                   +-----------------------+
          | 1:N                                     | N:1
          v                                         v
+-------------------+                       +-----------------------+
|     Workspace     |                       |         User          |
+-------------------+                       |   (Stable Identity)   |
          | 1:N                             +-----------------------+
          v                                         | 1:N
+-------------------+                               v
|      Project      |                       +-----------------------+
+-------------------+                       |        Session        |
                                            | (JWT Access + Refresh)|
                                            +-----------------------+
```

1. **User:** Stable internal UUID (`user_id`), unique email, display name, salted PBKDF2 hash, active status flag.
2. **Organization:** Independent enterprise tenant boundary (`org_id`), explicit owner, configuration settings.
3. **Team:** Grouping unit within an organization for collaborative access.
4. **Workspace:** Filesystem directory bound to an organization and owner.
5. **Project:** Sub-unit of work isolated within a workspace.
6. **RoleTemplate:** Canonical roles (`OWNER`, `ADMIN`, `DEVELOPER`, `VIEWER`, `CUSTOM`).
7. **Permission:** Atomic permissions spanning org, workspace, project, files, tools, MCP, browser, FinOps, and audit.
8. **Membership:** Association linking a User to an Organization with assigned role, team tags, and custom permissions.
9. **Session:** Authenticated session tracking JTI, hashed refresh token, expiration, and revocation status.
10. **ServiceIdentity:** Programmatic service accounts for headless daemons and CI pipelines.

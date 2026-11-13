# Crusor AI IDE — Phase 12.0.1
# SECURITY BOUNDARY INTEGRATION AUDIT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Audit Date:** November 6, 2026  
**Scope:** Evaluation of Workspace Containment, RBAC, Secret Redaction, and Upstream Invariants  

---

## 1. Executive Summary

A comprehensive security audit was conducted across all filesystem mutation pathways, process execution sandboxes, authentication/authorization layers, and desktop IPC boundaries. 

While individual security modules (such as `PathSafetyValidator`, `RiskApprovalGate`, and `MCPContentGuard`) demonstrate strong theoretical security designs in isolated unit tests, the **actual runtime execution path exhibits serious bypass vulnerabilities** due to the architectural split between the desktop bridge and the Phase 11 intelligence stack.

---

## 2. Core Security Boundary Findings

### 2.1 Workspace Containment & Path Traversal
- **Implementation:** `src/workspace/path_safety.py:PathSafetyValidator`
- **Design:** Validates that all candidate file paths resolve within `workspace_root`. Rejects directory traversal attempts (`../`), symlink redirections escaping workspace, absolute drive jumps (`C:\Windows`), and access to sensitive folders (`.git`, `.env`, `.crusorai/auth`).
- **Enforcement in `EngineeringExecutionOrchestrator`:** **ENFORCED.** All mutations pass through `ControlledImplementationEngine` -> `WorkspaceMutationBroker` -> `PathSafetyValidator.validate_safe_path()`. Attempted path escapes throw `PathSecurityViolation`.
- **Enforcement in Desktop `chat_graph`:** **PARTIAL.** `file_tools.py:resolve_workspace_path()` checks `Path.resolve().is_relative_to(workspace)`. However, it does NOT enforce the comprehensive exclusion list (e.g. `.git/hooks`, credentials, SSH keys) defined in `PathSafetyValidator`.

---

### 2.2 Mutation Broker Bypass Vulnerability
- **Severity:** `CRITICAL`
- **Location:** `src/tools/file_tools.py:write_file()` and `edit_file()`
- **Vulnerability Description:**
  In `src/workspace/mutation_broker.py`, the broker enforces strict safety rules:
  1. User files (`FileOwnershipCategory.USER_OWNED`) cannot be overwritten or deleted without an explicit `approval_token`.
  2. High-risk edits (e.g. files containing "auth", "security", "schema") trigger mandatory approval tokens.
  3. All operations generate pre- and post-mutation SHA256 hashes recorded in `WorkspaceChangeLedger`.
  4. Concurrent file modifications by multiple tasks on the same path are detected and rejected (`ConcurrencyConflictError`).
  
  **The Bypass:** When a user interacts with Crusor via the Desktop UI, `chat_graph.py` calls `src/tools/file_tools.py:write_file()` and `edit_file()`. These tools **completely bypass `WorkspaceMutationBroker`**. They use raw `open()` and `Path.write_text()`. Consequently:
  - An agent running from the desktop can overwrite existing user files without any approval token.
  - Security-sensitive files (e.g. `auth.py`, `settings.py`) can be modified without high-risk warnings.
  - No entries are written to the durable change ledger.
  - No rollback snapshots are created.

---

### 2.3 Identity, Multi-Tenancy, and Tool RBAC
- **Implementation:** `src/identity/tool_authorizer.py:IdentityAwareToolAuthorizer`
- **Design:** Evaluates user role hierarchy (`ADMIN`, `MAINTAINER`, `DEVELOPER`, `GUEST`), verifies tenant identity, and gates tool calls (e.g. guests cannot execute terminal commands or delete files).
- **Audit Finding:** **COMPLETELY UNENFORCED.**
  - `IdentityAwareToolAuthorizer` is NOT hooked into `SafeToolNode` in `chat_graph.py`.
  - It is NOT hooked into `ControlledImplementationEngine` in `orchestrator.py`.
  - All tools execute with whatever process-level OS permissions the user's desktop application possesses. Multi-tenant isolation is not enforced at the tool boundary.

---

### 2.4 Secret Redaction and Credential Leakage Protection
- **Implementation:** `src/security/contracts.py:SENSITIVE_SECRET_PATTERNS` + `src/orchestration/visibility.py`
- **Design:** Redacts API keys (`sk-`, `ghp_`, `bearer`), tokens, private keys (`-----BEGIN PRIVATE KEY-----`), and database passwords from progress reports, logs, and IPC frames.
- **Audit Finding:** **VERIFIED ENFORCED.**
  - `DesktopVisibilityReporter` actively scrubs modified file summaries and task progress views.
  - `src/tools/mcp_client.py` filters environment variables, scrubbing secret keys before passing environment dictionaries to child MCP processes.
  - Unit tests in `test_phase_11_6_autonomous_execution.py:test_35_secret_redaction_progress_views` confirm that secrets are redacted from serialized views.

---

### 2.5 Preservation of Upstream Invariant 7
- **Policy:** Invariant 7 of the canonical Code OSS fork dictates:
  1. Crusor UI must be registered strictly from `desktop/vscode/src/vs/workbench/contrib/crusorai/`.
  2. Exactly five upstream Code OSS source files may be modified:
     - `vscode/product.json` (Product branding)
     - `vscode/src/vs/workbench/workbench.common.main.ts` (Workbench registration)
     - `vscode/src/vs/workbench/workbench.desktop.main.ts` (Desktop utility process registration)
     - `vscode/build/buildfile.ts` (Legacy gulp bundle entrypoint)
     - `vscode/build/next/index.ts` (Current esbuild bundle entrypoint)
  3. No upstream code inside `src/vs/workbench/contrib/chat/` or `extensions/copilot/` may be altered or deleted.
- **Audit Verification:**
  - `desktop/vscode/src/vs/workbench/workbench.common.main.ts` line 48 registers Crusor:
    ```typescript
    import './contrib/crusorai/browser/crusorAI.contribution.js';
    ```
  - `desktop/vscode/src/vs/workbench/workbench.desktop.main.ts` line 34 registers the worker:
    ```typescript
    import './contrib/crusorai/electron-browser/crusorAI.desktop.contribution.js';
    ```
  - `desktop/vscode/product.json` sets `nameShort: "CrusorAI"`, `nameLong: "CrusorAI IDE"`.
  - `git diff` against upstream pin confirms: **Invariant 7 is strictly preserved.** No unauthorized upstream files have been modified.

---

## 3. Security Boundary Audit Summary Table

| Security Boundary | Specification | Orchestrator Path (`orchestrator.py`) | Desktop Path (`chat_graph.py`) | Compliance Status |
|---|---|---|---|---|
| **Path Traversal Protection** | Restrict all I/O to workspace | Enforced via `PathSafetyValidator` | Partially enforced via `resolve_workspace_path` | `PARTIALLY_INTEGRATED` |
| **User File Protection** | Refuse overwrite without token | Enforced via `WorkspaceMutationBroker` | **NOT ENFORCED** (Raw writes) | `BROKEN` (Desktop) |
| **High-Risk Path Gating** | Warn/block edits to auth/security files | Enforced via `RiskApprovalGate` | **NOT ENFORCED** | `BROKEN` (Desktop) |
| **Change Ledger & Rollback** | Cryptographic SHA256 journal | Enforced via `WorkspaceChangeLedger` | **NOT ENFORCED** | `BROKEN` (Desktop) |
| **Tool RBAC & Tenant Isolation** | Role-based permission checks | **NOT ENFORCED** | **NOT ENFORCED** | `DISCONNECTED` |
| **Secret Redaction** | Scrub tokens & keys from logs/IPC | Enforced | Enforced | `VERIFIED_INTEGRATED` |
| **Fork Invariant 7** | Max 5 modified upstream files | Enforced | Enforced | `VERIFIED_INTEGRATED` |

---

## 4. Required Security Fixes

1. **Mandatory Broker Interception:** Deprecate raw file writing in `src/tools/file_tools.py`. Route all desktop file creation and modification calls through `WorkspaceMutationBroker.get_instance(workspace)`.
2. **Hook Identity Authorizer:** Integrate `IdentityAwareToolAuthorizer.authorize_tool_call()` into `SafeToolNode` so that role boundaries and tenant permissions are actively checked prior to tool execution.


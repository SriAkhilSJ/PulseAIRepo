# CRUSOR AI IDE — PHASE 9.3.5 SECURITY & EXECUTION INTEGRITY VERIFICATION

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Scope:** Security Alignment between Desktop Workbench & Backend Agent Runtime  
**Audit Verdict:** **FULLY VERIFIED (Strict Parity & Fail-Closed Boundaries)**  

---

## 1. DESKTOP & BACKEND EXECUTION CONTRACT PARITY

A core security invariant of Crusor AI IDE is that **the desktop agent workbench must not provide a less restrictive execution path than the backend runtime**.

| Security Dimension | Desktop Workbench Contract | Backend Agent Runtime Contract | Parity Status |
| :--- | :--- | :--- | :--- |
| **Workspace Identity** | Verified via active workspace URI; missing or outside folder refused. | `_extract_workspace` requires non-empty `workspace` in `RunnableConfig`. | **IDENTICAL (Fail-Closed)** |
| **Session Identity** | Tracked via `session_id` in Bridge Protocol v2. | Tracked via `ApprovalQueue` and LangGraph thread IDs. | **IDENTICAL** |
| **Request Correlation** | Every reverse-RPC and agent turn carries unique `tool_id` / `request_id`. | Every tool invocation logs `request_id` in `CallLedger`. | **IDENTICAL** |
| **Capability Authorization** | Reverse-RPC allowlist strictly limited to 9 read-only endpoints. | Tool catalog restricted to authorized runtime toolsets. | **IDENTICAL** |
| **SafetyGuard Inspection** | Mutating actions evaluated before execution; exceptions fail closed. | `execute_safety_guard` blocks unapproved/uninspected calls. | **IDENTICAL (Fail-Closed)** |
| **Explicit Approval** | Mutating tools (`terminal.*`, `edit.bulkApply`) prompt user confirmation. | `MUTATING_TOOLS` require affirmative `approved=True`. | **IDENTICAL** |
| **Cancellation Handling** | Client AbortController triggers immediate turn cancellation. | Graph and retry controller terminate immediately on `CANCELLATION`. | **IDENTICAL** |
| **Workspace Switching** | Opening a different folder invalidates prior approvals and context chips. | Tool executions targeting paths outside authorized root fail closed. | **IDENTICAL** |

---

## 2. REVERSE-RPC ALLOWLIST BOUNDARIES

Renderer reverse-RPC is strictly locked to the 9 authorized read-only inspection methods:
1. `workbench.getActiveEditor`
2. `workbench.getVisibleEditors`
3. `workbench.getDiagnostics`
4. `workbench.getWorkspaceFolders`
5. `workbench.getConfiguration`
6. `editor.getSelection`
7. `editor.getDocumentSymbols`
8. `editor.getLineCount`
9. `editor.getText`

All attempts to invoke mutating commands (`executeCommand`, `terminal.write`, `fs.delete`, `process.spawn`) over reverse-RPC are denied at the protocol boundary.

---

## 3. OS-LEVEL SANDBOX LIMITATION DISCLOSURE

> [!WARNING]
> **OS-Level Process Sandboxing Limitation:**  
> When `terminal.native`, `run_in_terminal`, or `code_exec_tool` execute scripts or tests on Windows, they run with the security privileges of the active OS user (`Administrator`).  
> Kernel-level sandbox isolation (such as Windows AppContainer, Hyper-V containers, or Linux namespaces/seccomp filters) is **not implemented** in the current userland agent architecture. Security boundaries rely on path canonicalization, workspace containment guards, SafetyGuard pattern analysis, and human approval gates. Crusor AI does not falsely claim OS kernel-level process isolation.


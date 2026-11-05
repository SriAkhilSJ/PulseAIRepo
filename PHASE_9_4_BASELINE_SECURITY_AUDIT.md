# CRUSOR AI IDE — PHASE 9.4 BASELINE SECURITY AUDIT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.3.5.1  
**Audit Date:** 2026-11-04  
**Audit Scope:** Process execution routes, OS privileges, environment inheritance, and boundary isolation across desktop and agent runtime.  
**Execution Budget:** ₹0.00 (Zero paid API calls)  

---

## 1. EXECUTIVE OVERVIEW

Crusor AI IDE provides several application-level security features:
- **Workspace Containment:** `extract_workspace_root_fail_closed` and `RunnableConfig` enforcement.
- **SafetyGuard:** Semantic inspection of tool calls, critical path heuristics, and git status analysis.
- **Durable Middleware:** `execute_tool_transaction` in `src/runtime/tool_middleware.py`.
- **Process Boundary:** `detect_conversational_leak` in `src/tools/process_boundary.py`.
- **Desktop Separation:** Bridge Protocol v2 RPC separating VS Code OSS workbench from Python agent backend.

However, prior to Phase 9.4, **none of these mechanisms establish operating-system-enforced process isolation**. 

When untrusted agent-generated code or shell commands execute:
- Processes run with the full security context of the logged-in host user (`Administrator`).
- Processes inherit the entire host environment, including cloud credentials and API keys.
- Processes possess unrestricted outbound network connectivity.
- Python code execution runs in-process via `exec()` within the agent runtime itself.
- Child processes can spawn arbitrarily without process-tree termination guarantees on process exit.

---

## 2. CURRENT PROCESS TREE & EXECUTION TOPOLOGY

```text
[Host Operating System: Windows_NT x64 10.0.26100]
 │
 ├── CrusorAI.exe (Electron Main Process - PID: Desktop Host)
 │    │
 │    ├── VS Code Renderer (BrowserWindow / Monaco Editor)
 │    │    └── Crusor AI Extension / Custom Workbench Contribution
 │    │
 │    ├── Utility Process / RPC Bridge Client
 │    │    └── Bridge Protocol v2 (WebSocket / Named Pipe)
 │    │
 │    └── Python Agent Backend Process (`python.exe` - LangGraph Runtime)
 │         │
 │         ├── ThreadPoolExecutor (Worker threads for parallel tools)
 │         │
 │         ├── [VULNERABILITY 1: In-Process Code Exec]
 │         │    └── exec() in CPython runtime (execute_code)
 │         │
 │         └── [VULNERABILITY 2: Unsandboxed Subprocesses]
 │              ├── subprocess.Popen(cmd.exe / bash.exe) [terminal]
 │              ├── subprocess.Popen(tracked background processes) [start_terminal]
 │              └── Uncontrolled Child Process Trees (node, python, compilers, curl)
```

---

## 3. AUDIT OF EXECUTION ENTRY POINTS

| Entry Point | Source File | Invocation Mechanism | Current Execution Target | Risk Level |
| :--- | :--- | :--- | :--- | :--- |
| `execute_code` | `src/tools/code_exec_tool.py` | `exec(compile(tree, "<execute_code>", "exec"), namespace)` | In-process within the Python LangGraph agent runtime | **CRITICAL** |
| `terminal` / `run_terminal` | `src/tools/terminal_tools.py` | `subprocess.Popen(argv, cwd=workspace, env=dict(os.environ))` | Host user shell (`cmd.exe` or `bash.exe`) | **CRITICAL** |
| `start_terminal` | `src/tools/terminal_tools.py` | `_spawn_tracked_background` -> `subprocess.Popen` | Background detached process on host | **CRITICAL** |
| `process_boundary` | `src/tools/process_boundary.py` | `subprocess.run(tokens, cwd=workspace, env=env)` | Host user process | **HIGH** |
| `install_toolchain` | `src/tools/toolchain_install.py` | `subprocess.Popen` | System installer execution | **HIGH** |
| Native Terminal | VS Code Workbench | Electron PTY / node-pty | Host user shell | **MEDIUM** |

---

## 4. DETAILED VULNERABILITY ANALYSIS

### 4.1 In-Process Code Execution (`code_exec_tool.py`)
- **Mechanism:** Uses Python's built-in `ast.parse()` and `exec()` with a restricted `__builtins__` dict and `sys.settrace()`.
- **Failure Mode:**
  1. Python `exec()` sandboxing is fundamentally unsound in CPython. Subclass traversal (`().__class__.__bases__[0].__subclasses__()`) allows escaping restricted builtins.
  2. The code runs inside the **same memory space** as the LangGraph agent, SQLite session store, API credentials, and financial ledger. A single memory leak, segfault, or malicious memory mutation compromises the entire agent runtime.

### 4.2 Full Environment Variable Inheritance
- **Source:**
  ```python
  # src/tools/terminal_tools.py
  env = dict(os.environ)
  env["CI"] = "1"
  env["NO_COLOR"] = "1"
  ```
- **Failure Mode:**
  All environment variables present in the parent process are forwarded directly to any terminal command. This includes:
  - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`
  - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AZURE_CLIENT_SECRET`
  - `GITHUB_TOKEN`, `GIT_CREDENTIALS`
  - `SSH_AUTH_SOCK`, user home tokens
  Any executed command (`env`, `set`, or malicious script) can exfiltrate these secrets immediately.

### 4.3 Filesystem Scope & Directory Traversal
- **Source:**
  `process_boundary.py` attempts jailing by checking `token == "cd"` and checking path strings:
  ```python
  if token == "cd" and i + 1 < len(tokens): ...
  ```
- **Failure Mode:**
  This string check is easily bypassed:
  1. `python -c "open('C:/Users/Administrator/.ssh/id_rsa').read()"` bypasses `cd` checks completely.
  2. Symlinks, Windows NTFS junctions, and reparse points inside the workspace pointing to `C:\` or user home are followed transparently by standard filesystem calls.
  3. Hard links and alternate data streams (`file:stream`) bypass simple path filters.

### 4.4 Unrestricted Network Access
- **Current State:** No network filtering exists at the process level.
- **Failure Mode:**
  Any spawned process can bind listening sockets, connect to external C2 servers, scan the internal LAN (`192.168.x.x`), or make requests to cloud metadata endpoints (`169.254.169.254`). Application-level checks cannot block standard socket syscalls.

### 4.5 Child Process Governance & Tree Termination
- **Current State:**
  On Windows, `subprocess.Popen` is invoked with `creationflags = CREATE_NEW_PROCESS_GROUP`.
- **Failure Mode:**
  When a process times out or is cancelled, `process.kill()` terminates only the root process. Any child processes spawned by it (e.g. `cmd.exe -> python.exe -> node.exe`) become orphaned background processes, consuming CPU, locking files, and continuing unauthorized operations.
  Windows Job Objects are required to guarantee complete tree termination via `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.

### 4.6 Resource Starvation (Denial of Service)
- **Current State:** Only wall-clock timeout (`timeout_s`) is enforced.
- **Failure Mode:**
  No CPU quota, no memory ceiling, and no disk write caps exist. A fork-bomb (`:(){ :|:& };:`) or infinite memory allocation (`x = ' ' * 10**10`) can exhaust host RAM, crashing the desktop IDE and freezing the user system.

---

## 5. OS-SPECIFIC ISOLATION REQUIREMENTS

### Windows (Primary Host)
1. **Windows Job Objects:**
   - Must create a Job Object with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`.
   - Apply `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (terminates all descendants on exit/cancel).
   - Apply `JOB_OBJECT_LIMIT_JOB_MEMORY` (caps aggregate memory).
   - Apply `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` (caps concurrent child processes).
   - Apply CPU rate control (`JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION`).
2. **Security Tokens & Integrity:**
   - Execute under a Restricted Token (`CreateRestrictedToken`) with LUA privileges (stripping `SeDebugPrivilege`, administrator SIDs).
   - Deny access to sensitive user profile paths (`.ssh`, `.aws`, `.azure`, credentials).
3. **Staging & Filesystem Jailing:**
   - Prohibit in-place workspace mutation by untrusted processes.
   - Use an isolated staging area for Mode B (proposed modifications) and inspect diff artifacts before applying through host workspace edit services.
4. **Environment Sanitization:**
   - Explicit allowlist of non-sensitive system keys (`SYSTEMROOT`, `COMSPEC`, `PATH`, `TMP`, `TEMP`). Zero credential inheritance.
5. **Network Policy:**
   - Default `NETWORK = DENY`. Document OS enforcement mechanism.

### Linux (Adapter Architecture)
1. User namespaces (`CLONE_NEWUSER`) for unprivileged isolation.
2. Mount namespaces (`CLONE_NEWNS`) with read-only root and bind-mounted staging.
3. Network namespaces (`CLONE_NEWNET`) for complete network blackout (`NETWORK = DENY`).
4. PID namespaces (`CLONE_NEWPID`) for process isolation and tree termination on exit.
5. Cgroups v2 for memory and CPU hard limits.
6. Fail-closed policy if namespaces are prohibited by host kernel policy.

### macOS (Adapter Architecture)
1. Target App Sandbox / `sandbox-exec` profiles.
2. Controlled helper processes with minimal entitlements.
3. Fail-closed policy if sandbox profile compilation or seatbelt policy is unavailable.

---

## 6. AUDIT CONCLUSION

The existing application-level checks (SafetyGuard, path normalization, string command filtering) are necessary pre-filters but **insufficient security boundaries**. 

Phase 9.4 must introduce an **OS-Level Execution Broker Architecture** that intercepts all code execution and terminal commands, strips sensitive environment variables, binds approval cryptographically, enforces Windows Job Object process trees, jails filesystem access via isolated staging, and produces immutable execution receipts.


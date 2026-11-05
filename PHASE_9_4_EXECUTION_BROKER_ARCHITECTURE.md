# CRUSOR AI IDE — PHASE 9.4 EXECUTION BROKER ARCHITECTURE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.4 (Enterprise Execution Sandbox & OS-Level Process Isolation)  
**Standard:** Enterprise Zero-Trust Execution Broker  
**Priority:** P0  

---

## 1. ARCHITECTURAL OVERVIEW

The Execution Broker is the sole authorized gateway for executing untrusted scripts, terminal commands, automated tests, and build tools within Crusor AI IDE. 

No direct `subprocess.Popen`, `subprocess.run`, or in-process `exec()` calls are permitted to bypass the Broker.

```text
                        ┌────────────────────────────────────────┐
                        │             CRUSOR AI IDE              │
                        │       (Electron Desktop Shell)         │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │        LangGraph Agent Runtime         │
                        │     (Agent Logic & Decision State)     │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │            Tool Dispatcher             │
                        │       (SafeToolNode / Middleware)      │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │              SafetyGuard               │
                        │     (Semantic & Risk Path Checks)      │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │           Explicit Approval            │
                        │   (Cryptographic Approval Token)       │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
     ═════════════════════════════════════════════════════════════════════════
     🔒 TRUST BOUNDARY: EXECUTION BROKER CHOKEPOINT (`src/security/`)
     ═════════════════════════════════════════════════════════════════════════
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │            EXECUTION BROKER            │
                        │  - Authenticate Request & Session      │
                        │  - Validate Workspace & Nonce          │
                        │  - Verify Cryptographic Approval Token │
                        │  - Initialize Staging Isolation        │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │            SANDBOX MANAGER             │
                        │   (Platform Factory: Windows / POSIX)  │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │      OS-LEVEL ISOLATED EXECUTION       │
                        │   - Windows Job Object Limits          │
                        │   - Restricted Token / LUA Integrity   │
                        │   - Sanitized Environment Allowlist    │
                        │   - Network Denial (Default)           │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │          RESTRICTED PROCESS            │
                        │       (Isolated Staging Worker)        │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │          CONTROLLED ARTIFACTS          │
                        │       (Diff Inspection & Staging)      │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │          VALIDATION PIPELINE           │
                        │       (Universal Task Validators)      │
                        └───────────────────┬────────────────────┘
                                            │
                                            ▼
                        ┌────────────────────────────────────────┐
                        │          AUDITABLE RECEIPTS            │
                        │    (Immutable SHA-256 ExecutionReceipt)│
                        └────────────────────────────────────────┘
```

---

## 2. THE 15 BROKER EXECUTION CONTRACT REQUIREMENTS

| # | Requirement | Broker Implementation | Enforcement Mechanism |
| :--- | :--- | :--- | :--- |
| **1** | **Authenticate Execution Request** | Validates structured `ExecutionRequest` schema with required nonces and caller identities. | Reject requests missing schema fields or non-conforming parameters. |
| **2** | **Validate Session Identity** | Correlates request with an active, unexpired LangGraph session thread. | Cross-checks `session_id` against `SessionStore`. |
| **3** | **Validate Workspace Identity** | Requires valid canonicalized `workspace_root`. No fallback to process CWD. | Path resolution verifies workspace exists and is a directory. |
| **4** | **Validate Approved Operation** | Matches requested tool and sanitized command against safety policies. | SafetyGuard verdict validation. |
| **5** | **Bind Approval to Exact Request** | Verifies cryptographic token: $\text{HMAC-SHA256}(\text{session\_id} \parallel \text{request\_id} \parallel \text{cmd\_hash} \parallel \text{workspace})$. | Single-use consumption token; invalidates replay attacks. |
| **6** | **Create Restricted Environment** | Generates isolated staging directory and filters environment variables. | `MinimalEnvironmentPolicy`: allowlists only safe system variables; strips all credentials. |
| **7** | **Launch Process Under Sandbox** | Instantiates target subprocess inside OS sandbox container. | Windows: Assigns process to Windows Job Object with restricted token. |
| **8** | **Monitor Resource Consumption** | Queries Job Object counters for peak memory, CPU time, and active process count. | `QueryInformationJobObject` extended limits. |
| **9** | **Capture Output Safely** | Captures stdout/stderr via bounded buffers with hard byte truncation. | Caps streams at 1MB per stream; prevents memory exhaustion. |
| **10** | **Enforce Bounded Timeout** | Enforces wall-clock timeout (`timeout_s`). | Terminates process when timeout expires and marks `timed_out = True`. |
| **11** | **Support Cancellation** | Immediately responds to human or client cancellation signals. | Abort channel triggers job termination. |
| **12** | **Terminate Complete Child Tree** | Guarantees all descendant processes are terminated upon exit or abort. | Windows Job Object `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. |
| **13** | **Collect Authorized Outputs** | In Mode B (proposed modifications), collects modified files in staging for review. | Diff generation and path validation against workspace boundaries. |
| **14** | **Destroy Temporary Resources** | Cleans up staging directories, job handles, and temporary files. | Deterministic `finally` cleanup with verification. |
| **15** | **Produce Auditable Receipt** | Emits immutable `ExecutionReceipt` with SHA-256 evidence hash. | Cryptographic hash over all execution telemetry and outputs. |

---

## 3. DATA STRUCTURE CONTRACTS

### 3.1 ExecutionRequest
```python
@dataclass(frozen=True)
class ExecutionRequest:
    execution_id: str
    session_id: str
    request_id: str
    workspace_root: str
    tool_name: str
    command: str
    argv: list[str]
    mode: ExecutionMode  # READ_ONLY (Mode A) or PROPOSED_MUTATION (Mode B)
    approval_token: str
    timeout_s: float = 60.0
    max_memory_mb: int = 512
    max_processes: int = 10
    network_allowed: bool = False
    env_overrides: dict[str, str] = field(default_factory=dict)
```

### 3.2 ExecutionReceipt
```python
@dataclass(frozen=True)
class ExecutionReceipt:
    execution_id: str
    session_id: str
    request_id: str
    workspace_root: str
    tool_name: str
    executable: str
    sanitized_argv: list[str]
    sandbox_backend: str  # e.g. "windows_job_object_lua"
    policy_version: str
    start_time: str
    end_time: str
    duration_s: float
    exit_code: int
    timed_out: bool
    cancelled: bool
    cpu_user_s: float
    cpu_kernel_s: float
    peak_memory_bytes: int
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    staged_files_created: list[str]
    staged_files_modified: list[str]
    security_violations: list[str]
    cleanup_status: str
    evidence_hash: str
```

---

## 4. INTEGRATION POINTS

1. **Tool Middleware:** `execute_tool_transaction` in `src/runtime/tool_middleware.py` forwards protected tool calls through `ExecutionBroker`.
2. **Terminal Tools:** `run_terminal`, `terminal`, and `start_terminal` in `src/tools/terminal_tools.py` invoke `broker.execute()`.
3. **Code Execution:** `execute_code` in `src/tools/code_exec_tool.py` compiles scripts into an isolated temporary runner script and executes via `broker.execute()`, terminating in-process `exec()`.
4. **Task Validation Engine:** Universal validators in `src/graphs/task_validation.py` inspect `ExecutionReceipt` evidence to verify task completion.


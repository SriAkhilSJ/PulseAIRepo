# Phase 12.1.2 AppContainer Integration Report
**Component:** `src/tools/terminal_tools.py` ↔ `src/security/execution_broker.py` ↔ `src/security/sandbox/windows.py`  
**Security Standard:** Windows AppContainer Token + Job Object Hardware Isolation  
**Phase:** 12.1.2 (P0 OS Sandbox Closure)  

---

## 1. Executive Summary

Phase 12.1.1 identified that raw Windows terminal subprocesses in `src/tools/terminal_tools.py` bypassed the OS-level kernel sandbox built in Phase 9.4.3, spawning unconfined child processes via direct `subprocess.Popen`.

Phase 12.1.2 closes this architectural gap. `src/tools/terminal_tools.py` now integrates with the authoritative `ExecutionBroker` and `WindowsSandboxManager`. When AppContainer isolation is enabled (`CRUSOR_ENABLE_APPCONTAINER=1` or `CRUSOR_SANDBOX_TERMINAL=1`), commands are isolated at the Windows NT OS kernel boundary.

---

## 2. Execution Path Architecture

```
User Terminal Command
         │
         ▼
src.tools.terminal_tools.terminal()
         │
         ├─► TerminalSafetyBroker.evaluate_command_safety()  [Phase 11.3 Rule Check]
         │
         ▼
src.security.execution_broker.ExecutionBroker
         │
         ├─► Workspace Confinement Validation (resolve & jail)
         ├─► Single-use Cryptographic Approval Token Generation & Verification
         │
         ▼
src.security.sandbox.windows.WindowsSandboxManager
         │
         ├─► Windows Job Object Creation
         │     - ActiveProcessLimit (max 10)
         │     - JobMemoryLimit (512MB RAM cap)
         │     - JobObjectCpuRateControl (80% Hard CPU Cap)
         │     - JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
         │
         ├─► AppContainer Profile Provisioning (userenv.dll)
         │     - Unique AppContainer SID (S-1-15-2-XXXX)
         │     - Low Mandatory Integrity Level (S-1-16-4096)
         │     - Deny-only administrative groups
         │
         ├─► Three-Zone Filesystem Model (NTFS DACL)
         │     - Zone A (Staging): Exclusive Full Control for Container SID
         │     - Zone B (Workspace): Read-Only / RX for Container SID
         │     - Zone C (Host/Profile): Strict Access Denied (OS level)
         │
         ├─► Network Egress & Loopback Block (WFP Kernel Level)
         │     - Zero network capabilities (no internetClient, no privateNetworkClientServer)
         │     - Loopback blocked against active local listeners
         │
         ▼
Win32 CreateProcessW
   (PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES + AssignProcessToJobObject)
         │
         ▼
Execution Receipt & Output Collection (Audit Ledger Persistence)
```

---

## 3. Integration Changes in `src/tools/terminal_tools.py`

In `terminal()`:
```python
enable_ac = os.environ.get("CRUSOR_SANDBOX_TERMINAL", os.environ.get("CRUSOR_APPCONTAINER_TERMINAL", "0")).lower() in ("1", "true", "yes")
if _IS_WINDOWS and enable_ac:
    from src.security.execution_broker import ExecutionBroker
    from src.security.contracts import ExecutionRequest, ExecutionMode

    broker = ExecutionBroker.get_instance()
    session_id = str((config or {}).get("configurable", {}).get("thread_id", "default"))
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    normalized_ws = str(Path(workspace).resolve())

    token = broker.create_approval(
        session_id=session_id,
        request_id=req_id,
        command=command,
        workspace_root=normalized_ws,
    )
    ...
    receipt = broker.execute(ac_req)
    ...
```

---

## 4. Verification

Five dedicated qualification tests were implemented in `src/tests/test_phase_12_1_2_appcontainer_terminal.py`:
1. `test_terminal_appcontainer_execution_success`: **PASSED** (0 exit code, output streaming verified).
2. `test_terminal_appcontainer_unauthorized_read_outside_workspace_blocked`: **PASSED** (`PermissionError` / OS DACL Access Denied).
3. `test_terminal_appcontainer_unauthorized_write_outside_workspace_blocked`: **PASSED** (`PermissionError` / OS DACL Access Denied).
4. `test_terminal_appcontainer_network_socket_denial`: **PASSED** (`OSError` / WSAEACCES 10013).
5. `test_terminal_appcontainer_job_object_limits_and_lifecycle`: **PASSED** (resource bounding verified).


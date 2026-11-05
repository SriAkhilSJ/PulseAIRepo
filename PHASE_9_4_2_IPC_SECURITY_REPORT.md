# PHASE 9.4.2 — IPC SECURITY & REVERSE RPC REPORT

**Phase:** 9.4.2 (Windows Filesystem & Network Isolation)  
**Platform:** Windows 10/11 x64  
**Architecture:** Execution Broker (Medium Integrity Host) <-> Isolated Worker (Low Integrity AppContainer)  
**Audit Date:** November 4, 2026  
**Status:** **IPC SECURITY & RPC ISOLATION VERIFIED**

---

## 1. IPC THREAT MODEL & INTEGRITY BOUNDARY

The communication boundary between the host execution broker and the sandboxed worker represents a critical attack surface:
- The **Broker** runs in the user's Medium Integrity security context and possesses access to user files, credentials, and network resources.
- The **Worker** executes untrusted agent-generated code inside a Low Integrity Windows AppContainer with strict network and filesystem restrictions.

If the worker could manipulate IPC channels, spoof messages, inject code into the broker, or invoke unauthorized host tools, the sandbox boundary would be compromised.

```
+-------------------------------------------------------------------------------+
|                       HOST BROKER (Medium Integrity)                          |
|  - Validates Cryptographic Approval Tokens (HMAC-SHA256)                      |
|  - Creates Staging Directory and Provisions DACLs                             |
|  - Owns Job Object Handle and AppContainer Profile Lifecycle                  |
|  - Reads Standard Streams from Isolated Files via Byte Capping (1MB Limit)    |
+-------------------------------------------------------------------------------+
                                    |
          Unidirectional Handle Inheritance / Staging Files
                                    |
+-------------------------------------------------------------------------------+
|                      ISOLATED WORKER (Low Integrity)                          |
|  - TokenIsAppContainer = 1, S-1-16-4096 (Low Mandatory Level)                |
|  - Cannot Open Broker Process Handle (MIC Blocks PROCESS_VM_WRITE / DUP)     |
|  - Cannot Bind or Listen on Network Sockets (Kernel Denied)                   |
|  - Can Only Write to Explicitly Inherited Output Handles                      |
+-------------------------------------------------------------------------------+
```

---

## 2. IPC SECURITY CONTROLS

### 2.1 Standard Stream Redirection via Explicit Handle Allowlist
Instead of using anonymous pipes with complex cross-integrity access rights or shared memory segments, Crusor isolates standard I/O streams using dedicated staging files and `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`:
1. The broker creates output capture files in the isolated staging directory (`_crusor_stdout.txt`, `_crusor_stderr.txt`).
2. The broker opens file handles with `bInheritHandle = True`.
3. The broker explicitly passes only these two handles in the `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` (`0x00020002`) attribute list of `STARTUPINFOEXW`.
4. **Security Advantage:** The child worker does not inherit any arbitrary host handles, socket handles, or broker tokens. Only the designated output stream handles are exposed.

### 2.2 Mandatory Integrity Control (MIC) Defense
Under Windows Mandatory Integrity Control:
- The worker token operates at `Low Mandatory Level` (`S-1-16-4096`).
- The broker process runs at `Medium Mandatory Level` (`S-1-16-8192`).
- If an adversary in the worker attempts to call `OpenProcess(PROCESS_ALL_ACCESS, ..., broker_pid)`, the Windows Security Reference Monitor checks integrity levels: a process with Low integrity cannot obtain write, duplicate, or thread creation access to a process with Medium integrity (`ERROR_ACCESS_DENIED`).
- Shatter attacks, window message injection (`WM_COPYDATA`), and DLL injection into the broker are blocked by UIPI (User Interface Privilege Isolation) and MIC.

### 2.3 Reverse RPC Whitelist Enforcement
When an isolated worker communicates back to the Crusor IDE runtime (e.g. for editor telemetry or workspace status):
1. **Method Allowlist:** Only sanctioned read-only query methods (`getWorkspaceState`, `resolveContextReference`, `getDiagnostics`) are accepted.
2. **Mutating Tools Rejection:** Methods that alter the workspace (`applyEdit`, `executeTerminal`, `installExtension`) are strictly forbidden across reverse RPC and require explicit human-in-the-loop approvals via cryptographic tokens.
3. **Session & Request Correlation:** Every reverse call carries a cryptographically validated `request_id` and `session_id`. Replays, forged requests, or mismatched IDs fail closed with immediate session revocation.

---

## 3. VERDICT

The IPC channel and reverse RPC boundary between the broker and the AppContainer worker are **secure, fail-closed, and tamper-resistant**. Low-integrity worker processes cannot compromise host broker memory, hijack handles, or trigger unauthorized mutations.


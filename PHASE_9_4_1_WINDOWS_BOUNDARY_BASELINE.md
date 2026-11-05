# CRUSOR AI IDE — PHASE 9.4.1 WINDOWS BOUNDARY BASELINE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.4  
**Audit Date:** 2026-11-04  
**Platform:** Windows_NT x64 10.0.26100  
**Paid LLM API Budget Expended:** **₹0.00**  

---

## 1. INITIAL IMPLEMENTATION INSPECTION

Phase 9.4 introduced an Execution Broker (`src/security/execution_broker.py`) and a Windows Sandbox Manager (`src/security/sandbox/windows.py`) utilizing Windows Job Objects, environment sanitization, stream byte-capping, and isolated staging directories.

This baseline audit evaluates the **actual underlying Windows operating system boundary** to answer the 10 mandatory architectural questions.

---

## 2. THE 10 BOUNDARY QUESTIONS & FINDINGS

### 1. Which Windows security identity executes the worker?
- **Identity:** `desktop-1ulgf16\administrator`
- **User SID:** `S-1-5-21-3927822043-602086999-1184865301-500`
- **Execution Model:** The worker runs as an interactive win32 process spawned by Python under the logged-in interactive desktop user's account.

### 2. Which SIDs and groups are enabled?
- `Everyone` (`S-1-1-0`) — Mandatory group, Enabled.
- `BUILTIN\Users` (`S-1-5-32-545`) — Mandatory group, Enabled.
- `NT AUTHORITY\Authenticated Users` (`S-1-5-11`) — Mandatory group, Enabled.
- `NT AUTHORITY\INTERACTIVE` (`S-1-5-4`) — Mandatory group, Enabled.
- `BUILTIN\Administrators` (`S-1-5-32-544`) — Group used for deny only (standard non-elevated token).

### 3. Which privileges are enabled?
- `SeChangeNotifyPrivilege` (Bypass traverse checking) — **Enabled** (standard Windows default).
- Administrative privileges (`SeShutdownPrivilege`, `SeUndockPrivilege`, `SeTimeZonePrivilege`, `SeIncreaseWorkingSetPrivilege`) — **Disabled**.
- Token assignment privileges (`SeAssignPrimaryTokenPrivilege`, `SeImpersonatePrivilege`) — **Not held**.

### 4. Whether the worker uses a restricted token?
- **Finding:** No. `subprocess.Popen` inherits the primary interactive process token. In standard Windows user mode, calling `CreateProcessAsUserW` requires `SeAssignPrimaryTokenPrivilege` (which is restricted to `LocalSystem` / services). A user-mode desktop application cannot swap primary process tokens without service elevation.

### 5. Whether it executes inside an AppContainer?
- **Finding:** No. The process token does not possess an AppContainer SID. It runs as a standard medium-integrity Win32 desktop process.

### 6. Whether filesystem access is restricted by the OS?
- **Finding:** **Partially / Application-Enforced.**
  - **By Broker Application Policy:** Traversal sequences (`..`), sensitive paths (`.ssh`, `.aws`, `.azure`), and unapproved workspace paths are strictly intercepted and rejected with exit code 126 before process invocation.
  - **By OS Filesystem DACLs:** The OS permits read access to arbitrary files within the user profile (`C:\Users\Administrator`) because standard NTFS DACLs grant Read permissions to the interactive user. Direct dynamic Python calls that bypass application argument parsing can read user-owned files on disk.

### 7. Whether outbound networking is denied by the OS?
- **Finding:** **Partially / Environment-Enforced.**
  - **By Environment Configuration:** `HTTP_PROXY=http://127.0.0.1:0`, `HTTPS_PROXY=http://127.0.0.1:0`, `ALL_PROXY=http://127.0.0.1:0`, `NO_PROXY=""`, and `CRUSOR_NETWORK=DENY` successfully block standard HTTP/urllib/requests traffic.
  - **By OS Kernel:** Direct raw TCP socket connections, UDP packets, and DNS resolutions (`socket.create_connection`, `socket.sendto`) are permitted by the Windows networking stack because no Windows Filtering Platform (WFP) driver or Windows Firewall rule is injected.

### 8. Whether child processes inherit the intended restrictions?
- **Finding:** Yes. Windows Job Objects enforce restrictions hierarchically. Any child process spawned by the worker is automatically assigned to the parent's Job Object, inheriting the active process cap (10), aggregate memory limit (512MB), and CPU quota (80%).

### 9. Whether the process can escape its Job Object?
- **Finding:** No. The Job Object is created without `JOB_OBJECT_LIMIT_BREAKAWAY_OK` and without `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK`. Attempts by child processes to pass `CREATE_BREAKAWAY_FROM_JOB` are rejected by the Windows kernel.

### 10. Which resource limits are configured and actually enforced?
- `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: **Enforced by OS Kernel**. Closing or terminating the job handle unconditionally kills all descendants.
- `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`: **Enforced by OS Kernel** (ActiveProcessLimit = 10).
- `JOB_OBJECT_LIMIT_JOB_MEMORY`: **Enforced by OS Kernel** (JobMemoryLimit = 512MB default; configurable down to 64MB).
- `JobObjectCpuRateControlInformation`: **Enforced by OS Kernel** (CpuRate = 8000 basis points = 80.00% hard CPU quota).
- Output stream capping: **Enforced by Broker reader threads** (1MB hard cap per stream).

---

## 3. SUMMARY BASELINE VERDICT

Windows process and resource containment (Job Objects, process-tree termination, CPU rate quotas, memory limits, process limits) is **genuinely enforced at the OS kernel level**. 

However, filesystem containment and network denial rely on **Execution Broker path jailing, isolated staging, and environment proxy routing**, rather than kernel-level AppContainers or WFP filters. In accordance with Phase 9.4.1 criteria, this distinction is explicitly recognized and documented.


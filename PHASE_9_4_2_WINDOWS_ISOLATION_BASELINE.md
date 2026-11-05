# PHASE 9.4.2 — WINDOWS ISOLATION BASELINE REPORT

**Phase:** 9.4.2 (Windows Filesystem & Network Isolation)  
**Parent Phase:** 9.4.1 (Windows OS Boundary Proof & Sandbox Hardening)  
**Platform:** Windows 10/11 x64 (`DESKTOP-1ULGF16`)  
**Operating Architecture:** Execution Broker + Windows AppContainer + Job Objects  
**Audit Date:** November 4, 2026  
**Status:** **CLOSED — BASELINE RECONCILED**

---

## 1. EXECUTIVE SUMMARY & RECONCILIATION

In Phase 9.4.1, empirical auditing of Crusor's Windows execution sandbox established that while Windows Job Object containment provided kernel-level process tree termination (`KILL_ON_JOB_CLOSE`), active process limits (10), CPU rate control (80% hard cap), and memory bounding (512MB), the worker process remained bound to the interactive user's security token.

Specifically, Phase 9.4.1 empirical tests proved:
1. **Security Identity:** The worker executed under user `desktop-1ulgf16\administrator` (`S-1-5-21-3927822043-602086999-1184865301-500`) with `Medium Mandatory Level` (`S-1-16-8192`).
2. **Filesystem Boundary Defect:** While application-level path checks in `execution_broker.py` blocked traversal strings (`..`) and sensitive directory tokens, dynamic runtime code (e.g. dynamic Python `open()`) could read any file permitted by the user's interactive DACL (including external canary files in `%USERPROFILE%`).
3. **Network Boundary Defect:** Network isolation was enforced primarily via blackhole proxy environment variables (`HTTP_PROXY=http://127.0.0.1:0`). Direct raw TCP sockets (`socket.create_connection`) and DNS queries bypassed the proxy variables completely, connecting to arbitrary external IPs and domain servers.

These findings formed the rationale for Phase 9.4.1's verdict of `PARTIAL ISOLATION`. Phase 9.4.2 directly closes each of these gaps by migrating the execution worker into a genuine Windows AppContainer.

---

## 2. DEFECT COMPARISON MATRIX: PHASE 9.4.1 VS PHASE 9.4.2

| Security Boundary | Phase 9.4.1 (Job Object Only) | Phase 9.4.2 (AppContainer + Job Object) | OS Mechanism |
| :--- | :--- | :--- | :--- |
| **Token Mandatory Level** | Medium (`S-1-16-8192`) | **Low (`S-1-16-4096`)** | Windows Token Integrity |
| **AppContainer Token** | No (`TokenIsAppContainer == 0`) | **Yes (`TokenIsAppContainer == 1`)** | `userenv.dll` + `ntdll.dll` |
| **Admin Group Status** | Active / Enabled | **Deny-Only (`S-1-5-32-544`)** | Restricted Token Filter |
| **Privileges Held** | 20+ Privileges Enabled | **1 Enabled (`SeChangeNotifyPrivilege`)** | AppContainer Token Stripping |
| **Unauthorized File Read** | `LEAK_SUCCESS` (DACL Match) | **`PermissionError: [Errno 13]`** | NTFS DACL Check (`ntfs.sys`) |
| **Unauthorized File Write**| `WRITE_SUCCESS` (User Home) | **`PermissionError: [Errno 13]`** | NTFS DACL Check (`ntfs.sys`) |
| **Direct TCP Socket** | `CONNECTED` (Bypassed Proxy) | **`WSAEACCES: 10013` (Denied)** | Kernel Socket Driver (`tcpip.sys`) |
| **DNS Resolution** | `RESOLVED` (Direct UDP/TCP) | **`gaierror: 11001` (Denied)** | Kernel Socket Driver (`tcpip.sys`) |
| **Job Object Termination** | Enforced (`KILL_ON_JOB_CLOSE`) | **Enforced (`KILL_ON_JOB_CLOSE`)** | Windows Job Object Kernel |
| **CPU Rate Hard Cap** | Enforced (80% Hard Cap) | **Enforced (80% Hard Cap)** | `JobObjectCpuRateControlInformation` |
| **Memory Limit** | Enforced (512MB Quota) | **Enforced (512MB Quota)** | `JobObjectExtendedLimitInformation` |

---

## 3. THREAT VECTOR ANALYSIS

### 3.1 CVE-style Attack Vector 1: Arbitrary File Read Outside Staging
- **Phase 9.4.1 Vulnerability:** Untrusted code executing in the worker could evaluate `open('C:/Users/Administrator/.gitconfig')`. Because the process possessed the interactive Administrator DACL token, the kernel granted read access.
- **Phase 9.4.2 Resolution:** Under AppContainer SID (`S-1-15-2-...`), the Windows Security Reference Monitor (`SRM`) denies read access to any file object whose Security Descriptor does not explicitly grant the AppContainer SID or `ALL APPLICATION PACKAGES` (`S-1-15-2-1`). All unauthorized host files return `ERROR_ACCESS_DENIED` at the kernel level.

### 3.2 CVE-style Attack Vector 2: Socket Exfiltration via Raw TCP/UDP
- **Phase 9.4.1 Vulnerability:** Setting `HTTP_PROXY=http://127.0.0.1:0` only constrained applications that voluntarily consulted environment variables (such as `requests` or `urllib`). Low-level sockets created via `socket.socket()` initiated connections directly to public endpoints (e.g. `1.1.1.1:443`).
- **Phase 9.4.2 Resolution:** The AppContainer token is provisioned with `CapabilityCount = 0` (omitting `internetClient` and `privateNetworkClientServer`). In `tcpip.sys`/`afd.sys`, socket bind, connect, and DNS dispatch evaluate capability tokens. Lacking network capabilities, the kernel immediately aborts socket operations with `WSAEACCES` (10013).

---

## 4. INTEGRITY RECONCILIATION SUMMARY

Phase 9.4.2 resolves all architectural deficiencies recorded in `PHASE_9_4_1_WINDOWS_BOUNDARY_BASELINE.md`. By augmenting the Windows Job Object resource layer with an AppContainer token layer, Crusor achieves complete defense-in-depth where process isolation, memory containment, CPU rate control, filesystem access control, and network isolation are all enforced directly by the Windows NT kernel.


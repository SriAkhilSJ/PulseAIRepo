# Phase 12.1.3 AppContainer Runtime Evidence Report
**Report ID:** `P12-1-3-REP-APPCONTAINER-01`  
**Host OS:** Microsoft Windows 10/11 Enterprise x64  
**Isolation Architecture:** Windows AppContainer Token Isolation + Win32 Job Object Hard Resource Bounding  
**Security Module:** `src.security.sandbox.windows.WindowsSandboxManager`  
**Date:** 2026-11-06  

---

## 1. Executive Summary

Phase 12.1.3 independently qualified the Windows OS-kernel level AppContainer sandboxing integrated into terminal operations and autonomous tool execution. The runtime environment was verified using direct Win32 `OpenProcessToken`, `GetTokenInformation`, and `IsProcessInJob` queries on active processes.

---

## 2. Live Process OS Kernel Token Evidence

A live execution process was spawned inside an active AppContainer sandbox profile (`use_appcontainer=True`) with an authorized workspace path (`apps/personal_finance`). The process token was directly queried via Win32 API before process termination.

### Observed Kernel Values:
- **Child Process PID:** `12856`
- **Backend Type:** `windows_appcontainer_job_object`
- **AppContainer Profile SID:**  
  `S-1-15-2-1540007691-2285156905-3583033357-8313743-1069793555-2511094240-2908067048`
- **TokenIsAppContainer (`TokenInformationClass = 29`):**  
  `True` (`DWORD value = 1`)
- **Token Integrity Level (`TokenInformationClass = 25`):**  
  `S-1-16-4096` (`SECURITY_MANDATORY_LOW_RID` / Low Mandatory Level)
- **Job Object Membership (`kernel32.IsProcessInJob`):**  
  `True` (Assigned to `WindowsSandboxManager._job_handle`)

---

## 3. Four-Tier Security Boundary Distinction

1. **Application-Level Enforcement:**
   - Command validation (`_posix_violations`, argument normalization).
   - Dynamic path allowlisting and permission gating.
2. **OS-Level AppContainer Isolation:**
   - Token-level sandboxing with zero default capability SIDs (no `internetClient`, no `privateNetworkClientServer`).
   - NTFS DACL restriction: kernel denies read/write access to `%APPDATA%`, system binaries, registry, and any directory outside the explicitly granted workspace folder.
3. **Win32 Job Object Resource Bounding:**
   - Active process count cap (`ActiveProcessLimit = 4`).
   - Memory limit cap (`JobMemoryLimit = 128 MB`).
   - Process tree auto-termination (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`).
   - CPU rate hard cap at 80%.
4. **WFP (Windows Filtering Platform) Network Isolation:**
   - Outbound socket calls fail immediately with WinError 10013 (`WSAEACCES: An attempt was made to access a socket in a way forbidden by its access permissions`).

---

## 4. Test Suite Execution

All 5 dedicated tests in `src/tests/test_phase_12_1_2_appcontainer_terminal.py` passed:
- `test_terminal_appcontainer_execution_success`: **PASSED**
- `test_terminal_appcontainer_unauthorized_read_outside_workspace_blocked`: **PASSED**
- `test_terminal_appcontainer_unauthorized_write_outside_workspace_blocked`: **PASSED**
- `test_terminal_appcontainer_network_socket_denial`: **PASSED**
- `test_terminal_appcontainer_job_object_limits_and_lifecycle`: **PASSED**

**Qualification Status:** **APPCONTAINER ISOLATION QUALIFIED**


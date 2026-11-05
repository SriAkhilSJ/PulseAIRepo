# PHASE 9.4.2 — APPCONTAINER IMPLEMENTATION ARCHITECTURE

**Phase:** 9.4.2 (Windows Filesystem & Network Isolation)  
**Implementation Target:** `src/security/sandbox/windows.py` & `src/security/sandbox/manager.py`  
**Platform:** Windows 10/11 x64  
**Runtime Isolation:** Windows AppContainer (`userenv.dll`) + Windows Job Objects (`kernel32.dll`)  
**Status:** **IMPLEMENTED & VERIFIED**

---

## 1. ARCHITECTURAL OVERVIEW

The Crusor Windows Sandbox implementation in Phase 9.4.2 combines two native Windows NT OS security subsystems into a unified isolation architecture:

```
+-----------------------------------------------------------------------------------+
|                            CRUSOR EXECUTION BROKER                                |
|  - Workspace path verification (Fail-closed)                                      |
|  - Cryptographic HMAC-SHA256 single-use approval token verification               |
|  - Environment secret stripping & allowlist sanitization                          |
|  - Isolated staging directory creation with AppContainer ACL                      |
+-----------------------------------------------------------------------------------+
                                        |
       Spawns via kernel32.CreateProcessW (EXTENDED_STARTUPINFO_PRESENT)
                                        |
                                        v
+-----------------------------------------------------------------------------------+
|                        ISOLATED WORKER PROCESS BOUNDARY                           |
|                                                                                   |
|  [ LAYER 1: WINDOWS APPCONTAINER TOKEN ]                                           |
|  - Token Type: Low Mandatory Level (S-1-16-4096)                                  |
|  - AppContainer Identity: S-1-15-2-XXXX-XXXX-...                                  |
|  - Token Flags: TokenIsAppContainer == 1                                          |
|  - Group Restrictions: BUILTIN\Administrators marked "Deny-Only"                  |
|  - Capabilities: CapabilityCount = 0 (No internetClient, No privateNetwork)       |
|  - Filesystem Enforcement: NTFS DACL denies all host access; allows staging only   |
|  - Network Enforcement: tcpip.sys/afd.sys denies TCP/UDP/DNS (WSAEACCES 10013)    |
|                                                                                   |
|  [ LAYER 2: WINDOWS JOB OBJECT RESOURCE CONTAINER ]                               |
|  - Process Termination: JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (Tree kill on exit)    |
|  - Process Limit: JOB_OBJECT_LIMIT_ACTIVE_PROCESS (Max 10 concurrent processes)   |
|  - Memory Limit: JOB_OBJECT_LIMIT_JOB_MEMORY (512MB hard limit)                   |
|  - CPU Rate Limit: JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP (80.00% max CPU rate)     |
+-----------------------------------------------------------------------------------+
```

---

## 2. WIN32 API INTEGRATION DETAILS

### 2.1 Profile Provisioning & SID Derivation (`userenv.dll`)
Crusor provisions an isolated AppContainer profile per execution request using native C-runtime bindings:
```python
hr = _userenv.CreateAppContainerProfile(
    profile_name,
    profile_name,
    "Crusor Isolated Worker Sandbox Profile",
    None,
    0,
    ctypes.byref(sid_ptr),
)
```
If the profile already exists from a previous uncleaned invocation, Crusor dynamically recovers the profile SID via:
```python
hr = _userenv.DeriveAppContainerSidFromAppContainerName(profile_name, ctypes.byref(sid_ptr))
```
Upon completion of the execution lifecycle, the profile is completely unlinked and removed:
```python
_userenv.DeleteAppContainerProfile(profile_name)
```

### 2.2 Unpackaged Win32 AppContainer Initialization Fix (`0xc0000142`)
Unpackaged Win32 console binaries (such as `cmd.exe` or `python.exe`) require access to the interactive window station (`WinSta0`) and desktop (`Default`). Without this, process startup immediately aborts in `csrss`/`ntdll` with `STATUS_DLL_INIT_FAILED (0xc0000142)`.

Crusor solves this by updating the DACL of the current window station and thread desktop:
```python
ea = EXPLICIT_ACCESS_W()
ea.grfAccessPermissions = GENERIC_ALL
ea.grfAccessMode = GRANT_ACCESS
ea.grfInheritance = NO_INHERITANCE
ea.Trustee.TrusteeForm = TRUSTEE_IS_NAME
ea.Trustee.TrusteeType = TRUSTEE_IS_WELL_KNOWN_GROUP
ea.Trustee.ptstrName = "ALL APPLICATION PACKAGES"

_advapi32.SetEntriesInAclW(1, ctypes.byref(ea), p_dacl, ctypes.byref(p_new_dacl))
_advapi32.SetSecurityInfo(hwinsta, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)
```

### 2.3 Process Creation Attributes (`kernel32.dll`)
Process initialization configures two thread attributes:
1. `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` (`0x00020009`): Attaches the AppContainer SID and sets `CapabilityCount = 0`.
2. `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` (`0x00020002`): Explicitly allows inheritance of standard output and error stream handles (`h_stdout`, `h_stderr`).

```python
sec_caps = SECURITY_CAPABILITIES()
sec_caps.AppContainerSid = self._appcontainer_sid
sec_caps.Capabilities = None
sec_caps.CapabilityCount = 0
sec_caps.Reserved = 0

_kernel32.UpdateProcThreadAttribute(
    attr_buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, ctypes.byref(sec_caps), ctypes.sizeof(sec_caps), None, None
)

handle_array = (wintypes.HANDLE * 2)(h_out, h_err)
_kernel32.UpdateProcThreadAttribute(
    attr_buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handle_array, ctypes.sizeof(handle_array), None, None
)
```

### 2.4 Suspended Process Job Object Assignment
To prevent race conditions where a child process could spawn unbound workers or consume resources before assignment, processes are created in a suspended state, assigned to the Job Object, and then resumed:
```python
flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW | CREATE_SUSPENDED | 0x00000400
res_cp = _kernel32.CreateProcessW(
    None, cmd_line, None, None, True, flags, env_buf, cwd, ctypes.byref(si_ex.StartupInfo), ctypes.byref(pi)
)
_kernel32.AssignProcessToJobObject(self._job_handle, pi.hProcess)
_kernel32.ResumeThread(pi.hThread)
```

### 2.5 Windows Environment Block Case-Insensitive Alphabetical Sorting
Windows `CreateProcessW` requires Unicode environment blocks to be sorted alphabetically in case-insensitive Unicode order. Failure to sort results in `ERROR_ENVVAR_NOT_FOUND (203)`. Furthermore, AppContainer profiles require `LOCALAPPDATA` to locate package state.

Crusor formats the environment block as:
```python
sorted_keys = sorted(env.keys(), key=lambda k: k.upper())
env_str = "".join(f"{k}={env[k]}\0" for k in sorted_keys) + "\0"
env_buf = ctypes.create_unicode_buffer(env_str)
```

---

## 3. FAIL-CLOSED AND DEGRADED RECOVERY

1. **Unsupported OS / Platform:** If executed on a non-Windows host, `get_sandbox_manager()` immediately raises `NotImplementedError`, preventing execution.
2. **Profile Creation Failure:** If AppContainer profile creation fails (e.g. on Windows Server without userenv support), the manager falls back to Job Object isolation with `CRUSOR_SANDBOX_BACKEND="windows_job_object_lua"` while strictly logging the degradation.
3. **Cancellation & Timeout:** If the timeout expires or an `abort_event` is signaled, `TerminateJobObject(self._job_handle, 1)` and `TerminateProcess(pi.hProcess, 1)` unconditionally kill the worker and all child processes.


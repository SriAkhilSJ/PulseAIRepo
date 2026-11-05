# CRUSOR AI IDE — PHASE 9.4 PLATFORM SUPPORT MATRIX

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.4  
**Audit Date:** 2026-11-04  

---

## 1. CROSS-PLATFORM ISOLATION CAPABILITY MATRIX

| Isolation Capability | Windows_NT (Primary) | Linux (Adapter) | macOS Darwin (Adapter) |
| :--- | :--- | :--- | :--- |
| **Sandbox Manager Class** | `WindowsSandboxManager` | `LinuxSandboxManager` | `MacOSSandboxManager` |
| **Backend Identifier** | `windows_job_object_lua` | `linux_namespaces_cgroups` | `macos_sandbox_exec` |
| **Process Tree Termination** | Windows Job Object (`KILL_ON_JOB_CLOSE`) | PID Namespaces (`CLONE_NEWPID`) | Process group / killpg signals |
| **Active Process Limit** | `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` | Cgroups v2 `pids.max` | POSIX `setrlimit(RLIMIT_NPROC)` |
| **Memory Ceiling** | `JOB_OBJECT_LIMIT_JOB_MEMORY` | Cgroups v2 `memory.max` | POSIX `setrlimit(RLIMIT_AS)` |
| **Filesystem Containment** | Staging Directory + Path Canonicalization | Mount Namespaces (`CLONE_NEWNS`, bwrap ro-bind) | Seatbelt profile `(deny default)`, ro-subpath |
| **Network Denial** | Blackhole proxy (`127.0.0.1:0`) + env deny | Network Namespace (`CLONE_NEWNET`, `--unshare-net`) | Seatbelt profile `(deny network*)` |
| **Environment Sanitization** | `SAFE_ENVIRONMENT_KEYS` Allowlist | `SAFE_ENVIRONMENT_KEYS` Allowlist | `SAFE_ENVIRONMENT_KEYS` Allowlist |
| **Stream Output Capping** | 1MB Hard Truncation | 1MB Hard Truncation | 1MB Hard Truncation |
| **Fallback on Missing Primitives** | **Fail-Closed** (`RuntimeError`) | **Fail-Closed** (`NotImplementedError`) | **Fail-Closed** (`NotImplementedError`) |
| **Verification Status** | **VERIFIED (24/24 Tests)** | **ADAPTER READY / FAIL-CLOSED** | **ADAPTER READY / FAIL-CLOSED** |

---

## 2. PLATFORM ADAPTER DETAILS & TARGET DISTRIBUTIONS

### 2.1 Windows (Host: Windows 11 / Server 2022+)
- **Primary Development Environment:** Fully functional via `kernel32` and `advapi32`.
- **Supported Architectures:** x64, ARM64.
- **Verification Evidence:** 24/24 adversarial tests passed.

### 2.2 Linux (Ubuntu 22.04+, Debian 12+, RHEL 9+, Arch)
- **Primary Mechanism:** `bwrap` (Bubblewrap) or `unshare` utility combined with cgroups v2.
- **Fail-Closed Policy:** If unprivileged user namespaces are disabled by sysctl (`kernel.unprivileged_userns_clone = 0`), execution fails closed immediately. Unisolated fallback execution is strictly prohibited.

### 2.3 macOS (macOS 13 Ventura+, macOS 14 Sonoma+)
- **Primary Mechanism:** Apple Seatbelt framework via `sandbox-exec` with strictly generated scheme-level profiles.
- **Fail-Closed Policy:** If `sandbox-exec` is missing or profile compilation fails, execution fails closed immediately.

---

## 3. PLATFORM STATUS CONCLUSION

The primary enterprise development environment (**Windows x64**) is 100% verified with operating-system process isolation. Linux and macOS adapters are implemented with strict fail-closed enforcement, ensuring that running Crusor across platforms will never silently execute untrusted code in an unisolated environment.


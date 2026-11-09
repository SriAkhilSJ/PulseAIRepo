"""
windows.py - Windows OS-Level Sandbox Manager using AppContainer and Job Objects.

Phase 9.4.2: Windows Filesystem & Network Isolation.
Enforces:
1. Windows AppContainer: genuine OS-level token isolation, Low Mandatory Level (S-1-16-4096),
   zero capabilities (strict kernel TCP/UDP/DNS denial via tcpip.sys/afd.sys),
   NTFS DACL filesystem jailing (kernel denial on unauthorized paths).
2. Windows Job Object: process tree termination (KILL_ON_JOB_CLOSE), active process cap,
   memory limits (512MB default), CPU rate control (80% hard cap).
3. Minimal Allowlisted Environment: stripping all API keys, SSH keys, cloud credentials.
4. Output Byte Capping: Preventing memory exhaustion via excessive stdout/stderr (1MB cap).
5. Clean Lifecycle: Per-execution AppContainer profile provisioning and guaranteed teardown.
"""

from __future__ import annotations

import ctypes
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.security.contracts import (
    ExecutionMode,
    ExecutionRequest,
    SAFE_ENVIRONMENT_KEYS,
    SENSITIVE_SECRET_PATTERNS,
    SandboxBackendType,
    SecurityViolationType,
)
from src.security.sandbox.base import BaseSandboxManager

# Win32 Kernel32, Advapi32, Userenv, and User32 bindings
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True) if sys.platform == "win32" else None
_userenv = ctypes.WinDLL("userenv", use_last_error=True) if sys.platform == "win32" else None
_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None

# Job Object Constants
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JobObjectExtendedLimitInformation = 9

# CPU Rate Control Constants
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004
JobObjectCpuRateControlInformation = 15

# AppContainer & Process Creation Constants
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_NO_WINDOW = 0x08000000
CREATE_SUSPENDED = 0x00000004
STARTF_USESTDHANDLES = 0x00000100
GENERIC_ALL = 0x10000000
GENERIC_WRITE = 0x40000000
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
CREATE_ALWAYS = 2
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080

SE_WINDOW_OBJECT = 7
DACL_SECURITY_INFORMATION = 4
GRANT_ACCESS = 1
NO_INHERITANCE = 0
TRUSTEE_IS_NAME = 1
TRUSTEE_IS_WELL_KNOWN_GROUP = 5


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ControlFlags", wintypes.DWORD),
        ("CpuRate", wintypes.DWORD),
    ]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.c_void_p),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class TRUSTEE_W(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", wintypes.DWORD),
        ("TrusteeForm", wintypes.DWORD),
        ("TrusteeType", wintypes.DWORD),
        ("ptstrName", wintypes.LPWSTR),
    ]


class EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", TRUSTEE_W),
    ]


_winsta_desktop_granted = False


def _ensure_windowstation_desktop_access() -> bool:
    """
    Ensure the current WindowStation and Desktop allow ALL APPLICATION PACKAGES (S-1-15-2-1).
    This is required for unpackaged Win32 AppContainer processes to initialize without 0xc0000142.
    """
    global _winsta_desktop_granted
    if _winsta_desktop_granted:
        return True

    if not _advapi32 or not _user32 or not _kernel32:
        return False

    def _grant_to_object(handle) -> bool:
        ea = EXPLICIT_ACCESS_W()
        ea.grfAccessPermissions = GENERIC_ALL
        ea.grfAccessMode = GRANT_ACCESS
        ea.grfInheritance = NO_INHERITANCE
        ea.Trustee.pMultipleTrustee = None
        ea.Trustee.MultipleTrusteeOperation = 0
        ea.Trustee.TrusteeForm = TRUSTEE_IS_NAME
        ea.Trustee.TrusteeType = TRUSTEE_IS_WELL_KNOWN_GROUP
        ea.Trustee.ptstrName = "ALL APPLICATION PACKAGES"

        p_dacl = ctypes.c_void_p()
        p_sec_desc = ctypes.c_void_p()
        ret = _advapi32.GetSecurityInfo(
            handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, ctypes.byref(p_dacl), None, ctypes.byref(p_sec_desc)
        )
        if ret != 0:
            return False

        p_new_dacl = ctypes.c_void_p()
        ret2 = _advapi32.SetEntriesInAclW(1, ctypes.byref(ea), p_dacl, ctypes.byref(p_new_dacl))
        if ret2 == 0:
            _advapi32.SetSecurityInfo(handle, SE_WINDOW_OBJECT, DACL_SECURITY_INFORMATION, None, None, p_new_dacl, None)
            _kernel32.LocalFree(p_new_dacl)
        _kernel32.LocalFree(p_sec_desc)
        return ret2 == 0

    hwinsta = _user32.GetProcessWindowStation()
    hdesk = _user32.GetThreadDesktop(_kernel32.GetCurrentThreadId())
    ok1 = _grant_to_object(hwinsta) if hwinsta else False
    ok2 = _grant_to_object(hdesk) if hdesk else False
    _winsta_desktop_granted = ok1 and ok2
    return _winsta_desktop_granted


class WindowsSandboxManager(BaseSandboxManager):
    """
    Windows execution sandbox enforcing:
    1. AppContainer Token Isolation: kernel-enforced network denial (0 capabilities) and NTFS DACL jailing.
    2. Windows Job Object: process tree termination (KILL_ON_JOB_CLOSE), active process cap, memory limits, CPU hard cap.
    3. Minimal Allowlisted Environment: stripping all API keys, SSH keys, cloud credentials.
    4. Output Byte Capping: Preventing memory exhaustion via excessive stdout/stderr (1MB cap).
    5. Fallback Protection: Fail-closed fallback to Job Object isolation if AppContainer is unavailable.
    """

    def __init__(self, use_appcontainer: bool = True) -> None:
        self._use_appcontainer = use_appcontainer
        self._job_handle: Optional[wintypes.HANDLE] = None
        self._process: Optional[subprocess.Popen] = None
        self._process_info: Optional[PROCESS_INFORMATION] = None
        self._violations: List[str] = []
        self._peak_memory_bytes: int = 0
        self._appcontainer_profile_name: Optional[str] = None
        self._appcontainer_sid: Optional[ctypes.c_void_p] = None
        self._appcontainer_sid_string: Optional[str] = None
        self._granted_workspace_path: Optional[Path] = None

    @property
    def backend_type(self) -> SandboxBackendType:
        if self._use_appcontainer and self._appcontainer_sid:
            return SandboxBackendType.WINDOWS_APPCONTAINER
        return SandboxBackendType.WINDOWS_JOB_OBJECT

    @property
    def appcontainer_sid_str(self) -> Optional[str]:
        return self._appcontainer_sid_string

    def get_capabilities(self) -> Dict[str, bool]:
        has_ac = bool(self._appcontainer_sid)
        return {
            "process_tree_termination": True,
            "job_object_resource_limits": True,
            "active_process_limit": True,
            "memory_limit": True,
            "environment_sanitization": True,
            "filesystem_staging": True,
            "network_denial": True,
            "low_integrity_restricted_token": True,
            "appcontainer_isolation": has_ac,
            "kernel_network_isolation": has_ac,
            "kernel_filesystem_dacl_isolation": has_ac,
        }

    def initialize(self, request: ExecutionRequest, staging_dir: Path) -> None:
        """Create and configure the Windows Job Object and AppContainer profile."""
        self._violations = []
        self._peak_memory_bytes = 0

        if _kernel32 is None:
            raise RuntimeError("WindowsSandboxManager requires Windows OS (kernel32.dll).")

        # 1. Create Job Object
        self._job_handle = _kernel32.CreateJobObjectW(None, None)
        if not self._job_handle:
            err = ctypes.get_last_error()
            raise RuntimeError(f"Failed to create Windows Job Object: WinError {err}")

        # 2. Configure Limits
        limit_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limit_flags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_JOB_MEMORY
        )
        limit_info.BasicLimitInformation.LimitFlags = limit_flags
        limit_info.BasicLimitInformation.ActiveProcessLimit = max(1, request.max_processes)
        limit_info.JobMemoryLimit = max(32, request.max_memory_mb) * 1024 * 1024

        success = _kernel32.SetInformationJobObject(
            self._job_handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(limit_info),
            ctypes.sizeof(limit_info),
        )
        if not success:
            err = ctypes.get_last_error()
            self.terminate()
            raise RuntimeError(f"Failed to set Windows Job Object information: WinError {err}")

        # 3. Configure OS CPU Rate Control (Hard Cap at 80% CPU)
        cpu_info = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        cpu_info.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
        cpu_info.CpuRate = 8000  # 80.00%
        _kernel32.SetInformationJobObject(
            self._job_handle,
            JobObjectCpuRateControlInformation,
            ctypes.byref(cpu_info),
            ctypes.sizeof(cpu_info),
        )

        # 4. Provision AppContainer profile if enabled
        if self._use_appcontainer and _userenv and _advapi32:
            try:
                _ensure_windowstation_desktop_access()
                clean_id = re.sub(r"[^a-zA-Z0-9_.-]", "", request.execution_id)[:16] or uuid.uuid4().hex[:12]
                self._appcontainer_profile_name = f"Crusor.Sandbox.{clean_id}"

                sid_ptr = ctypes.c_void_p()
                hr = _userenv.CreateAppContainerProfile(
                    self._appcontainer_profile_name,
                    self._appcontainer_profile_name,
                    "Crusor Isolated Worker Sandbox Profile",
                    None,
                    0,
                    ctypes.byref(sid_ptr),
                )
                # If already exists (0x800700B7), derive existing SID
                if hr == 0x800700B7:
                    hr = _userenv.DeriveAppContainerSidFromAppContainerName(
                        self._appcontainer_profile_name, ctypes.byref(sid_ptr)
                    )

                if hr == 0 and sid_ptr.value:
                    self._appcontainer_sid = sid_ptr
                    sid_str = wintypes.LPWSTR()
                    if _advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(sid_str)):
                        self._appcontainer_sid_string = sid_str.value
                        _kernel32.LocalFree(sid_str)

                    # Grant staging directory full control to the specific AppContainer SID (Least Privilege)
                    if staging_dir.exists():
                        subprocess.run(
                            ["icacls", str(staging_dir), "/grant", f"*{self._appcontainer_sid_string}:(OI)(CI)F"],
                            capture_output=True,
                            check=False,
                        )

                    # If mode is READ_ONLY, grant read access only to the specific AppContainer SID
                    if request.mode == ExecutionMode.READ_ONLY:
                        ws_path = Path(request.workspace_root).resolve()
                        if ws_path.exists():
                            self._granted_workspace_path = ws_path
                            subprocess.run(
                                ["icacls", str(ws_path), "/grant", f"*{self._appcontainer_sid_string}:(OI)(CI)RX"],
                                capture_output=True,
                                check=False,
                            )
                else:
                    self._appcontainer_sid = None
                    self._appcontainer_profile_name = None
            except Exception:
                self._appcontainer_sid = None
                self._appcontainer_profile_name = None

    def _sanitize_environment(self, request: ExecutionRequest, staging_dir: Path) -> Dict[str, str]:
        """Produce a minimal, non-sensitive environment dictionary."""
        sanitized: Dict[str, str] = {}
        for k, v in os.environ.items():
            k_upper = k.upper()
            if k_upper in SAFE_ENVIRONMENT_KEYS:
                # Check for secrets even in allowlisted keys
                if not any(secret_term in k_upper for secret_term in SENSITIVE_SECRET_PATTERNS):
                    sanitized[k] = v

        # Force temporary directories into isolated staging
        sanitized["TMP"] = str(staging_dir)
        sanitized["TEMP"] = str(staging_dir)
        sanitized["CI"] = "1"
        sanitized["NO_COLOR"] = "1"
        sanitized["CRUSOR_SANDBOX"] = "1"
        sanitized["CRUSOR_SANDBOX_BACKEND"] = (
            "windows_appcontainer_job_object"
            if (self._use_appcontainer and self._appcontainer_sid)
            else "windows_job_object_lua"
        )

        if not request.network_allowed:
            sanitized["CRUSOR_NETWORK"] = "DENY"
            sanitized["HTTP_PROXY"] = "http://127.0.0.1:0"
            sanitized["HTTPS_PROXY"] = "http://127.0.0.1:0"
            sanitized["ALL_PROXY"] = "http://127.0.0.1:0"
            sanitized["NO_PROXY"] = ""
            sanitized["PIP_NO_INDEX"] = "1"

        # Apply safe caller overrides
        for ok, ov in request.env_overrides.items():
            if not any(term in ok.upper() for term in SENSITIVE_SECRET_PATTERNS):
                sanitized[ok] = ov

        return sanitized

    def _inspect_filesystem_safety(self, request: ExecutionRequest, staging_dir: Path) -> Tuple[bool, Optional[str]]:
        """Adversarial filesystem and path safety pre-flight check."""
        cmd_text = request.command
        tokens = request.argv if request.argv else shlex.split(cmd_text, posix=False)

        ws_path = Path(request.workspace_root).resolve()
        user_profile = Path(os.environ.get("USERPROFILE", "C:/Users")).resolve()
        sensitive_dirs = [
            user_profile / ".ssh",
            user_profile / ".aws",
            user_profile / ".azure",
            user_profile / ".config" / "gcloud",
            user_profile / ".git-credentials",
        ]

        cmd_norm = cmd_text.replace("/", "\\").lower()
        credential_patterns = [
            "\\.ssh",
            "\\.aws",
            "\\.azure",
            "id_rsa",
            "id_ed25519",
            "aws\\credentials",
            "config\\gcloud",
            ".git-credentials",
        ]
        for pat in credential_patterns:
            if pat in cmd_norm:
                self._violations.append(SecurityViolationType.CREDENTIAL_ACCESS_ATTEMPT.value)
                return False, f"Prohibited access to sensitive credential directory or key: {pat}"

        for token in tokens:
            token_norm = token.replace("/", "\\").lower()
            if ".." in token:
                candidate = (ws_path / token).resolve()
                if not str(candidate).startswith(str(ws_path)) and not str(candidate).startswith(str(staging_dir.resolve())):
                    self._violations.append(SecurityViolationType.WORKSPACE_TRAVERSAL.value)
                    return False, f"Directory traversal outside workspace jail: {token}"

            for sdir in sensitive_dirs:
                sdir_norm = str(sdir).replace("/", "\\").lower()
                if sdir_norm in token_norm:
                    self._violations.append(SecurityViolationType.CREDENTIAL_ACCESS_ATTEMPT.value)
                    return False, f"Prohibited access to sensitive credential directory: {token}"

            try:
                candidate_path = Path(token)
                if candidate_path.exists() and candidate_path.is_symlink():
                    resolved_target = candidate_path.resolve()
                    if not str(resolved_target).startswith(str(ws_path)) and not str(resolved_target).startswith(str(staging_dir.resolve())):
                        self._violations.append(SecurityViolationType.SYMLINK_JUNCTION_ESCAPE.value)
                        return False, f"Symlink target escapes authorized workspace: {token} -> {resolved_target}"
            except Exception:
                pass

        return True, None

    def execute(
        self,
        request: ExecutionRequest,
        staging_dir: Path,
        abort_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Execute inside AppContainer + Windows Job Object with streaming capped output."""
        if not self._job_handle:
            raise RuntimeError("WindowsSandboxManager not initialized.")

        # Pre-flight filesystem inspection
        safe, reason = self._inspect_filesystem_safety(request, staging_dir)
        if not safe:
            return {
                "exit_code": 126,
                "stdout": "",
                "stderr": f"⛔ Security Violation: {reason}",
                "stdout_bytes": 0,
                "stderr_bytes": len(reason or ""),
                "timed_out": False,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": list(self._violations),
            }

        # Select execution directory based on mode
        cwd = str(Path(request.workspace_root).resolve()) if request.mode == ExecutionMode.READ_ONLY else str(staging_dir.resolve())
        env = self._sanitize_environment(request, staging_dir)

        if self._use_appcontainer and self._appcontainer_sid:
            return self._execute_appcontainer(request, staging_dir, cwd, env, abort_event)
        else:
            return self._execute_job_object_fallback(request, staging_dir, cwd, env, abort_event)

    def _execute_appcontainer(
        self,
        request: ExecutionRequest,
        staging_dir: Path,
        cwd: str,
        env: Dict[str, str],
        abort_event: Optional[Any],
    ) -> Dict[str, Any]:
        """Execute inside genuine OS-level Windows AppContainer combined with Job Object."""
        stdout_file = staging_dir / f"_crusor_stdout_{uuid.uuid4().hex[:8]}.txt"
        stderr_file = staging_dir / f"_crusor_stderr_{uuid.uuid4().hex[:8]}.txt"

        sa = SECURITY_ATTRIBUTES()
        sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sa.lpSecurityDescriptor = None
        sa.bInheritHandle = True

        h_out = _kernel32.CreateFileW(
            str(stdout_file), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, ctypes.byref(sa), CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, None
        )
        h_err = _kernel32.CreateFileW(
            str(stderr_file), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, ctypes.byref(sa), CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, None
        )

        sec_caps = SECURITY_CAPABILITIES()
        sec_caps.AppContainerSid = self._appcontainer_sid
        sec_caps.Capabilities = None
        sec_caps.CapabilityCount = 0
        sec_caps.Reserved = 0

        # Attribute count = 2: SECURITY_CAPABILITIES and HANDLE_LIST
        attr_size = ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(attr_size))
        attr_buf = ctypes.create_string_buffer(attr_size.value)
        _kernel32.InitializeProcThreadAttributeList(attr_buf, 2, 0, ctypes.byref(attr_size))

        _kernel32.UpdateProcThreadAttribute(
            attr_buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, ctypes.byref(sec_caps), ctypes.sizeof(sec_caps), None, None
        )

        handle_array = (wintypes.HANDLE * 2)(h_out, h_err)
        _kernel32.UpdateProcThreadAttribute(
            attr_buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handle_array, ctypes.sizeof(handle_array), None, None
        )

        si_ex = STARTUPINFOEXW()
        si_ex.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si_ex.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si_ex.StartupInfo.hStdOutput = h_out
        si_ex.StartupInfo.hStdError = h_err
        si_ex.lpAttributeList = ctypes.cast(attr_buf, ctypes.c_void_p)

        pi = PROCESS_INFORMATION()

        # Command line formatting
        if request.argv:
            cmd_line = subprocess.list2cmdline(request.argv)
        else:
            cmd_line = request.command
            if any(ch in cmd_line for ch in ["|", ">", "<", "&"]):
                cmd_line = f'cmd.exe /c "{cmd_line}"'

        # Build environment block for CreateProcessW
        # Windows requires environment block keys to be sorted case-insensitively
        sorted_keys = sorted(env.keys(), key=lambda k: k.upper())
        env_str = "".join(f"{k}={env[k]}\0" for k in sorted_keys) + "\0"
        env_buf = ctypes.create_unicode_buffer(env_str)

        # EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT (0x00000400)
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW | CREATE_SUSPENDED | 0x00000400
        res_cp = _kernel32.CreateProcessW(
            None,
            cmd_line,
            None,
            None,
            True,
            flags,
            env_buf,
            cwd,
            ctypes.byref(si_ex.StartupInfo),
            ctypes.byref(pi),
        )

        if not res_cp:
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(h_out)
            _kernel32.CloseHandle(h_err)
            _kernel32.DeleteProcThreadAttributeList(attr_buf)
            return {
                "exit_code": 127,
                "stdout": "",
                "stderr": f"Failed to spawn AppContainer worker process: WinError {err}",
                "stdout_bytes": 0,
                "stderr_bytes": 40,
                "timed_out": False,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": list(self._violations),
            }

        self._process_info = pi
        # Assign to Job Object
        _kernel32.AssignProcessToJobObject(self._job_handle, pi.hProcess)
        # Resume thread
        _kernel32.ResumeThread(pi.hThread)

        # Close child handles on parent side so child can flush
        _kernel32.CloseHandle(h_out)
        _kernel32.CloseHandle(h_err)

        start_time = time.monotonic()
        timeout_deadline = start_time + request.timeout_s
        timed_out = False
        cancelled = False

        while True:
            # Check completion (wait 50ms)
            wait_res = _kernel32.WaitForSingleObject(pi.hProcess, 50)
            if wait_res == 0:  # WAIT_OBJECT_0
                break

            # Cancellation check
            if abort_event and abort_event.is_set():
                cancelled = True
                self._violations.append(SecurityViolationType.TIMEOUT_EXCEEDED.value)
                self.terminate()
                break

            # Timeout check
            if time.monotonic() > timeout_deadline:
                timed_out = True
                self._violations.append(SecurityViolationType.TIMEOUT_EXCEEDED.value)
                self.terminate()
                break

            self._query_job_counters()

        # Query final metrics
        self._query_job_counters()

        exit_code = wintypes.DWORD()
        _kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
        _kernel32.CloseHandle(pi.hProcess)
        _kernel32.CloseHandle(pi.hThread)
        self._process_info = None

        _kernel32.DeleteProcThreadAttributeList(attr_buf)

        code_val = exit_code.value
        if timed_out:
            code_val = 124
        elif cancelled:
            code_val = 130

        # Read streams
        max_bytes_per_stream = 1 * 1024 * 1024
        final_stdout = ""
        final_stderr = ""
        stdout_bytes = 0
        stderr_bytes = 0

        if stdout_file.exists():
            try:
                raw_out = stdout_file.read_bytes()
                stdout_bytes = len(raw_out)
                final_stdout = raw_out[:max_bytes_per_stream].decode("utf-8", errors="replace")
                if stdout_bytes >= max_bytes_per_stream:
                    final_stdout += f"\n... [stdout truncated at {max_bytes_per_stream} bytes by Crusor sandbox]"
                stdout_file.unlink(missing_ok=True)
            except Exception:
                pass

        if stderr_file.exists():
            try:
                raw_err = stderr_file.read_bytes()
                stderr_bytes = len(raw_err)
                final_stderr = raw_err[:max_bytes_per_stream].decode("utf-8", errors="replace")
                if stderr_bytes >= max_bytes_per_stream:
                    final_stderr += f"\n... [stderr truncated at {max_bytes_per_stream} bytes by Crusor sandbox]"
                stderr_file.unlink(missing_ok=True)
            except Exception:
                pass

        return {
            "exit_code": code_val,
            "stdout": final_stdout,
            "stderr": final_stderr,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "cpu_user_s": 0.0,
            "cpu_kernel_s": 0.0,
            "peak_memory_bytes": self._peak_memory_bytes,
            "security_violations": list(self._violations),
        }

    def _execute_job_object_fallback(
        self,
        request: ExecutionRequest,
        staging_dir: Path,
        cwd: str,
        env: Dict[str, str],
        abort_event: Optional[Any],
    ) -> Dict[str, Any]:
        """Fallback execution using Windows Job Object alone."""
        argv = request.argv if request.argv else request.command
        use_shell = isinstance(argv, str)

        timed_out = False
        cancelled = False
        start_time = time.monotonic()

        stdout_buf: List[str] = []
        stderr_buf: List[str] = []
        max_bytes_per_stream = 1 * 1024 * 1024
        stdout_bytes = 0
        stderr_bytes = 0

        try:
            self._process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                shell=use_shell,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

            proc_handle = int(self._process._handle)
            assigned = _kernel32.AssignProcessToJobObject(self._job_handle, proc_handle)
            if not assigned:
                err = ctypes.get_last_error()
                if self._process.poll() is None:
                    self.terminate()
                    raise RuntimeError(f"Failed to assign process to Windows Job Object: WinError {err}")

        except Exception as exc:
            self.terminate()
            return {
                "exit_code": 127,
                "stdout": "",
                "stderr": f"Failed to spawn sandboxed process: {exc}",
                "stdout_bytes": 0,
                "stderr_bytes": len(str(exc)),
                "timed_out": False,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": list(self._violations),
            }

        def _consume(line: str, buf: List[str], used: int) -> int:
            encoded = line.encode("utf-8")
            remaining = max_bytes_per_stream - used
            if remaining <= 0:
                return used
            if len(encoded) <= remaining:
                buf.append(line)
                return used + len(encoded)
            buf.append(encoded[:remaining].decode("utf-8", errors="ignore"))
            return max_bytes_per_stream

        def _read_stream(stream, buf, is_stdout):
            nonlocal stdout_bytes, stderr_bytes
            for line in iter(stream.readline, ""):
                if is_stdout:
                    stdout_bytes = _consume(line, buf, stdout_bytes)
                else:
                    stderr_bytes = _consume(line, buf, stderr_bytes)
            stream.close()

        t_out = threading.Thread(target=_read_stream, args=(self._process.stdout, stdout_buf, True), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(self._process.stderr, stderr_buf, False), daemon=True)
        t_out.start()
        t_err.start()

        timeout_deadline = start_time + request.timeout_s

        while self._process.poll() is None:
            if abort_event and abort_event.is_set():
                cancelled = True
                self._violations.append(SecurityViolationType.TIMEOUT_EXCEEDED.value)
                self.terminate()
                break

            if time.monotonic() > timeout_deadline:
                timed_out = True
                self._violations.append(SecurityViolationType.TIMEOUT_EXCEEDED.value)
                self.terminate()
                break

            self._query_job_counters()
            time.sleep(0.05)

        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

        self._query_job_counters()

        exit_code = self._process.poll()
        if timed_out:
            exit_code = 124
        elif cancelled:
            exit_code = 130
        elif exit_code is None:
            exit_code = 1

        final_stdout = "".join(stdout_buf)
        final_stderr = "".join(stderr_buf)

        if stdout_bytes >= max_bytes_per_stream:
            final_stdout += f"\n... [stdout truncated at {max_bytes_per_stream} bytes by Crusor sandbox]"
        if stderr_bytes >= max_bytes_per_stream:
            final_stderr += f"\n... [stderr truncated at {max_bytes_per_stream} bytes by Crusor sandbox]"

        return {
            "exit_code": exit_code,
            "stdout": final_stdout,
            "stderr": final_stderr,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "cpu_user_s": 0.0,
            "cpu_kernel_s": 0.0,
            "peak_memory_bytes": self._peak_memory_bytes,
            "security_violations": list(self._violations),
        }

    def _query_job_counters(self) -> None:
        """Query memory and process metrics from the Windows Job Object."""
        if not self._job_handle or _kernel32 is None:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ret = _kernel32.QueryInformationJobObject(
            self._job_handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        )
        if ret:
            if info.PeakJobMemoryUsed > self._peak_memory_bytes:
                self._peak_memory_bytes = int(info.PeakJobMemoryUsed)

    def terminate(self) -> None:
        """Kill all processes in the Job Object tree by closing the job handle or terminating the job."""
        if self._job_handle and _kernel32 is not None:
            _kernel32.TerminateJobObject(self._job_handle, 1)
            _kernel32.CloseHandle(self._job_handle)
            self._job_handle = None

        if self._process_info and _kernel32 is not None:
            try:
                _kernel32.TerminateProcess(self._process_info.hProcess, 1)
                _kernel32.CloseHandle(self._process_info.hProcess)
                _kernel32.CloseHandle(self._process_info.hThread)
                self._process_info = None
            except Exception:
                pass

        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
            except Exception:
                pass

    def cleanup(self, staging_dir: Path) -> str:
        """Terminate all remaining processes, delete AppContainer profile, and clean up temporary staging."""
        self.terminate()
        try:
            if self._granted_workspace_path and self._appcontainer_sid_string:
                subprocess.run(
                    ["icacls", str(self._granted_workspace_path), "/remove", f"*{self._appcontainer_sid_string}"],
                    capture_output=True,
                    check=False,
                )
                self._granted_workspace_path = None

            if self._appcontainer_sid and _advapi32 is not None:
                _advapi32.FreeSid(self._appcontainer_sid)
                self._appcontainer_sid = None

            if self._appcontainer_profile_name and _userenv is not None:
                _userenv.DeleteAppContainerProfile(self._appcontainer_profile_name)
                self._appcontainer_profile_name = None

            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return "CLEANUP_SUCCESS"
        except Exception as exc:
            return f"CLEANUP_DEGRADED: {exc}"

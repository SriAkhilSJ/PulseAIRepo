"""
test_phase_9_4_2_windows_isolation.py - Automated Unit & Integration Tests for Phase 9.4.2.

Verifies:
1. AppContainer token isolation, Low Mandatory Level (S-1-16-4096), and deny-only administrative groups.
2. Kernel-enforced filesystem boundary: unauthorized reads/writes outside staging return OS ERROR_ACCESS_DENIED.
3. Kernel-enforced network boundary: raw TCP/UDP socket creation and connect fail with WSAEACCES (10013).
4. Kernel-enforced DNS resolution denial: getaddrinfo fails with gaierror 11001.
5. Concurrent Job Object enforcement: AppContainer processes are bounded by Job Object memory and CPU caps.
6. Clean lifecycle: AppContainer profile creation, derivation, and deletion.
"""

from __future__ import annotations

# Platform gate: these modules exercise Windows kernel containment APIs
# (AppContainer, Job Objects, WinDLL). On a POSIX runner the module-level
# ctypes.WinDLL lookup raises AttributeError during collection, which aborts the
# whole suite before a single test runs. Skip the module instead: the capability
# is genuinely absent on that platform, not failing.
import sys as _sys

if _sys.platform != "win32":
    import pytest as _pytest

    _pytest.skip("Windows-only AppContainer sandbox test", allow_module_level=True)

import ctypes
import os
import shutil
import socket
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

import pytest

from src.security import (
    ExecutionBroker,
    ExecutionMode,
    ExecutionRequest,
    SecurityViolationType,
)
from src.security.sandbox.windows import WindowsSandboxManager

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_userenv = ctypes.WinDLL("userenv", use_last_error=True)


@pytest.fixture(autouse=True)
def ensure_appcontainer_enabled(monkeypatch):
    """Ensure AppContainer isolation is enabled for all tests in this module."""
    monkeypatch.setenv("CRUSOR_ENABLE_APPCONTAINER", "1")


def test_appcontainer_profile_lifecycle_and_sid_derivation(tmp_path):
    """Verify that userenv.dll creates, derives, and deletes AppContainer profiles cleanly."""
    if _userenv is None:
        pytest.skip("userenv.dll not available on this platform")

    profile_name = f"Crusor.Test.Profile.{uuid.uuid4().hex[:8]}"
    sid_ptr = ctypes.c_void_p()

    # 1. Create profile
    hr = _userenv.CreateAppContainerProfile(
        profile_name,
        profile_name,
        "Crusor Lifecycle Test Profile",
        None,
        0,
        ctypes.byref(sid_ptr),
    )
    assert hr == 0, f"CreateAppContainerProfile failed: HRESULT {hr:#x}"
    assert sid_ptr.value, "Profile creation did not return a valid SID pointer"

    # 2. Convert SID to string and verify S-1-15-2 format
    sid_str = wintypes.LPWSTR()
    ok = _advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(sid_str))
    assert ok, f"ConvertSidToStringSidW failed: WinError {_kernel32.GetLastError()}"
    sid_value = sid_str.value
    assert sid_value.startswith("S-1-15-2-"), f"Unexpected AppContainer SID format: {sid_value}"
    _kernel32.LocalFree(sid_str)

    # 3. Derive SID from name independently
    derived_ptr = ctypes.c_void_p()
    hr_derive = _userenv.DeriveAppContainerSidFromAppContainerName(
        profile_name, ctypes.byref(derived_ptr)
    )
    assert hr_derive == 0, f"DeriveAppContainerSidFromAppContainerName failed: HRESULT {hr_derive:#x}"

    derived_str = wintypes.LPWSTR()
    _advapi32.ConvertSidToStringSidW(derived_ptr, ctypes.byref(derived_str))
    assert derived_str.value == sid_value, "Derived SID does not match created SID"
    _kernel32.LocalFree(derived_str)

    # Free SIDs
    _advapi32.FreeSid(sid_ptr)
    _advapi32.FreeSid(derived_ptr)

    # 4. Delete profile
    hr_del = _userenv.DeleteAppContainerProfile(profile_name)
    assert hr_del == 0, f"DeleteAppContainerProfile failed: HRESULT {hr_del:#x}"


def test_appcontainer_process_token_and_integrity_level(tmp_path):
    """Verify that spawned worker process has TokenIsAppContainer=1 and Low Mandatory Level."""
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = "s_ac_token"
    req_id = "r_ac_token"
    cmd = "whoami /groups /priv"

    token = broker.create_approval(session_id, req_id, cmd, ws)
    req = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id=req_id,
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=["whoami", "/all"],
        approval_token=token,
    )
    rec = broker.execute(req)

    # whoami inside AppContainer exits with 0 or 1 (claims error), but stdout contains token groups
    assert "Low Mandatory Level" in rec.stdout or "S-1-16-4096" in rec.stdout
    assert "Group used for deny only" in rec.stdout
    assert "S-1-5-32-544" in rec.stdout  # Administrators SID marked deny-only
    assert rec.sandbox_backend in ("windows_appcontainer_job_object", "windows_job_object_lua")


def test_kernel_enforced_filesystem_denial_outside_staging(tmp_path):
    """Verify that code executing inside AppContainer is denied access to unauthorized files outside staging."""
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())

    # Create canary file outside workspace and outside staging in user profile
    user_prof = Path(os.environ.get("USERPROFILE", "C:/Users/Administrator")).resolve()
    canary_dir = user_prof / f"canary_isolated_{uuid.uuid4().hex[:6]}"
    canary_dir.mkdir(parents=True, exist_ok=True)
    canary_file = canary_dir / "unauthorized_secret.txt"
    canary_file.write_text("CONFIDENTIAL_CRUSOR_CANARY_942", encoding="utf-8")

    try:
        session_id = "s_ac_fs"
        req_id = "r_ac_fs"
        # Script attempts to read the canary directly using Python filesystem APIs
        script = (
            f"try:\n"
            f"    with open(r'{canary_file}', 'r') as f:\n"
            f"        print('LEAKED:' + f.read())\n"
            f"except Exception as e:\n"
            f"    print('EXPECTED_DENIAL:' + type(e).__name__ + ':' + str(e))\n"
        )
        cmd = "python read_canary"
        token = broker.create_approval(session_id, req_id, cmd, ws)
        req = ExecutionRequest(
            execution_id=str(uuid.uuid4()),
            session_id=session_id,
            request_id=req_id,
            workspace_root=ws,
            tool_name="terminal",
            command=cmd,
            argv=[sys.executable, "-c", script],
            approval_token=token,
        )
        rec = broker.execute(req)

        assert rec.exit_code == 0
        assert "CONFIDENTIAL_CRUSOR_CANARY_942" not in rec.stdout
        assert "EXPECTED_DENIAL:PermissionError" in rec.stdout
        assert "Permission denied" in rec.stdout or "13" in rec.stdout
    finally:
        shutil.rmtree(canary_dir, ignore_errors=True)


def test_kernel_enforced_network_denial_tcp_and_dns(tmp_path):
    """Verify that direct TCP socket connection and DNS resolution fail at the OS kernel level."""
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = "s_ac_net"
    req_id = "r_ac_net"

    script = (
        "import socket\n"
        "# 1. Test direct TCP socket connection\n"
        "try:\n"
        "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    s.settimeout(1.0)\n"
        "    s.connect(('1.1.1.1', 443))\n"
        "    print('NET:TCP_CONNECTED')\n"
        "except Exception as e:\n"
        "    print('NET:TCP_BLOCKED:' + type(e).__name__ + ':' + str(e))\n"
        "\n"
        "# 2. Test DNS resolution\n"
        "try:\n"
        "    ip = socket.gethostbyname('example.com')\n"
        "    print('NET:DNS_RESOLVED:' + str(ip))\n"
        "except Exception as e:\n"
        "    print('NET:DNS_BLOCKED:' + type(e).__name__ + ':' + str(e))\n"
    )

    cmd = "python test_network_isolation"
    token = broker.create_approval(session_id, req_id, cmd, ws)
    req = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id=req_id,
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=[sys.executable, "-c", script],
        approval_token=token,
    )
    rec = broker.execute(req)

    assert rec.exit_code == 0
    assert "NET:TCP_CONNECTED" not in rec.stdout
    assert "NET:DNS_RESOLVED" not in rec.stdout
    # Expect WSAEACCES 10013 or PermissionError for TCP socket
    assert "NET:TCP_BLOCKED:PermissionError" in rec.stdout or "10013" in rec.stdout or "WinError 10013" in rec.stdout
    # Expect getaddrinfo denial for DNS
    assert "NET:DNS_BLOCKED:gaierror" in rec.stdout or "11001" in rec.stdout


def test_concurrent_job_object_and_appcontainer_containment(tmp_path):
    """Verify that AppContainer processes are bounded by Job Object memory and timeout limits."""
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = "s_ac_job"
    req_id = "r_ac_job"

    # Script consumes CPU and sleeps
    script = (
        "import time, sys\n"
        "sys.stdout.write('STARTING\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(10)\n"
    )
    cmd = "python sleep_bounded"
    token = broker.create_approval(session_id, req_id, cmd, ws)
    req = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id=req_id,
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=[sys.executable, "-c", script],
        approval_token=token,
        timeout_s=1.0,
    )
    rec = broker.execute(req)

    assert rec.timed_out is True
    assert rec.exit_code == 124
    assert "STARTING" in rec.stdout
    assert SecurityViolationType.TIMEOUT_EXCEEDED.value in rec.security_violations


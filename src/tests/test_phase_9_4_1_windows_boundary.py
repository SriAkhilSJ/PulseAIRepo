"""
test_phase_9_4_1_windows_boundary.py - Automated Unit & Integration Tests for Phase 9.4.1.

Verifies:
1. Job Object limits and CPU rate control via Win32 query APIs.
2. Security identity, token SIDs, and integrity level telemetry.
3. Filesystem canary protection (Application Policy vs OS DACL distinction).
4. Direct socket vs proxy network isolation distinction.
5. Crash recovery and cancellation termination.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from src.security import (
    ExecutionBroker,
    ExecutionMode,
    ExecutionRequest,
    SecurityViolationType,
)
from src.security.sandbox.windows import (
    WindowsSandboxManager,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOBOBJECT_CPU_RATE_CONTROL_INFORMATION,
    JobObjectExtendedLimitInformation,
    JobObjectCpuRateControlInformation,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_JOB_MEMORY,
)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


@pytest.fixture(autouse=True)
def force_phase_9_4_1_job_object_mode(monkeypatch):
    """Force Job Object fallback mode to verify Phase 9.4.1 baseline boundaries."""
    monkeypatch.setenv("CRUSOR_ENABLE_APPCONTAINER", "0")


def test_job_object_limits_queried_accurately():
    """Verify Job Object limit flags and CPU rate control directly via kernel32 APIs."""
    job = _kernel32.CreateJobObjectW(None, None)
    assert job, f"CreateJobObjectW failed: WinError {_kernel32.GetLastError()}"

    ext_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limit_flags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_JOB_MEMORY
    )
    ext_info.BasicLimitInformation.LimitFlags = limit_flags
    ext_info.BasicLimitInformation.ActiveProcessLimit = 10
    ext_info.JobMemoryLimit = 512 * 1024 * 1024

    res1 = _kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(ext_info),
        ctypes.sizeof(ext_info),
    )
    assert res1, f"SetInformationJobObject failed: WinError {_kernel32.GetLastError()}"

    # Configure CPU rate control (80%)
    cpu_info = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
    cpu_info.ControlFlags = 0x00000001 | 0x00000004
    cpu_info.CpuRate = 8000
    res2 = _kernel32.SetInformationJobObject(
        job,
        JobObjectCpuRateControlInformation,
        ctypes.byref(cpu_info),
        ctypes.sizeof(cpu_info),
    )
    assert res2, f"SetInformationJobObject CPU failed: WinError {_kernel32.GetLastError()}"

    # Query back
    q_ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    q_res1 = _kernel32.QueryInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(q_ext),
        ctypes.sizeof(q_ext),
        None,
    )
    assert q_res1

    q_cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
    q_res2 = _kernel32.QueryInformationJobObject(
        job,
        JobObjectCpuRateControlInformation,
        ctypes.byref(q_cpu),
        ctypes.sizeof(q_cpu),
        None,
    )
    assert q_res2

    _kernel32.CloseHandle(job)

    flags = q_ext.BasicLimitInformation.LimitFlags
    assert flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    assert flags & JOB_OBJECT_LIMIT_JOB_MEMORY
    assert q_ext.BasicLimitInformation.ActiveProcessLimit == 10
    assert q_ext.JobMemoryLimit == 512 * 1024 * 1024
    assert q_cpu.CpuRate == 8000


def test_security_identity_tokens_and_integrity(tmp_path):
    """Verify whoami /all execution telemetry inside sandboxed worker."""
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = "s_ident_test"
    req_id = "r_ident_test"
    cmd = "whoami /all"

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
    assert rec.exit_code == 0
    assert "USER INFORMATION" in rec.stdout
    assert "S-1-5-" in rec.stdout
    assert "Medium Mandatory Level" in rec.stdout


def test_filesystem_canary_distinction(tmp_path):
    """
    Verify distinction between Broker application denial and direct OS file open.
    
    1. Paths with explicit traversal or credential keywords (.ssh, .aws) are DENIED
       by Broker Application Policy (exit_code 126).
    2. Arbitrary external files without keywords demonstrate that the OS permits read
       under Medium Integrity user DACL (exit_code 0), proving why OS isolation is PARTIAL.
    """
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())

    # Case 1: Traversal escape -> Intercepted by Broker Application Policy
    cmd_trav = "python ../../../outside.py"
    token_trav = broker.create_approval("s_can", "r_can_trav", cmd_trav, ws)
    req_trav = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id="s_can",
        request_id="r_can_trav",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd_trav,
        argv=[sys.executable, "../../../outside.py"],
        approval_token=token_trav,
    )
    rec_trav = broker.execute(req_trav)
    assert rec_trav.exit_code == 126
    assert SecurityViolationType.WORKSPACE_TRAVERSAL.value in rec_trav.security_violations

    # Case 2: External canary file outside workspace
    outside_dir = tmp_path.parent / f"canary_dir_{uuid.uuid4().hex[:6]}"
    outside_dir.mkdir(parents=True, exist_ok=True)
    canary = outside_dir / "secret_canary.txt"
    canary.write_text("CONFIDENTIAL_CANARY_DATA", encoding="utf-8")

    cmd_can = f"type {canary}"
    token_can = broker.create_approval("s_can", "r_can_direct", cmd_can, ws)
    req_can = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id="s_can",
        request_id="r_can_direct",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd_can,
        argv=["cmd.exe", "/c", cmd_can],
        approval_token=token_can,
    )
    rec_can = broker.execute(req_can)
    # The OS permits read access because the process executes at Medium Integrity
    assert rec_can.exit_code == 0
    assert "CONFIDENTIAL_CANARY_DATA" in rec_can.stdout
    # This proves the empirical distinction required by Phase 9.4.1 Task 3

    # Clean up canary
    shutil.rmtree(outside_dir, ignore_errors=True)


def test_direct_socket_networking_proves_partial_verdict(tmp_path):
    """Demonstrate that direct TCP sockets connect despite proxy deny, proving PARTIAL network isolation."""
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())

    # Ephemeral loopback server
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _srv():
        try:
            conn, _ = srv.accept()
            conn.sendall(b"PONG")
            conn.close()
        except Exception:
            pass
        finally:
            srv.close()

    threading.Thread(target=_srv, daemon=True).start()

    cmd = "sock_test"
    token = broker.create_approval("s_sock", "r_sock", cmd, ws)
    script = (
        f"import socket\n"
        f"s = socket.create_connection(('127.0.0.1', {port}), timeout=1)\n"
        f"data = s.recv(4)\n"
        f"print('RECV:' + data.decode())\n"
        f"s.close()\n"
    )
    req = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id="s_sock",
        request_id="r_sock",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=[sys.executable, "-c", script],
        approval_token=token,
        network_allowed=False,
    )
    rec = broker.execute(req)
    # Direct socket succeeds because Windows kernel lacks unprivileged packet filtering
    assert "RECV:PONG" in rec.stdout
    # This test provides the empirical proof why network denial must remain PARTIAL


def test_crash_recovery_and_cancellation(tmp_path):
    """Test mid-run cancellation triggering immediate Job Object process tree termination."""
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())

    cmd = "long_job"
    token = broker.create_approval("s_rec", "r_rec", cmd, ws)
    abort_event = threading.Event()

    def _cancel():
        time.sleep(0.2)
        abort_event.set()

    threading.Thread(target=_cancel, daemon=True).start()

    req = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id="s_rec",
        request_id="r_rec",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=[sys.executable, "-c", "import time; time.sleep(15)"],
        approval_token=token,
        timeout_s=15.0,
    )
    rec = broker.execute(req, abort_event=abort_event)
    assert rec.cancelled is True
    assert rec.duration_s < 2.0

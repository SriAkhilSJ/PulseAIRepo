"""Windows-only runtime qualification for the execution sandbox.

Safety:
  * Job Object tests use only disposable temp directories and harmless children.
  * AppContainer tests are opt-in (CRUSOR_RUN_APPCONTAINER_RUNTIME=1).
  * AppContainer tests monkeypatch the WindowStation/Desktop ACL helper to a
    no-op, so no machine-level ACL is modified.
  * A disposable temp directory is explicitly denied to the disposable
    AppContainer SID to prove kernel DACL enforcement.
  * No existing machine object is changed, and no provider/network service is
    contacted.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

import pytest

from src.security import ExecutionMode, ExecutionRequest
from src.security.sandbox.windows import (
    JOBOBJECT_CPU_RATE_CONTROL_INFORMATION,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JobObjectCpuRateControlInformation,
    JobObjectExtendedLimitInformation,
    WindowsSandboxManager,
    _kernel32,
)

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows-only runtime qualification",
)

CHILD_PY = getattr(sys, "_base_executable", sys.executable)
RUN_APPCONTAINER = os.environ.get("CRUSOR_RUN_APPCONTAINER_RUNTIME") == "1"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25
TokenIsAppContainer = 29

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.IsProcessInJob.restype = wintypes.BOOL
kernel32.IsProcessInJob.argtypes = [
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.BOOL),
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
advapi32.ConvertSidToStringSidW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.LPWSTR),
]


def _request(
    workspace: Path,
    argv: list[str],
    *,
    max_processes: int = 4,
    max_memory_mb: int = 256,
    timeout_s: float = 20.0,
    mode: ExecutionMode = ExecutionMode.PROPOSED_MUTATION,
) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=f"qual-{uuid.uuid4().hex[:10]}",
        session_id="phase1.4",
        request_id=f"req-{uuid.uuid4().hex[:10]}",
        workspace_root=str(workspace),
        tool_name="runtime_qualification",
        command=" ".join(argv),
        argv=argv,
        mode=mode,
        timeout_s=timeout_s,
        max_memory_mb=max_memory_mb,
        max_processes=max_processes,
        network_allowed=False,
    )


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    staging = tmp_path / "staging"
    workspace.mkdir(parents=True)
    staging.mkdir(parents=True)
    return workspace, staging


def _limits(handle) -> dict:
    ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
    _kernel32.QueryInformationJobObject(
        handle,
        JobObjectExtendedLimitInformation,
        ctypes.byref(ext),
        ctypes.sizeof(ext),
        None,
    )
    _kernel32.QueryInformationJobObject(
        handle,
        JobObjectCpuRateControlInformation,
        ctypes.byref(cpu),
        ctypes.sizeof(cpu),
        None,
    )
    return {
        "limit_flags": int(ext.BasicLimitInformation.LimitFlags),
        "active_process_limit": int(ext.BasicLimitInformation.ActiveProcessLimit),
        "job_memory_limit": int(ext.JobMemoryLimit),
        "cpu_control_flags": int(cpu.ControlFlags),
        "cpu_rate": int(cpu.CpuRate),
    }


def _sid_to_string(sid) -> str | None:
    text = wintypes.LPWSTR()
    if advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        try:
            return text.value
        finally:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    return None


def _token_identity(token) -> dict:
    out: dict = {}
    value = wintypes.DWORD(0)
    size = wintypes.DWORD(0)
    if advapi32.GetTokenInformation(
        token,
        TokenIsAppContainer,
        ctypes.byref(value),
        ctypes.sizeof(value),
        ctypes.byref(size),
    ):
        out["is_appcontainer"] = bool(value.value)

    buffer = ctypes.create_string_buffer(256)
    if advapi32.GetTokenInformation(
        token,
        TokenIntegrityLevel,
        buffer,
        ctypes.sizeof(buffer),
        ctypes.byref(size),
    ):
        sid = ctypes.c_void_p.from_buffer(buffer).value
        out["integrity_sid"] = _sid_to_string(sid)
    return out


def _run_job_case(
    workspace: Path,
    staging: Path,
    argv: list[str],
    *,
    max_processes: int,
    max_memory_mb: int,
    timeout_s: float = 20.0,
) -> tuple[dict, dict]:
    manager = WindowsSandboxManager(use_appcontainer=False)
    request = _request(
        workspace,
        argv,
        max_processes=max_processes,
        max_memory_mb=max_memory_mb,
        timeout_s=timeout_s,
    )
    try:
        manager.initialize(request, staging)
        limits = _limits(manager._job_handle)
        result = manager.execute(request, staging)
        return result, limits
    finally:
        manager.cleanup(staging)


def test_job_object_limits_and_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, staging = _paths(tmp_path)
    code = (
        "import os;"
        "print('RUNTIME_OK');"
        "print('TMP=' + os.environ.get('TMP',''));"
        "print('OPENAI=' + os.environ.get('OPENAI_API_KEY','MISSING'));"
        "print('SANDBOX=' + os.environ.get('CRUSOR_SANDBOX','MISSING'))"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-PHASE14-RUNTIME-SECRET")
    result, limits = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=256,
    )
    assert result["exit_code"] == 0
    assert "RUNTIME_OK" in result["stdout"]
    assert f"TMP={staging}" in result["stdout"]
    assert "OPENAI=MISSING" in result["stdout"]
    assert "SANDBOX=1" in result["stdout"]
    assert limits["active_process_limit"] == 4
    assert limits["job_memory_limit"] == 256 * 1024 * 1024
    assert limits["limit_flags"] & 0x2000  # KILL_ON_JOB_CLOSE
    assert limits["limit_flags"] & 0x8  # ACTIVE_PROCESS
    assert limits["limit_flags"] & 0x200  # JOB_MEMORY
    assert limits["cpu_control_flags"] == 5
    assert limits["cpu_rate"] == 8000


def test_active_process_limit_denies_grandchild(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    code = (
        "import subprocess,sys,time,os;"
        "time.sleep(0.8);"
        "\ntry:\n"
        " subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/c','echo','grandchild'],"
        "capture_output=True,timeout=5);"
        " print('GRANDCHILD_OK')\n"
        "except OSError as e:\n"
        " print('GRANDCHILD_DENIED='+type(e).__name__+':winerror='+str(e.winerror))\n"
        "except BaseException as e:\n"
        " print('UNEXPECTED='+type(e).__name__)\n"
    )
    result, limits = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=1,
        max_memory_mb=256,
    )
    assert limits["active_process_limit"] == 1
    assert result["exit_code"] == 0
    assert "GRANDCHILD_DENIED=OSError:winerror=1816" in result["stdout"], result["stdout"]
    assert "GRANDCHILD_OK" not in result["stdout"]
    assert "UNEXPECTED=" not in result["stdout"]


def test_memory_limit_denies_large_allocation(tmp_path: Path) -> None:
    code = (
        "try:\n"
        " b=bytearray(128*1024*1024); print('MEMORY_OK')\n"
        "except BaseException as e:\n"
        " print('MEMORY_DENIED='+type(e).__name__)\n"
    )

    control_root = tmp_path / "control"
    control_root.mkdir()
    control_workspace, control_staging = _paths(control_root)
    control_result, control_limits = _run_job_case(
        control_workspace,
        control_staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=512,
    )
    assert control_limits["job_memory_limit"] == 512 * 1024 * 1024
    assert control_result["exit_code"] == 0
    assert "MEMORY_OK" in control_result["stdout"], control_result["stdout"]

    limited_root = tmp_path / "limited"
    limited_root.mkdir()
    workspace, staging = _paths(limited_root)
    result, limits = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=64,
    )
    assert limits["job_memory_limit"] == 64 * 1024 * 1024
    assert result["exit_code"] == 0
    assert "MEMORY_DENIED=MemoryError" in result["stdout"], result["stdout"]
    assert result["peak_memory_bytes"] > 0
    # The behavioral denial is observed. Peak accounting is recorded, not
    # asserted below the configured limit (Phase 1.4 observed ~140 MB).


def test_output_cap_is_strict_for_one_large_line(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    code = "import sys; sys.stdout.write('x' * 2000000)"
    result, _limits_out = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=256,
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1024 * 1024
    assert "truncated at" in result["stdout"]


def test_output_cap_multiple_lines(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    code = "import sys\nfor _ in range(30): sys.stdout.write('x' * 100000)"
    result, _limits_out = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=256,
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1024 * 1024
    assert "truncated at" in result["stdout"]


def test_output_cap_separate_streams(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    code = (
        "import sys;"
        "sys.stdout.buffer.write(b'x' * 1500000);"
        "sys.stdout.flush();"
        "sys.stderr.buffer.write(b'y' * 1500000);"
        "sys.stderr.flush()"
    )
    result, _limits_out = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=256,
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1024 * 1024
    assert result["stderr_bytes"] == 1024 * 1024
    assert "stdout truncated at" in result["stdout"]
    assert "stderr truncated at" in result["stderr"]


def test_output_cap_utf8_boundary(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    code = (
        "import sys;"
        "sys.stdout.buffer.write(b'a' * (1024*1024 - 2));"
        "sys.stdout.buffer.write('é'.encode('utf-8'));"
        "sys.stdout.buffer.write(b'z' * 100);"
        "sys.stdout.flush()"
    )
    result, _limits_out = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=256,
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1024 * 1024
    assert "é" in result["stdout"]
    assert "\ufffd" not in result["stdout"]
    assert "truncated at" in result["stdout"]


def test_output_cap_continuous_until_timeout(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    code = (
        "import sys\n"
        "while True:\n"
        " sys.stdout.write('x' * 1024)\n"
        " sys.stdout.flush()\n"
    )
    result, _limits_out = _run_job_case(
        workspace,
        staging,
        [CHILD_PY, "-c", code],
        max_processes=4,
        max_memory_mb=256,
        timeout_s=2.0,
    )
    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert result["stdout_bytes"] == 1024 * 1024
    assert "truncated at" in result["stdout"]


def test_terminate_kills_process_and_cleanup_removes_staging(
    tmp_path: Path,
) -> None:
    workspace, staging = _paths(tmp_path)
    manager = WindowsSandboxManager(use_appcontainer=False)
    request = _request(
        workspace,
        [CHILD_PY, "-c", "import time; time.sleep(30)"],
        timeout_s=60.0,
    )
    manager.initialize(request, staging)
    holder: dict = {}

    def run() -> None:
        holder["result"] = manager.execute(request, staging)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(1.0)
    child = manager._process
    assert child is not None
    manager.terminate()
    child.wait(timeout=5)
    thread.join(timeout=5)
    assert child.poll() is not None
    assert manager._job_handle is None
    assert manager.cleanup(staging) == "CLEANUP_SUCCESS"
    assert not staging.exists()


def test_filesystem_traversal_and_credential_preflight(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE_SECRET", encoding="utf-8")
    manager = WindowsSandboxManager(use_appcontainer=False)
    request = _request(
        workspace,
        [CHILD_PY, "-c", "print('SHOULD_NOT_RUN')"],
        mode=ExecutionMode.READ_ONLY,
    )
    manager.initialize(request, staging)
    try:
        traversal = ExecutionRequest(
            **{
                **request.__dict__,
                "command": r"type ..\outside.txt",
                "argv": [],
            }
        )
        result = manager.execute(traversal, staging)
        assert result["exit_code"] == 126
        assert "SHOULD_NOT_RUN" not in result["stdout"]
        assert "WORKSPACE_TRAVERSAL" in result["security_violations"]

        credential = ExecutionRequest(
            **{
                **request.__dict__,
                "command": r"type C:\Users\Administrator\.ssh\id_rsa",
                "argv": [],
            }
        )
        result = manager.execute(credential, staging)
        assert result["exit_code"] == 126
        assert "CREDENTIAL_ACCESS_ATTEMPT" in result["security_violations"]
    finally:
        manager.cleanup(staging)


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_token_is_low_integrity_and_in_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.security.sandbox.windows as windows

    workspace, staging = _paths(tmp_path)
    monkeypatch.setattr(
        windows,
        "_ensure_windowstation_desktop_access",
        lambda: True,
    )
    manager = WindowsSandboxManager(use_appcontainer=True)
    request = _request(
        workspace,
        ["cmd.exe", "/c", "for /l %i in (1,1,100000000) do @rem"],
        timeout_s=4.0,
    )
    holder: dict = {}
    try:
        manager.initialize(request, staging)
        assert manager.appcontainer_sid_str

        def run() -> None:
            holder["result"] = manager.execute(request, staging)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        deadline = time.time() + 10
        pi = None
        while time.time() < deadline:
            pi = manager._process_info
            if pi is not None and pi.dwProcessId:
                break
            time.sleep(0.05)
        assert pi is not None and pi.dwProcessId

        process = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            int(pi.dwProcessId),
        )
        assert process
        try:
            in_job = wintypes.BOOL(False)
            assert kernel32.IsProcessInJob(
                process,
                manager._job_handle,
                ctypes.byref(in_job),
            )
            assert in_job.value

            token = wintypes.HANDLE()
            assert advapi32.OpenProcessToken(
                process,
                TOKEN_QUERY,
                ctypes.byref(token),
            )
            try:
                identity = _token_identity(token)
                assert identity["is_appcontainer"] is True
                assert identity["integrity_sid"] == "S-1-16-4096"
            finally:
                kernel32.CloseHandle(token)
        finally:
            kernel32.CloseHandle(process)

        thread.join(timeout=15)
        result = holder["result"]
        assert result["timed_out"] is True
        assert result["exit_code"] == 124
        assert manager._job_handle is None
    finally:
        manager.cleanup(staging)


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_denies_disposable_denied_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.security.sandbox.windows as windows

    workspace, staging = _paths(tmp_path)
    denied = tmp_path / "denied"
    denied.mkdir()
    secret = denied / "secret.txt"
    secret.write_text("PHASE14_SECRET_VALUE", encoding="utf-8")
    target = denied / "poison.txt"
    monkeypatch.setattr(
        windows,
        "_ensure_windowstation_desktop_access",
        lambda: True,
    )
    manager = WindowsSandboxManager(use_appcontainer=True)
    request = _request(workspace, ["cmd.exe", "/c", "echo", "boot"])
    try:
        manager.initialize(request, staging)
        sid = manager.appcontainer_sid_str
        assert sid

        baseline = manager.execute(
            _request(
                workspace,
                ["cmd.exe", "/c", "echo", "APPCONTAINER_STARTED"],
            ),
            staging,
        )
        assert baseline["exit_code"] == 0
        assert "APPCONTAINER_STARTED" in baseline["stdout"]
        assert "Failed to spawn AppContainer worker process" not in baseline["stderr"]

        denied_acl = subprocess.run(
            ["icacls", str(denied), "/deny", f"*{sid}:(OI)(CI)(F)"],
            capture_output=True,
            text=True,
        )
        assert denied_acl.returncode == 0, denied_acl.stderr

        result = manager.execute(
            _request(workspace, ["cmd.exe", "/c", "type", str(secret)]),
            staging,
        )
        assert "PHASE14_SECRET_VALUE" not in result["stdout"]
        assert result["exit_code"] == 1
        assert "access is denied" in result["stderr"].lower()
        assert "Failed to spawn AppContainer worker process" not in result["stderr"]

        result = manager.execute(
            _request(
                workspace,
                ["cmd.exe", "/c", f"echo POISON > {target}"],
            ),
            staging,
        )
        assert not target.exists()
        assert result["exit_code"] == 1
        assert "access is denied" in result["stderr"].lower()
        assert "Failed to spawn AppContainer worker process" not in result["stderr"]
    finally:
        manager.cleanup(staging)

def _run_appcontainer_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command_builder,
    *,
    files: dict[str, bytes] | None = None,
    timeout_s: float = 20.0,
):
    import src.security.sandbox.windows as windows

    workspace, staging = _paths(tmp_path)
    for name, data in (files or {}).items():
        (workspace / name).write_bytes(data)
    monkeypatch.setattr(
        windows,
        "_ensure_windowstation_desktop_access",
        lambda: True,
    )
    manager = WindowsSandboxManager(use_appcontainer=True)
    request = _request(
        workspace,
        command_builder(workspace),
        timeout_s=timeout_s,
        mode=ExecutionMode.READ_ONLY,
    )
    try:
        manager.initialize(request, staging)
        assert manager.appcontainer_sid_str
        return manager.execute(request, staging)
    finally:
        manager.cleanup(staging)


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_output_cap_single_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_appcontainer_case(
        tmp_path,
        monkeypatch,
        lambda workspace: ["cmd.exe", "/c", "type", str(workspace / "big.txt")],
        files={"big.txt": b"x" * 2000000},
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1024 * 1024
    assert "truncated at" in result["stdout"]


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_output_cap_multiple_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"\n".join(b"x" * 200 for _ in range(20000))
    result = _run_appcontainer_case(
        tmp_path,
        monkeypatch,
        lambda workspace: ["cmd.exe", "/c", "type", str(workspace / "lines.txt")],
        files={"lines.txt": data},
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1024 * 1024
    assert "truncated at" in result["stdout"]


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_output_cap_separate_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_result = _run_appcontainer_case(
        tmp_path / "stdout",
        monkeypatch,
        lambda workspace: ["cmd.exe", "/c", "type", str(workspace / "out.txt")],
        files={"out.txt": b"o" * 1500000},
    )
    assert out_result["exit_code"] == 0
    assert out_result["stdout_bytes"] == 1024 * 1024
    assert "stdout truncated at" in out_result["stdout"]

    err_result = _run_appcontainer_case(
        tmp_path / "stderr",
        monkeypatch,
        lambda workspace: [
            "cmd.exe",
            "/c",
            f"type {workspace / 'err.txt'} 1>&2",
        ],
        files={"err.txt": b"e" * 1500000},
    )
    assert err_result["exit_code"] == 0
    assert err_result["stderr_bytes"] == 1024 * 1024
    assert "stderr truncated at" in err_result["stderr"]


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_output_cap_utf8_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"a" * (1024 * 1024 - 2) + "é".encode("utf-8") + b"z" * 100
    result = _run_appcontainer_case(
        tmp_path,
        monkeypatch,
        lambda workspace: ["cmd.exe", "/c", "type", str(workspace / "utf8.txt")],
        files={"utf8.txt": data},
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1024 * 1024
    assert "truncated at" in result["stdout"]


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_output_cap_continuous_until_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_appcontainer_case(
        tmp_path,
        monkeypatch,
        lambda workspace: [
            "cmd.exe",
            "/c",
            f'for /l %i in (1,1,100000000) do @type {workspace / "big.txt"}',
        ],
        files={"big.txt": b"x" * 2000000},
        timeout_s=3.0,
    )
    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert result["stdout_bytes"] == 1024 * 1024
    assert "truncated at" in result["stdout"]

def test_cancellation_stops_process(tmp_path: Path) -> None:
    workspace, staging = _paths(tmp_path)
    manager = WindowsSandboxManager(use_appcontainer=False)
    request = _request(
        workspace,
        [CHILD_PY, "-c", "import time; time.sleep(30)"],
        timeout_s=60.0,
    )
    manager.initialize(request, staging)
    abort = threading.Event()
    holder: dict = {}

    def run() -> None:
        holder["result"] = manager.execute(request, staging, abort_event=abort)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(1.0)
    abort.set()
    thread.join(timeout=10)
    assert thread.is_alive() is False
    result = holder["result"]
    assert result["cancelled"] is True
    assert result["exit_code"] == 130
    assert manager._process is not None
    assert manager._process.poll() is not None
    assert manager.cleanup(staging) == "CLEANUP_SUCCESS"


@pytest.mark.skipif(
    not RUN_APPCONTAINER,
    reason="set CRUSOR_RUN_APPCONTAINER_RUNTIME=1 to run AppContainer runtime tests",
)
def test_appcontainer_cancellation_stops_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.security.sandbox.windows as windows

    workspace, staging = _paths(tmp_path)
    monkeypatch.setattr(
        windows,
        "_ensure_windowstation_desktop_access",
        lambda: True,
    )
    manager = WindowsSandboxManager(use_appcontainer=True)
    request = _request(
        workspace,
        ["cmd.exe", "/c", "for /l %i in (1,1,100000000) do @rem"],
        timeout_s=60.0,
    )
    abort = threading.Event()
    holder: dict = {}

    def run() -> None:
        holder["result"] = manager.execute(request, staging, abort_event=abort)

    try:
        manager.initialize(request, staging)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        time.sleep(1.5)
        abort.set()
        thread.join(timeout=10)
        assert thread.is_alive() is False
        result = holder["result"]
        assert result["cancelled"] is True
        assert result["exit_code"] == 130
        assert manager._job_handle is None
    finally:
        manager.cleanup(staging)

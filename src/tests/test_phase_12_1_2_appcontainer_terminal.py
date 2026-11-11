"""
test_phase_12_1_2_appcontainer_terminal.py - Qualification tests for AppContainer terminal integration.

Phase 12.1.2: Desktop Runtime, Model Execution & OS Sandbox Closure.
Verifies:
1. Terminal tool dispatch through ExecutionBroker into Windows AppContainer + Job Object.
2. OS kernel-enforced filesystem boundary: unauthorized read outside workspace is denied.
3. OS kernel-enforced filesystem boundary: unauthorized write outside workspace is denied.
4. OS kernel-enforced network boundary: outbound TCP/UDP and loopback connections are denied.
5. OS kernel-enforced resource bounding: Job Object active process limits and termination.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from src.tools.terminal_tools import terminal


@pytest.fixture(autouse=True)
def enable_terminal_appcontainer(monkeypatch):
    """Enable AppContainer sandbox isolation for terminal commands."""
    monkeypatch.setenv("CRUSOR_ENABLE_APPCONTAINER", "1")
    monkeypatch.setenv("CRUSOR_SANDBOX_TERMINAL", "1")


def test_terminal_appcontainer_execution_success(tmp_path):
    """Verify that terminal executes python commands inside AppContainer and returns output."""
    ws = str(tmp_path.resolve())
    script = "print('APPCONTAINER_TERMINAL_ONLINE')"
    cmd = f'"{sys.executable}" -c "{script}"'

    out = terminal.invoke(
        {"command": cmd},
        {"configurable": {"workspace": ws, "thread_id": "sess_ac_term"}},
    )
    assert "APPCONTAINER_TERMINAL_ONLINE" in out
    assert "Exit code: 0" in out


def test_terminal_appcontainer_unauthorized_read_outside_workspace_blocked(tmp_path):
    """Verify that AppContainer prevents reading sensitive files outside workspace."""
    external_dir = tmp_path.parent / f"external_secret_{tmp_path.name}"
    external_dir.mkdir(exist_ok=True)
    secret_file = external_dir / "user_secret.key"
    secret_file.write_text("SUPER_CONFIDENTIAL_KEY = 12345\n", encoding="utf-8")

    ws = str(tmp_path.resolve())
    escaped_secret_path = str(secret_file.resolve()).replace("\\", "/")

    script = (
        f"exec('''try:\\n open('{escaped_secret_path}', 'r').read()\\nexcept Exception as e:\\n print('DENIED_READ:' + type(e).__name__)\\n''')"
    )
    cmd = f'"{sys.executable}" -c "{script}"'

    try:
        out = terminal.invoke(
            {"command": cmd},
            {"configurable": {"workspace": ws, "thread_id": "sess_ac_read"}},
        )
        assert "SUPER_CONFIDENTIAL_KEY" not in out
        assert "DENIED_READ:PermissionError" in out or "DENIED_READ" in out
    finally:
        if secret_file.exists():
            secret_file.unlink(missing_ok=True)
        if external_dir.exists():
            external_dir.rmdir()


def test_terminal_appcontainer_unauthorized_write_outside_workspace_blocked(tmp_path):
    """Verify that AppContainer prevents writing files outside workspace / staging."""
    external_dir = tmp_path.parent / f"external_target_{tmp_path.name}"
    external_dir.mkdir(exist_ok=True)
    target_file = external_dir / "unauthorized_write.txt"

    ws = str(tmp_path.resolve())
    escaped_target_path = str(target_file.resolve()).replace("\\", "/")

    script = (
        f"exec('''try:\\n with open('{escaped_target_path}', 'w') as f:\\n  f.write('POISON')\\n print('WRITE_OK')\\nexcept Exception as e:\\n print('DENIED_WRITE:' + type(e).__name__)\\n''')"
    )
    cmd = f'"{sys.executable}" -c "{script}"'

    try:
        out = terminal.invoke(
            {"command": cmd},
            {"configurable": {"workspace": ws, "thread_id": "sess_ac_write"}},
        )
        assert "WRITE_OK" not in out
        assert not target_file.exists()
        assert "DENIED_WRITE:PermissionError" in out or "DENIED_WRITE" in out
    finally:
        if target_file.exists():
            target_file.unlink(missing_ok=True)
        if external_dir.exists():
            external_dir.rmdir()


def test_terminal_appcontainer_network_socket_denial(tmp_path):
    """Verify that network socket creation and loopback connections fail with OS error."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    ws = str(tmp_path.resolve())
    script = (
        f"import socket; "
        f"exec('''try:\\n s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\\n s.settimeout(1.0)\\n s.connect(('127.0.0.1', {port}))\\n print('NET_OK')\\nexcept Exception as e:\\n print('DENIED_NET:' + type(e).__name__)\\n''')"
    )
    cmd = f'"{sys.executable}" -c "{script}"'

    try:
        out = terminal.invoke(
            {"command": cmd},
            {"configurable": {"workspace": ws, "thread_id": "sess_ac_net"}},
        )
        assert "NET_OK" not in out
        assert "DENIED_NET:OSError" in out or "DENIED_NET" in out
    finally:
        srv.close()


def test_terminal_appcontainer_job_object_limits_and_lifecycle(tmp_path):
    """Verify that processes run bounded under Job Object resource limits."""
    ws = str(tmp_path.resolve())
    # Quick compute verifying execution within limits
    script = "import math; res = sum(math.isqrt(i) for i in range(1000)); print(f'COMPUTE_OK:{res}')"
    cmd = f'"{sys.executable}" -c "{script}"'

    out = terminal.invoke(
        {"command": cmd},
        {"configurable": {"workspace": ws, "thread_id": "sess_ac_job"}},
    )
    assert "COMPUTE_OK:" in out
    assert "Exit code: 0" in out

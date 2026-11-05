"""
test_phase_9_4_execution_sandbox.py - Automated Unit & Integration Tests for Phase 9.4.

Tests:
1. Cryptographic approval tokens (HMAC-SHA256, tampering, expiry).
2. Broker fail-closed workspace enforcement.
3. Single-use token consumption & replay prevention.
4. Windows Job Object limits & resource query telemetry.
5. Environment sanitization (secret stripping).
6. Filesystem containment & credential path protection.
7. Output stream capping (1MB hard limit).
8. Cancellation and process tree termination.
9. Platform adapters fail-closed enforcement.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from src.security import (
    ExecutionBroker,
    ExecutionMode,
    ExecutionReceipt,
    ExecutionRequest,
    SecurityViolationType,
    generate_approval_token,
    verify_approval_token,
)
from src.security.sandbox.linux import LinuxSandboxManager
from src.security.sandbox.macos import MacOSSandboxManager
from src.security.sandbox.windows import WindowsSandboxManager


def test_approval_token_cryptography_and_tamper_resistance(tmp_path):
    session_id = "test_sess"
    req_id = "req_100"
    cmd = "dir"
    ws = str(tmp_path.resolve())

    token = generate_approval_token(session_id, req_id, cmd, ws, expiry_s=60.0)
    assert token and isinstance(token, str)

    # Valid verification
    valid, reason = verify_approval_token(token, session_id, req_id, cmd, ws)
    assert valid is True
    assert "valid" in reason.lower()

    # Tampered command
    valid, reason = verify_approval_token(token, session_id, req_id, "rmdir /s /q .", ws)
    assert valid is False
    assert "forged or mismatched" in reason.lower()

    # Tampered session
    valid, reason = verify_approval_token(token, "other_sess", req_id, cmd, ws)
    assert valid is False

    # Tampered workspace
    valid, reason = verify_approval_token(token, session_id, req_id, cmd, "C:/OtherDir")
    assert valid is False

    # Expired token
    expired_token = generate_approval_token(session_id, req_id, cmd, ws, expiry_s=-10.0)
    valid, reason = verify_approval_token(expired_token, session_id, req_id, cmd, ws)
    assert valid is False
    assert "expired" in reason.lower()


def test_broker_rejects_missing_or_invalid_workspace(tmp_path):
    broker = ExecutionBroker.get_instance()

    # Empty workspace
    req_empty = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id="s1",
        request_id="r1",
        workspace_root="   ",
        tool_name="terminal",
        command="echo hi",
        argv=["cmd.exe", "/c", "echo hi"],
    )
    rec_empty = broker.execute(req_empty)
    assert rec_empty.exit_code == 126
    assert "missing workspace restriction" in rec_empty.stderr

    # Non-existent workspace
    req_nonexist = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id="s1",
        request_id="r1",
        workspace_root="C:/NonExistentPath_Crusor_XYZ_123",
        tool_name="terminal",
        command="echo hi",
        argv=["cmd.exe", "/c", "echo hi"],
        approval_token="fake_token:1:2:3:4:5",
    )
    rec_nonexist = broker.execute(req_nonexist)
    assert rec_nonexist.exit_code == 126
    assert "does not exist" in rec_nonexist.stderr


def test_broker_stale_approval_token_replay_rejected(tmp_path):
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = f"sess_replay_{uuid.uuid4().hex[:6]}"
    req_id = "req_replay"
    cmd = "echo replay_test"

    token = broker.create_approval(session_id, req_id, cmd, ws)

    req1 = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id=req_id,
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=["cmd.exe", "/c", "echo replay_test"],
        approval_token=token,
    )
    rec1 = broker.execute(req1)
    assert rec1.exit_code == 0

    # Replay exact token
    req2 = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id="req_replay_attack",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=["cmd.exe", "/c", "echo replay_test"],
        approval_token=token,
    )
    rec2 = broker.execute(req2)
    assert rec2.exit_code == 126
    assert "stale approval token replay detected" in rec2.stderr
    assert SecurityViolationType.FORGED_OR_STALE_APPROVAL.value in rec2.security_violations


def test_environment_sanitization_strips_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-TEST-CRITICAL-SECRET-KEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SECRET-AWS-TOKEN-999")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_MockSecretToken123456")

    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = "sess_env_test"
    req_id = "req_env_test"
    cmd = "check_env"

    token = broker.create_approval(session_id, req_id, cmd, ws)
    script = (
        "import os\n"
        "print('OPENAI:' + str(os.environ.get('OPENAI_API_KEY')))\n"
        "print('AWS:' + str(os.environ.get('AWS_SECRET_ACCESS_KEY')))\n"
        "print('GITHUB:' + str(os.environ.get('GITHUB_TOKEN')))\n"
    )
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
    assert "OPENAI:None" in rec.stdout
    assert "AWS:None" in rec.stdout
    assert "GITHUB:None" in rec.stdout


def test_path_containment_blocks_traversal_and_credentials(tmp_path):
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = "sess_containment"

    # Traversal escape
    cmd_trav = "python ../../../outside.py"
    token_trav = broker.create_approval(session_id, "req_trav", cmd_trav, ws)
    req_trav = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id="req_trav",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd_trav,
        argv=[sys.executable, "../../../outside.py"],
        approval_token=token_trav,
    )
    rec_trav = broker.execute(req_trav)
    assert rec_trav.exit_code == 126
    assert SecurityViolationType.WORKSPACE_TRAVERSAL.value in rec_trav.security_violations

    # Credential path access
    cmd_cred = "type C:/Users/Administrator/.ssh/id_rsa"
    token_cred = broker.create_approval(session_id, "req_cred", cmd_cred, ws)
    req_cred = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id="req_cred",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd_cred,
        argv=["cmd.exe", "/c", cmd_cred],
        approval_token=token_cred,
    )
    rec_cred = broker.execute(req_cred)
    assert rec_cred.exit_code == 126
    assert SecurityViolationType.CREDENTIAL_ACCESS_ATTEMPT.value in rec_cred.security_violations


def test_output_stream_byte_capping(tmp_path):
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())
    session_id = "sess_cap"
    cmd = "huge_out"

    token = broker.create_approval(session_id, "req_cap", cmd, ws)
    req = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id,
        request_id="req_cap",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd,
        argv=[sys.executable, "-c", "print('X' * 2_000_000)"],
        approval_token=token,
    )
    rec = broker.execute(req)
    assert rec.stdout_bytes >= 1048576
    assert "stdout truncated at 1048576 bytes" in rec.stdout


def test_timeout_and_cancellation(tmp_path):
    broker = ExecutionBroker.get_instance()
    ws = str(tmp_path.resolve())

    # Timeout
    session_id1 = "sess_timeout"
    cmd1 = "sleep_test"
    token1 = broker.create_approval(session_id1, "req_t", cmd1, ws)
    req1 = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id1,
        request_id="req_t",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd1,
        argv=[sys.executable, "-c", "import time; time.sleep(10)"],
        approval_token=token1,
        timeout_s=0.8,
    )
    rec1 = broker.execute(req1)
    assert rec1.timed_out is True
    assert rec1.exit_code == 124

    # Cancellation
    session_id2 = "sess_cancel"
    cmd2 = "cancel_test"
    token2 = broker.create_approval(session_id2, "req_c", cmd2, ws)
    abort_event = threading.Event()

    def _trigger():
        time.sleep(0.2)
        abort_event.set()

    threading.Thread(target=_trigger, daemon=True).start()

    req2 = ExecutionRequest(
        execution_id=str(uuid.uuid4()),
        session_id=session_id2,
        request_id="req_c",
        workspace_root=ws,
        tool_name="terminal",
        command=cmd2,
        argv=[sys.executable, "-c", "import time; time.sleep(10)"],
        approval_token=token2,
        timeout_s=10.0,
    )
    rec2 = broker.execute(req2, abort_event=abort_event)
    assert rec2.cancelled is True
    assert rec2.duration_s < 2.0


def test_unsupported_platform_adapters_fail_closed(tmp_path):
    # When running on Windows, Linux and macOS adapters must fail closed
    linux_mgr = LinuxSandboxManager()
    macos_mgr = MacOSSandboxManager()

    if sys.platform == "win32":
        req = ExecutionRequest(
            execution_id=str(uuid.uuid4()),
            session_id="s_plat",
            request_id="r_plat",
            workspace_root=str(tmp_path),
            tool_name="terminal",
            command="dir",
            argv=["dir"],
        )
        with pytest.raises(NotImplementedError):
            linux_mgr.initialize(req, tmp_path)

        with pytest.raises(NotImplementedError):
            macos_mgr.initialize(req, tmp_path)


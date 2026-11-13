"""R6: approval tokens must never be signed with a public constant.

The old fallback was `crusor-workspace-discipline-salt-2026`, so anyone who could
read the source could mint a token that the broker accepted. These tests pin the
replacement contract: env override -> per-install generated secret -> fail closed.
"""
from __future__ import annotations

import os
import stat

import pytest

from src.workspace.models import WorkspaceOperationType
from src.workspace.risk_policy import RiskApprovalGate, _load_approval_secret

OLD_PUBLIC_CONSTANT = b"crusor-workspace-discipline-salt-2026"


def _gate() -> RiskApprovalGate:
    return RiskApprovalGate()


def _mint(gate: RiskApprovalGate, **over) -> str:
    kwargs = dict(
        task_id="t1",
        workspace_root="/ws",
        file_path="a.py",
        operation_type=WorkspaceOperationType.MODIFY,
        content_digest="c" * 16,
        precondition_digest="p" * 16,
        session_id="s1",
        turn_id="u1",
    )
    kwargs.update(over)
    return gate.generate_approval_token(**kwargs)


def _verify(gate: RiskApprovalGate, token: str, **over):
    kwargs = dict(
        token=token,
        task_id="t1",
        workspace_root="/ws",
        file_path="a.py",
        operation_type=WorkspaceOperationType.MODIFY,
        content_digest="c" * 16,
        precondition_digest="p" * 16,
        session_id="s1",
        turn_id="u1",
        require_digest=True,
    )
    kwargs.update(over)
    return gate.verify_and_consume_approval_token(**kwargs)


def test_no_public_constant_is_used_and_a_secret_file_is_generated(tmp_path, monkeypatch):
    monkeypatch.delenv("CRUSOR_WORKSPACE_APPROVAL_KEY", raising=False)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path))

    secret = _load_approval_secret()
    assert secret and secret != OLD_PUBLIC_CONSTANT
    assert len(secret) == 64  # token_hex(32)

    key_file = tmp_path / "approval.key"
    assert key_file.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(key_file.stat().st_mode) & 0o077 == 0, "secret file must not be group/world readable"


def test_generated_secret_is_stable_across_calls(tmp_path, monkeypatch):
    monkeypatch.delenv("CRUSOR_WORKSPACE_APPROVAL_KEY", raising=False)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path))
    assert _load_approval_secret() == _load_approval_secret()


def test_env_override_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path))
    monkeypatch.setenv("CRUSOR_WORKSPACE_APPROVAL_KEY", "x" * 64)
    assert _load_approval_secret() == b"x" * 64


def test_token_forged_with_the_old_public_constant_is_rejected(tmp_path, monkeypatch):
    import hashlib
    import hmac
    import time

    monkeypatch.delenv("CRUSOR_WORKSPACE_APPROVAL_KEY", raising=False)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path))

    exp = int(time.time() + 300)
    payload = f"t1:/ws:a.py:{WorkspaceOperationType.MODIFY.value}:{'c' * 16}:{'p' * 16}:s1:u1:{exp}"
    sig = hmac.new(OLD_PUBLIC_CONSTANT, payload.encode(), hashlib.sha256).hexdigest()
    forged = f"APPV-{sig[:24]}-{exp}"

    ok, reason = _verify(_gate(), forged)
    assert ok is False
    assert "mismatch" in reason.lower()


def test_rotation_invalidates_outstanding_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path))
    monkeypatch.setenv("CRUSOR_WORKSPACE_APPROVAL_KEY", "a" * 64)
    token = _mint(_gate())

    monkeypatch.setenv("CRUSOR_WORKSPACE_APPROVAL_KEY", "b" * 64)
    ok, reason = _verify(_gate(), token)
    assert ok is False and "mismatch" in reason.lower()


def test_missing_secret_fails_closed(monkeypatch):
    monkeypatch.setattr("src.workspace.risk_policy._load_approval_secret", lambda: b"")
    with pytest.raises(RuntimeError, match="fail closed"):
        _mint(_gate())
    ok, reason = _verify(_gate(), "APPV-deadbeef-9999999999")
    assert ok is False and "unavailable" in reason.lower()


def test_replay_and_cross_operation_still_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("CRUSOR_WORKSPACE_APPROVAL_KEY", raising=False)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path))
    gate = _gate()
    token = _mint(gate)

    ok, _ = _verify(gate, token)
    assert ok is True
    ok, reason = _verify(gate, token)
    assert ok is False and "consumed" in reason.lower()

    create_token = _mint(_gate(), operation_type=WorkspaceOperationType.CREATE)
    ok, _ = _verify(_gate(), create_token, operation_type=WorkspaceOperationType.MODIFY)
    assert ok is False

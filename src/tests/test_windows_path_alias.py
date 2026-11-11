"""Windows short-name/long-name identity and containment tests.

These are native Windows tests: if 8.3 alias creation is unavailable they skip
rather than pretending the alias case passed.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.workspace.mutation_broker import MutationAuthorizationError, WorkspaceMutationBroker
from src.workspace.path_safety import PathSafetyValidator, PathSecurityViolation

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows path identity")


def _short_path(path: Path) -> Path:
    buf = ctypes.create_unicode_buffer(32768)
    ok = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    if not ok:
        pytest.skip(f"8.3 alias unavailable for {path}")
    short = Path(buf.value)
    if short == path:
        pytest.skip(f"8.3 aliases are disabled on this volume: {path}")
    return short


def test_short_and_long_names_are_one_authorization_target(tmp_path: Path) -> None:
    long_ws = tmp_path / "workspace"
    long_ws.mkdir()
    short_ws = _short_path(long_ws)

    long_target = PathSafetyValidator.resolve_and_verify(long_ws, "new/file.txt")
    short_target = PathSafetyValidator.resolve_and_verify(short_ws, "new/file.txt")

    assert long_target == short_target
    assert PathSafetyValidator.get_relative_normalized(long_ws, long_target) == "new/file.txt"
    assert PathSafetyValidator.get_relative_normalized(short_ws, long_target) == "new/file.txt"


def test_case_insensitive_existing_file_is_one_target(tmp_path: Path) -> None:
    long_ws = tmp_path / "workspace"
    long_ws.mkdir()
    (long_ws / "Case.TXT").write_text("x", encoding="utf-8")
    resolved = PathSafetyValidator.resolve_and_verify(long_ws, "case.txt")
    short_ws = _short_path(long_ws)
    assert resolved.name == "Case.TXT"
    assert (
        PathSafetyValidator.get_relative_normalized(long_ws, resolved)
        == PathSafetyValidator.get_relative_normalized(short_ws, resolved)
    )


def test_approved_write_via_long_alias_blocks_token_replay_via_short_alias(tmp_path: Path) -> None:
    from src.workspace.models import WorkspaceOperationType
    from src.workspace.mutation_broker import approval_digest, approval_precondition

    long_ws = tmp_path / "workspace"
    long_ws.mkdir()
    short_ws = _short_path(long_ws)
    original = "first\n"
    (long_ws / "alias.txt").write_text(original, encoding="utf-8")
    broker = WorkspaceMutationBroker(str(long_ws))

    updated = "second\n"
    token = broker.risk_gate.generate_approval_token(
        "alias-task",
        str(broker.workspace_root),
        "alias.txt",
        WorkspaceOperationType.CREATE,
        content_digest=approval_digest(updated),
        precondition_digest=approval_precondition(True, original),
    )
    broker.create_file(
        path=str(long_ws / "alias.txt"),
        content=updated,
        task_id="alias-task",
        approval_token=token,
        require_digest=True,
    )
    assert (long_ws / "alias.txt").read_text(encoding="utf-8") == updated

    with pytest.raises(MutationAuthorizationError):
        broker.create_file(
            path=str(short_ws / "alias.txt"),
            content="third\n",
            task_id="alias-task",
            approval_token=token,
            require_digest=True,
        )


def test_alias_parent_cannot_escape_workspace(tmp_path: Path) -> None:
    long_ws = tmp_path / "workspace"
    long_ws.mkdir()
    short_ws = _short_path(long_ws)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(PathSecurityViolation):
        PathSafetyValidator.resolve_and_verify(short_ws, str(outside / "secret.txt"))
    with pytest.raises(PathSecurityViolation):
        PathSafetyValidator.resolve_and_verify(long_ws, "../outside/secret.txt")


def test_junction_escape_is_rejected(tmp_path: Path) -> None:
    long_ws = tmp_path / "workspace"
    long_ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = long_ws / "link"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")

    with pytest.raises(PathSecurityViolation):
        PathSafetyValidator.resolve_and_verify(long_ws, "link/escaped.txt")


def test_nonexisting_target_under_aliased_parent_is_contained(tmp_path: Path) -> None:
    long_ws = tmp_path / "workspace"
    long_ws.mkdir()
    short_ws = _short_path(long_ws)
    nested = long_ws / "nested"
    nested.mkdir(exist_ok=True)

    long_target = PathSafetyValidator.resolve_and_verify(long_ws, "nested/new.md")
    short_target = PathSafetyValidator.resolve_and_verify(short_ws, "nested/new.md")
    assert long_target == short_target
    assert os.path.commonpath([str(long_target), str(long_ws)]) == str(long_ws)

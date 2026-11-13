"""P1-A-R2 B-1: ``session_create`` must count checkpoints in the SAME database
the graph checkpointer writes.

The bridge used to fall back to ``~/.crusorai/sessions.db`` regardless of
``CRUSORAI_CHECKPOINT_DB`` / ``CRUSORAI_CHECKPOINT_HOME`` /
``CRUSORAI_SESSIONS_DB`` / ``CRUSORAI_HOME``. These regressions drive a real
stdio bridge subprocess (echo runner, zero provider traffic) and assert:

* a custom checkpoint database wins over the shared session database;
* a custom session database is used when there is no checkpoint override;
* ``session_resume`` works against the isolated stores;
* a missing checkpoint database yields zero, never a silent home fallback;
* the developer's real database and all sidecars stay untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from src.bridge.protocol import PROTOCOL_VERSION

REPO = Path(__file__).resolve().parents[2]

_DB_FILES = (
    "sessions.db",
    "sessions.db-wal",
    "sessions.db-shm",
    "runtime_events.db",
    "runtime_events.db-wal",
    "runtime_events.db-shm",
    "verification.db",
    "verification.db-wal",
    "verification.db-shm",
)


def _full_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_snapshot(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _full_hash(path),
    }


def _real_snapshot() -> dict[str, dict]:
    real_dir = Path.home() / ".crusorai"
    return {name: _db_snapshot(real_dir / name) for name in _DB_FILES}


def _assert_real_db_unchanged(before: dict[str, dict]) -> None:
    after = _real_snapshot()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed during a custom-DB run: "
            f"{before[name]} -> {after[name]}"
        )


def _make_checkpoint_db(path: Path, rows: dict[str, int]) -> None:
    """Create a LangGraph-schema checkpoint DB with a known row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints ("
            "thread_id TEXT NOT NULL, "
            "checkpoint_ns TEXT NOT NULL DEFAULT '', "
            "checkpoint_id TEXT NOT NULL, "
            "parent_checkpoint_id TEXT, type TEXT, checkpoint BLOB, "
            "metadata BLOB, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS writes ("
            "thread_id TEXT NOT NULL, "
            "checkpoint_ns TEXT NOT NULL DEFAULT '', "
            "checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, "
            "idx INTEGER NOT NULL, channel TEXT NOT NULL, type TEXT, "
            "value BLOB, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))"
        )
        for thread_id, count in rows.items():
            for index in range(count):
                con.execute(
                    "INSERT INTO checkpoints "
                    "(thread_id, checkpoint_ns, checkpoint_id, "
                    "parent_checkpoint_id, type, checkpoint, metadata) "
                    "VALUES (?, '', ?, NULL, NULL, NULL, NULL)",
                    (thread_id, str(index)),
                )
        con.commit()


def _bridge_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    env["CRUSORAI_BRIDGE_RUNNER"] = "echo"
    # Never let the developer's shell override the test's explicit stores.
    for key in (
        "CRUSORAI_CHECKPOINT_DB",
        "CRUSORAI_CHECKPOINT_HOME",
        "CRUSORAI_SESSIONS_DB",
        "CRUSORAI_SESSIONS_DB_PATH",
        "CRUSORAI_HOME",
    ):
        env.pop(key, None)
    env.update(overrides)
    return env


class _Bridge:
    def __init__(self, env: dict[str, str]) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "src.bridge"],
            cwd=str(REPO),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    def send(self, frame: dict, timeout_s: float = 60.0) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(frame) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout_s
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"no reply to {frame.get('type')}")
            line = self.proc.stdout.readline()
            if not line:
                stderr = self.proc.stderr.read() if self.proc.stderr else ""
                raise AssertionError(f"bridge closed stdout; stderr={stderr[-2000:]}")
            reply = json.loads(line)
            if reply.get("type") not in {"workspace.bound", "llm.request"}:
                return reply

    def close(self) -> None:
        try:
            self.proc.kill()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            pass


def _start(env: dict[str, str]) -> _Bridge:
    bridge = _Bridge(env)
    hello = bridge.send({"type": "hello", "protocol": PROTOCOL_VERSION})
    assert hello["type"] == "hello", hello
    return bridge


def test_session_create_reads_checkpoints_from_custom_checkpoint_db(tmp_path):
    """An explicit checkpoint DB wins over the checkpoint home and sessions DB."""
    sid = "b1-checkpoint-home"
    ckpt_home = tmp_path / "ckpt"
    checkpoint_db = ckpt_home / "sessions.db"
    decoy_home = tmp_path / "decoy-ckpt"
    session_db = tmp_path / "sessions.db"
    _make_checkpoint_db(checkpoint_db, {sid: 2})
    _make_checkpoint_db(decoy_home / "sessions.db", {sid: 5})  # must NOT win
    _make_checkpoint_db(session_db, {sid: 7})  # must NOT be read
    before = _real_snapshot()

    bridge = _start(
        _bridge_env(
            CRUSORAI_CHECKPOINT_DB=str(checkpoint_db),
            CRUSORAI_CHECKPOINT_HOME=str(decoy_home),
            CRUSORAI_SESSIONS_DB=str(session_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
        )
    )
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert created["prior_checkpoints"] == 2, created
    _assert_real_db_unchanged(before)


def test_session_create_uses_custom_session_db_without_checkpoint_override(tmp_path):
    """With only CRUSORAI_SESSIONS_DB set, checkpoints share that database."""
    sid = "b1-session-db"
    session_db = tmp_path / "custom-sessions.db"
    _make_checkpoint_db(session_db, {sid: 3})
    before = _real_snapshot()

    bridge = _start(
        _bridge_env(
            CRUSORAI_SESSIONS_DB=str(session_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
        )
    )
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert created["prior_checkpoints"] == 3, created
    _assert_real_db_unchanged(before)


def test_session_resume_uses_isolated_stores_and_leaves_real_db_alone(tmp_path):
    """session_resume must not reopen the developer's real checkpoint DB."""
    sid = "b1-resume"
    ckpt_home = tmp_path / "ckpt"
    _make_checkpoint_db(ckpt_home / "sessions.db", {sid: 1})
    session_db = tmp_path / "session" / "sessions.db"
    before = _real_snapshot()

    bridge = _start(
        _bridge_env(
            CRUSORAI_CHECKPOINT_HOME=str(ckpt_home),
            CRUSORAI_SESSIONS_DB=str(session_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
        )
    )
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
        resumed = bridge.send(
            {"type": "session_resume", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert resumed["type"] == "session_info", resumed
    assert resumed["resumed"] is True, resumed
    assert resumed["resolved_session_id"] == sid, resumed
    _assert_real_db_unchanged(before)


def test_missing_checkpoint_db_does_not_fall_back_to_home(tmp_path):
    """A missing custom path reports zero, never the developer's home DB."""
    sid = "b1-no-fallback"
    fake_home = tmp_path / "fake-home"
    decoy_db = fake_home / ".crusorai" / "sessions.db"
    _make_checkpoint_db(decoy_db, {sid: 9})  # a fallback would report 9
    missing = tmp_path / "missing" / "sessions.db"
    before = _real_snapshot()

    env = _bridge_env(
        CRUSORAI_CHECKPOINT_DB=str(missing),
        CRUSORAI_HOME=str(tmp_path / "app-home"),
        HOME=str(fake_home),
        USERPROFILE=str(fake_home),
    )
    bridge = _start(env)
    try:
        created = bridge.send(
            {"type": "session_create", "session_id": sid, "workspace": str(tmp_path)}
        )
    finally:
        bridge.close()

    assert created["type"] == "session_info", created
    assert created["prior_checkpoints"] == 0, created
    assert not missing.exists(), "counting must not create the override DB"
    _assert_real_db_unchanged(before)

"""P1-A-R3 B-4: checkpoint count must use a correctly encoded SQLite URI.

A filesystem path is not a URI. The old construction
``f"file:{db}?mode=ro"`` let ``#`` start a URI fragment, so a path such as
``cp#frag/sessions.db`` was truncated to ``cp``. If a decoy database existed
there, the bridge silently reported another database's checkpoint count.

These regressions drive the real stdio bridge and prove the intended database
(2 checkpoints) wins over a decoy at the incorrectly truncated path
(1 checkpoint), for ``#``, spaces, ``%`` and Unicode. ``?`` is covered at the
URI-encoding layer everywhere and end-to-end on platforms that allow it in a
filename (Windows does not).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from src.runtime.app_paths import sqlite_readonly_uri
from src.tests.test_prior_checkpoint_isolation import (
    _assert_real_db_unchanged,
    _bridge_env,
    _full_hash,
    _make_checkpoint_db,
    _real_snapshot,
    _start,
)


def _assert_bridge_reads_intended_db(tmp_path, checkpoint_db: Path, sid: str) -> None:
    """Run session_create through the real bridge and assert 2, not the decoy."""
    before_real = _real_snapshot()
    before_db = _full_hash(checkpoint_db)
    bridge = _start(
        _bridge_env(
            CRUSORAI_CHECKPOINT_DB=str(checkpoint_db),
            CRUSORAI_HOME=str(tmp_path / "home"),
            CRUSORAI_SESSIONS_DB=str(tmp_path / "sessions.db"),
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
    # The count path is read-only; the selected database must be unchanged.
    assert _full_hash(checkpoint_db) == before_db
    _assert_real_db_unchanged(before_real)


def test_hash_in_path_uses_intended_db_not_truncated_decoy(tmp_path):
    """B-4 repro: intended=2, decoy at the pre-# path=1, bridge must say 2."""
    sid = "uri-hash-probe"
    decoy = tmp_path / "cp"
    intended = tmp_path / "cp#frag" / "sessions.db"
    _make_checkpoint_db(decoy, {sid: 1})  # the old URI would open this file
    _make_checkpoint_db(intended, {sid: 2})

    _assert_bridge_reads_intended_db(tmp_path, intended, sid)
    assert decoy.exists()


def test_space_in_path_uses_intended_db(tmp_path):
    sid = "uri-space-probe"
    intended = tmp_path / "cp space" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_percent_in_path_uses_intended_db(tmp_path):
    sid = "uri-percent-probe"
    intended = tmp_path / "cp%percent" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_unicode_in_path_uses_intended_db(tmp_path):
    sid = "uri-unicode-probe"
    intended = tmp_path / "caf\u00e9-\u65e5\u672c" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_question_mark_is_percent_encoded_and_never_a_query_delimiter(tmp_path):
    """A literal ? in the filename must become %3F before ?mode=ro is appended."""
    db = tmp_path / "cp?frag" / "sessions.db"
    uri = sqlite_readonly_uri(db)
    assert "%3F" in uri
    assert uri.endswith("?mode=ro")
    assert uri.count("?") == 1  # only the read-only query delimiter
    assert "%23" not in uri  # no accidental fragment


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows does not allow '?' in a filename; the URI encoding test above covers it",
)
def test_question_mark_in_path_uses_intended_db(tmp_path):
    sid = "uri-question-probe"
    intended = tmp_path / "cp?frag" / "sessions.db"
    _make_checkpoint_db(intended, {sid: 2})
    _assert_bridge_reads_intended_db(tmp_path, intended, sid)


def test_readonly_uri_rejects_writes_and_keeps_database_hash(tmp_path):
    sid = "uri-readonly-probe"
    db = tmp_path / "readonly" / "sessions.db"
    _make_checkpoint_db(db, {sid: 2})
    before = _full_hash(db)

    conn = sqlite3.connect(sqlite_readonly_uri(db), uri=True, timeout=2.0)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM checkpoints")
    finally:
        conn.close()

    assert _full_hash(db) == before

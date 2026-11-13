"""P1-A: checkpoint storage must be hermetic and lazy.

The graph checkpointer used to open ``~/.crusorai/sessions.db`` at import time
and ignore every test/home override. These tests pin the contract:

* path precedence: CRUSORAI_CHECKPOINT_DB > CRUSORAI_CHECKPOINT_HOME >
  CRUSORAI_SESSIONS_DB/_PATH > CRUSORAI_HOME > ~/.crusorai/sessions.db;
* importing the graph must not create or open a database;
* the first checkpoint operation creates the configured database only;
* real LangGraph checkpoint tables still exist (persistence is not disabled);
* the developer's real databases and all SQLite sidecars are byte-identical
  (full SHA-256 + size + mtime) before/after an isolated run;
* invalid checkpoint paths fail closed without a home fallback.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.runtime.app_paths import checkpoint_db_path, session_db_path

REPO = Path(__file__).resolve().parents[2]
_ENV_KEYS = (
    "CRUSORAI_CHECKPOINT_DB",
    "CRUSORAI_CHECKPOINT_HOME",
    "CRUSORAI_SESSIONS_DB",
    "CRUSORAI_SESSIONS_DB_PATH",
    "CRUSORAI_HOME",
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _clean_subprocess_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in _ENV_KEYS:
        env.pop(key, None)
    env.update(overrides)
    env["PYTHONPATH"] = str(REPO)
    env.setdefault("CRUSORAI_MEMORY", "off")
    return env


def _run_isolated(code: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        env=_clean_subprocess_env(**env_overrides),
        text=True,
        capture_output=True,
        timeout=120,
    )


def _full_hash(path: Path) -> str:
    """Hash the complete file (not a sample) so sidecar content is covered."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Main databases + every SQLite sidecar named by the P1-A review contract.
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
# A rollback-journal file is absent while WAL is active; snapshot it too so an
# unexpected journal can never slip past the immutability check.
_JOURNAL_FILES = (
    "sessions.db-journal",
    "runtime_events.db-journal",
    "verification.db-journal",
)


# ---------------------------------------------------------------------------
# Path precedence
# ---------------------------------------------------------------------------
def test_explicit_checkpoint_db_wins(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_CHECKPOINT_DB", str(tmp_path / "explicit.db"))
    monkeypatch.setenv("CRUSORAI_CHECKPOINT_HOME", str(tmp_path / "ckpt"))
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "explicit.db"


def test_checkpoint_home_wins_over_sessions_db(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_CHECKPOINT_HOME", str(tmp_path / "ckpt"))
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "ckpt" / "sessions.db"


def test_sessions_db_override_is_used_without_checkpoint_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "sessions.db"


def test_app_home_override_is_used_without_sessions_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert checkpoint_db_path() == tmp_path / "home" / "sessions.db"


def test_default_path_is_unchanged(monkeypatch):
    _clear_env(monkeypatch)
    expected = Path.home() / ".crusorai" / "sessions.db"
    assert checkpoint_db_path() == expected
    assert session_db_path() == expected


def test_session_db_path_keeps_existing_precedence(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
    assert session_db_path() == tmp_path / "home" / "sessions.db"
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "custom.db"))
    assert session_db_path() == tmp_path / "custom.db"


# ---------------------------------------------------------------------------
# Import-time behaviour
# ---------------------------------------------------------------------------
def test_import_does_not_create_or_open_checkpoint_db(tmp_path):
    ckpt = tmp_path / "ckpt"
    home = tmp_path / "home"
    code = f"""
import pathlib
import src.graphs.chat_graph as g
p = pathlib.Path(g._CHECKPOINT_DB)
print(p)
print("exists", p.exists())
print("is_setup", g.memory.is_setup)
assert p == pathlib.Path({str(ckpt / 'sessions.db')!r}), p
assert not p.exists(), p
assert g.memory.is_setup is False, g.memory.is_setup
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(home),
    )
    assert result.returncode == 0, result.stderr
    assert "exists False" in result.stdout
    assert "is_setup False" in result.stdout
    assert not (ckpt / "sessions.db").exists()


def test_checkpoint_home_override_creates_only_the_isolated_db(tmp_path):
    ckpt = tmp_path / "ckpt"
    home = tmp_path / "home"
    code = f"""
import pathlib, sqlite3
import src.graphs.chat_graph as g
p = pathlib.Path(g._CHECKPOINT_DB)
g.memory.setup()
print("db", p)
print("exists", p.exists())
con = sqlite3.connect(str(p))
tables = {{r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}}
con.close()
print("tables", sorted(tables))
assert p == pathlib.Path({str(ckpt / 'sessions.db')!r}), p
assert p.exists(), p
assert {{"checkpoints", "writes"}} <= tables, tables
assert not pathlib.Path({str(home / 'sessions.db')!r}).exists()
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(home),
    )
    assert result.returncode == 0, result.stderr
    assert "exists True" in result.stdout
    assert "checkpoints" in result.stdout and "writes" in result.stdout


def test_sessions_db_override_names_the_checkpoint_file(tmp_path):
    db = tmp_path / "custom-sessions.db"
    code = f"""
import pathlib
import src.graphs.chat_graph as g
p = pathlib.Path(g._CHECKPOINT_DB)
print(p)
assert p == pathlib.Path({str(db)!r}), p
"""
    result = _run_isolated(
        code,
        CRUSORAI_SESSIONS_DB=str(db),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert result.returncode == 0, result.stderr
    assert str(db) in result.stdout


# ---------------------------------------------------------------------------
# Actual checkpoint storage still works
# ---------------------------------------------------------------------------
def test_lazy_connection_defers_file_creation(tmp_path):
    from src.graphs.chat_graph import _LazySqliteConnection

    db = tmp_path / "lazy.db"
    conn = _LazySqliteConnection(str(db))
    assert not db.exists()
    assert conn.execute("SELECT 1").fetchone() == (1,)
    assert db.exists()


def test_invalid_checkpoint_path_directory_target_fails_closed(tmp_path):
    """A path that is an existing directory is not silently replaced."""
    from src.graphs.chat_graph import _LazySqliteConnection

    target = tmp_path / "as-directory"
    target.mkdir()
    conn = _LazySqliteConnection(str(target))
    with pytest.raises((sqlite3.OperationalError, OSError)):
        conn.execute("SELECT 1")
    assert target.is_dir()
    # No sibling database was invented as a fallback.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["as-directory"]


def test_invalid_checkpoint_path_parent_is_a_file_fails_closed(tmp_path):
    """A file where a parent directory is required fails closed."""
    from src.graphs.chat_graph import _LazySqliteConnection

    parent = tmp_path / "parent-file"
    parent.write_text("not a directory", encoding="utf-8")
    target = parent / "sessions.db"
    conn = _LazySqliteConnection(str(target))
    with pytest.raises((FileExistsError, NotADirectoryError, OSError)):
        conn.execute("SELECT 1")
    assert parent.is_file()
    assert not target.exists()


def test_nested_missing_parent_is_created_lazily(tmp_path):
    """A writable nested path is created on first use, not at construction."""
    from src.graphs.chat_graph import _LazySqliteConnection

    db = tmp_path / "one" / "two" / "three" / "sessions.db"
    conn = _LazySqliteConnection(str(db))
    assert not db.parent.exists()
    assert conn.execute("SELECT 1").fetchone() == (1,)
    assert db.exists()
    assert db.parent.is_dir()


def test_writable_custom_checkpoint_location_is_used(tmp_path):
    """CRUSORAI_CHECKPOINT_DB can point at a fresh nested directory."""
    ckpt = tmp_path / "custom" / "nested" / "sessions.db"
    code = f"""
import pathlib
import src.graphs.chat_graph as g
g.memory.setup()
p = pathlib.Path(g._CHECKPOINT_DB)
print(p)
assert p == pathlib.Path({str(ckpt)!r}), p
assert p.exists(), p
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_DB=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert result.returncode == 0, result.stderr
    assert ckpt.exists()


def test_invalid_checkpoint_location_fails_closed_without_home_fallback(tmp_path):
    """An unusable override must fail; it must never fall back to the home DB."""
    bad = tmp_path / "not-a-database"
    bad.mkdir()
    home = tmp_path / "home"
    before = _snapshot_real_databases()
    code = """
import src.graphs.chat_graph as g
g.memory.setup()
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_DB=str(bad),
        CRUSORAI_HOME=str(home),
    )
    assert result.returncode != 0
    assert "OperationalError" in result.stderr or "unable to open" in result.stderr
    assert not (home / "sessions.db").exists()
    after = _snapshot_real_databases()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed after a failed override: "
            f"{before[name]} -> {after[name]}"
        )


def test_snapshot_treats_previously_absent_sidecars_as_absent(tmp_path):
    """Absent sidecars are tracked explicitly, so a later creation is visible."""
    missing = tmp_path / "never-created.db-wal"
    assert _db_snapshot(missing) == {"exists": False}
    missing.write_bytes(b"")
    snapshot = _db_snapshot(missing)
    assert snapshot["exists"] is True
    assert snapshot["size"] == 0


def test_sqlite_saver_setup_and_read_write_tables(tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    from src.graphs.chat_graph import _LazySqliteConnection

    db = tmp_path / "saver.db"
    saver = SqliteSaver(_LazySqliteConnection(str(db)))
    saver.setup()
    with sqlite3.connect(str(db)) as con:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"checkpoints", "writes"} <= tables


def test_checkpoint_survives_a_process_restart_in_isolated_storage(tmp_path):
    ckpt = tmp_path / "ckpt"
    write_code = """
import src.graphs.chat_graph as g
cfg = {"configurable": {"thread_id": "restart-probe"}}
g.graph.update_state(cfg, {"turn_receipt": {"probe": 1}})
print(g._CHECKPOINT_DB)
"""
    written = _run_isolated(
        write_code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert written.returncode == 0, written.stderr
    assert (ckpt / "sessions.db").exists()

    read_code = """
import src.graphs.chat_graph as g
cfg = {"configurable": {"thread_id": "restart-probe"}}
state = g.graph.get_state(cfg)
print(state.values)
assert state.values.get("turn_receipt") == {"probe": 1}, state.values
"""
    read = _run_isolated(
        read_code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert read.returncode == 0, read.stderr
    assert "probe" in read.stdout


# ---------------------------------------------------------------------------
# The fixture and the real user database
# ---------------------------------------------------------------------------
def test_fixture_checkpoint_home_is_isolated():
    configured = os.environ.get("CRUSORAI_CHECKPOINT_HOME", "").strip()
    assert configured, "conftest must set CRUSORAI_CHECKPOINT_HOME"
    import src.graphs.chat_graph as chat_graph

    path = Path(chat_graph._CHECKPOINT_DB).resolve()
    real = (Path.home() / ".crusorai" / "sessions.db").resolve()
    assert path != real
    assert path.is_relative_to(Path(configured).resolve())


def test_fixture_sessions_db_and_checkpoint_share_the_isolated_root():
    configured_home = Path(os.environ["CRUSORAI_CHECKPOINT_HOME"]).resolve()
    configured_db = Path(os.environ["CRUSORAI_SESSIONS_DB"]).resolve()
    real = (Path.home() / ".crusorai" / "sessions.db").resolve()
    assert configured_db != real
    assert configured_db.parent == configured_home
    assert session_db_path().resolve() == configured_db
    assert checkpoint_db_path().resolve() == configured_db
    from src.runtime.session_store import get_session_store

    store = get_session_store()
    assert Path(store.db_path).resolve() == configured_db
    from src.runtime.app_paths import workspace_app_data_root

    isolated_workspace_root = workspace_app_data_root("/any/workspace").resolve()
    assert isolated_workspace_root.is_relative_to(
        Path(os.environ["CRUSORAI_HOME"]).resolve()
    )
    assert isolated_workspace_root != (
        Path.home() / ".crusorai" / "workspaces"
    ).resolve()


def _db_snapshot(path: Path) -> dict:
    """Existence + size + mtime + full SHA-256 (absent files stay absent)."""
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _full_hash(path),
    }


def _snapshot_real_databases() -> dict[str, dict]:
    real_dir = Path.home() / ".crusorai"
    return {
        name: _db_snapshot(real_dir / name)
        for name in (*_DB_FILES, *_JOURNAL_FILES)
    }


def test_real_user_database_is_not_modified_by_an_isolated_run(tmp_path):
    before = _snapshot_real_databases()
    if not before["sessions.db"].get("exists"):
        pytest.skip("no developer database on this host")

    ckpt = tmp_path / "ckpt"
    code = """
import pathlib
import src.graphs.chat_graph as g
g.memory.setup()
from src.runtime.factory import get_runtime_services
services = get_runtime_services()
from src.runtime.session_store import get_session_store
store = get_session_store()
store.create_session("isolation-probe", str(pathlib.Path.cwd()), title="probe")
print(g._CHECKPOINT_DB)
print(store.db_path)
print(services.journal.path)
print(services.verification.path)
"""
    result = _run_isolated(
        code,
        CRUSORAI_CHECKPOINT_HOME=str(ckpt),
        CRUSORAI_HOME=str(tmp_path / "home"),
    )
    assert result.returncode == 0, result.stderr
    assert (ckpt / "sessions.db").exists()
    assert (tmp_path / "home" / "sessions.db").exists()
    assert (tmp_path / "home" / "runtime_events.db").exists()
    assert (tmp_path / "home" / "verification.db").exists()

    after = _snapshot_real_databases()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed during an isolated run: "
            f"{before[name]} -> {after[name]}"
        )


def test_otel_cleanup_targets_the_isolated_db_and_never_the_real_db():
    """B-2: test hygiene deletes from the graph's resolved DB, not home."""
    from src.graphs import chat_graph
    from src.tests.test_otel_tracing import _drop_checkpoints

    configured = Path(os.environ["CRUSORAI_CHECKPOINT_HOME"]).resolve()
    db = Path(chat_graph._CHECKPOINT_DB).resolve()
    real = (Path.home() / ".crusorai" / "sessions.db").resolve()
    assert db != real
    assert db.is_relative_to(configured)

    before = _snapshot_real_databases()
    chat_graph.memory.setup()
    thread = "p1a-b2-cleanup-probe"
    with sqlite3.connect(str(db)) as con:
        con.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread,))
        con.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, "
            "parent_checkpoint_id, type, checkpoint, metadata) "
            "VALUES (?, '', '1', NULL, NULL, NULL, NULL)",
            (thread,),
        )
        con.commit()

    _drop_checkpoints(thread)

    with sqlite3.connect(str(db)) as con:
        remaining = con.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread,)
        ).fetchone()[0]
    assert remaining == 0

    after = _snapshot_real_databases()
    for name in before:
        assert after[name] == before[name], (
            f"real database/sidecar {name} changed during OTel cleanup: "
            f"{before[name]} -> {after[name]}"
        )

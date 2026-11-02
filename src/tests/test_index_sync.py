"""Tests for index synchronization and workspace scanning (Phase 5.2)."""

from pathlib import Path

from src.context.bounded_scan import ContextBudget
from src.context.indexing.index_storage import IndexStorage
from src.context.indexing.index_sync import (
    _SKIP_DIRS,
    IndexSynchronizer,
    edges_for,
    index_workspace,
    iter_source_files,
    read_source,
    sync_file,
    sync_workspace,
)


def test_skip_dirs_defaults():
    assert ".git" in _SKIP_DIRS
    assert "node_modules" in _SKIP_DIRS
    assert "__pycache__" in _SKIP_DIRS


def test_read_source_bounded(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text("def hello(): pass")
    budget = ContextBudget()
    content = read_source(f, budget)
    assert content == "def hello(): pass"
    assert budget.read_files == 1
    assert budget.read_bytes > 0


def test_edges_for_python(tmp_path: Path):
    f_main = tmp_path / "main.py"
    f_util = tmp_path / "util.py"
    f_util.write_text("def util_func(): pass")
    f_main.write_text("import util\n")

    edges = edges_for(f_main, "main.py", tmp_path, ContextBudget(), "import util\n")
    assert "util.py" in edges


def test_sync_file_and_workspace_incremental(tmp_path: Path):
    db_file = str(tmp_path / "sync_test.db")
    storage = IndexStorage(db_file)
    try:
        f1 = tmp_path / "mod1.py"
        f1.write_text("def fn1():\n    pass\n")

        # 1. Sync file
        sync_file(storage, tmp_path, f1)
        assert storage.is_index_empty() is False

        # 2. Sync workspace - nothing changed
        changed = sync_workspace(storage, tmp_path)
        assert changed == 0

        # 3. Add second file and sync workspace
        f2 = tmp_path / "mod2.py"
        f2.write_text("def fn2():\n    pass\n")
        changed = sync_workspace(storage, tmp_path)
        assert changed == 1

        # 4. Delete f1 and sync workspace -> ghost pruning
        f1.unlink()
        changed = sync_workspace(storage, tmp_path)
        assert changed == 2  # 2 chunks pruned (module + fn1)

        # Check remaining
        remaining = [r[0] for r in storage.conn.execute("SELECT file_path FROM code_chunks").fetchall()]
        assert "mod1.py" not in remaining
        assert "mod2.py" in remaining
    finally:
        storage.close()


def test_index_workspace_full_rebuild(tmp_path: Path):
    db_file = str(tmp_path / "rebuild_test.db")
    storage = IndexStorage(db_file)
    try:
        f = tmp_path / "code.py"
        f.write_text("def foo(): pass")
        index_workspace(storage, tmp_path)

        rows = storage.conn.execute("SELECT symbol_name FROM code_chunks").fetchall()
        assert any(r[0] == "foo" for r in rows)
    finally:
        storage.close()


def test_index_synchronizer_facade(tmp_path: Path):
    db_file = str(tmp_path / "facade_test.db")
    storage = IndexStorage(db_file)
    try:
        f = tmp_path / "app.py"
        f.write_text("def app_main(): pass")

        syncer = IndexSynchronizer(tmp_path, storage)
        syncer.sync_workspace()
        assert syncer.last_scan_report is not None

        rows = storage.conn.execute("SELECT symbol_name FROM code_chunks").fetchall()
        assert any(r[0] == "app_main" for r in rows)
    finally:
        storage.close()

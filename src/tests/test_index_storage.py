"""Tests for index storage and schema operations (Phase 5.1)."""

import sqlite3
import threading
from pathlib import Path

from src.context.bounded_scan import ContextBudget
from src.context.indexing.index_storage import (
    EMBED_DIM,
    IndexStorage,
    get_neighbors,
    init_schema,
    insert_chunks,
    is_index_empty,
    open_database,
    remove_file,
)


def test_open_database_and_pragmas(tmp_path: Path):
    db_file = str(tmp_path / "test.db")
    conn, uses_vec = open_database(db_file)
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal.lower() == "wal"
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000
    finally:
        conn.close()


def test_init_schema_creates_tables(tmp_path: Path):
    db_file = str(tmp_path / "schema_test.db")
    storage = IndexStorage(db_file)
    try:
        tables = {
            r[0]
            for r in storage.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
            ).fetchall()
        }
        assert "code_chunks" in tables
        assert "chunk_fts" in tables
        assert "import_edges" in tables
        if storage.uses_vec:
            assert "chunk_vec" in tables
        else:
            assert "chunk_vec_fallback" in tables

        version = storage.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 3
        assert storage.is_index_empty() is True
    finally:
        storage.close()


def test_insert_chunks_and_neighbors(tmp_path: Path):
    db_file = str(tmp_path / "insert_test.db")
    storage = IndexStorage(db_file)
    try:
        chunks = [
            {
                "id": "c1",
                "file_path": "foo/bar.py",
                "symbol_name": "func_a",
                "symbol_type": "function",
                "start_line": 1,
                "end_line": 10,
                "signature": "def func_a():",
                "docstring": "Docs for func_a",
                "body": "def func_a():\n    pass",
                "content": "def func_a(): pass",
                "content_hash": "hash1",
            },
            {
                "id": "c2",
                "file_path": "foo/bar.py",
                "symbol_name": "func_b",
                "symbol_type": "function",
                "start_line": 12,
                "end_line": 20,
                "signature": "def func_b():",
                "docstring": "Docs for func_b",
                "body": "def func_b():\n    pass",
                "content": "def func_b(): pass",
                "content_hash": "hash2",
            },
        ]
        storage.insert_chunks(chunks, mtime=123.456, commit=True)
        assert storage.is_index_empty() is False

        # Verify FTS
        fts_rows = storage.conn.execute("SELECT chunk_id FROM chunk_fts").fetchall()
        assert {r[0] for r in fts_rows} == {"c1", "c2"}

        # Verify get_neighbors
        neighbors = storage.get_neighbors("c1", radius=3)
        assert len(neighbors) == 2
        assert neighbors[0].symbol_name == "func_a"
        assert neighbors[1].symbol_name == "func_b"
    finally:
        storage.close()


def test_remove_file(tmp_path: Path):
    db_file = str(tmp_path / "remove_test.db")
    storage = IndexStorage(db_file)
    ws = tmp_path
    fpath = tmp_path / "foo" / "bar.py"
    try:
        chunks = [
            {
                "id": "c1",
                "file_path": "foo/bar.py",
                "symbol_name": "func_a",
                "symbol_type": "function",
                "start_line": 1,
                "end_line": 10,
                "signature": "def func_a():",
                "docstring": None,
                "body": "def func_a(): pass",
                "content": "def func_a(): pass",
                "content_hash": "hash1",
            }
        ]
        storage.insert_chunks(chunks, mtime=123.0, commit=True)
        # Add import edge
        storage.conn.execute(
            "INSERT INTO import_edges (importer, imported) VALUES (?, ?)",
            ("foo/bar.py", "foo/baz.py"),
        )
        storage.conn.commit()

        # Remove file
        removed = storage.remove_file(ws, fpath)
        assert removed == 1
        assert storage.is_index_empty() is True

        edge_count = storage.conn.execute(
            "SELECT COUNT(*) FROM import_edges WHERE importer = 'foo/bar.py'"
        ).fetchone()[0]
        assert edge_count == 0
    finally:
        storage.close()

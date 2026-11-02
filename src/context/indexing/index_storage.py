"""
Index Storage — SQLite Storage and Schema Management for CrusorAI Context Engine
==============================================================================

Manages the SQLite database connection, PRAGMA setup, schema definitions,
fts5 virtual tables, vector tables (sqlite-vec vec0 or JSON-blob fallback),
chunk persistence, chunk removal, and neighbor queries.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from src.context.budgeting.context_budget import ContextBudget

EMBED_DIM = 384  # all-MiniLM-L6-v2 output size
SCHEMA_USER_VERSION = 3


def open_database(db_path: str) -> tuple[sqlite3.Connection, bool]:
    """Open a SQLite database with WAL mode and 5s busy timeout.
    Attempts to load sqlite-vec extension. Returns (conn, uses_vec).
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    uses_vec = False
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        uses_vec = True
    except Exception:
        uses_vec = False

    return conn, uses_vec


def init_schema(
    conn: sqlite3.Connection,
    uses_vec: bool,
    write_lock: threading.RLock | threading.Lock,
    embed_dim: int = EMBED_DIM,
) -> bool:
    """Initialize SQLite tables, virtual tables, and indexes.
    Returns True if edge re-sync is needed (migration from older schema).
    """
    with write_lock:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS code_chunks (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                symbol_name TEXT NOT NULL,
                symbol_type TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                signature TEXT,
                docstring TEXT,
                body TEXT,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                modified_time REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON code_chunks(file_path)")

        # Standalone FTS5 (NOT external-content). Managed explicitly in
        # the same transactions as code_chunks.
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                content, file_path, symbol_name,
                chunk_id UNINDEXED
            )
        """)

        if uses_vec:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(
                    chunk_id TEXT PRIMARY KEY,
                    embedding FLOAT[{embed_dim}]
                )
            """)
        else:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunk_vec_fallback (
                    chunk_id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL
                )
            """)

        # v2: file->file import edges for the related-files section.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_edges (
                importer TEXT NOT NULL,
                imported TEXT NOT NULL,
                PRIMARY KEY (importer, imported)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_imported ON import_edges(imported)"
        )
        conn.commit()

    # Migration edge: an existing DB has chunks but no edges.
    needs_edge_resync = False
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_USER_VERSION:
        has_chunks = conn.execute(
            "SELECT 1 FROM code_chunks LIMIT 1"
        ).fetchone()
        needs_edge_resync = bool(has_chunks)
        conn.execute(f"PRAGMA user_version = {SCHEMA_USER_VERSION}")
        conn.commit()

    return needs_edge_resync


def insert_chunks_no_commit(
    conn: sqlite3.Connection,
    chunks: Sequence[dict],
    mtime: float,
    uses_vec: bool,
    embedder: Any = None,
    budget: ContextBudget | None = None,
    ensure_embedder_fn: Optional[Callable[[], None]] = None,
) -> None:
    """Insert chunks into code_chunks, chunk_vec, and chunk_fts without committing.
    The caller must hold the write lock / transaction.
    """
    budget = budget if budget is not None else ContextBudget()
    if budget.expired:
        embeddings: list[list[float] | None] = [None] * len(chunks)
    elif budget.allow_embedding_compute:
        if ensure_embedder_fn is not None:
            ensure_embedder_fn()
        if embedder is None:
            embeddings = [None] * len(chunks)
        else:
            from src.context.memory.embedding_cache import get_embedding_cache
            try:
                vecs = get_embedding_cache().encode(
                    embedder, [c["content"] for c in chunks]
                )
                embeddings = [list(v) for v in vecs]
            except Exception:
                embeddings = [None] * len(chunks)
    elif embedder is not None:
        from src.context.memory.embedding_cache import get_embedding_cache
        cache = get_embedding_cache()
        embeddings = [
            cache.lookup(embedder, c["content"]) for c in chunks
        ]
    else:
        embeddings = [None] * len(chunks)

    vec_table_insert = (
        "INSERT INTO chunk_vec (chunk_id, embedding) VALUES (?, vec_f32(?))"
        if uses_vec else
        "INSERT INTO chunk_vec_fallback (chunk_id, embedding) VALUES (?, ?)"
    )

    for chunk, emb in zip(chunks, embeddings):
        conn.execute("""
            INSERT INTO code_chunks
            (id, file_path, symbol_name, symbol_type, start_line, end_line,
             signature, docstring, body, content, content_hash, modified_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk["id"], chunk["file_path"], chunk["symbol_name"],
            chunk["symbol_type"], chunk["start_line"], chunk["end_line"],
            chunk["signature"], chunk["docstring"], chunk["body"],
            chunk["content"], chunk["content_hash"], mtime,
        ))
        if emb is not None:
            if uses_vec:
                conn.execute(vec_table_insert, (chunk["id"], json.dumps(emb)))
            else:
                conn.execute(vec_table_insert, (chunk["id"], json.dumps(emb).encode("utf-8")))
        conn.execute(
            "INSERT INTO chunk_fts (content, file_path, symbol_name, chunk_id) VALUES (?, ?, ?, ?)",
            (chunk["content"], chunk["file_path"], chunk["symbol_name"], chunk["id"]),
        )


def insert_chunks(
    conn: sqlite3.Connection,
    write_lock: threading.RLock | threading.Lock,
    chunks: Sequence[dict],
    mtime: float,
    commit: bool,
    uses_vec: bool,
    embedder: Any = None,
    budget: ContextBudget | None = None,
    ensure_embedder_fn: Optional[Callable[[], None]] = None,
) -> None:
    """Thread-safe chunk insertion."""
    with write_lock:
        insert_chunks_no_commit(
            conn=conn,
            chunks=chunks,
            mtime=mtime,
            uses_vec=uses_vec,
            embedder=embedder,
            budget=budget,
            ensure_embedder_fn=ensure_embedder_fn,
        )
        if commit:
            conn.commit()


def remove_file(
    conn: sqlite3.Connection,
    write_lock: threading.RLock | threading.Lock,
    workspace: Path,
    file_path: Path,
    uses_vec: bool,
) -> int:
    """Drop all chunks and import edges for a file. Returns count of removed chunks."""
    try:
        rel = str(file_path.relative_to(workspace))
    except ValueError:
        rel = str(file_path)
    rel_alt = rel.replace("\\", "/") if "\\" in rel else rel.replace("/", "\\")

    vec_table = "chunk_vec" if uses_vec else "chunk_vec_fallback"
    with write_lock:
        with conn:
            old_ids = [r[0] for r in conn.execute(
                "SELECT id FROM code_chunks WHERE file_path = ? OR file_path = ?", (rel, rel_alt)
            )]
            for cid in old_ids:
                conn.execute(f"DELETE FROM {vec_table} WHERE chunk_id = ?", (cid,))
                conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (cid,))
            cur = conn.execute(
                "DELETE FROM code_chunks WHERE file_path = ? OR file_path = ?", (rel, rel_alt)
            )
            conn.execute("DELETE FROM import_edges WHERE importer = ? OR importer = ?", (rel, rel_alt))
            return len(old_ids) if old_ids else cur.rowcount


def is_index_empty(
    conn: sqlite3.Connection,
    write_lock: threading.RLock | threading.Lock,
) -> bool:
    """Check if the code_chunks table is empty."""
    with write_lock:
        row = conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()
    return not row or row[0] == 0


def get_neighbors(
    conn: sqlite3.Connection,
    write_lock: threading.RLock | threading.Lock,
    chunk_id: str,
    radius: int = 3,
    chunk_cls: Optional[type] = None,
) -> list[Any]:
    """Retrieve surrounding-chunk context window for a chunk."""
    if chunk_cls is None:
        try:
            from src.context.types import ChunkResult
            chunk_cls = ChunkResult
        except ImportError:
            chunk_cls = dict

    with write_lock:
        row = conn.execute(
            "SELECT file_path, start_line FROM code_chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if not row:
            return []
        file_path, center = row[0], row[1]
        rows = conn.execute("""
            SELECT id, file_path, symbol_name, symbol_type, start_line, end_line,
                   signature, docstring, body
            FROM code_chunks
            WHERE file_path = ? AND start_line BETWEEN ? AND ?
            ORDER BY start_line
        """, (file_path, center - radius * 5, center + radius * 5)).fetchall()

    if chunk_cls is dict:
        return [
            {
                "id": r[0], "file_path": r[1], "symbol_name": r[2], "symbol_type": r[3],
                "start_line": r[4], "end_line": r[5], "signature": r[6] or "",
                "docstring": r[7], "body": r[8] or "", "score": 0.0,
            }
            for r in rows
        ]

    return [
        chunk_cls(
            id=r[0], file_path=r[1], symbol_name=r[2], symbol_type=r[3],
            start_line=r[4], end_line=r[5], signature=r[6] or "",
            docstring=r[7], body=r[8] or "", score=0.0,
        )
        for r in rows
    ]


class IndexStorage:
    """Encapsulates SQLite connection management, schema initialization,
    and storage operations for code chunks and import edges.
    """

    def __init__(
        self,
        db_path: str,
        conn: Optional[sqlite3.Connection] = None,
        write_lock: Optional[threading.RLock] = None,
        embed_dim: int = EMBED_DIM,
    ):
        self.db_path = db_path
        self._write_lock = write_lock if write_lock is not None else threading.RLock()
        self.embed_dim = embed_dim

        if conn is None:
            self.conn, self.uses_vec = open_database(self.db_path)
        else:
            self.conn = conn
            self.uses_vec = False
            try:
                import sqlite_vec
                self.conn.enable_load_extension(True)
                sqlite_vec.load(self.conn)
                self.conn.enable_load_extension(False)
                self.uses_vec = True
            except Exception:
                self.uses_vec = False

        self._needs_edge_resync = False
        self.init_schema()

    def init_schema(self) -> None:
        self._needs_edge_resync = init_schema(
            conn=self.conn,
            uses_vec=self.uses_vec,
            write_lock=self._write_lock,
            embed_dim=self.embed_dim,
        )

    def remove_file(self, workspace: Path, file_path: Path) -> int:
        return remove_file(
            conn=self.conn,
            write_lock=self._write_lock,
            workspace=workspace,
            file_path=file_path,
            uses_vec=self.uses_vec,
        )

    def insert_chunks_no_commit(
        self,
        chunks: Sequence[dict],
        mtime: float,
        embedder: Any = None,
        budget: ContextBudget | None = None,
        ensure_embedder_fn: Optional[Callable[[], None]] = None,
    ) -> None:
        insert_chunks_no_commit(
            conn=self.conn,
            chunks=chunks,
            mtime=mtime,
            uses_vec=self.uses_vec,
            embedder=embedder,
            budget=budget,
            ensure_embedder_fn=ensure_embedder_fn,
        )

    def insert_chunks(
        self,
        chunks: Sequence[dict],
        mtime: float,
        commit: bool = True,
        embedder: Any = None,
        budget: ContextBudget | None = None,
        ensure_embedder_fn: Optional[Callable[[], None]] = None,
    ) -> None:
        insert_chunks(
            conn=self.conn,
            write_lock=self._write_lock,
            chunks=chunks,
            mtime=mtime,
            commit=commit,
            uses_vec=self.uses_vec,
            embedder=embedder,
            budget=budget,
            ensure_embedder_fn=ensure_embedder_fn,
        )

    def is_index_empty(self) -> bool:
        return is_index_empty(conn=self.conn, write_lock=self._write_lock)

    def get_neighbors(
        self,
        chunk_id: str,
        radius: int = 3,
        chunk_cls: Optional[type] = None,
    ) -> list[Any]:
        return get_neighbors(
            conn=self.conn,
            write_lock=self._write_lock,
            chunk_id=chunk_id,
            radius=radius,
            chunk_cls=chunk_cls,
        )

    def close(self) -> None:
        with self._write_lock:
            try:
                self.conn.close()
            except Exception:
                pass


__all__ = [
    "EMBED_DIM",
    "SCHEMA_USER_VERSION",
    "open_database",
    "init_schema",
    "insert_chunks",
    "insert_chunks_no_commit",
    "remove_file",
    "is_index_empty",
    "get_neighbors",
    "IndexStorage",
]

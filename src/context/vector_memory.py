"""
Vector Memory v2 — SQLite-backed semantic retrieval.
Survives restarts. Zero external dependencies (stdlib sqlite3).
"""
import json
import os
import sqlite3
import time
from typing import Any


class VectorMemory:
    """
    Persistent vector memory using SQLite + sentence-transformers embeddings.
    Replaces the in-memory list with a local database file.
    """

    def __init__(self, db_path: str | None = None):
        """
        db_path: SQLite file location. Defaults to ~/.pulseai/vector_memory.db
        """
        if db_path is None:
            db_path = os.path.join(os.path.expanduser("~"), ".pulseai", "vector_memory.db")
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self._embedder = None
        try:
            from src.llm.factory import get_embedder
            self._embedder = get_embedder()
        except Exception as exc:
            raise RuntimeError(
                "VectorMemory requires an embedder. "
                "Install sentence-transformers or configure an embedding provider. "
                f"Error: {exc}"
            )

        self._init_db()

    # ------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON memories(created_at)
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def add(self, text: str, metadata: dict[str, Any] | None = None):
        """Store a memory with its embedding."""
        vector = self._embedder.encode([text], normalize_embeddings=True).tolist()[0]
        vector_blob = json.dumps(vector).encode("utf-8")
        meta_json = json.dumps(metadata or {})

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO memories (text, vector, metadata, created_at) VALUES (?, ?, ?, ?)",
                (text, vector_blob, meta_json, time.time()),
            )
            conn.commit()

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """
        Find top-k memories by cosine similarity to query.

        NOTE: scans the most recent 500 rows and scores them in Python — fine
        for a desktop agent, not a production vector DB. The "timestamp" key
        is an alias of "created_at" for backward compatibility.
        """
        query_vector = self._embedder.encode([query], normalize_embeddings=True).tolist()[0]

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, text, vector, metadata, created_at FROM memories ORDER BY created_at DESC LIMIT 500"
            ).fetchall()

        scored = []
        for row in rows:
            mem_vector = json.loads(row[2].decode("utf-8"))
            score = self._cosine_similarity(query_vector, mem_vector)
            scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, row in scored[:top_k]:
            results.append({
                "id": row[0],
                "text": row[1],
                "metadata": json.loads(row[3]) if row[3] else {},
                "created_at": row[4],
                "timestamp": row[4],  # backward-compat alias
                "score": score,
            })
        return results

    def delete_old(self, max_age_seconds: float = 86400 * 30) -> int:
        """Delete memories older than max_age. Returns count deleted."""
        cutoff = time.time() - max_age_seconds
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM memories WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

    def clear(self) -> None:
        """Wipe all memories. Use with caution."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM memories")
            conn.commit()

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        return sum(a * b for a, b in zip(vec_a, vec_b))

"""
Vector Memory v3 — SQLite-backed semantic retrieval.

Survives restarts. Two retrieval paths:

- **Indexed (default):** sqlite-vec vec0 table does exact KNN in C —
  `vec_distance_l2` verified working on v0.1.9 (same lessons as
  chunk_index.py). Embeddings are unit-normalized, so
  cosine = 1 - L2^2/2 EXACTLY (no max-distance normalization — that
  divides by zero on exact matches).
- **Legacy fallback:** the original "latest 500 rows, score in Python"
  scan, preserved verbatim for environments without sqlite-vec. The
  500-row recency cap is retained there BY DESIGN (behavior freeze).

The v2 bug the indexed path fixes: search silently saw only the newest
500 memories — older memories were un-recallable no matter how relevant.

Migration: zero. The JSON blob column stays the source of truth; the
vec0 table is a derived index, backfilled once at boot and dual-written
on every add() after that. (Blob stays because an external-content-style
managed-by-hand index tables drift lesson is written in chunk_index.py.)
"""
import json
import os
import sqlite3
import time
from typing import Any, Optional

try:
    import sqlite_vec
except Exception:  # pragma: no cover - exercised via monkeypatch in tests
    sqlite_vec = None

# all-MiniLM-L6-v2 output size (matches chunk_index.EMBED_DIM)
EMBED_DIM = 384

# Fallback path keeps the historical behavior exactly: newest 500 rows.
_LEGACY_SCAN_LIMIT = 500


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

        self._uses_vec = False
        self._init_db()

    # ------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Fresh per-call connection (v2 semantics kept — no shared-conn
        threading surface). The sqlite-vec extension must be registered on
        EVERY connection; it is loaded before any statement executes so the
        transaction context never wraps the load."""
        conn = sqlite3.connect(self.db_path)
        if self._uses_vec and sqlite_vec is not None:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        return conn

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

        if sqlite_vec is None:
            return  # legacy scan fallback (documented in module docstring)

        self._uses_vec = True
        with self._connect() as conn:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
                    memory_id INTEGER PRIMARY KEY,
                    embedding FLOAT[{EMBED_DIM}]
                )
            """)
            conn.commit()

        self._backfill_vec_index()

    def _backfill_vec_index(self) -> None:
        """One-time catch-up for DBs written before the vec0 table existed
        (or rows added while sqlite-vec was unavailable). Idempotent."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT m.id, m.vector FROM memories m
                WHERE m.id NOT IN (SELECT memory_id FROM memory_vec)
            """).fetchall()
            for mem_id, blob in rows:
                conn.execute(
                    "INSERT INTO memory_vec(memory_id, embedding) VALUES (?, vec_f32(?))",
                    (mem_id, blob.decode("utf-8")),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def add(self, text: str, metadata: dict[str, Any] | None = None):
        """Store a memory with its embedding."""
        vector = self._embedder.encode([text], normalize_embeddings=True).tolist()[0]
        vector_blob = json.dumps(vector).encode("utf-8")
        meta_json = json.dumps(metadata or {})

        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO memories (text, vector, metadata, created_at) VALUES (?, ?, ?, ?)",
                (text, vector_blob, meta_json, time.time()),
            )
            if self._uses_vec:
                # vec0 parses JSON TEXT into floats; raw bytes are read as a
                # float32 BLOB and rejected (odd length -> OperationalError).
                conn.execute(
                    "INSERT INTO memory_vec(memory_id, embedding) VALUES (?, vec_f32(?))",
                    (cur.lastrowid, json.dumps(vector)),
                )
            conn.commit()

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """
        Find top-k memories by cosine similarity to query.

        Indexed path (default): exact KNN over ALL memories in C.
        Fallback: newest-500 Python scan (pre-v3 behavior, kept verbatim).
        The "timestamp" key is an alias of "created_at" for backward
        compatibility.
        """
        query_vector = self._embedder.encode([query], normalize_embeddings=True).tolist()[0]
        if self._uses_vec:
            return self._search_knn(query_vector, top_k)
        return self._search_scan(query_vector, top_k)

    def _search_knn(self, query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Exact KNN via vec0's MATCH + k constraint, joining the ~top_k
        content rows AFTER limiting. Measured at 20K rows (§25):
        JOIN-then-ORDER-BY materializes the whole join (155ms); MATCH+k
        is 13ms. Ties are NOT order-stable across engines (verified —
        the synthetic word-bucket embedder ties exactly); real embedder
        cosines don't tie, so no explicit tie-break is added."""
        with self._connect() as conn:
            hits = conn.execute("""
                SELECT memory_id, distance FROM memory_vec
                WHERE embedding MATCH vec_f32(?) AND k = ?
                ORDER BY distance
            """, (json.dumps(query_vector), top_k)).fetchall()
            if not hits:
                return []
            ids = [mid for mid, _d in hits]
            rows = conn.execute(
                f"SELECT id, text, metadata, created_at FROM memories WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            ).fetchall()

        by_id = {r[0]: r for r in rows}
        results = []
        for mem_id, distance in hits:
            row = by_id.get(mem_id)
            if row is None:
                continue  # vec/content drift can only come from a crash mid-write
            _id, text, meta, created_at = row
            score = max(0.0, 1.0 - (distance * distance) / 2.0)
            results.append({
                "id": mem_id,
                "text": text,
                "metadata": json.loads(meta) if meta else {},
                "created_at": created_at,
                "timestamp": created_at,  # backward-compat alias
                "score": score,
            })
        return results

    def _search_scan(self, query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
        """Legacy path: newest-500 rows, cosine in Python. Preserved
        verbatim so the no-sqlite-vec environment behaves EXACTLY as v2."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, text, vector, metadata, created_at FROM memories ORDER BY created_at DESC LIMIT ?",
                (_LEGACY_SCAN_LIMIT,),
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
        with self._connect() as conn:
            if self._uses_vec:
                conn.execute(
                    "DELETE FROM memory_vec WHERE memory_id IN (SELECT id FROM memories WHERE created_at < ?)",
                    (cutoff,),
                )
            cur = conn.execute("DELETE FROM memories WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

    def clear(self) -> None:
        """Wipe all memories. Use with caution."""
        with self._connect() as conn:
            if self._uses_vec:
                conn.execute("DELETE FROM memory_vec")
            conn.execute("DELETE FROM memories")
            conn.commit()

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        return sum(a * b for a, b in zip(vec_a, vec_b))

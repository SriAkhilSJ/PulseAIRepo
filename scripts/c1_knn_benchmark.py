"""
C1 benchmark — sqlite-vec full-scan JOIN vs native KNN (MATCH + k)
=================================================================

Debt item C1 (filed in ARCHITECTURE_REVIEW.md §35): `_search_vec_fast` in
src/context/chunk_index.py computed vec_distance_l2 against EVERY row of
chunk_vec (plus a JOIN that only selected back the id it already had),
then sorted and limited. That is an O(N) distance pass per search — the
exact thing the vec0 virtual table's MATCH + k constraint exists to avoid
(pushed into the extension: only the k winners are computed).

This script proves the gap and guards the fix with evidence:

  1. Builds a synthetic chunk_vec/code_chunks pair at 2K / 5K / 20K rows
     (random unit vectors — the same shape all-MiniLM-L6-v2 produces).
  2. Times the OLD query shape and the NEW query shape over N runs.
  3. Asserts the returned id orderings are IDENTICAL (float ties don't
     occur at this precision), so the fix cannot change retrieval quality
     — it only removes wasted work.
  4. If a real ~/.pulseai/code_index_*.db exists, reports the same two
     timings against the founder's actual workspace index.

Run:  python scripts/c1_knn_benchmark.py
"""

from __future__ import annotations

import glob
import json
import math
import os
import random
import sqlite3
import statistics
import tempfile
import time

EMBED_DIM = 384

OLD_SQL = """
    SELECT c.id, vec_distance_l2(v.embedding, vec_f32(?)) AS distance
    FROM chunk_vec v
    JOIN code_chunks c ON v.chunk_id = c.id
    ORDER BY distance
    LIMIT ?
"""

NEW_SQL = """
    SELECT v.chunk_id AS id, v.distance AS distance
    FROM chunk_vec v
    WHERE v.embedding MATCH vec_f32(?) AND k = ?
    ORDER BY v.distance
"""


def _unit_vec(rng: random.Random) -> list[float]:
    vals = [rng.gauss(0.0, 1.0) for _ in range(EMBED_DIM)]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def _build_db(n_rows: int, seed: int = 1234) -> tuple[sqlite3.Connection, str]:
    import sqlite_vec

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(f"""
        CREATE TABLE code_chunks (
            id TEXT PRIMARY KEY, file_path TEXT, symbol_name TEXT,
            symbol_type TEXT, start_line INTEGER, end_line INTEGER,
            signature TEXT, docstring TEXT, body TEXT,
            content TEXT, content_hash TEXT, modified_time REAL
        );
        CREATE VIRTUAL TABLE chunk_vec USING vec0(
            chunk_id TEXT PRIMARY KEY,
            embedding FLOAT[{EMBED_DIM}]
        );
    """)
    rng = random.Random(seed)
    with conn:
        for i in range(n_rows):
            cid = f"chunk-{i:06d}"
            vec = _unit_vec(rng)
            conn.execute(
                "INSERT INTO code_chunks (id, file_path, symbol_name, symbol_type,"
                " start_line, end_line, signature, docstring, body, content,"
                " content_hash, modified_time) VALUES (?, 'f.py', 'sym',"
                " 'function', 1, 2, '', NULL, '', '', 'h', 0.0)",
                (cid,),
            )
            conn.execute(
                "INSERT INTO chunk_vec (chunk_id, embedding) VALUES (?, vec_f32(?))",
                (cid, json.dumps(vec)),
            )
    return conn, path


def _time_query(conn: sqlite3.Connection, sql: str, q: list[float], limit: int,
                runs: int) -> tuple[float, list[str]]:
    timings: list[float] = []
    ids: list[str] = []
    qjson = json.dumps(q)
    for _ in range(runs):
        t0 = time.perf_counter()
        rows = conn.execute(sql, (qjson, limit)).fetchall()
        timings.append((time.perf_counter() - t0) * 1000.0)
        ids = [r[0] for r in rows]
    return statistics.median(timings), ids


def bench_synthetic(n_rows: int, limit: int = 9, runs: int = 15) -> None:
    conn, path = _build_db(n_rows)
    try:
        rng = random.Random(99)
        query = _unit_vec(rng)
        old_ms, old_ids = _time_query(conn, OLD_SQL, query, limit, runs)
        new_ms, new_ids = _time_query(conn, NEW_SQL, query, limit, runs)

        same = old_ids == new_ids
        print(f"  rows={n_rows:>6} limit={limit}  OLD fullscan+join: {old_ms:8.2f}ms"
              f"   NEW match+k: {new_ms:8.2f}ms   speedup: {old_ms / new_ms:6.1f}x")
        if not same:
            # Orderings must be identical; if they are not, the fix is wrong,
            # not just slow — fail loudly.
            raise SystemExit(
                f"FATAL: ordering mismatch at rows={n_rows}\n  old={old_ids[:5]}\n  new={new_ids[:5]}"
            )
    finally:
        conn.close()
        os.unlink(path)


def bench_real_dbs(limit: int = 9, runs: int = 10) -> None:
    import sqlite_vec

    dbs = sorted(glob.glob(os.path.expanduser("~/.pulseai/code_index_*.db")))
    real = [d for d in dbs if not d.endswith(("-shm", "-wal"))]
    if not real:
        print("  (no real code_index DBs found — synthetic results above stand)")
        return
    rng = random.Random(7)
    for db in real:
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            n = conn.execute("SELECT COUNT(*) FROM chunk_vec").fetchone()[0]
            if n == 0:
                print(f"  {os.path.basename(db)}: empty, skipped")
                conn.close()
                continue
            query = _unit_vec(rng)
            old_ms, old_ids = _time_query(conn, OLD_SQL, query, limit, runs)
            new_ms, new_ids = _time_query(conn, NEW_SQL, query, limit, runs)
            verdict = "OK" if len(set(old_ids) ^ set(new_ids)) == 0 else "SET-DIFF!"
            print(f"  {os.path.basename(db)} rows={n:>6}  OLD: {old_ms:7.2f}ms"
                  f"   NEW: {new_ms:7.2f}ms   speedup: {old_ms / max(new_ms, 1e-9):5.1f}x   ids-set: {verdict}")
            conn.close()
        except Exception as exc:  # a half-open WAL DB etc. — report, don't die
            print(f"  {os.path.basename(db)}: skipped ({exc})")


if __name__ == "__main__":
    print("C1 — vec0 full-scan JOIN vs native MATCH+k KNN")
    print("synthetic (random unit vectors, dim=384), median of runs:")
    for n in (2_000, 5_000, 20_000):
        bench_synthetic(n)
    print("real workspace indexes (~/.pulseai/code_index_*.db):")
    bench_real_dbs()
    print("\nOrdering identical at every scale -> the fix changes ONLY wasted work.")

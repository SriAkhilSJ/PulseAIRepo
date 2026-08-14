#!/usr/bin/env python3
"""Pre-flight verification for ChunkIndex (sqlite-vec + FTS5 + extraction).

Run: python scripts/verify_chunk_index.py
Exits non-zero if any hard requirement fails.
"""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

failures = 0


def check(ok, label, detail=""):
    global failures
    mark = "✅" if ok else "❌"
    print(f"{mark} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures += 1


# 1. sqlite-vec import/load
try:
    import sqlite_vec
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    version = conn.execute("SELECT vec_version()").fetchone()[0]
    check(True, f"sqlite-vec loads ({version})")
except Exception as e:
    check(False, "sqlite-vec install/load", str(e))
    sys.exit(1)

# 2. vec0 table + insert + KNN query (syntax verified on v0.1.9)
try:
    conn.execute(
        "CREATE VIRTUAL TABLE test_vec USING vec0(chunk_id TEXT PRIMARY KEY, embedding FLOAT[384])"
    )
    emb = [1.0] + [0.0] * 383
    conn.execute(
        "INSERT INTO test_vec (chunk_id, embedding) VALUES ('a', vec_f32(?))",
        (json.dumps(emb),),
    )
    rows = conn.execute(
        "SELECT chunk_id, vec_distance_l2(embedding, vec_f32(?)) AS d "
        "FROM test_vec ORDER BY d",
        (json.dumps(emb),),
    ).fetchall()
    check(rows and rows[0][0] == "a" and rows[0][1] < 1e-6,
          "vec_f32 insert + vec_distance_l2 KNN query")
except Exception as e:
    check(False, "sqlite-vec KNN syntax", str(e))

# 3. FTS5 standalone with UNINDEXED id + explicit delete
try:
    conn.execute(
        "CREATE VIRTUAL TABLE test_fts USING fts5(content, chunk_id UNINDEXED)"
    )
    conn.execute(
        "INSERT INTO test_fts (content, chunk_id) VALUES ('auth token parser', 'c1')"
    )
    rows = conn.execute(
        "SELECT chunk_id FROM test_fts WHERE test_fts MATCH ? ORDER BY rank",
        ('"auth" OR "token"',),
    ).fetchall()
    ok1 = rows and rows[0][0] == "c1"
    conn.execute("DELETE FROM test_fts WHERE chunk_id = 'c1'")
    rows = conn.execute(
        "SELECT chunk_id FROM test_fts WHERE test_fts MATCH ?",
        ('"auth"',),
    ).fetchall()
    check(ok1 and not rows, "FTS5 standalone + explicit delete (no stale rows)")
except Exception as e:
    check(False, "FTS5 standalone behavior", str(e))

# 4. Cross-thread connection requirement (guards a real past bug)
th_conn = sqlite3.connect(":memory:")
thread_err = []


def _use_cross_thread():
    try:
        th_conn.execute("SELECT 1").fetchone()
    except Exception as e:  # expected: ProgrammingError on default conns
        thread_err.append(type(e).__name__)


import threading

t = threading.Thread(target=_use_cross_thread)
t.start()
t.join()
check(thread_err == ["ProgrammingError"],
      "default sqlite3 rejects cross-thread use (check_same_thread=False is required)")

# 5. AST chunking smoke test
with tempfile.TemporaryDirectory() as td:
    src = Path(td) / "sample.py"
    src.write_text(
        'def add(a, b):\n    """Add two numbers."""\n    return a + b\n\n'
        "class Calc:\n    def mul(self, a, b):\n        return a * b\n"
    )
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.context.chunk_index import extract_chunks

    chunks = extract_chunks(src, Path(td))
    names = [(c["symbol_type"], c["symbol_name"]) for c in chunks]
    check(
        ("module", "(module)") in names
        and ("function", "add") in names
        and ("class", "Calc") in names,
        "AST chunking extracts module + function + class",
    )

if failures:
    print(f"\n{failures} check(s) FAILED")
    sys.exit(1)
print("\n🎉 ALL CHECKS PASSED — ChunkIndex prerequisites verified")

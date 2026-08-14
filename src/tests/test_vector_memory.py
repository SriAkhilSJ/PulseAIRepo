"""VectorMemory v3 — sqlite-vec KNN path (ARCHITECTURE_REVIEW.md §25).

Verifies against the LEGACY scan (preserved verbatim):
  1. parity: identical top-k on small stores (same ranking, ±1e-6 scores)
  2. the v2 recall bug: memories older than the newest-500 window were
     invisible to search; the KNN path sees the whole store
  3. dual-write: memory_vec stays in sync across add/delete_old/clear
  4. fallback: no sqlite-vec -> byte-for-byte legacy behavior
  5. backfill: pre-v3 DBs gain the index on first boot after upgrade

Word-bucket FakeEmbedder, no sentence-transformers, no network.
"""

import hashlib
import math
import re

import pytest

import src.context.vector_memory as vm_mod
from src.context.vector_memory import VectorMemory


class _Embeds(list):
    def tolist(self):
        return list(self)


class FakeEmbedder:
    """Deterministic word-bucket hashing; texts sharing words score higher."""

    DIM = 384

    def encode(self, texts, normalize_embeddings=True):
        out = _Embeds()
        for text in texts:
            vec = [0.0] * self.DIM
            for word in re.findall(r"\w+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0 if (h >> 8) % 2 == 0 else -1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr("src.llm.factory.get_embedder", lambda: FakeEmbedder())
    return VectorMemory(db_path=str(tmp_path / "mem.db"))


def _vec(mem, text):
    return mem._embedder.encode([text], normalize_embeddings=True).tolist()[0]


# Measured physics (probe before assertions, ARCHITECTURE_REVIEW.md §25):
# real matches agree to ~1e-8 (cosine = 1-L2^2/2 == float64 dot); rows at
# the noise floor diverge in ORDER only — float32 vec0 storage turns exact
# zeros into ~2e-7 positives and KNN tie-breaks by rowid while the legacy
# scan tie-breaks by recency. Ordering below the floor is user-invisible,
# so parity is asserted on positive scores only.
_NOISE_FLOOR = 1e-5

_TOPICS = [
    "alpha beta gamma delta",             # query overlap: 3 words
    "echo foxtrot golf hotel",
    "india juliet kilo lima",
    "mike november oscar papa",
    "quebec romeo sierra tango",
    "uniform victor whiskey xray",
    "yankee zulu cobra viper",
    "moon river piano static",
    "crimson tulip saddle winter",
    "alpha beta shared extra one",        # bait: 2-word overlap
    "alpha beta gamma shared extra two",  # bait: 3-word overlap, extra words
    "harbor ledger timber frost",
]


def test_knn_matches_legacy_scan_on_small_store(mem):
    for t in _TOPICS:
        mem.add(t)

    for query in ("alpha beta gamma", "moon river", "timber frost"):
        qv = _vec(mem, query)
        legacy = [r for r in mem._search_scan(qv, 3) if r["score"] > _NOISE_FLOOR]
        knn = [r for r in mem._search_knn(qv, 3) if r["score"] > _NOISE_FLOOR]
        assert legacy, f"fixture broken — no positive match for {query!r}"
        assert [r["id"] for r in knn] == [r["id"] for r in legacy], (
            f"KNN and legacy scan disagree on positive-score ranking for {query!r}"
        )
        for a, b in zip(knn, legacy):
            assert a["score"] == pytest.approx(b["score"], abs=1e-6)


def test_recall_beyond_500_row_window_is_fixed(mem):
    # The planted memory is the OLDEST row — outside the legacy newest-500
    # window — yet the best global match for the query. 4-word memory vs
    # 3-word query gives cosine 3/sqrt(3*4) = 0.866 by construction.
    mem.add("zebra unicorn quixotic telescope")
    for i in range(504):
        mem.add(f"routine housekeeping note number {i} ordinary stuff")

    qv = _vec(mem, "zebra unicorn quixotic")
    legacy = mem._search_scan(qv, 3)
    knn = mem._search_knn(qv, 3)

    assert all("zebra" not in r["text"] for r in legacy), (
        "legacy window unexpectedly saw the oldest row — fixture broken"
    )
    assert "zebra" in knn[0]["text"], (
        "KNN path must recall the global best match regardless of age"
    )
    assert knn[0]["score"] > 0.8


def test_vec_index_stays_in_sync_across_writes(mem, tmp_path):
    import sqlite3

    def vec_count():
        conn = sqlite3.connect(str(tmp_path / "mem.db"))
        conn.enable_load_extension(True)
        vm_mod.sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        n = conn.execute("SELECT COUNT(*) FROM memory_vec").fetchone()[0]
        conn.close()
        return n

    for i in range(5):
        mem.add(f"sync check note {i}")
    assert vec_count() == mem.count() == 5

    assert mem.delete_old(max_age_seconds=0) == 5
    assert vec_count() == mem.count() == 0

    mem.add("one more")
    mem.clear()
    assert vec_count() == mem.count() == 0


def test_fallback_without_sqlite_vec_is_byte_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr("src.llm.factory.get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(vm_mod, "sqlite_vec", None)
    legacy = VectorMemory(db_path=str(tmp_path / "legacy.db"))
    assert legacy._uses_vec is False

    for i in range(8):
        legacy.add(f"fallback path note {i}")
    hits = legacy.search("fallback note", top_k=3)
    assert len(hits) == 3
    assert all("score" in h and "timestamp" in h for h in hits)


def test_preexisting_db_backfills_index_on_upgrade(tmp_path, monkeypatch):
    monkeypatch.setattr("src.llm.factory.get_embedder", lambda: FakeEmbedder())
    db = str(tmp_path / "old.db")

    # Simulate a pre-v3 install: write rows with sqlite-vec unavailable.
    monkeypatch.setattr(vm_mod, "sqlite_vec", None)
    old = VectorMemory(db_path=db)
    for i in range(6):
        old.add(f"ancient memory {i} about legacy")

    # Upgrade: sqlite-vec present again -> boot must backfill.
    monkeypatch.setattr(vm_mod, "sqlite_vec", __import__("sqlite_vec"))
    upgraded = VectorMemory(db_path=db)
    assert upgraded._uses_vec is True
    hits = upgraded.search("ancient legacy", top_k=3)
    assert len(hits) == 3, "backfill did not index pre-existing rows"

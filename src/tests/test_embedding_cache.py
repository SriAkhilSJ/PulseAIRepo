"""D2: embedding cache — kill the ~2N+29 re-encodes per engine turn.

Embeddings are a pure function of (model, normalize flag, text), so the
cache can never serve a stale vector. Every test here is pure/CI-safe:
a deterministic counting embedder, no model downloads, no network.
"""

import hashlib
import math
import threading
from array import array

from langchain_core.messages import SystemMessage

from src.context.context_engine import ContextEngine, TaskClassifier, TaskType
from src.context.embedding_cache import EmbeddingCache


# ---------------------------------------------------------------- helpers


class _FakeBatch:
    """Stand-in for the np.ndarray real embedders return (has .tolist())."""

    def __init__(self, rows):
        self._rows = rows

    def tolist(self):
        return [list(r) for r in self._rows]


class CountingEmbedder:
    """Deterministic per-text vectors + encode counters. dim=8 keeps the
    float32 round-trip trivially auditable."""

    def __init__(self, model_name: str = "fake-minilm", dim: int = 16):
        self.model_name = model_name
        self.dim = dim
        self.calls = 0     # encode() invocations
        self.encoded = 0   # total texts encoded

    def encode(self, texts, normalize_embeddings=True):
        self.calls += 1
        self.encoded += len(texts)
        rows = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            # Zero-centered components: real embedders emit mixed-sign
            # vectors (unrelated texts ~ 0 cosine). An all-positive fake
            # makes EVERYTHING similar — caught via accidental dedup.
            row = [((digest[i] % 32) - 16) / 16.0 for i in range(self.dim)]
            norm = math.sqrt(sum(x * x for x in row))
            if normalize_embeddings and norm:
                row = [x / norm for x in row]
            rows.append(row)
        return _FakeBatch(rows)


def _f32(rows):
    """What the cache stores/returns: float32-rounded values."""
    return [array("f", r).tolist() for r in rows]


def _layer(name: str, content: str) -> SystemMessage:
    return SystemMessage(content=content, response_metadata={"layer": name})


LAYERS = [
    _layer("task", "=== CURRENT TASK ===\nOverall goal: fix the login bug"),
    _layer("plan", "=== PLAN ===\n1. [pending] reproduce\n2. [pending] fix"),
    _layer("progress", "=== PROGRESS ===\nSuccessful steps:\n  (none yet)"),
    _layer("quality", "=== QUALITY STANDARDS ===\nVerify before claiming success"),
    _layer("tone", "=== TONE ===\nBe direct and technical."),
    _layer("repo_map", "=== CODEBASE STRUCTURE (Repo Map) ===\nsrc/auth.py -> login"),
]

TASK = "fix the login bug in auth.py"


def _engine_and_cache(monkeypatch, tmp_path):
    """Offline engine + fresh shared cache + counting embedder, all patched."""
    fake = CountingEmbedder()
    cache = EmbeddingCache()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("src.llm.factory.get_embedder", lambda: fake)
    monkeypatch.setattr(
        "src.context.context_engine.get_embedding_cache", lambda: cache
    )
    eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
    return eng, fake, cache


# ---------------------------------------------------------------- engine paths


def test_warm_turn_reencodes_zero_layers(monkeypatch, tmp_path):
    """The D2 headline: turn 2 of an unchanged session computes NOTHING."""
    eng, fake, _ = _engine_and_cache(monkeypatch, tmp_path)

    eng._score_and_sort_layers(LAYERS, TASK, TaskType.DEBUG)
    after_turn1 = fake.encoded
    assert after_turn1 == 1 + len(LAYERS)  # task + one batch of layers

    eng._score_and_sort_layers(LAYERS, TASK, TaskType.DEBUG)
    assert fake.encoded == after_turn1  # turn 2: zero new vectors


def test_scoring_identical_cold_vs_warm(monkeypatch, tmp_path):
    """Memoization must not change scores by a single bit."""
    eng, _, _ = _engine_and_cache(monkeypatch, tmp_path)
    cold = eng._score_and_sort_layers(LAYERS, TASK, TaskType.DEBUG)
    warm = eng._score_and_sort_layers(LAYERS, TASK, TaskType.DEBUG)
    assert [(s, n.content, t) for s, n, t in cold] == [
        (s, n.content, t) for s, n, t in warm
    ]


def test_dedup_rides_on_scoring_vectors(monkeypatch, tmp_path):
    """Dedup used to re-encode exactly the texts scoring had just encoded."""
    eng, fake, _ = _engine_and_cache(monkeypatch, tmp_path)
    scored = eng._score_and_sort_layers(LAYERS, TASK, TaskType.DEBUG)
    before = fake.encoded
    out = eng._deduplicate_layers(scored)
    assert fake.encoded == before  # zero new encodes
    assert len(out) == len(scored)

    # semantics preserved: a true duplicate still gets removed
    dup = scored + [(0.01, LAYERS[0], 10)]  # same content as the task layer
    assert len(eng._deduplicate_layers(dup)) == len(scored)


def test_ambiguity_constants_encoded_once(monkeypatch, tmp_path):
    """26 module-constant strings were re-encoded every single turn."""
    eng, fake, _ = _engine_and_cache(monkeypatch, tmp_path)
    # NOTE: the task may NOT itself be one of the 26 constants — the cache
    # correctly dedups overlaps (first draft of this test used "make it
    # better", which IS in the ambiguous list: 26 encodes, not 27).
    eng._detect_ambiguity_advanced("make things nicer all around")
    assert fake.encoded == 27  # task + 10 ambiguous + 16 specific

    eng._detect_ambiguity_advanced("polish the rough edges please")
    assert fake.encoded == 28  # only the NEW task string; constants are hits


def test_classifier_query_cached(monkeypatch, tmp_path):
    """The same task string classified across turns encodes once."""
    fake = CountingEmbedder()
    cache = EmbeddingCache()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("src.llm.factory.get_embedder", lambda: fake)
    monkeypatch.setattr(
        "src.context.context_engine.get_embedding_cache", lambda: cache
    )
    clf = TaskClassifier()  # warm-up encodes the prototypes directly (once)
    warmup_total = fake.encoded

    # no regex hit -> embedding path, guaranteed by a nonsense verb phrase
    clf.classify("glorble the schmooze pleasantry")
    assert fake.encoded == warmup_total + 1
    clf.classify("glorble the schmooze pleasantry")
    assert fake.encoded == warmup_total + 1  # cached


# ---------------------------------------------------------------- cache unit


def test_order_and_duplicates_preserved():
    cache, fake = EmbeddingCache(), CountingEmbedder()
    out = cache.encode(fake, ["alpha", "beta", "alpha"])
    assert fake.encoded == 2  # 'alpha' computed once
    assert out[0] == out[2]
    assert out[0] != out[1]


def test_only_changed_text_reencodes():
    cache, fake = EmbeddingCache(), CountingEmbedder()
    first = cache.encode(fake, ["a", "b"])
    assert fake.encoded == 2
    out = cache.encode(fake, ["a", "b2", "c"])
    assert fake.encoded == 4  # b2 and c only
    assert out[0] == first[0]


def test_lru_eviction_bound():
    cache, fake = EmbeddingCache(max_entries=4), CountingEmbedder()
    cache.encode(fake, [f"text-{i}" for i in range(6)])
    assert len(cache) <= 4
    cache.encode(fake, ["text-0"])  # evicted long ago -> computed again
    assert fake.encoded == 7


def test_identity_swap_never_shares_entries():
    cache = EmbeddingCache()
    a, b = CountingEmbedder("model-a"), CountingEmbedder("model-b")
    out_a = cache.encode(a, ["same text"])
    out_b = cache.encode(b, ["same text"])
    # The fake is deterministic per text, so values coincide — the property
    # under test is that model-b was FORCED to compute: its vectors must
    # never share model-a's cache entry.
    assert a.encoded == 1 and b.encoded == 1
    assert out_a == out_b


def test_concurrent_hammer_no_corruption():
    cache, fake = EmbeddingCache(), CountingEmbedder()
    pool = [f"layer-text-{i}" for i in range(60)]
    barrier = threading.Barrier(8)
    errors: list[str] = []

    def worker():
        try:
            barrier.wait(timeout=5)
            for _ in range(150):
                cache.encode(fake, pool)
        except Exception as exc:  # pragma: no cover - asserted empty below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []

    # no corruption: every pooled text is present with the correct vector,
    # and one more pass computes nothing at all.
    expected = _f32(fake.encode(pool).tolist())
    before = fake.encoded
    out = cache.encode(fake, pool)
    assert fake.encoded == before
    assert out == expected

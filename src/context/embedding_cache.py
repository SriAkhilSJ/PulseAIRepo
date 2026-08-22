# src/context/embedding_cache.py
"""Process-wide content-addressed embedding cache (debt D2).

Embeddings are a PURE function of (embedder identity, normalize flag, text):
the same text through the same model always yields the same vector. That
makes them perfectly memoizable — no TTL, no invalidation, no staleness
risk. The only management needed is a memory bound (LRU).

Why this exists — measured per-turn cost of the old code, N = layer count:

    _score_and_sort_layers ....... 1 (task) + N single encode() calls
    _deduplicate_layers .......... N (the SAME layer texts, again)
    _detect_ambiguity_advanced ... 27 (26 of them CONSTANT strings!)
    TaskClassifier ............... 1 (the same task string, re-classified)
    TOTAL ........................ ~2N + 29 encode operations PER TURN

...even though layer texts almost never change between turns (repo map,
memory blocks, plans are stable; the engine's own differential layer cache
already knows this). Session-scoped engines (D1) made it worse: every
dashboard session re-encoded the same workspace texts independently.

After: a steady-state turn encodes ZERO texts. Cold turns additionally win
by batching (the old scoring loop fired N single encode() calls; the cache
encodes all misses in ONE batch — same vectors, far fewer round trips for
API-backed embedders).

Design notes:

- **Key** = sha256(embedder identity + normalize flag + text). Embedder
  identity is model-class + first available of model_name/model/model_id,
  so swapping models never shares entries; the flag is part of the key so a
  future non-normalized call site can never receive normalized vectors.
- **Values** are stored as array('f') (float32) — the native precision of
  the embedder backend (sentence-transformers emits float32), so round-
  tripping is exact in production. Callers receive plain lists, exactly
  what `embedder.encode(...).tolist()` used to hand them.
- **Shared process-wide** (like the shared TaskClassifier): layer texts
  are identical across sessions, so 128 session engines must share hits.
- **Compute outside the lock**: a duplicate encode of the same text under
  a race is harmless (identical output) while serializing embedding
  compute across sessions would be a real latency hit. Locking covers
  lookup/insert/stats only.
"""

from __future__ import annotations

import hashlib
import threading
from array import array
from collections import OrderedDict
from typing import Any, Optional


def _embedder_identity(embedder: Any) -> str:
    """Cache-key identity for an embedder: distinct models must never share
    vectors, even if they see the same text."""
    for attr in ("model_name", "model", "model_id"):
        val = getattr(embedder, attr, None)
        if val:
            return f"{type(embedder).__name__}:{val}"
    return type(embedder).__name__


class EmbeddingCache:
    """Content-addressed LRU memoization for embedding vectors."""

    def __init__(self, max_entries: int = 4096):
        # 4096 x 384-dim float32 ~= 6 MB plus dict overhead — bounded even
        # for the 128-session engine registry with heavy churn.
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._store: "OrderedDict[str, array]" = OrderedDict()
        # Stats (proof + observability; tests pin them).
        self.served = 0     # vectors requested
        self.encoded = 0    # vectors actually computed by the backend
        self.hits = 0

    @staticmethod
    def _key(identity: str, normalize: bool, text: str) -> str:
        h = hashlib.sha256()
        h.update(identity.encode("utf-8", "replace"))
        h.update(b"\x00")
        h.update(b"n1" if normalize else b"n0")
        h.update(b"\x00")
        h.update(text.encode("utf-8", "replace"))
        return h.hexdigest()

    def encode(
        self,
        embedder: Any,
        texts: list[str],
        normalize_embeddings: bool = True,
    ) -> list[list[float]]:
        """Return vectors for `texts` in input order, computing only misses.

        Semantics match `embedder.encode(texts).tolist()` — same values,
        same order, duplicates preserved — minus the compute for any text
        seen before with the same model + normalize flag.
        """
        if not texts:
            return []

        identity = _embedder_identity(embedder)
        coerced = [t if isinstance(t, str) else str(t) for t in texts]
        keys = [self._key(identity, normalize_embeddings, t) for t in coerced]

        results: list[Optional[array]] = [None] * len(coerced)
        missing_keys: "OrderedDict[str, str]" = OrderedDict()  # key -> text (dedup)

        with self._lock:
            self.served += len(coerced)
            for i, key in enumerate(keys):
                vec = self._store.get(key)
                if vec is not None:
                    self._store.move_to_end(key)
                    results[i] = vec
                    self.hits += 1
                else:
                    missing_keys.setdefault(key, coerced[i])

        if missing_keys:
            miss_texts = list(missing_keys.values())
            # Compute OUTSIDE the lock (pure function; a duplicate compute
            # under a race is benign and beats serializing embedder work).
            new_vecs = embedder.encode(
                miss_texts, normalize_embeddings=normalize_embeddings
            ).tolist()
            with self._lock:
                self.encoded += len(new_vecs)
                for key, vec in zip(missing_keys.keys(), new_vecs):
                    self._store[key] = array("f", vec)
                    self._store.move_to_end(key)
                # Fill results BEFORE evicting: a batch larger than the
                # cache's capacity must still return every vector (the LRU
                # then keeps the newest entries). Evicting first drops the
                # batch's own oldest members and leaves None slots — caught
                # by test_lru_eviction_bound.
                for i, key in enumerate(keys):
                    if results[i] is None:
                        results[i] = self._store.get(key)
                while len(self._store) > self._max_entries:
                    self._store.popitem(last=False)  # evict LRU

        if any(v is None for v in results):
            # Unreachable by construction (fill precedes eviction); if this
            # ever fires, a store invariant broke — say so, never return a
            # silently missing vector.
            raise RuntimeError("EmbeddingCache invariant violated: unfilled slot")

        # A backend failure raises above (same as the old direct call), so
        # callers see identical failure semantics to `encode(...).tolist()`.
        return [v.tolist() for v in results]  # type: ignore[union-attr]

    def lookup(
        self,
        embedder: Any,
        text: str,
        normalize_embeddings: bool = True,
    ) -> Optional[list[float]]:
        """Return the CACHED vector for ``text`` WITHOUT computing anything.

        ``None`` when absent. This is the only embedding operation allowed
        inside the synchronous initial-turn deadline: it is a bounded hash
        lookup, so a slow or hung embedder can never block the turn. The
        deadline path of ChunkIndex uses this to consume cache hits and
        defer uncached embeddings.
        """
        identity = _embedder_identity(embedder)
        key = self._key(identity, normalize_embeddings, str(text))
        with self._lock:
            self.served += 1
            vec = self._store.get(key)
            if vec is None:
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return vec.tolist()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# One cache per PROCESS, shared by every session engine (same pattern as
# the shared TaskClassifier). Layer texts are identical across sessions —
# a per-engine cache would pay the warm-up 128 times for nothing.
_SHARED_EMBEDDING_CACHE: Optional[EmbeddingCache] = None
_SHARED_EMBEDDING_CACHE_LOCK = threading.Lock()


def get_embedding_cache() -> EmbeddingCache:
    global _SHARED_EMBEDDING_CACHE
    if _SHARED_EMBEDDING_CACHE is None:
        with _SHARED_EMBEDDING_CACHE_LOCK:
            if _SHARED_EMBEDDING_CACHE is None:
                _SHARED_EMBEDDING_CACHE = EmbeddingCache()
    return _SHARED_EMBEDDING_CACHE

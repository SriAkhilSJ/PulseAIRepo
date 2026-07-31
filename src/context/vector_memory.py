# src/context/vector_memory.py
"""
Vector Memory
=============

This is the agent's long-term memory.

It stores summaries of past tasks and failures as NUMBER VECTORS.
When a new task starts, it finds the most similar past memories
and gives them to the AI so it doesn't repeat old mistakes.

HOW IT WORKS (simple version):

1. "Create a Python API"  ->  [0.1, -0.5, 0.8, ...]
2. "Build a FastAPI server" -> [0.12, -0.48, 0.82, ...]
3. These two vectors are CLOSE because the MEANING is similar
4. The agent retrieves memory #1 when task #2 starts
"""

import hashlib
import math
import re
import time
from collections import Counter
from typing import Any


# =========================================================
# EMBEDDING: Text -> Numbers
# =========================================================

class SimpleEmbedding:
    """
    FREE fallback embedding. No API key needed. No internet needed.

    How it works: Count how many times each word appears, then place those
    counts into a fixed-size vector using a stable hash.

    This is NOT as smart as OpenAI embeddings, but it teaches the concept and
    works without spending money.
    """

    def __init__(self, dimensions: int = 512):
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Turn a list of texts into a list of vectors.
        """
        if not texts:
            return []

        vectors = []

        for text in texts:
            words = self._tokenize(text)
            counts = Counter(words)

            vector = [0.0] * self.dimensions

            for word, count in counts.items():
                index = self._stable_index(word)
                vector[index] += float(count)

            # NORMALIZE: make the vector length = 1.
            # This is required for cosine similarity to work correctly.
            magnitude = math.sqrt(sum(x * x for x in vector))
            if magnitude > 0:
                vector = [x / magnitude for x in vector]

            vectors.append(vector)

        return vectors

    def _tokenize(self, text: str) -> list[str]:
        """Simple word tokenizer with lowercase normalization."""
        return re.findall(r"[a-z0-9_]+", text.lower())

    def _stable_index(self, word: str) -> int:
        """Map a word to a stable vector index."""
        digest = hashlib.md5(word.encode("utf-8")).hexdigest()
        return int(digest, 16) % self.dimensions


# =========================================================
# VECTOR MEMORY: Store and Search
# =========================================================

class VectorMemory:
    """
    An in-memory vector database.

    Stores memories as {text, vector, metadata, timestamp}.
    Searches using cosine similarity.

    "In-memory" means: when you restart the program, memory is lost.
    For production, you would save this to a file or use a real DB.
    """

    def __init__(self, embedding_provider=None):
        """
        embedding_provider: An object with an .embed() method.
                           If None, uses the free SimpleEmbedding.
        """
        if embedding_provider is None:
            embedding_provider = SimpleEmbedding()

        self.embedding_provider = embedding_provider

        # This list holds all memories.
        # Each memory is a dictionary.
        self.memories: list[dict[str, Any]] = []

    def add(self, text: str, metadata: dict[str, Any] | None = None):
        """
        Store a new memory.

        text: What happened (e.g., "Task: Build API. Lesson: Use uv, not npm")
        metadata: Extra info (e.g., {"type": "replan_lesson", "task": "Build API"})
        """
        # Turn the text into a vector of numbers.
        vector = self.embedding_provider.embed([text])[0]

        memory = {
            "text": text,
            "vector": vector,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }

        self.memories.append(memory)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """
        Find the top_k most similar memories to the query.

        query: The new task text (e.g., "Create a Python API")
        top_k: How many memories to return (default 3)

        Returns: List of memory dictionaries, sorted by relevance.
        """
        if not self.memories:
            return []

        # Turn the query into a vector.
        query_vector = self.embedding_provider.embed([query])[0]

        # Score every memory by similarity.
        scored_memories = []

        for memory in self.memories:
            score = self._cosine_similarity(query_vector, memory["vector"])
            scored_memories.append((score, memory))

        # Sort: highest score first.
        scored_memories.sort(key=lambda x: x[0], reverse=True)

        # Return top_k results, including score for debugging/visibility.
        results = []
        for score, memory in scored_memories[:top_k]:
            item = memory.copy()
            item["score"] = score
            results.append(item)

        return results

    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """
        Calculate how similar two vectors are.

        Result: 1.0 = identical, 0.0 = completely different.
        """
        # Both vectors are already normalized (length = 1), so cosine
        # similarity is just the dot product.
        return sum(a * b for a, b in zip(vec_a, vec_b))

    def clear(self):
        """Delete all memories. Useful for testing."""
        self.memories.clear()

    def count(self) -> int:
        """How many memories are stored."""
        return len(self.memories)

"""
Vector Memory v2 — Semantic retrieval using the shared embedder.
"""
import time
from typing import Any


class VectorMemory:
    def __init__(self, embedding_provider=None):
        """
        embedding_provider: ignored — always uses the shared factory embedder
        so the agent uses one consistent embedding model.
        """
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

        self.memories: list[dict[str, Any]] = []

    def add(self, text: str, metadata: dict[str, Any] | None = None):
        vector = self._embedder.encode([text], normalize_embeddings=True).tolist()[0]
        memory = {
            "text": text,
            "vector": vector,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }
        self.memories.append(memory)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if not self.memories:
            return []

        query_vector = self._embedder.encode([query], normalize_embeddings=True).tolist()[0]

        scored = []
        for memory in self.memories:
            score = self._cosine_similarity(query_vector, memory["vector"])
            scored.append((score, memory))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, memory in scored[:top_k]:
            item = memory.copy()
            item["score"] = score
            results.append(item)
        return results

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        return sum(a * b for a, b in zip(vec_a, vec_b))

    def clear(self):
        self.memories.clear()

    def count(self) -> int:
        return len(self.memories)

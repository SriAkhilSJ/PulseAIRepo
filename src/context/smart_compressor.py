"""
Smart Context Compressor for PulseCodeAI v2
============================================
Replaces arbitrary heuristics with semantic relevance scoring.
"""
from typing import Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage


class SmartCompressor:
    """
    Compresses conversation history by semantic relevance to the task,
    not just message type heuristics.
    """

    def __init__(self, model: str | None = None):
        self.model = model
        self._embedder = None
        try:
            from src.llm.factory import get_embedder
            self._embedder = get_embedder()
        except Exception:
            pass

    def compress(
        self,
        history: list[BaseMessage],
        budget: int,
        token_counter: Any,
        task: str = "",
    ) -> list[BaseMessage]:
        """
        Compress history to fit within token budget.
        If task is provided, uses semantic similarity for scoring.
        """
        if not history:
            return []

        task_emb = None
        if self._embedder and task:
            try:
                task_emb = self._embedder.encode([task], normalize_embeddings=True).tolist()[0]
            except Exception:
                pass

        scored = []
        for i, msg in enumerate(history):
            score = self._score_message(msg, i, len(history), task_emb)
            scored.append((score, i, msg))

        scored.sort(key=lambda x: x[0], reverse=True)

        selected = []
        current_tokens = 0
        for score, idx, msg in scored:
            msg_tokens = token_counter([msg], self.model)
            if current_tokens + msg_tokens <= budget:
                selected.append((idx, msg))
                current_tokens += msg_tokens

        selected.sort(key=lambda x: x[0])
        return [msg for _, msg in selected]

    def _score_message(
        self, msg: BaseMessage, index: int, total: int, task_emb: list | None
    ) -> float:
        score = 0.0

        # Recency (newer = more important)
        recency = index / max(total - 1, 1)
        score += recency * 25

        # Base type scores (reduced from v1 — embeddings do the heavy lifting)
        if isinstance(msg, HumanMessage):
            score += 40
        elif isinstance(msg, SystemMessage):
            score += 30
        elif isinstance(msg, AIMessage):
            score += 20
            if getattr(msg, "tool_calls", None):
                score += 15
            content = str(msg.content).lower()
            if any(w in content for w in ["error", "failed", "sorry", "mistake", "wrong"]):
                score += 25
        elif isinstance(msg, ToolMessage):
            score += 10
            content = str(msg.content).lower()
            if any(w in content for w in ["error", "traceback", "failed", "exception"]):
                score += 35
            if "verified" in content or "success" in content:
                score += 15
            if getattr(msg, "name", "") == "think":
                score -= 10

            # SEMANTIC BOOST: tool outputs relevant to task are critical
            if task_emb and self._embedder:
                try:
                    msg_emb = self._embedder.encode(
                        [content[:500]], normalize_embeddings=True
                    ).tolist()[0]
                    sim = sum(a * b for a, b in zip(task_emb, msg_emb))
                    score += sim * 50  # up to +50 for highly relevant output
                except Exception:
                    pass

        # Length penalty
        if len(str(msg.content)) > 2000:
            score -= 8

        return max(score, 0)

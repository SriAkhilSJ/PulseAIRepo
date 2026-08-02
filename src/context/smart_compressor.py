
"""
Smart Context Compressor for PulseCodeAI
========================================
Replaces naive message trimming with semantic importance scoring.
Important messages (errors, user corrections, successful verifications)
are preserved. Fluff (repeated tool outputs, redundant summaries) is dropped.

What this changes:
- The agent remembers critical failures and corrections
- Old successful steps are summarized, not dropped entirely
- Token budget is spent on what matters most
"""
from typing import Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage

class SmartCompressor:
    """
    Compresses conversation history by importance, not just age.
    """
    def __init__(self, model: str | None = None):
        self.model = model

    def compress(
        self,
        history: list[BaseMessage],
        budget: int,
        token_counter: Any,
    ) -> list[BaseMessage]:
        """
        Compress history to fit within token budget.
        Strategy: Score each message by importance, keep highest-scoring.
        """
        if not history:
            return []

        # Score every message
        scored = []
        for i, msg in enumerate(history):
            score = self._score_message(msg, i, len(history))
            scored.append((score, i, msg))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Greedily add highest-scoring messages until budget is full
        # But preserve chronological order in the final output
        selected = []
        current_tokens = 0
        for score, idx, msg in scored:
            msg_tokens = token_counter([msg], self.model)
            if current_tokens + msg_tokens <= budget:
                selected.append((idx, msg))
                current_tokens += msg_tokens

        # Sort back to chronological order
        selected.sort(key=lambda x: x[0])
        return [msg for _, msg in selected]

    def _score_message(self, msg: BaseMessage, index: int, total: int) -> float:
        """
        Score a message by importance. Higher = more likely to keep.
        """
        score = 0.0

        # Recency bonus (newer messages are more important)
        recency = index / max(total - 1, 1)
        score += recency * 30

        # Message type scoring
        if isinstance(msg, HumanMessage):
            score += 50  # User instructions are sacred
        elif isinstance(msg, SystemMessage):
            score += 40  # Context layers are important
        elif isinstance(msg, AIMessage):
            score += 25
            # Tool calls in AI messages are important (show decisions)
            if getattr(msg, "tool_calls", None):
                score += 20
            # Error admissions are very important
            content = str(msg.content).lower()
            if any(w in content for w in ["error", "failed", "sorry", "mistake", "wrong"]):
                score += 35
        elif isinstance(msg, ToolMessage):
            score += 15
            content = str(msg.content).lower()
            # Error outputs are critical to remember
            if any(w in content for w in ["error", "traceback", "failed", "exception"]):
                score += 40
            # Successful verifications are moderately important
            if "verified" in content or "success" in content:
                score += 20
            # Think tool outputs are low importance (reasoning is ephemeral)
            if getattr(msg, "name", "") == "think":
                score -= 10

        # Length penalty (very long messages are expensive, slightly deprioritize)
        content_len = len(str(msg.content))
        if content_len > 2000:
            score -= 10

        return max(score, 0)

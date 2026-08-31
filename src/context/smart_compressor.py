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

    def __init__(
        self,
        model: str | None = None,
        allow_embedding_compute: bool = False,
    ):
        self.model = model
        self._embedder = None
        # Explicit inference policy: the deadline-bound turn path compresses
        # with the deterministic scoring heuristics below — NO model load and
        # NO encode during context preparation. Embedding similarity is
        # enabled exclusively for explicit offline maintenance.
        self.allow_embedding_compute = allow_embedding_compute
        if allow_embedding_compute:
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
        """Compress history to fit within token budget — TURN-ATOMIC.

        Per-message selection (the old behavior) could keep a ToolMessage but
        drop the AIMessage whose tool_call it answers (or vice versa). That is
        not merely incoherent prose — sequences like [ToolMessage] without the
        preceding tool_calls AI turn are PROTOCOL-INVALID for most providers
        (HTTP 400 on send). Messages are therefore grouped into atomic turns:
        a turn starts at a HumanMessage (or a standalone SystemMessage) and
        includes every following AI/tool message up to the next HumanMessage.
        Scoring, budget-fitting, and selection happen per turn.
        """
        if not history:
            return []

        task_emb = None
        if self.allow_embedding_compute and self._embedder and task:
            try:
                task_emb = self._embedder.encode([task], normalize_embeddings=True).tolist()[0]
            except Exception:
                pass

        # 1. Group into atomic turns
        units = self._group_turns(history)

        # 2. Score every message once; a turn's score = its strongest member
        #    (max preserves any high-signal member — an erroring tool result
        #    protects its whole turn, as does the user's own words).
        total = len(history)
        scored_units = []
        flat_index = 0
        for unit in units:
            member_scores = [
                (self._score_message(m, flat_index + j, total, task_emb), j, m)
                for j, m in enumerate(unit)
            ]
            flat_index += len(unit)
            unit_score = max(s for s, _, _ in member_scores)
            first_idx = flat_index - len(unit)
            scored_units.append((unit_score, first_idx, unit))

        # 3. Budget-fit: highest-scoring turns first
        scored_units.sort(key=lambda x: x[0], reverse=True)
        selected: list[tuple[int, list[BaseMessage]]] = []
        current_tokens = 0
        for _score, first_idx, unit in scored_units:
            unit_tokens = sum(token_counter([m], self.model) for m in unit)
            if current_tokens + unit_tokens <= budget:
                selected.append((first_idx, unit))
                current_tokens += unit_tokens

        # 4. Restore chronological order
        selected.sort(key=lambda x: x[0])
        result = [m for _, unit in selected for m in unit]

        # 5. Final validity pass: never emit a ToolMessage whose answering
        #    AIMessage (tool_calls) is absent, and never an AIMessage with
        #    tool_calls whose ToolMessages are absent. (Can only occur if the
        #    input history itself was pre-trimmed mid-turn.)
        return self._enforce_tool_pairing(result)

    @staticmethod
    def _group_turns(history: list[BaseMessage]) -> list[list[BaseMessage]]:
        """Split history into atomic turns.

        A turn starts at a HumanMessage; everything up to the next
        HumanMessage belongs to it (AI replies, tool calls, tool results).
        Stray leading messages (before the first HumanMessage — e.g. an
        AI greeting) form their own preamble unit. SystemMessages found
        inside history stay attached to the unit they landed in.
        """
        units: list[list[BaseMessage]] = []
        current: list[BaseMessage] = []
        for msg in history:
            if isinstance(msg, HumanMessage):
                if current:
                    units.append(current)
                current = [msg]
            else:
                if not current:
                    current = []
                current.append(msg)
        if current:
            units.append(current)
        return units

    @staticmethod
    def _enforce_tool_pairing(messages: list[BaseMessage]) -> list[BaseMessage]:
        """Drop orphaned tool results and unanswered tool calls."""
        answered_call_ids = {
            m.tool_call_id for m in messages
            if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None)
        }
        first_pass: list[BaseMessage] = []
        for m in messages:
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                kept_calls = [
                    c for c in m.tool_calls
                    if (c.get("id") if isinstance(c, dict) else getattr(c, "id", None))
                    in answered_call_ids
                ]
                if kept_calls:
                    if len(kept_calls) == len(m.tool_calls):
                        first_pass.append(m)
                    else:
                        # P6: materialize the FILTERED call list. Appending
                        # the original message kept unanswered tool_calls,
                        # which OpenAI/Anthropic-compatible APIs reject
                        # ("each tool_call must be answered") — a pre-trimmed
                        # mid-turn history could 400 the next request.
                        first_pass.append(AIMessage(
                            content=m.content,
                            tool_calls=kept_calls,
                            id=getattr(m, "id", None),
                        ))
                elif m.content:
                    # AI text without its tool exchange is still valid prose
                    first_pass.append(
                        AIMessage(content=m.content, id=getattr(m, "id", None))
                    )
                continue
            first_pass.append(m)

        valid_call_ids = set()
        for m in first_pass:
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                for c in m.tool_calls:
                    valid_call_ids.add(
                        c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                    )
        return [
            m for m in first_pass
            if not isinstance(m, ToolMessage)
            or getattr(m, "tool_call_id", None) in valid_call_ids
        ]

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

            # SEMANTIC BOOST: tool outputs relevant to task are critical.
            # Explicit offline policy only — a turn never encodes here.
            if task_emb and self._embedder and self.allow_embedding_compute:
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

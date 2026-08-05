# src/context/context_engine.py
"""
Context Engine for PulseCodeAI
================================

Think of this as the agent's "memory organizer."

Before the AI makes any decision, the Context Engine:

1. Looks at the current state (what's happening right now)
2. Picks the most relevant information
3. Organizes it into clean layers
4. Makes sure it fits within the token budget
5. Hands it to the AI

This prevents:

- Token overflow (saving money)
- Confusion (AI only sees what it needs)
- Lost information (important stuff is preserved)
"""

import hashlib
import json
import os
import re
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    ToolMessage,
    AIMessage,
)

from src.context.token_budget import count_tokens, trim_messages_to_budget
from src.context.summarizer import SmartSummarizer
from src.context.memory_manager import MemoryManager
from src.context.repo_map import get_repo_map
from src.config.settings import CONTEXT_MODEL


class TaskType(Enum):
    EXPLORE = "explore"
    DEBUG = "debug"
    CREATE = "create"
    REFACTOR = "refactor"
    TEST = "test"
    EXPLAIN = "explain"
    CHAT = "chat"
    PLAN = "plan"
    RECOVERY = "recovery"


class TaskClassifier:
    """
    Classifies a raw user instruction into a TaskType.
    Uses fast regex heuristics + optional embedding similarity.
    """

    HEURISTICS: dict[TaskType, list[str]] = {
        TaskType.DEBUG: [r"bug|error|fail|traceback|exception|broken|crash|wrong"],
        TaskType.CREATE: [r"create|add|implement|build|write|generate|new file"],
        TaskType.TEST: [r"test|verify|pytest|unittest|assert|validate|check"],
        TaskType.REFACTOR: [r"refactor|restructure|rename|extract|optimize|migrate"],
        TaskType.EXPLORE: [r"find|locate|where is|show me|list|explore|structure"],
        TaskType.EXPLAIN: [r"explain|how does|what does|document|describe|clarify"],
        TaskType.RECOVERY: [r"recover|retry|try again|fix the failure|handle error"],
    }

    PROTOTYPES: dict[TaskType, list[str]] = {
        TaskType.EXPLORE: ["explore the codebase", "find where", "show me the structure"],
        TaskType.DEBUG: ["fix the bug", "debug this error", "why is this failing", "there is a bug", "fix this error", "why is this breaking"],
        TaskType.CREATE: ["create a new feature", "add an endpoint", "implement this"],
        TaskType.REFACTOR: ["refactor this", "restructure", "optimize performance"],
        TaskType.TEST: ["run tests", "verify this works", "pytest"],
        TaskType.EXPLAIN: ["explain this code", "how does this work", "document this"],
        TaskType.CHAT: ["hello", "what can you do", "help"],
        TaskType.RECOVERY: ["try again", "recover from failure", "fix the error"],
    }

    def __init__(self):
        self._embedder = None
        self._prototype_embs: dict[TaskType, list] = {}
        try:
            from src.llm.factory import get_embedder
            self._embedder = get_embedder()
            self._warm_up()
        except Exception:
            pass

    def _warm_up(self) -> None:
        for task_type, texts in self.PROTOTYPES.items():
            self._prototype_embs[task_type] = self._embedder.encode(
                texts, normalize_embeddings=True
            ).tolist()

    def classify(self, task: str) -> TaskType:
        if not task or len(task.strip()) < 3:
            return TaskType.CHAT

        text = task.lower().strip()
        scores: dict[TaskType, float] = {}

        for task_type, patterns in self.HEURISTICS.items():
            for pat in patterns:
                if re.search(pat, text):
                    scores[task_type] = scores.get(task_type, 0.0) + 1.0

        if scores:
            best = max(scores, key=scores.get)
            # High-confidence regex hit (multiple patterns matched): skip embedder
            if scores[best] >= 2.0:
                return best
            # Embedder available: use it to disambiguate lower-confidence hits
            if self._embedder and self._prototype_embs:
                return self._embedding_classify(text)
            # No embedder: use best regex match if any signal exists
            if scores[best] >= 1.0:
                return best

        if self._embedder and self._prototype_embs:
            return self._embedding_classify(text)

        return TaskType.CREATE if len(task) > 60 else TaskType.CHAT

    def _embedding_classify(self, text: str) -> TaskType:
        emb = self._embedder.encode([text], normalize_embeddings=True).tolist()[0]
        best_type = TaskType.CHAT
        best_score = -1.0
        for task_type, proto_embs in self._prototype_embs.items():
            max_sim = max(self._cosine_sim(emb, pe) for pe in proto_embs)
            if max_sim > best_score:
                best_score = max_sim
                best_type = task_type
        return best_type

    @staticmethod
    def _cosine_sim(a: list, b: list) -> float:
        return sum(x * y for x, y in zip(a, b))


class ContextEngine:

    """
    The Context Engine class.

    You create ONE of these when your agent starts.
    It lives for the whole conversation.
    """

    def __init__(
        self,
        max_tokens: int = 8000,
        model: str | None = None,
        llm=None,
        memory_manager: MemoryManager | None = None,
    ):
        """
        max_tokens: How many tokens the AI can handle total.
                    (Check your model context window before raising this.)
        model: Which model you're using (affects token counting).
        """
        self.max_tokens = max_tokens
        self.model = model or CONTEXT_MODEL

        # We reserve some tokens for "context" (the stuff we build)
        # and leave the rest for "history" (past conversation)
        self.context_budget = 3000   # Tokens for our organized context
        self.history_budget = max_tokens - self.context_budget  # Rest for chat history

        # SmartSummarizer compresses long tool outputs before they reach the AI
        # llm=None means: use only free heuristics (recommended for budget)
        # Pass an LLM if you want AI-powered summarization for massive outputs
        self.summarizer = SmartSummarizer(llm=llm)

        # Long-term memory: retrieves relevant past tasks/lessons.
        # If None, the agent has no long-term memory (like before).
        self.memory_manager = memory_manager

        # Differential-update cache
        self._last_state_hash: Optional[str] = None
        self._layer_cache: dict[str, Any] = {}
        self._current_task: Optional[str] = None

        # Layer names actually SENT in the most recent build (post-scoring,
        # post-dedup, post-budget). Used by record_feedback() for true
        # attribution instead of snapshotting the session-wide layer cache.
        self._last_layers_sent: list[str] = []

        # Per-instance copy: _apply_learned_weights() mutates these weights,
        # and the class-level dict would otherwise leak learned drift across
        # ALL engine instances in the process (dashboard sessions, threads).
        import copy
        self.LAYER_RELEVANCE = copy.deepcopy(type(self).LAYER_RELEVANCE)

        # Task classification is read-only after warm-up; reuse one instance
        # instead of re-encoding ~25 prototype embeddings on every turn.
        self._classifier: Optional[TaskClassifier] = None

        # Feedback loop for learning layer weights
        self._feedback_history: list[dict] = []
        self._feedback_path = os.path.join(os.path.expanduser("~"), ".pulseai", "context_feedback.json")
        self._load_feedback()


    # =========================================================
    # MAIN METHOD: Build messages for the AI node
    # =========================================================

    def _hash_state(self, state: dict[str, Any]) -> str:
        """Hash everything except messages (they change every turn)."""
        keys = sorted(k for k in state.keys() if k != "messages")
        payload = json.dumps({k: str(state.get(k)) for k in keys}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _allocate_budget(self, task_type: TaskType) -> tuple[int, int]:
        """
        Return (context_budget, history_budget) based on task type.
        Ratios are tuned: debug needs history, explore needs context.
        """
        ratios = {
            TaskType.EXPLORE:  (0.50, 0.50),
            TaskType.DEBUG:    (0.35, 0.65),
            TaskType.CREATE:   (0.45, 0.55),
            TaskType.REFACTOR: (0.40, 0.60),
            TaskType.TEST:     (0.30, 0.70),
            TaskType.EXPLAIN:  (0.40, 0.60),
            TaskType.CHAT:     (0.20, 0.80),
            TaskType.PLAN:     (0.50, 0.50),
            TaskType.RECOVERY: (0.35, 0.65),
        }
        ctx_ratio, hist_ratio = ratios.get(task_type, (0.40, 0.60))
        ctx = int(self.max_tokens * ctx_ratio)
        return ctx, self.max_tokens - ctx

    # Relevance map: which layers matter for which task types
    LAYER_RELEVANCE: dict[str, dict[TaskType, float]] = {
        "repo_map": {
            # Demoted from v2: chunk-level retrieval (relevant_chunks) now
            # carries the coding context; the map remains king for EXPLORE.
            TaskType.EXPLORE: 1.0, TaskType.CREATE: 0.55, TaskType.REFACTOR: 0.55,
            TaskType.DEBUG: 0.45, TaskType.TEST: 0.35, TaskType.EXPLAIN: 0.55,
            TaskType.CHAT: 0.10, TaskType.PLAN: 0.65, TaskType.RECOVERY: 0.45,
        },
        "relevant_chunks": {
            TaskType.CREATE: 0.95, TaskType.REFACTOR: 0.95, TaskType.DEBUG: 0.95,
            TaskType.EXPLORE: 0.85, TaskType.TEST: 0.80, TaskType.PLAN: 0.80,
            TaskType.RECOVERY: 0.80, TaskType.EXPLAIN: 0.70, TaskType.CHAT: 0.0,
        },
        "task": {t: 1.0 for t in TaskType},
        "plan": {
            TaskType.PLAN: 1.0, TaskType.CREATE: 0.90, TaskType.REFACTOR: 0.90,
            TaskType.DEBUG: 0.80, TaskType.TEST: 0.80, TaskType.RECOVERY: 0.90,
            TaskType.EXPLORE: 0.30, TaskType.EXPLAIN: 0.20, TaskType.CHAT: 0.0,
        },
        "progress": {
            TaskType.DEBUG: 0.90, TaskType.RECOVERY: 0.90, TaskType.TEST: 0.80,
            TaskType.CREATE: 0.60, TaskType.REFACTOR: 0.60, TaskType.PLAN: 0.50,
            TaskType.EXPLORE: 0.20, TaskType.EXPLAIN: 0.10, TaskType.CHAT: 0.0,
        },
        "recovery": {
            TaskType.RECOVERY: 1.0, TaskType.DEBUG: 0.90, TaskType.TEST: 0.50,
            TaskType.CREATE: 0.30, TaskType.REFACTOR: 0.30, TaskType.PLAN: 0.20,
            TaskType.EXPLORE: 0.0, TaskType.EXPLAIN: 0.0, TaskType.CHAT: 0.0,
        },
        "replan": {
            TaskType.RECOVERY: 0.90, TaskType.DEBUG: 0.70, TaskType.PLAN: 0.80,
            TaskType.CREATE: 0.50, TaskType.REFACTOR: 0.50, TaskType.TEST: 0.40,
            TaskType.EXPLORE: 0.0, TaskType.EXPLAIN: 0.0, TaskType.CHAT: 0.0,
        },
        "attempt_history": {
            TaskType.RECOVERY: 1.0, TaskType.DEBUG: 0.90, TaskType.TEST: 0.60,
            TaskType.CREATE: 0.40, TaskType.REFACTOR: 0.40, TaskType.PLAN: 0.30,
            TaskType.EXPLORE: 0.0, TaskType.EXPLAIN: 0.0, TaskType.CHAT: 0.0,
        },
        "long_term_memory": {
            TaskType.CREATE: 0.80, TaskType.REFACTOR: 0.80, TaskType.DEBUG: 0.70,
            TaskType.TEST: 0.60, TaskType.PLAN: 0.70, TaskType.RECOVERY: 0.60,
            TaskType.EXPLORE: 0.30, TaskType.EXPLAIN: 0.40, TaskType.CHAT: 0.10,
        },
        "tool_memory": {
            TaskType.DEBUG: 0.90, TaskType.RECOVERY: 0.90, TaskType.TEST: 0.70,
            TaskType.CREATE: 0.60, TaskType.REFACTOR: 0.60, TaskType.PLAN: 0.40,
            TaskType.EXPLORE: 0.40, TaskType.EXPLAIN: 0.30, TaskType.CHAT: 0.0,
        },
        "ambiguity": {
            TaskType.CREATE: 0.80, TaskType.REFACTOR: 0.80, TaskType.DEBUG: 0.60,
            TaskType.PLAN: 0.90, TaskType.TEST: 0.50, TaskType.RECOVERY: 0.40,
            TaskType.EXPLORE: 0.30, TaskType.EXPLAIN: 0.20, TaskType.CHAT: 0.0,
        },
        "tone": {t: 0.30 for t in TaskType},
        "quality": {t: 0.50 for t in TaskType},
        "conventions": {
            TaskType.CREATE: 0.90, TaskType.REFACTOR: 0.90, TaskType.TEST: 0.70,
            TaskType.DEBUG: 0.50, TaskType.PLAN: 0.60, TaskType.RECOVERY: 0.30,
            TaskType.EXPLORE: 0.20, TaskType.EXPLAIN: 0.30, TaskType.CHAT: 0.0,
        },
        "memory_validation": {
            TaskType.CREATE: 0.60, TaskType.REFACTOR: 0.60, TaskType.DEBUG: 0.70,
            TaskType.RECOVERY: 0.80, TaskType.TEST: 0.50, TaskType.PLAN: 0.50,
            TaskType.EXPLORE: 0.20, TaskType.EXPLAIN: 0.20, TaskType.CHAT: 0.0,
        },
        "reflections": {
            TaskType.DEBUG: 0.80, TaskType.RECOVERY: 0.90, TaskType.TEST: 0.60,
            TaskType.CREATE: 0.50, TaskType.REFACTOR: 0.50, TaskType.PLAN: 0.40,
            TaskType.EXPLORE: 0.20, TaskType.EXPLAIN: 0.20, TaskType.CHAT: 0.10,
        },
        "skills": {
            TaskType.CREATE: 0.80, TaskType.REFACTOR: 0.80, TaskType.TEST: 0.70,
            TaskType.DEBUG: 0.60, TaskType.PLAN: 0.60, TaskType.RECOVERY: 0.40,
            TaskType.EXPLORE: 0.30, TaskType.EXPLAIN: 0.30, TaskType.CHAT: 0.10,
        },
    }

    def build_ai_messages(
        self,
        state: dict[str, Any],
        system_message: SystemMessage,
    ) -> list[BaseMessage]:
        """Adaptive, hierarchical, deduplicated context assembly."""

        # 1. Classify task
        task = state.get("current_task", "")
        self._current_task = task
        if self._classifier is None:
            self._classifier = TaskClassifier()
        task_type = self._classifier.classify(task)

        # 2. Differential state check
        current_hash = self._hash_state(state)
        rebuild_all = current_hash != self._last_state_hash

        # 3. Build layers (task-aware + differential cache)
        if rebuild_all:
            self._layer_cache.clear()
        raw_layers = self._build_context_layers(state, task_type)

        # 4. Score relevance
        scored = self._score_and_sort_layers(raw_layers, task, task_type)

        # 5. Deduplicate
        scored = self._deduplicate_layers(scored)

        # 6. Dynamic budget
        context_budget, history_budget = self._allocate_budget(task_type)

        # 7. Hierarchical assembly: fit highest-relevance layers first
        context_messages = self._assemble_hierarchical(scored, context_budget)

        # 7b. Snapshot the names of layers actually SENT (after scoring,
        # dedup, and budget fit) so record_feedback() can attribute outcomes
        # to the real composition — not the session-wide layer cache.
        self._last_layers_sent = [
            self._infer_layer_name(m) for m in context_messages
        ]

        # 8. Smart history
        raw_history = list(state.get("messages", []))
        raw_history = self._summarize_tool_messages(raw_history)
        trimmed_history = self._trim_history(raw_history, history_budget)

        # 9. Assemble final
        final_messages = [system_message] + context_messages + trimmed_history

        # 10. Cache for next turn
        self._last_state_hash = current_hash

        return final_messages

    def _build_context_layers(self, state: dict[str, Any], task_type: TaskType) -> list[SystemMessage]:
        """Build organized layers, but skip irrelevant ones for this task type."""
        layers = []
        builders = {
            "repo_map": self._repo_map_layer,
            "relevant_chunks": self._relevant_chunks_layer,
            "task": self._task_layer,
            "plan": self._plan_layer,
            "progress": self._progress_layer,
            "recovery": self._recovery_layer,
            "replan": self._replan_layer,
            "attempt_history": self._attempt_history_layer,
            "long_term_memory": self._long_term_memory_layer,
            "tool_memory": self._tool_memory_layer,
            "ambiguity": self._ambiguity_layer,
            "tone": self._tone_layer,
            "quality": self._quality_layer,
            "conventions": self._convention_layer,
            "memory_validation": self._memory_validation_layer,
            "reflections": self._reflection_layer,
            "skills": self._skills_layer,
        }

        # Compute the state hash ONCE for the whole build. (Previously this
        # ran json.dumps + sha256 up to 15x per turn on cache-hit paths.)
        # NOTE: invalidation is COARSE by design — one hash covers all layers,
        # so any state change rebuilds every layer. Correct, just not granular.
        # True per-layer dependency hashing is a deliberate non-goal for now.
        current_hash = self._hash_state(state)

        for name, builder in builders.items():
            relevance_map = self.LAYER_RELEVANCE.get(name, {})
            score = relevance_map.get(task_type, 0.0)
            if score < 0.15:
                continue  # Skip low-value layers entirely

            # Differential check: reuse cached layer if state deps haven't changed
            cached = self._layer_cache.get(name)
            if cached and self._last_state_hash == current_hash:
                layers.append(cached)
                continue

            try:
                msg = builder(state)
                if msg:
                    layers.append(msg)
                    self._layer_cache[name] = msg
            except Exception as exc:
                # Never silent: a masked builder error hid the _quality_layer
                # signature bug for months. Skip the layer, but say so.
                print(f"[ContextEngine] layer '{name}' builder failed: {exc}")
                continue

        return layers

    def _score_and_sort_layers(
        self, layers: list[SystemMessage], task: str, task_type: TaskType
    ) -> list[tuple[float, SystemMessage, int]]:
        """
        Score each layer by: 60% task-type prior + 30% semantic similarity + 10% recency.
        Returns list of (score, message, tokens) sorted by score descending.
        """
        scored = []
        try:
            from src.llm.factory import get_embedder
            embedder = get_embedder()
            task_emb = embedder.encode([task], normalize_embeddings=True).tolist()[0]
        except Exception:
            # Fallback: just use task-type relevance and recency
            for i, msg in enumerate(layers):
                name = self._infer_layer_name(msg)
                rel = self.LAYER_RELEVANCE.get(name, {}).get(task_type, 0.5)
                recency = i / max(len(layers) - 1, 1)
                score = rel * 0.9 + recency * 0.1
                scored.append((score, msg, count_tokens([msg], self.model)))
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored

        for i, msg in enumerate(layers):
            name = self._infer_layer_name(msg)
            base_rel = self.LAYER_RELEVANCE.get(name, {}).get(task_type, 0.5)

            content_emb = embedder.encode([msg.content], normalize_embeddings=True).tolist()[0]
            semantic_sim = sum(a * b for a, b in zip(task_emb, content_emb))

            recency = i / max(len(layers) - 1, 1)
            score = base_rel * 0.60 + semantic_sim * 0.30 + recency * 0.10
            scored.append((score, msg, count_tokens([msg], self.model)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _infer_layer_name(self, msg: SystemMessage) -> str:
        """Infer which layer this message belongs to for relevance lookup."""
        content = msg.content
        if content.startswith("=== CODEBASE STRUCTURE"):
            return "repo_map"
        if content.startswith("=== RELEVANT CODE CHUNKS"):
            return "relevant_chunks"
        if content.startswith("=== CURRENT TASK"):
            return "task"
        if content.startswith("=== PLAN"):
            return "plan"
        if content.startswith("=== PROGRESS"):
            return "progress"
        if content.startswith("=== RECOVERY"):
            return "recovery"
        if content.startswith("=== REPLAN"):
            return "replan"
        if content.startswith("=== PAST ATTEMPTS"):
            return "attempt_history"
        if content.startswith("=== LONG-TERM MEMORY"):
            return "long_term_memory"
        if content.startswith("=== RELEVANT PAST TOOL OUTPUTS"):
            return "tool_memory"
        if content.startswith("=== AMBIGUITY"):
            return "ambiguity"
        if content.startswith("=== TONE"):
            return "tone"
        if content.startswith("=== QUALITY"):
            return "quality"
        if content.startswith("=== PROJECT CONVENTIONS"):
            return "conventions"
        if content.startswith("=== MEMORY STALENESS"):
            return "memory_validation"
        if content.startswith("=== LESSONS FROM PAST"):
            return "reflections"
        if content.startswith("=== ACTIVE SKILLS"):
            return "skills"
        return "unknown"

    def _deduplicate_layers(
        self, scored_layers: list[tuple[float, SystemMessage, int]]
    ) -> list[tuple[float, SystemMessage, int]]:
        """Remove layers that are semantically identical to a higher-scored layer."""
        if len(scored_layers) < 2:
            return scored_layers

        try:
            from src.llm.factory import get_embedder
            embedder = get_embedder()
            texts = [msg.content for _, msg, _ in scored_layers]
            embs = embedder.encode(texts, normalize_embeddings=True).tolist()
        except Exception:
            return scored_layers

        to_remove = set()
        for i in range(len(scored_layers)):
            if i in to_remove:
                continue
            for j in range(i + 1, len(scored_layers)):
                if j in to_remove:
                    continue
                sim = sum(a * b for a, b in zip(embs[i], embs[j]))
                if sim > 0.88:  # Near-duplicate threshold
                    # Keep the higher-scored one
                    if scored_layers[i][0] >= scored_layers[j][0]:
                        to_remove.add(j)
                    else:
                        to_remove.add(i)
                        break

        return [layer for idx, layer in enumerate(scored_layers) if idx not in to_remove]

    def _assemble_hierarchical(
        self,
        scored_layers: list[tuple[float, SystemMessage, int]],
        budget: int,
    ) -> list[SystemMessage]:
        """
        Fit as many high-relevance layers as possible.
        If a layer is too expensive, try to compress it (summary/truncation).
        """
        if not scored_layers:
            return []

        total = sum(tokens for _, _, tokens in scored_layers)
        if total <= budget:
            return [msg for _, msg, _ in scored_layers]

        result = []
        remaining = budget

        for score, msg, tokens in scored_layers:
            if tokens <= remaining:
                result.append(msg)
                remaining -= tokens
                continue

            # Layer too big — try to compress
            compressed = self._compress_layer(msg, remaining)
            if compressed:
                result.append(compressed)
                remaining -= count_tokens([compressed], self.model)

        return result

    def _compress_layer(self, msg: SystemMessage, max_tokens: int) -> Optional[SystemMessage]:
        """Compress a single layer to fit a token budget."""
        content = msg.content

        # Repo map compression: strip symbol details
        if content.startswith("=== CODEBASE STRUCTURE"):
            lines = content.split("\n")
            compressed = []
            for line in lines:
                if " -> " in line:
                    compressed.append(line.split(" -> ")[0])
                else:
                    compressed.append(line)
            candidate = SystemMessage(content="\n".join(compressed))
            if count_tokens([candidate], self.model) <= max_tokens:
                return candidate

        # Generic truncation
        max_chars = int(max_tokens * 3.5)  # rough chars-per-token
        if len(content) > max_chars:
            truncated = content[:max_chars] + "\n... (truncated) ..."
            candidate = SystemMessage(content=truncated)
            if count_tokens([candidate], self.model) <= max_tokens:
                return candidate

        return None


    def _reflection_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 13: Inject lessons learned from past reflections."""
        from src.context.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        lessons = engine.get_recent_lessons(n=2)
        if not lessons:
            return None
        lines = ["=== LESSONS FROM PAST TASKS ==="]
        lines.append("Based on previous work, keep these in mind:\n")
        for lesson in lessons:
            lines.append(f"- {lesson}")
        lines.append("\nApply these lessons to avoid repeating past mistakes.")
        return SystemMessage(content="\n".join(lines))

    def _skills_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 14: Inject user-defined skills relevant to the task."""
        from src.agents.skill_manager import skill_manager
        task = state.get("current_task", "")
        if not task:
            return None
        text = skill_manager.get_skills_text(task)
        if not text:
            return None
        return SystemMessage(content=text)

    def _quality_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 8: Claude-quality response standards reminder.

        (This layer was silently NEVER built for months: it took no `state`
        arg while the builder loop calls builder(state), and the blanket
        try/except in _build_context_layers swallowed the TypeError. Signature
        fixed; the builder loop now warns loudly instead of failing silently.)
        """
        return SystemMessage(content=(
            "=== QUALITY STANDARDS ===\n"
            "As you work, remember to:\n"
            "- Explain your reasoning before taking action\n"
            "- Use markdown formatting for readability\n"
            "- Be honest about uncertainty rather than guessing\n"
            "- Summarize tool results in plain English\n"
            "- Ask clarifying questions when tasks are ambiguous\n"
            "- Verify your work before claiming success\n"
            "- Handle errors gracefully with root-cause analysis\n"
        ))

    def _convention_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 11: Inject learned project conventions."""
        from src.context.convention_learner import ConventionLearner
        workspace = state.get("workspace", ".")
        learner = ConventionLearner()
        text = learner.get_conventions_text(workspace)
        if not text:
            return None
        return SystemMessage(content=text)

    def _memory_validation_layer(
        self,
        state: dict[str, Any],
    ) -> SystemMessage | None:
        """Layer 12: Warn about stale memories."""
        from src.context.memory_validator import MemoryValidator

        # Only run if we actually have memories in context
        query = state.get("current_task", "")
        if not query or not self.memory_manager:
            return None

        memories = self.memory_manager.retrieve_relevant_memories(query, top_k=3)
        if not memories:
            return None

        validator = MemoryValidator(workspace=state.get("workspace", "."))
        validated = validator.validate_memories(memories)

        stale = [m for m in validated if m.get("confidence") == "low"]
        if not stale:
            return None

        lines = ["=== MEMORY STALENESS WARNING ==="]
        lines.append(
            "The following past memories may be outdated. "
            "Verify before relying on them:\n"
        )

        for mem in stale:
            warning = mem.get("stale_warning", "Potentially outdated")
            task_preview = mem.get("task", mem.get("text", "Unknown task"))[:100]
            lines.append(f"- **{task_preview}...**")
            lines.append(f"  ⚠️ {warning}")

        lines.append(
            "\nIf these memories no longer apply, focus on the current "
            "codebase state rather than past solutions."
        )
        return SystemMessage(content="\n".join(lines))

    def _tone_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 9: Adapt tone based on task complexity."""
        from src.context.tone_adapter import ToneAdapter

        task = state.get("current_task", "")
        if not task:
            return None

        adapter = ToneAdapter()
        guidelines = adapter.get_tone_guidelines(task)
        return SystemMessage(content=guidelines)

    def _repo_map_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """
        Layer 0: Structural map of the codebase.

        This helps the agent know WHERE files are without burning tokens on
        recursive directory listings.
        """
        # Only include repo map for coding tasks.
        current_task = state.get("current_task", "")
        if not current_task:
            return None

        # Get workspace from state or default to current dir.
        workspace = state.get("workspace", ".")

        try:
            repo_map_text = get_repo_map(workspace, max_tokens=1200)
        except Exception:
            # If repo map fails, don't break the agent.
            return None

        if not repo_map_text:
            return None

        content = (
            "=== CODEBASE STRUCTURE (Repo Map) ===\n"
            "Use this map to locate files without listing directories.\n"
            "When a task mentions a file or module, check this map first.\n\n"
            f"{repo_map_text}"
        )

        return SystemMessage(content=content)

    def _relevant_chunks_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 0b: chunk-level retrieval (replaces whole-file reads).

        Every failure path returns None — this layer must never break a build,
        including first-run (index still building) and no-embedder environments.
        """
        from src.context.chunk_index import build_relevant_chunks_layer
        return build_relevant_chunks_layer(state)

    def _task_layer(self, state: dict[str, Any]) -> SystemMessage:
        """Layer 1: What is the user trying to do?"""
        current_task = state.get("current_task", "")
        latest_instruction = state.get("latest_instruction", "")

        content = "=== CURRENT TASK ===\n"

        if current_task:
            content += f"Overall goal: {current_task}\n"
        if latest_instruction:
            content += f"Latest instruction: {latest_instruction}\n"

        return SystemMessage(content=content)

    def _plan_layer(self, state: dict[str, Any]) -> SystemMessage:
        """Layer 2: What is our execution plan?"""
        plan = state.get("plan", [])
        plan_goal = state.get("plan_goal", "")

        if not plan:
            return SystemMessage(content="=== PLAN ===\nNo active plan.")

        lines = [f"Plan goal: {plan_goal}"]
        lines.append("")

        for step in plan:
            status = step.get("status", "pending")
            desc = step.get("description", "")
            step_id = step.get("id", "?")
            lines.append(f"{step_id}. [{status}] {desc}")

        lines.append("")
        lines.append(f"All steps completed: {self._is_plan_complete(plan)}")

        return SystemMessage(content="=== PLAN ===\n" + "\n".join(lines))

    def _progress_layer(self, state: dict[str, Any]) -> SystemMessage:
        """Layer 3: What have we done so far?"""
        completed = state.get("steps_completed", [])
        failed = state.get("failed_steps", [])

        lines = ["=== PROGRESS ==="]

        lines.append("\nSuccessful steps:")
        if completed:
            for step in completed[-5:]:  # Only last 5 (keep it short)
                lines.append(f"  ✓ {step}")
        else:
            lines.append("  (none yet)")

        lines.append("\nFailed attempts:")
        if failed:
            for step in failed[-3:]:  # Only last 3 failures
                lines.append(f"  ✗ {step}")
        else:
            lines.append("  (none)")

        return SystemMessage(content="\n".join(lines))

    def _recovery_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 4: Recovery mode info (only if active)."""
        recovery_mode = state.get("recovery_mode", False)
        recovery_attempts = state.get("recovery_attempts", 0)
        recovery_command = state.get("recovery_command")
        failed_steps = state.get("failed_steps", [])

        if not recovery_mode and recovery_attempts == 0:
            return None

        lines = ["=== RECOVERY STATUS ==="]

        if recovery_mode:
            latest_failure = failed_steps[-1] if failed_steps else "Unknown"
            lines.append("RECOVERY MODE IS ACTIVE")
            lines.append(f"Original failed operation: {recovery_command}")
            lines.append(f"Recovery failures: {recovery_attempts}/3")
            lines.append(f"Latest failure: {latest_failure}")
            lines.append("")
            lines.append("Diagnose the root cause before retrying.")
            lines.append("Do NOT repeat the identical failed command.")
        else:
            lines.append(f"Recovery failures during this task: {recovery_attempts}/3")
            lines.append("Recovery mode is not active.")

        return SystemMessage(content="\n".join(lines))

    def _replan_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 5: Replan info (only if we've replanned)."""
        replan_count = state.get("replan_count", 0)

        if replan_count == 0:
            return None

        content = (
            f"=== REPLAN STATUS ===\n"
            f"Automatic replans during this task: {replan_count}/2.\n"
            f"This is separate from recovery attempts.\n"
        )

        # Add a warning if we're close to the limit
        if replan_count >= 2:
            content += "WARNING: Replan limit reached. No more replans allowed.\n"

        return SystemMessage(content=content)

    def _attempt_history_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 6: Summarized history of past attempts (learning memory)."""
        prior_attempts = state.get("prior_attempts", [])

        if not prior_attempts:
            return None

        lines = ["=== PAST ATTEMPTS (LEARN FROM THESE) ==="]

        # Only show last 2 attempts
        for i, attempt in enumerate(prior_attempts[-2:], 1):
            lines.append(f"\nAttempt {i}:")
            lines.append(f"  Strategy: {attempt.get('strategy_summary', 'N/A')}")
            lines.append(f"  Why it failed: {attempt.get('failure_reason', 'N/A')}")
            lines.append(f"  Lesson: {attempt.get('lesson', 'N/A')}")

        lines.append("\nUse these lessons to avoid repeating the same mistakes.")

        return SystemMessage(content="\n".join(lines))

    def _long_term_memory_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """
        Layer 7: Retrieve relevant memories from PAST tasks.

        This is how the agent learns across conversations.
        If the user asked for an API last week, and asks for a server today,
        the agent remembers what worked.
        """
        # If no memory manager is attached, skip this layer.
        if self.memory_manager is None:
            return None

        # Use the current task as the search query.
        query = state.get("current_task", "")

        if not query:
            return None

        # Search for similar past memories.
        memories = self.memory_manager.retrieve_relevant_memories(
            query=query,
            top_k=2,  # Don't overwhelm the AI with too many memories.
        )

        if not memories:
            return None

        lines = ["=== LONG-TERM MEMORY (Relevant Past Tasks) ==="]
        lines.append("The following similar tasks were completed in the past.")
        lines.append("Use these lessons to avoid repeating mistakes.\n")

        for i, memory in enumerate(memories, 1):
            lines.append(f"--- Memory {i} ---")
            lines.append(memory["text"])
            lines.append("")

        return SystemMessage(content="\n".join(lines))

    def _ambiguity_layer(self, state: dict[str, Any]) -> Optional[SystemMessage]:
        task = state.get("current_task", "")
        if not task:
            return None
        return self._detect_ambiguity_advanced(task)

    def _detect_ambiguity_advanced(self, task: str) -> Optional[SystemMessage]:
        ambiguous = [
            "fix it", "make it better", "improve", "update", "refactor",
            "optimize", "clean up", "debug", "solve", "handle this",
        ]
        specific = [
            "file", "function", "class", "method", "module",
            "create", "add", "delete", "rename", "move",
            "test", "bug", "error", "line", "import", "path",
        ]

        try:
            from src.llm.factory import get_embedder
            embedder = get_embedder()
            task_emb = embedder.encode([task], normalize_embeddings=True).tolist()[0]
            amb_embs = embedder.encode(ambiguous, normalize_embeddings=True).tolist()
            spec_embs = embedder.encode(specific, normalize_embeddings=True).tolist()

            amb_sim = max(sum(a * b for a, b in zip(task_emb, e)) for e in amb_embs)
            spec_sim = max(sum(a * b for a, b in zip(task_emb, e)) for e in spec_embs)

            if amb_sim > 0.55 and spec_sim < 0.50:
                return SystemMessage(content=(
                    "=== AMBIGUITY ALERT ===\n"
                    "The current task appears vague or underspecified.\n\n"
                    "Before acting, the agent should consider:\n"
                    "- Which specific file, function, or module needs attention?\n"
                    "- What does 'better' or 'fixed' mean in this context?\n"
                    "- Are there tests, examples, or docs that clarify the goal?\n\n"
                    "If the task remains unclear after checking available context, "
                    "use ask_user() to get clarification rather than making assumptions."
                ))
            return None
        except Exception:
            # Fallback to original heuristic if embedder fails
            return self._detect_ambiguity_fallback(task)

    def _detect_ambiguity_fallback(self, task: str) -> Optional[SystemMessage]:
        vague = ["fix it", "make it better", "improve", "update", "refactor",
                 "optimize", "clean up", "debug", "solve", "handle this",
                 "do it", "change it", "check it", "look at it"]
        specific = ["file", "function", "class", "method", "module",
                    "create", "add ", "delete", "rename", "move ",
                    "test", "bug", "error", "line ", "import ",
                    "path", "directory", "folder", "install"]
        has_vague = any(v in task.lower() for v in vague)
        has_specific = any(s in task.lower() for s in specific)
        if has_vague and not has_specific:
            return SystemMessage(content=(
                "=== AMBIGUITY ALERT ===\n"
                "The current task appears vague or underspecified. "
                "Consider clarifying before acting."
            ))
        return None

    def _tool_memory_layer(self, state: dict[str, Any]) -> Optional[SystemMessage]:
        """
        Retrieve semantically relevant past tool outputs.
        Requires memory_manager to have retrieve_tool_memories() method.
        """
        if not self.memory_manager or not hasattr(self.memory_manager, "retrieve_tool_memories"):
            return None

        query = state.get("current_task", "")
        if not query:
            return None

        try:
            tool_memories = self.memory_manager.retrieve_tool_memories(query, top_k=2)
        except Exception:
            return None

        if not tool_memories:
            return None

        lines = ["=== RELEVANT PAST TOOL OUTPUTS ===", "Previous tool results that may help:\n"]
        for mem in tool_memories:
            tool_name = mem.get("tool", "unknown")
            summary = mem.get("summary", "")[:180]
            lines.append(f"- {tool_name}: {summary}")
        return SystemMessage(content="\n".join(lines))

    def record_feedback(self, success: bool, task: Optional[str] = None) -> None:
        """Call after task completion to learn which layers worked."""
        # Build profile of what was sent this turn
        profile = {
            "timestamp": time.time(),
            "task": task or "",
            "success": success,
            # Attribute to the layers actually sent in the final build.
            # The cache fallback only fires if a task fails before ANY build
            # this session (e.g. planner crash on turn 1) — known-low value,
            # kept so the feedback row is never empty.
            "layers_used": self._last_layers_sent or list(self._layer_cache.keys()),
        }
        self._feedback_history.append(profile)
        if len(self._feedback_history) > 300:
            self._feedback_history = self._feedback_history[-150:]
        self._apply_learned_weights()
        self._save_feedback()

    def _load_feedback(self) -> None:
        if os.path.exists(self._feedback_path):
            try:
                with open(self._feedback_path, "r", encoding="utf-8") as f:
                    self._feedback_history = json.load(f)
            except Exception:
                pass

    def _save_feedback(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._feedback_path), exist_ok=True)
            with open(self._feedback_path, "w", encoding="utf-8") as f:
                json.dump(self._feedback_history, f)
        except Exception:
            pass

    def _apply_learned_weights(self) -> None:
        """Adjust LAYER_RELEVANCE based on historical success/failure."""
        if len(self._feedback_history) < 10:
            return

        from collections import defaultdict
        layer_stats: dict[str, dict] = defaultdict(lambda: {"success": 0, "failure": 0})

        for record in self._feedback_history:
            if record.get("success") is None:
                continue
            for layer_name in record.get("layers_used", []):
                key = "success" if record["success"] else "failure"
                layer_stats[layer_name][key] += 1

        for layer_name, stats in layer_stats.items():
            total = stats["success"] + stats["failure"]
            if total < 5:
                continue
            success_rate = stats["success"] / total
            # Boost layers with >70% success, demote <40%
            for task_type in TaskType:
                current = self.LAYER_RELEVANCE.get(layer_name, {}).get(task_type, 0.5)
                if success_rate > 0.70:
                    self.LAYER_RELEVANCE[layer_name][task_type] = min(1.0, current * 1.03)
                elif success_rate < 0.40:
                    self.LAYER_RELEVANCE[layer_name][task_type] = max(0.0, current * 0.97)

    # =========================================================
    # HISTORY TRIMMING
    # =========================================================

    def _summarize_tool_messages(
        self,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """
        Run every ToolMessage through the SmartSummarizer.

        If a tool output is long, replace it with a short summary.
        If it's short, leave it alone.
        """
        result = []

        for message in messages:
            if isinstance(message, ToolMessage):
                # This might return the same message (if short) or a compressed one
                summarized = self.summarizer.summarize_message(message)
                result.append(summarized)
            else:
                # Not a tool message — leave it alone
                result.append(message)

        return result

    def _trim_history(
        self,
        history: list[BaseMessage],
        budget: int,
    ) -> list[BaseMessage]:
        if not history:
            return []

        from src.context.smart_compressor import SmartCompressor
        compressor = SmartCompressor(model=self.model)
        compressed = compressor.compress(
            history,
            budget=budget,
            token_counter=lambda msgs, model: count_tokens(msgs, model),
            task=self._current_task or "",
        )

        if count_tokens(compressed, self.model) > budget:
            return trim_messages_to_budget(history, budget, self.model)

        return compressed

    # =========================================================
    # HELPER METHODS
    # =========================================================

    @staticmethod
    def _is_plan_complete(plan: list[dict]) -> bool:
        """Check if all plan steps are done."""
        if not plan:
            return False
        return all(step.get("status") == "completed" for step in plan)

    # =========================================================
    # PLANNER CONTEXT METHODS
    # =========================================================

    @staticmethod
    def _planner_prompt(planner_prompt: str) -> str:
        """Add strict output rules so reasoning models return parseable plans."""
        return (
            planner_prompt
            + "\n\nReturn ONLY the final plan as a numbered list."
            + "\nStart every line with a number like `1.`."
            + "\nDo not include analysis, reasoning, headings, examples, markdown, commentary, or duplicate steps."
            + "\nDo not include unrelated filler steps."
            + "\nKeep the plan concise: usually 3-8 steps."
        )

    def build_planner_messages(self, task: str, planner_prompt: str) -> list[BaseMessage]:
        """
        Build messages for the planner node.
        This is simpler — just the prompt + the task.
        """
        return [
            SystemMessage(content=self._planner_prompt(planner_prompt)),
            HumanMessage(content=task),
        ]

    def build_replanner_messages(
        self,
        task: str,
        plan: list[dict],
        failed_steps: list[str],
        planner_prompt: str,
        prior_attempts: list[dict] | None = None,
    ) -> list[BaseMessage]:
        """
        Build messages for the replanner node.
        This includes the original task, completed work, failures,
        and lessons from past attempts.
        """
        completed = [
            step["description"]
            for step in plan
            if step.get("status") == "completed"
        ]

        remaining = [
            step["description"]
            for step in plan
            if step.get("status") != "completed"
        ]

        lines = [
            f"Original task:\n{task}\n",
            "Already completed:",
        ]
        for step in completed:
            lines.append(f"  - {step}")

        lines.append("\nRemaining or blocked work:")
        for step in remaining:
            lines.append(f"  - {step}")

        lines.append("\nFailures:")
        for failure in failed_steps[-3:]:
            lines.append(f"  - {failure}")

        # Add lessons from past attempts
        if prior_attempts:
            lines.append("\n=== LESSONS FROM PAST ATTEMPTS ===")
            for attempt in prior_attempts[-2:]:
                lines.append(f"  - {attempt.get('lesson', 'No lesson recorded')}")

        lines.append("\nCreate a revised plan for ONLY the remaining work.")
        lines.append("Do not repeat completed work.")
        lines.append("Learn from past failures and choose a different approach.")

        return [
            SystemMessage(content=self._planner_prompt(planner_prompt)),
            HumanMessage(content="\n".join(lines)),
        ]

    def build_reviser_messages(
        self,
        task: str,
        plan: list[dict],
        revision: str,
        planner_prompt: str,
    ) -> list[BaseMessage]:
        """Build messages for the plan reviser node."""
        plan_text = "\n".join(
            f"{step.get('id', i)}. {step.get('description', '')}"
            for i, step in enumerate(plan, start=1)
        )

        content = (
            f"Original task:\n{task}\n\n"
            f"Current plan:\n{plan_text}\n\n"
            f"User requested this plan change:\n{revision}\n\n"
            "Revise the current plan according to the user's request.\n"
            "Preserve steps that do not need to change.\n"
            "Return the complete revised plan.\n"
            "Do not execute anything."
        )

        return [
            SystemMessage(content=self._planner_prompt(planner_prompt)),
            HumanMessage(content=content),
        ]

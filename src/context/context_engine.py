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
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    ToolMessage,
    AIMessage,
)

from src.context.bounded_scan import ContextBudget
from src.context.engine import ContextEngine as BaseContextEngine
from src.context.engine import sanitize_memory_context
from src.context.token_budget import count_tokens, trim_messages_to_budget
from src.context.task_types import TaskType  # P9: re-exported for existing imports
from src.context import layer_policy  # P9: scoring/dedup/placement/compression/budget
from src.context import ambiguity, plan_messages  # P10: detector + planner builders
from src.context.usage_pressure import UsagePressure
from src.context.feedback_memory import (
    FEEDBACK_COMPACT_AT,
    FEEDBACK_COMPACT_TO,
    FeedbackMemory,
    make_profile,
)
from src.context.history_shaper import HistoryShaper
from src.context.summarizer import SmartSummarizer
from src.context.memory_manager import MemoryManager
from src.context.repo_map import get_repo_map
from src.context.embedding_cache import get_embedding_cache
from src.config.settings import CONTEXT_MODEL


# P9: TaskType lives in src/context/task_types.py (imported above and
# re-exported so `from src.context.context_engine import TaskType`
# keeps working for every existing caller).


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

    def __init__(self, allow_embedding_compute: bool = False):
        self._embedder = None
        self._prototype_embs: dict[TaskType, list] = {}
        # Explicit inference policy: the deadline-bound turn path classifies
        # with deterministic regex heuristics ONLY. Embedding disambiguation
        # is enabled exclusively for explicit offline maintenance — never for
        # an automatic turn (a cache miss must never trigger inference during
        # context preparation, and no model may load at construction time).
        self.allow_embedding_compute = allow_embedding_compute
        if allow_embedding_compute:
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
            # Embedding disambiguation ONLY under the explicit offline policy
            # (never on the timed turn path): cache hits alone are not enough
            # — a miss would encode. Turn path falls through deterministically.
            if (
                self.allow_embedding_compute
                and self._embedder
                and self._prototype_embs
            ):
                return self._embedding_classify(text)
            # No embedder: use best regex match if any signal exists
            if scores[best] >= 1.0:
                return best

        if (
            self.allow_embedding_compute
            and self._embedder
            and self._prototype_embs
        ):
            return self._embedding_classify(text)

        return TaskType.CREATE if len(task) > 60 else TaskType.CHAT

    def _embedding_classify(self, text: str) -> TaskType:
        emb = get_embedding_cache().encode(self._embedder, [text])[0]
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


# One TaskClassifier per PROCESS, shared by every session engine (D1
# follow-up): ~25 prototype embeddings are encoded at warm-up, and the
# classifier is read-only afterwards (verified) — 128 session engines each
# paying that warm-up was pure waste.
_SHARED_CLASSIFIER: Optional["TaskClassifier"] = None
_SHARED_CLASSIFIER_LOCK = threading.Lock()


def _get_shared_classifier(allow_embedding_compute: bool = False) -> "TaskClassifier":
    """Shared DETERMINISTIC classifier for the turn path.

    The process-wide instance is inference-free (regex-only), so every
    session engine pays zero embedding cost and the shared object is safe
    to reuse. Explicit offline maintenance that genuinely wants embedding
    disambiguation gets a private instance instead of mutating the shared
    one."""
    global _SHARED_CLASSIFIER
    if allow_embedding_compute:
        return TaskClassifier(allow_embedding_compute=True)
    if _SHARED_CLASSIFIER is None:
        with _SHARED_CLASSIFIER_LOCK:
            if _SHARED_CLASSIFIER is None:
                _SHARED_CLASSIFIER = TaskClassifier(allow_embedding_compute=False)
    return _SHARED_CLASSIFIER


class ContextEngine(BaseContextEngine):
    """
    The Context Engine class.

    Engines are session-scoped (one per conversation thread, via the
    chat_graph registry) and live for that conversation.

    P3 (Hermes/OpenClaude alignment): implements the pluggable
    ContextEngine(ABC) from src/context/engine.py — the Hermes-parity
    token-state contract (update_from_response, should_compress,
    compress, get_status, on_turn_complete, on_session_reset). Before P3
    the ABC was ported but dead code; the engine now OWNS the compaction
    decision from the provider's ACTUAL usage instead of only static
    budget trims (Hermes: threshold_percent=0.75 of the real window), and
    surfaces one unified telemetry status (Hermes get_status + OpenClaude
    cacheStatsTracker).
    """

    # P6: the Hermes token-state contract (ABC attributes) is owned by the
    # extracted UsagePressure tracker; these delegating properties keep the
    # documented attribute surface (and the ABC's on_session_reset writes)
    # unchanged while making the tracker the single source of truth.
    @property
    def last_prompt_tokens(self) -> int:
        return self._pressure.last_prompt_tokens

    @last_prompt_tokens.setter
    def last_prompt_tokens(self, value: int) -> None:
        self._pressure.last_prompt_tokens = int(value or 0)

    @property
    def last_completion_tokens(self) -> int:
        return self._pressure.last_completion_tokens

    @last_completion_tokens.setter
    def last_completion_tokens(self, value: int) -> None:
        self._pressure.last_completion_tokens = int(value or 0)

    @property
    def last_total_tokens(self) -> int:
        return self._pressure.last_total_tokens

    @last_total_tokens.setter
    def last_total_tokens(self, value: int) -> None:
        self._pressure.last_total_tokens = int(value or 0)

    @property
    def threshold_tokens(self) -> int:
        return self._pressure.threshold_tokens

    @threshold_tokens.setter
    def threshold_tokens(self, value: int) -> None:
        self._pressure.threshold_tokens = int(value or 0)

    @property
    def _usage_pressure_active(self) -> bool:
        return self._pressure.active

    # P7: the feedback-learning loop (JSONL store + learned layer weights)
    # is owned by the extracted FeedbackMemory; these delegating properties
    # preserve the documented surface — tests re-point _feedback_path and
    # reset _feedback_history AFTER construction, so the module reads both
    # live instead of caching them at load time. The compaction bounds live
    # in feedback_memory (single source of truth); the aliases keep the
    # documented class-attribute surface.
    _FEEDBACK_COMPACT_AT = FEEDBACK_COMPACT_AT
    _FEEDBACK_COMPACT_TO = FEEDBACK_COMPACT_TO
    @property
    def _feedback_history(self) -> list:
        return self._feedback.history

    @_feedback_history.setter
    def _feedback_history(self, value: list) -> None:
        self._feedback.history = list(value)

    @property
    def _feedback_path(self) -> str:
        return self._feedback.path

    @_feedback_path.setter
    def _feedback_path(self, value: str) -> None:
        self._feedback.path = value

    @property
    def _legacy_feedback_path(self) -> str:
        return self._feedback.legacy_path

    @_legacy_feedback_path.setter
    def _legacy_feedback_path(self, value: str) -> None:
        self._feedback.legacy_path = value

    def __init__(
        self,
        max_tokens: int | None = None,
        model: str | None = None,
        llm=None,
        memory_manager: MemoryManager | None = None,
        probe_window: bool = True,
        volatile_tail: bool | None = None,
        thread_id: str | None = None,
    ):
        """
        max_tokens: How many tokens the AI can handle total. None (default)
                    = DYNAMIC discovery: env override -> cache -> static
                    table -> LIVE provider probe -> safe default, then
                    capped at PROVIDER_SAFE_LIMIT so the pre-send guard in
                    RetryLLMProxy never has to amputate our context layers
                    mid-flight (it trims middle-out: the layers die first).
                    Pass an explicit int to override everything.
        model: Which model you're using (affects token counting + budget).
        probe_window: allow the live provider HTTP probe for unknown models
                    (2.5s hard timeout, then cached for a week). Tests pass
                    False to stay offline.
        volatile_tail: D23 position of VOLATILE layers (git_context).
                    True (default): emitted AFTER history — the whole
                    stable block + history is one cache-friendly prefix;
                    only the small volatile tail recomputes on change.
                    False: legacy position (last layer, before history).
                    None = env PULSEAI_VOLATILE_TAIL (default on; "off"
                    restores legacy).
        """
        self.model = model or CONTEXT_MODEL

        # P3 (Hermes parity): usage-pressure episode state — the engine
        # tightens the history budget ONCE when the provider's ACTUAL last
        # prompt crossed the 75% threshold; it re-arms only after usage
        # relaxes below 60% of the window (anti-thrash — a genuinely full
        # window gets one decisive compaction, not one per graph lap).
        # P6: extracted to src/context/usage_pressure.py; this object is the
        # single source of truth for the token-state contract + episode
        # latch (the attribute surface is preserved by the delegating
        # properties above). MUST be created before any _apply_window call:
        # the delegating threshold_tokens setter reads it.
        self._pressure = UsagePressure(self.threshold_percent)

        if volatile_tail is None:
            import os as _os
            volatile_tail = _os.environ.get("PULSEAI_VOLATILE_TAIL", "").lower() != "off"
        self._volatile_tail = volatile_tail

        if max_tokens is not None:
            self.max_tokens = max_tokens
            self.context_window: int | None = None
            self.context_window_source = "explicit"
        else:
            from src.config.settings import PROVIDER_SAFE_LIMIT
            from src.context.model_budgets import resolve_context_window, usable_window_budget
            # Same call as before this file learned about reply caps -- the seam callers and tests patch
            # is resolve_context_window, and re-pointing it at a new function would silently disable
            # every one of them. The cap is a cache read beside it, not a second request.
            window, source = resolve_context_window(self.model, allow_network=probe_window)
            from src.context.model_budgets import max_output_for
            self._apply_window(window, source, max_output_for(self.model))
            usable = usable_window_budget(window, max_output_for(self.model))
            if PROVIDER_SAFE_LIMIT > 0 and usable > PROVIDER_SAFE_LIMIT:
                print(
                    f"[ContextEngine] — set PROVIDER_SAFE_LIMIT=0 to unlock "
                    f"{usable:,}"
                )
            elif PROVIDER_SAFE_LIMIT <= 0:
                print("[ContextEngine] (auto: trusting discovered window)")
            if source == "default" and probe_window:
                # "The endpoint answered nothing inside 12s" and "the endpoint publishes no window" are
                # different facts and the second one is the only one that justifies a permanent guess.
                # So retry it where a slow catalog costs nothing: off the startup path, like Hermes'
                # background fetch_model_metadata at agent_init.py:863.
                self._start_endpoint_retry()

        # We reserve some tokens for "context" (the stuff we build)
        # and leave the rest for "history" (past conversation).
        # NOTE: informational only — _allocate_budget() recomputes the real
        # per-task split from self.max_tokens on every turn.
        self.context_budget = int(self.max_tokens * 0.4)
        self.history_budget = self.max_tokens - self.context_budget

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

        # D19 prompt-cache prefix audit: lazily created per-session recorder
        # (see prompt_cache_audit.py). Records how much of each assembled
        # request is byte-identical to the previous turn's.
        self._cache_audit = None
        self._prompt_cache_scope: str | None = None

        # D22 per-session history compactor (compaction.py) + the whole
        # history-shaping pipeline — P8: extracted to
        # src/context/history_shaper.py (ONE HistoryCompactor shared by the
        # per-turn path and the ABC compress() entry: one anti-thrash state
        # per session). Getters, not values: the engine's model/task/session
        # identity mutate mid-life (update_model, per-build routing), and a
        # shaper that captured them by value would go stale.
        self._shaper = HistoryShaper(
            model=lambda: self.model,
            allow_embedding_compute=lambda: self._allow_embedding_compute,
            summarizer=self.summarizer,
            current_task=lambda: self._current_task or "",
            session_id=lambda: self.thread_id or self._active_thread_id or "",
            context_window=lambda: getattr(self, "context_window", None),
        )

        # P1: this engine's session id. The degraded-scan receipts must carry
        # it (not "unknown") or the session-scoped bridge forwarder drops them.
        self.thread_id: str | None = thread_id or None
        # By-design bounding receipt latch: engines are SESSION-scoped (one
        # per conversation thread), so an instance-level once-latch makes the
        # "workspace exceeds scan budget" receipt fire exactly ONCE per
        # session/turn-set. Measured live (founder-pbr004-1): a 20-lap turn
        # emitted 20 identical receipts — the FACT ("this workspace is bigger
        # than the budget") does not change per graph iteration; re-emitting
        # it per lap is noise and breaks the 1-receipt benchmark contract.
        # Truncation receipts (distinct real events) are NOT latched.
        self._by_design_receipt_emitted = False
        self._active_thread_id: str | None = None

        # Per-instance copy: the feedback learning nudge (FeedbackMemory
        # .apply_learned_weights) mutates these weights,
        # and the class-level dict would otherwise leak learned drift across
        # ALL engine instances in the process (dashboard sessions, threads).
        import copy
        self.LAYER_RELEVANCE = copy.deepcopy(type(self).LAYER_RELEVANCE)

        # Task classification is read-only after warm-up; reuse one instance
        # instead of re-encoding ~25 prototype embeddings on every turn.
        self._classifier: Optional[TaskClassifier] = None

        # Explicit inference policy (P1): the whole pre-model context path —
        # classification, layer scoring/dedup, ambiguity detection, memory
        # retrieval, history compression — is INFERENCE-FREE on the timed
        # path. Only explicit offline maintenance may flip this True.
        self._allow_embedding_compute = False

        # Guards ALL public build/record entry points. Engines are
        # session-scoped (chat_graph registry), but the dashboard can fire
        # two turns for the SAME session concurrently — cache/snapshot/weight
        # mutations must not interleave.
        self._api_lock = threading.RLock()

        # Feedback loop for learning layer weights.
        # P7: extracted to src/context/feedback_memory.py — append-only
        # JSONL store (session-scoped engines + dashboard/CLI processes
        # never overwrite each other's rows), legacy migration, tail
        # compaction, learned-weight nudges. All best-effort: learning
        # data must never block boot or the graph.
        self._feedback = FeedbackMemory()
        self._feedback.load()

        # P3 (OpenClaude promptCacheBreakDetection parity): the
        # "stable prefix regressed" receipt is latched once per session,
        # same contract as the by-design bounding receipt.
        self._cache_break_receipt_emitted = False

        # Set only here, at the end of construction: the background metadata probe reads this
        # before touching budget fields, and must not interleave with __init__'s own derived values.
        self._init_complete = True

    # =========================================================
    # WINDOW / BUDGET APPLICATION (shared by init, reconfigure, update_model)
    # =========================================================


    def _start_endpoint_retry(self) -> None:
        """Re-ask a slow endpoint for its window, in the background, once.

        Blocking startup on a provider's model registry is not an option (that is how a 5-second catalog
        becomes a 5-second app launch), and silently keeping the fallback is worse: it is what made a
        healthy endpoint look like an unsupported one. So the answer is fetched on a daemon thread and
        applied when it is safe -- after __init__ and between builds -- otherwise it is only cached, and
        the next build picks it up from the cache without waiting for anything.
        """
        import threading

        self._meta_thread: threading.Thread | None = None
        try:
            from src.config.settings import CUSTOM_BASE_URL
        except Exception:
            CUSTOM_BASE_URL = None
        if not (CUSTOM_BASE_URL or os.getenv("CUSTOM_BASE_URL")):
            return  # no endpoint to ask; the fallback is the honest answer here, not a timeout

        self._meta_thread = threading.Thread(
            target=self._endpoint_retry_worker,
            args=(self.model,),
            daemon=True,
            name="pulse-model-metadata",
        )
        self._meta_thread.start()

    def _provider_name(self) -> str:
        try:
            from src.config.settings import LLM_PROVIDER
            return LLM_PROVIDER or ""
        except Exception:
            import os
            return os.getenv("LLM_PROVIDER", "") or ""

    def _endpoint_retry_worker(self, model: str) -> None:
        try:
            from src.context.model_budgets import (
                _effective_provider,
                _failure_is_fresh,
                _probe_custom_endpoint,
                _remember_failure,
                _write_cache,
            )

            key = f"{_effective_provider(self._provider_name())}:{(model or '').strip().lower()}"
            if _failure_is_fresh(key):
                # A dead or slow endpoint gets retried in minutes, not on every engine build. The
                # alternative -- re-asking on every construction -- is how a 5s catalog turns into a
                # 5s-per-turn tax, and it is also what Hermes' short failure TTL exists to prevent.
                return
            from src.context.model_budgets import probe_endpoint_limits

            limits = probe_endpoint_limits(model or "")  # the one place the slow ask is allowed
            window = limits[0] if limits else None
            max_output = limits[1] if limits else None
            if not window:
                _remember_failure(key)
        except Exception as exc:  # a background thread must never surface as a mystery crash
            print(f"[ContextEngine] background window probe failed: {exc}")
            return
        if not window:
            print(
                "[ContextEngine] endpoint gave no window on retry either -- budgets stay on the fallback. "
                "Run scripts/model_capabilities_probe.py for the verdict (timeout vs no field)."
            )
            return

        _write_cache(key, window, max_output)

        # Wait briefly for construction to finish; never race a build in flight.
        import time as _time
        for _ in range(60):
            if getattr(self, "_init_complete", False) and getattr(self, "_active_pool", None) is None:
                break
            _time.sleep(0.05)
        if getattr(self, "_init_complete", False) and getattr(self, "_active_pool", None) is None:
            with self._api_lock:
                self._apply_window(window, "custom-api", max_output)
            print(f"[ContextEngine] endpoint reported {window:,} tokens (background); budgets re-applied")
        else:
            print(f"[ContextEngine] endpoint reported {window:,} tokens; cached, applied at the next build")

    def _apply_window(self, window: int, source: str, max_output: int | None = None) -> None:
        """Apply a resolved context window to the engine budget fields.

        The single place where context_window -> (context_window_source,
        max_tokens, context_budget, history_budget, threshold_tokens)
        flows. __init__, reconfigure_model and the ABC update_model all go
        through here so the three entry points cannot drift apart.
        """
        from src.config.settings import PROVIDER_SAFE_LIMIT
        from src.context.model_budgets import usable_window_budget

        self.context_window = int(window) if window else None
        self.context_window_source = source
        # None means the provider stated no reply cap, and the heuristic margin applies. It is NOT zero:
        # reserving nothing is how an oversized payload gets sent, so an unknown cap must stay unknown.
        self.max_output_tokens: int | None = int(max_output) if max_output else None
        if self.context_window:
            usable = usable_window_budget(self.context_window, self.max_output_tokens)
            # AUTO: trust the discovered window; RetryLLMProxy resolves the
            # same number, so engine and guard stay in lockstep.
            cap = usable if PROVIDER_SAFE_LIMIT <= 0 else PROVIDER_SAFE_LIMIT
            self.max_tokens = max(min(usable, cap), 4_096)
            self.context_budget = int(self.max_tokens * 0.4)
            self.history_budget = self.max_tokens - self.context_budget
            # Hermes threshold: the engine owns the compaction decision at
            # 75% of the REAL window (not the trimmed budget).
            self.threshold_tokens = int(self.context_window * self.threshold_percent)
            print(
                f"[ContextEngine] context window {self.context_window:,} for "
                f"{self.model!r} (source: {source}); token budget "
                f"{self.max_tokens:,} (provider cap {cap:,})"
            )

    def reconfigure_model(self, model: str, probe_window: bool = True) -> None:
        """Point THIS engine at a different model without replacing it.

        The per-session registry (chat_graph.get_context_engine) hands every
        node for a thread_id the SAME ContextEngine so the layer cache, the
        _last_layers_sent snapshot, feedback history and learned weights stay
        one object. A node may explicitly select a different model mid-session
        (the config carries a pinned model); the engine must follow it without
        losing that identity. Only model-derived state changes — the caches,
        feedback and weights are session-scoped, not model-scoped.
        """
        new_model = model or CONTEXT_MODEL
        # Same lock that guards build_ai_messages / record_feedback: a model
        # repoint mutates self.model + the budget fields that a concurrent
        # turn reads under _api_lock, so it must be atomic w.r.t. that build.
        # RLock: safe even if a caller already holds it (no nested-lock path
        # today, but the registry's _ENGINES_LOCK is a separate lock and this
        # never calls back into the registry, so no deadlock).
        with self._api_lock:
            if new_model == self.model:
                return
            self.model = new_model
            from src.context.model_budgets import resolve_context_window
            window, source = resolve_context_window(
                self.model, allow_network=probe_window
            )
            self._apply_window(window, source)
            if source == "default" and probe_window:
                # A model switch is exactly when a wrong window matters most, and the endpoint is the
                # only authority on it -- but not worth freezing the switch for, so ask in the background.
                self._start_endpoint_retry()
            print(
                f"[ContextEngine] repointed session engine to model {self.model!r}; "
                f"token budget {self.max_tokens:,} (source: {source})."
            )

    # =========================================================
    # P3 — Hermes/OpenClaude parity: actual-usage-driven engine
    # =========================================================
    #
    # Hermes's ContextEngine owns the compaction decision from the
    # provider's ACTUAL usage (threshold_percent=0.75 of the real window);
    # OpenClaude adds cache-break detection (a REGRESSION in the stable
    # prefix, >5% and >2000 tokens, is an event — not a silent cost) and a
    # unified status surface. Pulse's turn path counts tokens with a
    # heuristic fallback for unlisted models (tiktoken cl100k proxy,
    # measured for sarvam), so the provider's usage number is the ground
    # truth. ai_node feeds it in via update_from_response() after every
    # main-agent call.

    @property
    def name(self) -> str:
        return "layered"

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        """Record the provider's ACTUAL token usage for the last response.

        Canonical buckets (Hermes update_from_response): input/prompt,
        completion, total. The numbers drive should_compress() and the
        per-build usage pressure — the engine never guesses its own window
        pressure from estimates alone.
        """
        if not usage:
            return
        with self._api_lock:
            self._pressure.update(usage, self.context_window)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        """True when ACTUAL prompt usage is at/above the 75% threshold of
        the real window (Hermes semantics). No usage yet -> False (nothing
        to decide)."""
        tokens = int(
            prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        )
        return self._pressure.at_threshold(tokens, self.context_window)

    def should_compress_info(
        self, prompt_tokens: int = None
    ) -> tuple[bool, str | None]:
        if not self.should_compress(prompt_tokens):
            return False, None
        tokens = int(
            prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        )
        return True, (
            f"actual prompt {tokens:,} tokens >= "
            f"{int(self.threshold_percent * 100)}% threshold "
            f"({self.threshold_tokens:,}) of the {int(self.context_window):,} window"
        )

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: Optional[int] = None,
        focus_topic: Optional[str] = None,
        force: bool = False,
        memory_context: str = "",
    ) -> list:
        """Hermes-parity entry: compact a message list toward a
        compressible fraction of the window.

        Accepts LangChain BaseMessage objects OR plain dicts (the Hermes
        wire protocol) and returns the same shape. Head and tail are
        protected, AI(tool_calls)/ToolMessage pairs are never split, and
        the lean tail keeps the newest tool rounds verbatim. Reuses the
        SAME per-session HistoryCompactor as the per-turn path, so
        anti-thrash state (ineffective streak, summary, suppression) is
        shared.
        """
        with self._api_lock:
            if messages and isinstance(messages[0], dict):
                msgs = self._wire_dicts_to_messages(list(messages))
                as_dicts = True
            else:
                msgs = list(messages)
                as_dicts = False
            if not msgs:
                return []
            self._ensure_compactor()
            window = self.context_window or self.max_tokens
            target = max(int(window * 0.5), 1_024)
            if current_tokens and int(current_tokens) > 0:
                target = min(target, max(int(int(current_tokens) * 0.75), 1_024))
            from src.context.smart_compressor import SmartCompressor
            compressor = SmartCompressor(
                model=self.model,
                allow_embedding_compute=self._allow_embedding_compute,
            )
            result = self._compactor.compact(
                msgs,
                target,
                summarize_tools=self._summarize_tool_messages,
                structural_compress=lambda h, b: compressor.compress(
                    h,
                    budget=b,
                    token_counter=lambda m, model: count_tokens(m, model),
                    task=self._current_task or "",
                ),
                fallback_trim=lambda h, b: trim_messages_to_budget(h, b, self.model),
            )
            self.compression_count += 1
            self._invalidate_stable_prefix("compaction")
            if as_dicts:
                return [
                    m.model_dump() if hasattr(m, "model_dump") else dict(m)
                    for m in result
                ]
            return result

    @staticmethod
    def _wire_dicts_to_messages(dicts: List[Dict[str, Any]]) -> list:
        """Convert Hermes/OpenAI wire dicts ({role,type} + content) to
        LangChain messages. Deliberately local: langchain's
        messages_from_dict speaks the CHECKPOINT serialization format
        ({type, data}), not the wire format — the two must not be
        conflated."""
        role_map = {
            "human": HumanMessage, "user": HumanMessage,
            "ai": AIMessage, "assistant": AIMessage,
            "system": SystemMessage,
        }
        out: list = []
        for d in dicts:
            role = str(d.get("type") or d.get("role") or "human").lower()
            content = d.get("content", "")
            if role == "tool":
                out.append(ToolMessage(
                    content=content,
                    tool_call_id=str(d.get("tool_call_id") or d.get("id") or ""),
                    name=str(d.get("name") or "tool"),
                ))
            else:
                cls = role_map.get(role, HumanMessage)
                msg = cls(content=content)
                if role in ("ai", "assistant") and d.get("tool_calls"):
                    try:
                        msg.tool_calls = [
                            (
                                tc if isinstance(tc, dict)
                                else tc.model_dump()
                            )
                            for tc in d["tool_calls"]
                        ]
                    except Exception:
                        pass
                out.append(msg)
        return out

    # P8: the history-shaping pipeline (summarize/compact/trim/telemetry)
    # lives in history_shaper.HistoryShaper; the engine keeps the documented
    # method names — tests monkeypatch _trim_history on the instance and
    # read _compactor (e.g. the kill-switch and one-anti-thrash-state
    # contracts).
    @property
    def _compactor(self):
        return self._shaper.compactor

    def _ensure_compactor(self):
        """Lazily create (once per session) the HistoryCompactor shared by
        the per-turn path AND the ABC compress() entry."""
        return self._shaper.ensure_compactor()

    def _apply_usage_pressure(self, history_budget: int) -> int:
        """Hermes threshold_percent, applied at build time.

        When the provider's ACTUAL last prompt crossed 75% of the real
        window, tighten THIS build's history budget toward the lean-tail
        floor. One tightening per pressure episode (anti-thrash): the flag
        re-arms only after usage has relaxed to <=60% of the window.

        P6: the decision lives in ``usage_pressure.UsagePressure``; the
        engine keeps the side effects (counter, log) as the ONLY owner of
        them — the tightening itself persists for the whole episode, so
        reverting to the base budget mid-episode would resend the oversized
        history into the same overflow.
        """
        tightened, fired, floor = self._pressure.tighten(
            history_budget, self.context_window
        )
        if fired:
            window = int(self.context_window or 0)
            self.compression_count += 1
            print(
                f"[ContextEngine] usage pressure: actual prompt "
                f"{self.last_prompt_tokens:,} >= "
                f"{int(self.threshold_percent * 100)}% of {window:,} window — "
                f"history budget {history_budget:,} -> {tightened:,} "
                f"(lean-tail floor {floor:,})"
            )
        return tightened

    def _emit_cache_break_receipt(self, rec: dict) -> None:
        """OpenClaude promptCacheBreakDetection parity: the stable prefix
        REGRESSED (not just started small) — that is an event. Latched once
        per session (the WHY lives in the audit record; the receipt is the
        flag)."""
        try:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("runtime.cache_break", {
                "thread_id": self.thread_id or "unknown",
                "turn": rec.get("turn"),
                "breaker": rec.get("breaker"),
                "break_msg_idx": rec.get("break_msg_idx"),
                "dropped_chars": rec.get("cache_break_dropped_chars", 0),
                "stable_ratio": rec.get("stable_ratio"),
            })
        except Exception:
            pass  # telemetry must never break a turn

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
        api_mode: str = "",
    ) -> None:
        """ABC entry: re-point the engine at a model. An explicit
        context_length (bridge model registry) is trusted verbatim;
        otherwise the normal discovery chain resolves it."""
        new_model = model or self.model
        if context_length and int(context_length) > 0:
            with self._api_lock:
                self.model = new_model
                self._apply_window(int(context_length), "update-model")
        else:
            self.reconfigure_model(new_model)

    def on_turn_complete(
        self,
        messages: list,
        usage: Dict[str, Any] = None,
        **kwargs: Any,
    ) -> None:
        """ABC hook: end-of-turn ingestion. Folds caller-supplied usage
        into the same actual-usage state as update_from_response."""
        if usage:
            self.update_from_response(usage)

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self._pressure.reset()
        self._cache_break_receipt_emitted = False
        # Law 1 has two sides: reuse the prefix for the whole session, and drop
        # it the moment the session stops being the same conversation. A reset
        # that left the cached prefix behind would replay the previous
        # session's identity, skills index and memory snapshot.
        self._invalidate_stable_prefix("session_reset")

    def _invalidate_stable_prefix(self, reason: str) -> None:
        """Rebuild the 3-tier system prompt on the next turn (compaction/reset)."""
        thread_id = str(getattr(self, "thread_id", "") or "")
        if not thread_id:
            return
        try:  # pyrefly: ignore [missing-import]
            from src.prompts.hermes.session import invalidate_session

            if invalidate_session(thread_id):
                self._stable_prefix_invalidations = int(
                    getattr(self, "_stable_prefix_invalidations", 0)
                ) + 1
                print(f"[ContextEngine] stable system prefix invalidated ({reason}) for {thread_id}")
        except Exception as exc:
            print(f"[ContextEngine] stable-prefix invalidation skipped ({reason}): {exc}")

    def get_status(self) -> Dict[str, Any]:
        """Unified telemetry surface (Hermes get_status + OpenClaude cache
        stats + Pulse compaction counters) — one call for bridge,
        dashboard and diagnostics."""
        base = super().get_status()
        window = int(self.context_window or 0)
        base.update({
            "name": self.name,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "context_window": window,
            "context_window_source": self.context_window_source,
            "threshold_percent": self.threshold_percent,
            "usage_percent": self._pressure.usage_percent(window),
            "usage_pressure_active": self._pressure.active,
            "volatile_tail": bool(self._volatile_tail),
            "compaction": self.compaction_stats(),
            "prompt_cache": self.cache_audit_stats(),
            "stable_prefix_invalidations": int(getattr(self, "_stable_prefix_invalidations", 0)),
        })
        try:  # pyrefly: ignore [missing-import]
            from src.prompts.hermes.session import session_stats

            stats = session_stats({"configurable": {"thread_id": self.thread_id}})
            if stats.get("cached"):
                base["system_prompt"] = {
                    "stable_chars": stats.get("stable_chars"),
                    "context_chars": stats.get("context_chars"),
                    "volatile_chars": stats.get("volatile_chars"),
                    "tools_bound": stats.get("tools_bound"),
                }
        except Exception:
            pass
        return base

    # =========================================================
    # MAIN METHOD: Build messages for the AI node
    # =========================================================

    # D26 (§44): keys the layer builders (and only they) are ALLOWED to
    # depend on. An external review (Aug 7) claimed the differential layer
    # cache "is never hit in normal operation" — measured and CONFIRMED:
    # the hash covered every state key except messages, and chat_graph
    # merges token_usage EVERY ai turn + appends execution_trace EVERY tool
    # action (chat_graph.py:373-375, :871), while NO layer reads them
    # (grepped all 18 builders). Hit rate measured 0/10 turns; with this
    # whitelist, 70% (scripts/review6_adjudicate.py). test_engine_smoke
    # pins the set against the builders' actual state.get usage (AST), so
    # a future layer reading a new key fails loudly here, not silently
    # stale there.
    _HASHED_STATE_KEYS: frozenset[str] = frozenset({
        "current_task", "latest_instruction", "workspace",
        "_autonomous_workspace",
        "plan", "plan_goal",
        "steps_completed", "failed_steps",
        "recovery_mode", "recovery_attempts", "recovery_command",
        "replan_count", "prior_attempts",
        # NOTE: "execution_trace" is deliberately NOT hashed. It is appended
        # on every tool action (chat_graph per-turn noise), and NO layer
        # builder reads it for content — `_progress_layer` renders only
        # steps_completed / failed_steps (both hashed above), which already
        # mark real progress. Hashing execution_trace busted the differential
        # cache on pure trace churn (D26 regression: object identity lost on
        # every turn). Do not re-add it; the AST drift-guard only flags keys
        # that builders actually read, and none do.
        # P1: session identity used to route degraded receipts; stable per
        # session, so hashing it never busts the differential cache.
        "thread_id",
    })

    def _hash_state(self, state: dict[str, Any]) -> str:
        """Hash ONLY the keys layers read (messages excluded by design;
        token_usage/execution_trace excluded as measured noise)."""
        payload = json.dumps(
            {k: str(state.get(k)) for k in sorted(self._HASHED_STATE_KEYS)},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _allocate_budget(self, task_type: TaskType) -> tuple[int, int]:
        """
        Return (context_budget, history_budget) based on task type.
        Ratios are tuned: debug needs history, explore needs context.
        """
        # P9: ratios + arithmetic live in layer_policy.allocate_budget.
        return layer_policy.allocate_budget(self.max_tokens, task_type)

    # P9: the layer policy (D19 canonical emission order, D23 volatile
    # tail, the task-type relevance map) lives in
    # src/context/layer_policy.py. The class attributes are ALIASES, not
    # copies: cache_preservation and tests read them at the class level,
    # and __init__ deep-copies LAYER_RELEVANCE into a per-instance dict
    # that feedback learning mutates — the module-level base is never
    # touched by any engine.
    VOLATILE_LAYERS = layer_policy.VOLATILE_LAYERS
    VOLATILE_TAIL_PREAMBLE = layer_policy.VOLATILE_TAIL_PREAMBLE
    _BUILDER_ORDER = layer_policy.BUILDER_ORDER
    LAYER_RELEVANCE = layer_policy.LAYER_RELEVANCE_BASE

    def build_ai_messages(self, state, system_message):
        """Thread-safe public entry: same-session concurrent turns (the
        dashboard can double-fire a thread) must not interleave the
        cache / _last_layers_sent / hash mutations below."""
        with self._api_lock:
            return self._build_ai_messages(state, system_message)

    def _build_ai_messages(
        self,
        state: dict[str, Any],
        system_message: SystemMessage,
    ) -> list[BaseMessage]:
        """Adaptive, hierarchical, deduplicated context assembly."""

        # 1. Classify task
        task = state.get("current_task", "")
        self._current_task = task
        if self._classifier is None:
            self._classifier = _get_shared_classifier(
                allow_embedding_compute=self._allow_embedding_compute
            )
        task_type = self._classifier.classify(task)

        # 2. Differential state check — #10: the ONE hash computation of the
        # turn; _build_context_layers and the inner builder reuse the slot.
        self._active_state_hash = self._hash_state(state)
        current_hash = self._active_state_hash
        rebuild_all = current_hash != self._last_state_hash

        # 3. Build layers (task-aware + differential cache)
        if rebuild_all:
            self._layer_cache.clear()
        raw_layers = self._build_context_layers(state, task_type)

        # 4. Score relevance
        scored = self._score_and_sort_layers(raw_layers, task, task_type)

        # 5. Deduplicate
        scored = self._deduplicate_layers(scored)

        # 6. Dynamic budget (+ P3 usage pressure: the provider's ACTUAL
        # last-prompt usage can force a tighter history budget than the
        # static per-task ratio — Hermes threshold semantics).
        context_budget, history_budget = self._allocate_budget(task_type)
        history_budget = self._apply_usage_pressure(history_budget)

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
        trimmed_history = self._compact_history(raw_history, history_budget)

        # 9. Assemble final (D23: volatile layers tail the whole prompt —
        # system + stable layers + history becomes one long-lived cache
        # prefix; only the small volatile block recomputes when it changes)
        final_messages = [system_message] + self._position_volatile_tail(
            context_messages, trimmed_history
        )

        # 10. Cache for next turn
        self._last_state_hash = current_hash

        # 11. D19 audit: measure prompt-cache prefix stability turn-over-turn
        # (one prefix compare; cheap enough to be always on). P3: a
        # REGRESSION of the stable prefix (OpenClaude
        # promptCacheBreakDetection: >5% and >~2000 tokens below the
        # session peak) is a first-class event — latched receipt so the
        # bridge/dashboard can surface "cache prefix broke at <owner>".
        if self._cache_audit is None:
            from src.context.prompt_cache_audit import CachePrefixAudit
            self._cache_audit = CachePrefixAudit()
        audit_rec = self._cache_audit.record(final_messages)
        if audit_rec.get("cache_break") and not self._cache_break_receipt_emitted:
            self._cache_break_receipt_emitted = True
            self._emit_cache_break_receipt(audit_rec)

        # 12. P2: resolve rotation-stable prompt-cache scope (prompt_cache_scope.py)
        try:
            from src.context.prompt_cache_scope import resolve_prompt_cache_scope_safe
            scope = resolve_prompt_cache_scope_safe(self)
            if scope:
                self._prompt_cache_scope = scope
            elif self.thread_id:
                self._prompt_cache_scope = self.thread_id
        except Exception:
            pass

        return final_messages

    def prompt_cache_scope(self) -> str | None:
        if self._prompt_cache_scope:
            return self._prompt_cache_scope
        try:
            from src.context.prompt_cache_scope import resolve_prompt_cache_scope_safe
            return resolve_prompt_cache_scope_safe(self)
        except Exception:
            return self.thread_id

    def cache_audit_stats(self) -> dict:
        """D19: prompt-cache prefix-stability report for this session."""
        if self._cache_audit is None:
            return {"turns": 0, "hit_rate": None, "cache_hit_rate": None}
        stats = self._cache_audit.stats()
        if self._prompt_cache_scope:
            stats["prompt_cache_scope"] = self._prompt_cache_scope
        return stats

    def _build_context_layers(self, state: dict[str, Any], task_type: TaskType) -> list[SystemMessage]:
        """Build organized layers, but skip irrelevant ones for this task type.

        P1: wraps the build with ONE shared deadline (scan -> read -> chunk ->
        repo map -> index -> embed). Every file-walking layer derives its
        limits and stop predicate from ``self._active_budget``, so a huge
        workspace degrades to partial context instead of blocking the first
        model call. build_ai_messages holds _api_lock, so the instance slot
        is safe for the duration of the build.
        """
        # P1-fix: ONE shared pool, FAIRLY sliced among the file-walking
        # layers this build will actually run (repo_map, relevant_chunks,
        # conventions). Each walker gets its own slice of ~cap // n_walkers
        # via share(n) — never a fresh full 1,000-file/16 MiB allowance — so
        # the pipeline totals respect the caps and no single walker can
        # consume the whole pool and starve the others. All slices share the
        # same deadline and cancellation hook.
        walkers = [
            name for name in ("repo_map", "relevant_chunks", "conventions")
            if self.LAYER_RELEVANCE.get(name, {}).get(task_type, 0.0) >= 0.15
        ]
        self._active_pool = ContextBudget()
        # P1-fix: the engine build emits ONE aggregate degraded receipt; the
        # walkers record their component summaries instead of competing
        # top-level emissions (all slices share this flag via shared state).
        self._active_pool.collect_receipts = True
        if self.thread_id:
            from src.runtime.turn_control import turn_controls
            self._active_pool.extra_stop = lambda: turn_controls.cancelled(self.thread_id)
        self._active_budget = None
        # P1: route degraded-scan receipts to THIS session. Graph state does
        # not carry thread_id (it lives in config), so the engine's own id
        # (set by get_context_engine) is the authoritative fallback.
        self._active_thread_id = (
            self.thread_id or str(state.get("thread_id") or "") or None
        )
        self._active_workspace = str(state.get("workspace") or ".")
        # #10: hash the state ONCE per turn. _build_ai_messages normally
        # computed it already (differential check); only compute here when
        # called directly.
        if getattr(self, "_active_state_hash", None) is None:
            self._active_state_hash = self._hash_state(state)
        try:
            layers = self._build_context_layers_inner(state, task_type, walkers)
            self._emit_build_receipt()
            return layers
        finally:
            self._active_budget = None
            self._active_pool = None
            self._active_thread_id = None
            self._active_workspace = None
            self._active_state_hash = None

    @staticmethod
    def _workspace_exceeds_budget(workspace: str, cap: int) -> bool:
        """Bounded probe: does the workspace hold MORE entries than the scan
        budget could ever consider? Counting stops as soon as the total
        exceeds ``cap`` (listdir lengths are O(1)), with a visited-directory
        guard for pathological deep trees; no file content is read. Used for
        the by-design bounding receipt (PBR-004): when the raw workspace
        exceeds the budget, the bound is ACTIVELY protecting the turn and a
        receipt is owed even if skip rules pruned everything without a
        mid-walk truncation."""
        import os as _os
        seen = 0
        roots = 0
        try:
            if _os.path.isfile(workspace):
                return False
            for _root, dirs, files in _os.walk(workspace):
                seen += len(dirs) + len(files)
                roots += 1
                if seen > cap or roots > 2 * cap:
                    break
        except Exception:
            return False
        return seen > cap

    def _emit_build_receipt(self) -> None:
        """P1-fix: emit EXACTLY ONE turn/build-level ``runtime.degraded``
        receipt when any limit or cancellation terminated initial context
        work, OR when the workspace itself exceeds what the budget could
        consider (the bound is protecting the turn by design — pruning is
        still bounding). Counts are the pipeline-wide aggregates from the ONE
        shared ledger (not a single walker's scan); component-level summaries
        are nested inside. A deadline that expired before the first file was
        consumed still fires — zero values are honest evidence, never
        suppressed."""
        pool = self._active_pool
        if pool is None:
            return
        oversized = (
            not self._by_design_receipt_emitted
            and self._workspace_exceeds_budget(
                getattr(self, "_active_workspace", ".") or ".", pool.max_considered
            )
        )
        if not (pool.truncated or pool.cancelled or oversized):
            return
        # ONE consolidated receipt per session (benchmark contract: count==1).
        # The receipt answers "was context prep bounded, and how" — a single
        # answer per session; per-walk detail lives in `components`. A turn
        # that laps the graph must not emit one receipt per lap (measured:
        # 20), and a truncation + by-design pair in one run is still one
        # consolidated claim, strongest reason first.
        if self._by_design_receipt_emitted:
            return
        self._by_design_receipt_emitted = True
        reason = (
            "context scan bounded"
            if (pool.truncated or pool.cancelled)
            else "workspace exceeds scan budget — bounded by design"
        )
        # The bound is honest; the number behind it often is not. When no real model name resolved a
        # window, the engine runs on its fallback, which shrinks max_tokens and context_budget -- and so
        # the scan ceiling -- until any ordinary repo "exceeds" it. Measured on the owner's host:
        # LLM_MODEL=auto on a custom provider, window 8,192, budget 4,096, and a greeting came back
        # reading like a product limit on a config mistake. The base string stays byte-identical (the
        # benchmark contract counts this receipt by its reason); the cause rides behind it.
        # Two bounds are in play here and they are NOT the same one. The scan bound is ContextBudget's
        # file-count quota (engine:1031 constructs it with no arguments: 1,000 entries to consider,
        # 1,000 files, 16 MiB, 5s); the model window only sizes the TOKEN budgets. An earlier revision of
        # this line appended the assumed-window note to whichever reason fired, which read as "the window
        # caused the scan bound" -- a causal claim the code does not support, and the kind of
        # confident-looking text that sends the next reader down the wrong path. Each clause now states
        # its own bound, and the scan clause says out loud that the window is not the reason.
        extra = []
        if oversized and not (pool.truncated or pool.cancelled):
            extra.append(
                f"walk bound: {pool.max_considered:,} entries to consider, {pool.max_files:,} files,"
                f" {pool.max_bytes / 1_048_576:.0f} MiB, {pool.max_elapsed:.1f}s -- a file-count ceiling"
                " from ContextBudget defaults, independent of the model window"
            )
        if getattr(self, "context_window_source", "") == "default":
            extra.append(
                f"separately, the token budget runs on an assumed window of {self.context_window:,}:"
                f" max_tokens {self.max_tokens:,}, context budget {self.context_budget:,}. Naming LLM_MODEL"
                " lets the endpoint's own /models metadata resolve it; LLM_CONTEXT_WINDOW states it directly"
            )
        if extra:
            reason += " (" + "; ".join(extra) + ")"

        pool.emit_degraded({
            "thread_id": self._active_thread_id or "unknown",
            "reason": reason,
            "files_considered": pool.considered_files,
            "files_read": pool.read_files,
            "bytes_read": pool.read_bytes,
            "elapsed_ms": int(pool.elapsed * 1000),
            "skipped_generated": (
                pool.skipped_dirs + pool.skipped_generated + pool.skipped_gitignore
            ),
            "skipped_oversized": pool.skipped_oversize,
            "skipped_binary": pool.skipped_binary,
            "cancelled": pool.cancelled,
            "components": pool.component_summaries(),
        })

    def _build_context_layers_inner(
        self, state: dict[str, Any], task_type: TaskType, walkers: list[str] | None = None
    ) -> list[SystemMessage]:
        """See _build_context_layers — split so the shared budget can wrap it."""
        walkers = walkers or []
        n_walkers = max(1, len(walkers))
        layers = []
        builders = {
            "repo_map": self._repo_map_layer,
            "relevant_chunks": self._relevant_chunks_layer,
            "git_context": self._git_context_layer,
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
        # ran json.dumps + sha256 up to 15x per turn on cache-hit paths, and
        # until #10 the wrapper recomputed it once more per turn — the
        # wrapper now passes its hash down via _active_state_hash.)
        # NOTE: invalidation is COARSE by design — one hash covers all layers,
        # so any change to a HASHED key rebuilds every layer. Correct, just
        # not granular; true per-layer dependency hashing is a deliberate
        # non-goal. (D26 narrowed the keyset to what layers actually read —
        # before that, per-turn token/execution noise busted it every turn.)
        current_hash = self._active_state_hash or self._hash_state(state)

        autonomous = bool(state.get("_autonomous_workspace"))
        autonomous_skip = {
            "task", "tone", "quality", "ambiguity",
            # Keep headless runs deterministic and network/startup inert. Old
            # cross-session lessons and tool summaries must not contaminate a
            # fresh workspace contract; successful completion may still write
            # memory after the run.
            "long_term_memory", "tool_memory", "memory_validation", "reflections",
        }
        if autonomous and not state.get("plan"):
            autonomous_skip.add("plan")
        # Gate the progress layer on exactly what `_progress_layer` renders
        # (steps_completed / failed_steps). execution_trace is per-turn noise
        # that no layer reads; gating on it would couple a skip decision to
        # un-hashed churn without changing the layer's content.
        if autonomous and not (
            state.get("steps_completed") or state.get("failed_steps")
        ):
            autonomous_skip.add("progress")
        if autonomous:
            from pathlib import Path
            workspace = Path(state.get("workspace", "."))
            try:
                empty_workspace = not any(path.is_file() for path in workspace.rglob("*"))
            except OSError:
                empty_workspace = False
            if empty_workspace:
                autonomous_skip.update({"repo_map", "relevant_chunks", "git_context", "conventions"})

        for name, builder in builders.items():
            # Headless requests already carry the task as the HumanMessage.
            # Interactive response-style layers told Sarvam to explain its
            # reasoning, start with an overview, and ask questions—the direct
            # opposite of the autonomous action contract. Hermes keeps such UI
            # presentation policy out of its headless prompt.
            if autonomous and name in autonomous_skip:
                continue
            relevance_map = self.LAYER_RELEVANCE.get(name, {})
            score = relevance_map.get(task_type, 0.0)
            if score < 0.15:
                continue  # Skip low-value layers entirely

            # Differential check: reuse cached layer if state deps haven't
            # changed. VOLATILE layers (git_context) describe the world
            # OUTSIDE the state dict — a commit or `git add` does not change
            # the state hash — so they must rebuild every turn. Building one
            # is a handful of fast local subprocess calls, well under 100ms.
            cached = None if name in self.VOLATILE_LAYERS else self._layer_cache.get(name)
            if cached and self._last_state_hash == current_hash:
                layers.append(cached)
                continue

            # P1-fix: each file-walking layer gets its OWN slice of the shared
            # pool (cap // n_walkers), so three walkers cannot each consume a
            # fresh full allowance. Non-walking layers share the pool but
            # never scan, so they never touch it.
            if name in walkers:
                self._active_budget = self._active_pool.share(n_walkers)
            else:
                self._active_budget = None

            try:
                msg = builder(state)
                if msg:
                    # IDENTITY TAG: the layer's name travels IN the message
                    # (response_metadata is local-only — verified invisible
                    # in provider payloads). Scoring/dedup/feedback must not
                    # depend on string-sniffing a header line: one "=" short
                    # and attribution silently degrades to "unknown".
                    msg.response_metadata["layer"] = name
                    layers.append(msg)
                    if name not in self.VOLATILE_LAYERS:
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
        """P9: the scoring pipeline (task-type prior + optional semantic
        similarity + recency) lives in layer_policy.score_and_sort_layers.
        The engine feeds it the LIVE per-instance relevance dict — feedback
        learning mutates it mid-session — and the current model, so a
        mid-session update_model is always seen."""
        return layer_policy.score_and_sort_layers(
            layers, task, task_type,
            model=self.model,
            allow_embedding_compute=self._allow_embedding_compute,
            relevance=self.LAYER_RELEVANCE,
        )

    def _infer_layer_name(self, msg: SystemMessage) -> str:
        """Metadata tag first, header-prefix chain as fallback — P9:
        layer_policy.infer_layer_name."""
        return layer_policy.infer_layer_name(msg)

    def _deduplicate_layers(
        self, scored_layers: list[tuple[float, SystemMessage, int]]
    ) -> list[tuple[float, SystemMessage, int]]:
        """P9: layer_policy.deduplicate_layers (semantic near-duplicate
        removal, gated on the embedding policy)."""
        return layer_policy.deduplicate_layers(
            scored_layers, self._allow_embedding_compute
        )

    def _position_volatile_tail(
        self,
        context_messages: list[SystemMessage],
        trimmed_history: list,
    ) -> list:
        """D23 placement (volatile block tails the whole prompt) — P9:
        layer_policy.position_volatile_tail."""
        return layer_policy.position_volatile_tail(
            context_messages, trimmed_history, self._volatile_tail
        )

    def _emission_sort_key(self, msg: SystemMessage) -> tuple:
        """D19 canonical placement — P9: layer_policy.emission_sort_key."""
        return layer_policy.emission_sort_key(msg)

    def _assemble_hierarchical(
        self,
        scored_layers: list[tuple[float, SystemMessage, int]],
        budget: int,
    ) -> list[SystemMessage]:
        """Score-driven fit + canonical emission order — P9:
        layer_policy.assemble_hierarchical."""
        return layer_policy.assemble_hierarchical(
            scored_layers, budget, model=self.model
        )

    def _compress_layer(self, msg: SystemMessage, max_tokens: int) -> Optional[SystemMessage]:
        """Compress a single layer to fit a token budget — P9:
        layer_policy.compress_layer."""
        return layer_policy.compress_layer(msg, max_tokens, model=self.model)

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
            # P3: memory content is untrusted data — redact + cap before it
            # reaches the prompt (Hermes sanitize_memory_context parity).
            lines.append(f"- {sanitize_memory_context(str(lesson))}")
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
        learner.thread_id_hint = self._active_thread_id or None
        text = learner.get_conventions_text(workspace, self._active_budget)
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
            # P3: same untrusted-data rule as the other memory layers.
            warning = sanitize_memory_context(
                str(mem.get("stale_warning", "Potentially outdated"))
            )
            task_preview = sanitize_memory_context(
                str(mem.get("task", mem.get("text", "Unknown task")))
            )[:100]
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
            repo_map_text = get_repo_map(
                workspace, max_tokens=1200,
                budget=self._active_budget,
                thread_id=self._active_thread_id or None,
            )
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
        state = dict(state)
        if self._active_thread_id:
            state["thread_id"] = self._active_thread_id
        return build_relevant_chunks_layer(state, self._active_budget)

    def _git_context_layer(self, state: dict[str, Any]) -> SystemMessage | None:
        """Layer 0c: live git awareness (branch, staged/uncommitted, recent).

        Returns None outside a git repo. Marked VOLATILE (never cached):
        commits/staging happen outside the graph state dict.
        """
        from src.context.git_context import build_git_context_layer
        return build_git_context_layer(state)

    def _task_layer(self, state: dict[str, Any]) -> SystemMessage:
        """Layer 1: What is the user trying to do?"""
        current_task = state.get("current_task", "")
        latest_instruction = state.get("latest_instruction", "")

        content = "=== CURRENT TASK ===\n"

        if current_task:
            content += f"Overall goal: {current_task}\n"
        if latest_instruction:
            content += f"Latest instruction: {latest_instruction}\n"

        low = f"{current_task}\n{latest_instruction}".lower()
        if "_provided/" in low and "copy_file" in low:
            content += (
                "\nCOPY-FIRST DELIVERY RULE:\n"
                "- The named _provided files are the cheapest, highest-priority deliverables. "
                "Place them with copy_file before spending turns on optional setup.\n"
                "- When the user requires byte-for-byte copying, do NOT read the full source "
                "contents first. Confirm the names with list_files and use copy_file directly; "
                "reading large verbatim inputs only wastes context and cannot improve the copy.\n"
                "- If a new Next.js project is required, use scaffold_nextjs(packages=[...]). "
                "Do NOT run create-next-app at `.` (it conflicts with _provided) and do NOT "
                "create a child named after the workspace (workspace/workspace nesting).\n"
                "- After scaffolding, continue immediately to copy_file; never re-run the scaffold.\n"
            )

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
        if not self._allow_embedding_compute:
            # Semantic memory retrieval embeds the query — inference is
            # forbidden during context preparation (explicit offline policy
            # only). The layer degrades gracefully, exactly as it does when
            # no memory manager is attached.
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
            # P3: memory content is untrusted data (it may have come from a
            # previous run on a different / adversarial workspace). Redact
            # secrets and cap length before it reaches the prompt.
            lines.append(sanitize_memory_context(str(memory["text"])))
            lines.append("")

        return SystemMessage(content="\n".join(lines))

    def _ambiguity_layer(self, state: dict[str, Any]) -> Optional[SystemMessage]:
        task = state.get("current_task", "")
        if not task:
            return None
        return self._detect_ambiguity_advanced(task)

    def _detect_ambiguity_advanced(self, task: str) -> Optional[SystemMessage]:
        """P10: the embedding-gated advanced detector lives in
        ambiguity.detect_ambiguity_advanced; the engine feeds it the LIVE
        offline-policy flag so deadline-bound turns never encode."""
        return ambiguity.detect_ambiguity_advanced(
            task, self._allow_embedding_compute
        )

    def _detect_ambiguity_fallback(self, task: str) -> Optional[SystemMessage]:
        """P10: ambiguity.detect_ambiguity_fallback (deterministic
        vague/specific keyword heuristic)."""
        return ambiguity.detect_ambiguity_fallback(task)

    def _tool_memory_layer(self, state: dict[str, Any]) -> Optional[SystemMessage]:
        """
        Retrieve semantically relevant past tool outputs.
        Requires memory_manager to have retrieve_tool_memories() method.
        """
        if not self.memory_manager or not hasattr(self.memory_manager, "retrieve_tool_memories"):
            return None
        if not self._allow_embedding_compute:
            # Tool-memory retrieval is semantic (embeds the query) — same
            # inference-free rule as the long-term memory layer.
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
            # P3: past tool outputs are untrusted data — redact before
            # replay, then cap for context economy.
            summary = sanitize_memory_context(str(mem.get("summary", "")))[:180]
            lines.append(f"- {tool_name}: {summary}")
        return SystemMessage(content="\n".join(lines))

    def record_feedback(self, success: bool, task: Optional[str] = None) -> None:
        """Thread-safe public entry (see build_ai_messages)."""
        with self._api_lock:
            self._record_feedback(success, task)

    def _record_feedback(self, success: bool, task: Optional[str] = None) -> None:
        """Call after task completion to learn which layers worked.

        P7: the store/learning/append pipeline lives in
        ``feedback_memory.FeedbackMemory``; the engine supplies the
        attribution snapshot (layers ACTUALLY sent in the final build) and
        the weight dict the layer builders read.
        """
        profile = make_profile(
            success,
            task,
            # Attribute to the layers actually sent in the final build.
            # The cache fallback only fires if a task fails before ANY build
            # this session (e.g. planner crash on turn 1) — known-low value,
            # kept so the feedback row is never empty.
            self._last_layers_sent or list(self._layer_cache.keys()),
        )
        self._feedback.record(profile, self.LAYER_RELEVANCE, TaskType)

    # =========================================================
    # HISTORY TRIMMING
    # =========================================================

    def _summarize_tool_messages(
        self,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Run every ToolMessage through the SmartSummarizer (long outputs
        become short summaries; short ones pass through untouched)."""
        return self._shaper.summarize_tool_messages(messages)

    def _compact_history(
        self,
        history: list[BaseMessage],
        budget: int,
    ) -> list[BaseMessage]:
        """D22 hermes pack (compaction.py): prune-first with protected
        head/tail, structural dropping only if still over budget, dropped
        turns folded into an iterative AUX-model summary with anti-thrash.
        PULSEAI_COMPACTION=off restores the legacy structural pipeline;
        landed mutation omission has its own diagnostic kill switch."""
        return self._shaper.compact(
            history, budget, kill_switch_trim=self._trim_history
        )

    def compaction_stats(self) -> dict:
        """D22 telemetry: prune/compaction counters for this session."""
        return self._shaper.stats()

    def _trim_history(
        self,
        history: list[BaseMessage],
        budget: int,
    ) -> list[BaseMessage]:
        """Budget-fit trim with the P4 pairing guard (P8: the pipeline
        itself lives in history_shaper.HistoryShaper)."""
        return self._shaper.trim(history, budget)

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
        """P10: plan_messages.wrap_planner_prompt."""
        return plan_messages.wrap_planner_prompt(planner_prompt)

    def build_planner_messages(self, task: str, planner_prompt: str) -> list[BaseMessage]:
        """P10: plan_messages.build_planner_messages (planner node)."""
        return plan_messages.build_planner_messages(task, planner_prompt)

    def build_replanner_messages(
        self,
        task: str,
        plan: list[dict],
        failed_steps: list[str],
        planner_prompt: str,
        prior_attempts: list[dict] | None = None,
    ) -> list[BaseMessage]:
        """P10: plan_messages.build_replanner_messages (replanner node)."""
        return plan_messages.build_replanner_messages(
            task, plan, failed_steps, planner_prompt, prior_attempts
        )

    def build_reviser_messages(
        self,
        task: str,
        plan: list[dict],
        revision: str,
        planner_prompt: str,
    ) -> list[BaseMessage]:
        """P10: plan_messages.build_reviser_messages (plan reviser node)."""
        return plan_messages.build_reviser_messages(
            task, plan, revision, planner_prompt
        )

# src/context/context_engine.py
"""
Context Engine Facade for CrusorCodeAI
======================================

Backward-compatible facade providing `ContextEngine`, `TaskClassifier`, and all
context state, budgeting, and layer building APIs.

New modular imports are located in:
- `src.context.core.context_engine`
- `src.context.core.context_state`
- `src.context.core.context_builder`
"""

from __future__ import annotations

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
from src.context.engine import (
    resolve_model_threshold,
    sanitize_memory_context,
    load_model_thresholds_from_env,
    load_proactive_prune_config_from_env,
)
from src.context.token_budget import count_tokens, trim_messages_to_budget
from src.context.task_types import TaskType  # P9: re-exported for existing imports
from src.context import layer_policy  # P9: scoring/dedup/placement/compression/budget
from src.context import ambiguity, plan_messages  # P10: detector + planner builders
from src.context.usage_pressure import UsagePressure
from src.context.user_interest import interest_from_state, render_user_interest
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
from src.context.micro_compaction import MicroCompactionMixin
from src.context.compression_fence import (
    CompressionCommitFence,
    try_acquire_compression_lock,
    release_compression_lock,
)
from src.context.core.context_builder import ContextBuilder
from src.context.core.context_state import (
    HASHED_STATE_KEYS,
    ContextState,
    hash_state as _core_hash_state,
    wire_dicts_to_messages as _core_wire_dicts_to_messages,
    workspace_exceeds_budget as _core_workspace_exceeds_budget,
)
from src.context.core.context_engine import (
    ContextEngine as CoreContextEngine,
    TaskClassifier,
    _skills_phase,
    _skills_text,
    _get_shared_classifier,
)


class ContextEngine(CoreContextEngine):
    """
    Context Engine for CrusorCodeAI.

    Inherits full orchestration from `src.context.core.context_engine.ContextEngine`.
    Retains `_HASHED_STATE_KEYS` and the registered layer registry in
    `_build_context_layers_inner` for strict AST drift-guard compliance.
    """

    _HASHED_STATE_KEYS: frozenset[str] = HASHED_STATE_KEYS

    def _build_context_layers_inner(
        self, state: dict[str, Any], task_type: TaskType, walkers: list[str] | None = None
    ) -> list[SystemMessage]:
        """See _build_context_layers — split so the shared budget can wrap it."""
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
        return super()._build_context_layers_inner(state, task_type, walkers=walkers)

    def build_engineering_context(
        self,
        state: dict[str, Any],
        system_message: SystemMessage,
        *,
        max_history_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Assemble the bounded structured context bundle for delegation.

        Increment 2: ContextEngine remains the ONE context owner. This method
        calls the existing ``build_ai_messages`` exactly once, then splits the
        assembled result into an explicit bundle: the current request, bounded
        conversation history (never re-including the current message),
        workspace/memory context, provenance (the layers actually sent), and
        token/budget metadata. The engineering engine receives this and never
        performs its own retrieval or transcript assembly.
        """
        messages = self.build_ai_messages(state, system_message)
        model = getattr(self, "model", None)
        context_window = int(getattr(self, "context_window", 0) or 0)
        try:
            context_budget, history_budget = self._allocate_budget(TaskType.CREATE)
        except Exception:
            context_budget = max(4096, int(context_window * 0.55))
            history_budget = max(2048, int(context_window * 0.30))
        if max_history_tokens is not None:
            history_budget = max(512, min(int(max_history_tokens), int(history_budget)))

        # The newest human message is the current request: split it out so the
        # engine never sees it twice (once as "request", once in history).
        current_index = -1
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                current_index = index
                break
        current_request = ""
        history_messages: list[BaseMessage] = []
        system_blocks: list[str] = []
        for index, message in enumerate(messages):
            if isinstance(message, SystemMessage):
                text = str(getattr(message, "content", "") or "").strip()
                if text:
                    system_blocks.append(text)
                continue
            if index == current_index:
                current_request = str(getattr(message, "content", "") or "").strip()
                continue
            history_messages.append(message)

        if not current_request:
            current_request = str(
                state.get("latest_instruction")
                or state.get("current_task")
                or ""
            ).strip()

        history_before = len(history_messages)
        history_tokens_before = count_tokens(history_messages, model)
        trimmed = trim_messages_to_budget(history_messages, history_budget, model)
        history_tokens = count_tokens(trimmed, model)
        truncated = (
            len(trimmed) < history_before
            or history_tokens_before > history_budget
        )

        rows: list[dict[str, str]] = []
        for message in trimmed:
            role = {
                "human": "user",
                "ai": "assistant",
                "tool": "tool",
                "system": "system",
            }.get(getattr(message, "type", ""), "message")
            content = str(getattr(message, "content", "") or "").strip()
            if not content:
                continue
            if len(content) > 4000:
                content = content[:4000] + "\n[message truncated]"
            rows.append({"role": role, "content": content})

        workspace_context = "\n\n".join(system_blocks)
        if len(workspace_context) > 12_000:
            workspace_context = (
                workspace_context[:12_000]
                + "\n[workspace context truncated at context-bundle boundary]"
            )

        layers = list(getattr(self, "_last_layers_sent", []) or [])
        context_tokens = count_tokens(messages, model)
        return {
            "schema_version": 1,
            "current_request": current_request,
            "history": rows,
            "workspace_context": workspace_context,
            "provenance": {
                "engine": type(self).__name__,
                "layers": layers,
                "model": model,
                "source": "langgraph-context-engine",
                "assembled_once": True,
                "truncated": bool(truncated),
            },
            "budget": {
                "context_window": context_window,
                "context_budget": int(context_budget),
                "history_budget": int(history_budget),
                "context_tokens": int(context_tokens),
                "history_tokens": int(history_tokens),
                "history_tokens_before": int(history_tokens_before),
                "truncated": bool(truncated),
            },
            "counts": {
                "source_messages": len(messages),
                "history_messages": len(rows),
                "workspace_blocks": len(system_blocks),
            },
        }


__all__ = [
    "ContextEngine",
    "TaskClassifier",
    "TaskType",
    "ContextState",
    "ContextBuilder",
    "HASHED_STATE_KEYS",
    "hash_state",
    "workspace_exceeds_budget",
    "wire_dicts_to_messages",
    "count_tokens",
    "trim_messages_to_budget",
    "resolve_model_threshold",
    "sanitize_memory_context",
    "load_model_thresholds_from_env",
    "load_proactive_prune_config_from_env",
    "UsagePressure",
    "HistoryShaper",
    "SmartSummarizer",
    "MemoryManager",
    "get_repo_map",
    "get_embedding_cache",
    "_skills_phase",
    "_skills_text",
    "_get_shared_classifier",
]

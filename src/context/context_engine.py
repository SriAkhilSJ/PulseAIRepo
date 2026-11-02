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

import ast
import hashlib
import json
import os
import sys
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
]

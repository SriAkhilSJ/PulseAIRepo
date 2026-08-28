"""
PulseAI Context Engine Package
==============================
Provides hierarchical, adaptive, task-aware context management, prompt caching,
and Hermes-compatible compaction and lifecycle protocols.
"""

from src.context.base import ContextEngineBase
from src.context.context_engine import ContextEngine, TaskClassifier, TaskType
from src.context.compaction import HistoryCompactor, micro_compact, sanitize_tool_pairs
from src.context.registry import (
    register_context_engine,
    create_context_engine,
    get_context_engine_class,
    list_context_engines,
)

__all__ = [
    "ContextEngineBase",
    "ContextEngine",
    "TaskClassifier",
    "TaskType",
    "HistoryCompactor",
    "micro_compact",
    "sanitize_tool_pairs",
    "register_context_engine",
    "create_context_engine",
    "get_context_engine_class",
    "list_context_engines",
]

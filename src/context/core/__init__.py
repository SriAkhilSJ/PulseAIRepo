"""
Core Context Engine Package
===========================

Provides the orchestrator, state manager, context builder, and task classifier
for the Context Engine architecture.
"""

from src.context.core.context_state import (
    HASHED_STATE_KEYS,
    ContextState,
    hash_state,
    workspace_exceeds_budget,
    wire_dicts_to_messages,
)
from src.context.core.context_builder import ContextBuilder
from src.context.core.context_engine import ContextEngine, TaskClassifier

__all__ = [
    "ContextEngine",
    "TaskClassifier",
    "ContextState",
    "ContextBuilder",
    "HASHED_STATE_KEYS",
    "hash_state",
    "workspace_exceeds_budget",
    "wire_dicts_to_messages",
]

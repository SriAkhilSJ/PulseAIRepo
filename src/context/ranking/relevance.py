"""
Ranking Relevance
=================

Calculates layer relevance, task priors, and semantic similarity for Context Engine layers.
"""

from __future__ import annotations

from typing import Any
from langchain_core.messages import SystemMessage

from src.context.task_types import TaskType


# ---------------------------------------------------------------------------
# Relevance map: which layers matter for which task types.
# The engine deep-copies this into a per-instance dict in __init__
# (feedback learning mutates the copy — never this base), so the base
# is safe to share across every engine in the process.
# ---------------------------------------------------------------------------
LAYER_RELEVANCE_BASE: dict[str, dict[TaskType, float]] = {
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
    "git_context": {
        # Highest for DEBUG ("the bug I just introduced") and REFACTOR;
        # near-zero for CHAT, which is below the 0.15 build threshold
        # anyway — no git subprocesses are spawned for small talk.
        TaskType.DEBUG: 0.70, TaskType.REFACTOR: 0.60, TaskType.CREATE: 0.50,
        TaskType.RECOVERY: 0.40, TaskType.PLAN: 0.40, TaskType.TEST: 0.30,
        TaskType.EXPLAIN: 0.30, TaskType.EXPLORE: 0.20, TaskType.CHAT: 0.10,
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


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def infer_layer_name(msg: SystemMessage) -> str:
    """Which layer this message belongs to (relevance lookup + feedback).

    Metadata tag first (authoritative — stamped at build time); the
    header-prefix chain is only a fallback for messages that were not
    built by this engine's builder loop.
    """
    tag = msg.response_metadata.get("layer")
    if tag:
        return tag
    content = msg.content
    if content.startswith("=== CODEBASE STRUCTURE"):
        return "repo_map"
    if content.startswith("=== RELEVANT CODE CHUNKS"):
        return "relevant_chunks"
    if content.startswith("=== GIT CONTEXT"):
        return "git_context"
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


def get_layer_relevance(
    name: str,
    task_type: TaskType,
    relevance_map: dict[str, dict[TaskType, float]] | None = None,
) -> float:
    """Look up base relevance for a layer and task type, defaulting to 0.5."""
    source = relevance_map if relevance_map is not None else LAYER_RELEVANCE_BASE
    return source.get(name, {}).get(task_type, 0.5)


def calculate_semantic_similarity(
    task_emb: list[float],
    content_emb: list[float],
) -> float:
    """Calculate cosine similarity (dot product of normalized embeddings)."""
    return sum(a * b for a, b in zip(task_emb, content_emb))


def calculate_layer_score(
    base_rel: float,
    semantic_sim: float | None = None,
    position_bias: float = 0.0,
) -> float:
    """Calculate the layer relevance score.

    If semantic similarity is available:
        60% task-type prior + 30% semantic similarity + 10% position bias
    Otherwise (deterministic default):
        90% task-type prior + 10% position bias
    """
    if semantic_sim is not None:
        return base_rel * 0.60 + semantic_sim * 0.30 + position_bias * 0.10
    return base_rel * 0.90 + position_bias * 0.10


__all__ = [
    "LAYER_RELEVANCE_BASE",
    "infer_layer_name",
    "get_layer_relevance",
    "calculate_semantic_similarity",
    "calculate_layer_score",
]

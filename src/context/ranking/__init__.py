"""
Ranking Package
===============

Decides which built layers survive, in what order they are emitted,
and token budget allocations across task types.
"""

from __future__ import annotations

from src.context.task_types import TaskType
from src.context.ranking.relevance import (
    LAYER_RELEVANCE_BASE,
    infer_layer_name,
    get_layer_relevance,
    calculate_semantic_similarity,
    calculate_layer_score,
)
from src.context.ranking.layer_policy import (
    BUILDER_ORDER,
    VOLATILE_LAYERS,
    VOLATILE_TAIL_PREAMBLE,
    allocate_budget,
    score_and_sort_layers,
    deduplicate_layers,
    position_volatile_tail,
    emission_sort_key,
    assemble_hierarchical,
    compress_layer,
)

__all__ = [
    "TaskType",
    "BUILDER_ORDER",
    "VOLATILE_LAYERS",
    "VOLATILE_TAIL_PREAMBLE",
    "LAYER_RELEVANCE_BASE",
    "infer_layer_name",
    "get_layer_relevance",
    "calculate_semantic_similarity",
    "calculate_layer_score",
    "allocate_budget",
    "score_and_sort_layers",
    "deduplicate_layers",
    "position_volatile_tail",
    "emission_sort_key",
    "assemble_hierarchical",
    "compress_layer",
]

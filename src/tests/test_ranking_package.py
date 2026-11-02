"""
Tests for the modularized ranking package (Phase 7.3).
"""

from __future__ import annotations

import pytest
from langchain_core.messages import SystemMessage

from src.context import ranking
from src.context.ranking import relevance, layer_policy
from src.context.task_types import TaskType
from src.context import layer_policy as facade_layer_policy


def test_ranking_package_exports():
    for name in [
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
    ]:
        assert hasattr(ranking, name), f"ranking package missing export: {name}"
        assert hasattr(facade_layer_policy, name), f"facade missing export: {name}"


def test_relevance_calculations():
    # Base relevance lookup
    assert relevance.get_layer_relevance("repo_map", TaskType.EXPLORE) == 1.0
    assert relevance.get_layer_relevance("unknown_layer", TaskType.CHAT) == 0.5

    # Semantic similarity (normalized dot product)
    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]
    assert relevance.calculate_semantic_similarity(v1, v2) == 0.0
    assert relevance.calculate_semantic_similarity(v1, v1) == 1.0

    # Layer scoring formula
    # Default (no embedding): base_rel * 0.90 + position_bias * 0.10
    score_default = relevance.calculate_layer_score(0.8, position_bias=0.5)
    assert abs(score_default - (0.8 * 0.90 + 0.5 * 0.10)) < 1e-9

    # Embedding path: base_rel * 0.60 + semantic_sim * 0.30 + position_bias * 0.10
    score_emb = relevance.calculate_layer_score(0.8, semantic_sim=0.7, position_bias=0.5)
    assert abs(score_emb - (0.8 * 0.60 + 0.7 * 0.30 + 0.5 * 0.10)) < 1e-9


def test_infer_layer_name_priorities():
    # Tagged takes precedence
    tagged = SystemMessage(
        content="=== PLAN\ndo work",
        response_metadata={"layer": "skills"},
    )
    assert relevance.infer_layer_name(tagged) == "skills"

    # Header prefix fallback
    header = SystemMessage(content="=== CODEBASE STRUCTURE\nsrc/")
    assert relevance.infer_layer_name(header) == "repo_map"

    # Unknown fallback
    plain = SystemMessage(content="Hello world")
    assert relevance.infer_layer_name(plain) == "unknown"


def test_ranking_layer_policy_operations():
    # Budget allocation
    ctx, hist = layer_policy.allocate_budget(10000, TaskType.DEBUG)
    assert (ctx, hist) == (3500, 6500)

    # Emission key ordering
    m_task = SystemMessage(content="task", response_metadata={"layer": "task"})
    m_git = SystemMessage(content="git", response_metadata={"layer": "git_context"})
    m_custom = SystemMessage(content="custom", response_metadata={"layer": "custom"})

    k_task = layer_policy.emission_sort_key(m_task)
    k_git = layer_policy.emission_sort_key(m_git)
    k_custom = layer_policy.emission_sort_key(m_custom)

    assert k_task[0] == 0
    assert k_custom[0] == 1
    assert k_git[0] == 2
    assert k_task < k_custom < k_git


def test_ranking_parity_with_facade():
    # Ensure facade exports point to exact same implementations and constants
    assert facade_layer_policy.BUILDER_ORDER is layer_policy.BUILDER_ORDER
    assert facade_layer_policy.VOLATILE_LAYERS is layer_policy.VOLATILE_LAYERS
    assert facade_layer_policy.LAYER_RELEVANCE_BASE is relevance.LAYER_RELEVANCE_BASE
    assert facade_layer_policy.score_and_sort_layers is layer_policy.score_and_sort_layers
    assert facade_layer_policy.assemble_hierarchical is layer_policy.assemble_hierarchical
    assert facade_layer_policy.compress_layer is layer_policy.compress_layer

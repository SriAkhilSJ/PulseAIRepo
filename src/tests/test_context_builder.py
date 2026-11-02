"""Tests for src.context.core.context_builder."""

import pytest
from langchain_core.messages import SystemMessage, HumanMessage

from src.context.core.context_builder import ContextBuilder
from src.context.task_types import TaskType


def test_builder_initialization():
    builder = ContextBuilder(model="gpt-4o", allow_embedding_compute=False, volatile_tail=True)
    assert builder.model == "gpt-4o"
    assert builder.volatile_tail is True


def test_build_layers_execution_and_caching():
    builder = ContextBuilder()
    builders = {
        "layer_a": lambda state: SystemMessage(content="Layer A Content"),
        "layer_b": lambda state: SystemMessage(content="Layer B Content"),
    }
    relevance = {
        "layer_a": {TaskType.CREATE: 0.9},
        "layer_b": {TaskType.CREATE: 0.1},  # below 0.15 threshold
    }
    cache = {}
    layers = builder.build_layers(
        builders=builders,
        state={},
        task_type=TaskType.CREATE,
        layer_cache=cache,
        layer_relevance=relevance,
    )
    assert len(layers) == 1
    assert layers[0].content == "Layer A Content"
    assert layers[0].response_metadata.get("layer") == "layer_a"
    assert "layer_a" in cache


def test_build_layers_autonomous_skips():
    builder = ContextBuilder()
    builders = {
        "task": lambda state: SystemMessage(content="Task"),
        "plan": lambda state: SystemMessage(content="Plan"),
        "quality": lambda state: SystemMessage(content="Quality"),
    }
    relevance = {
        "task": {TaskType.CREATE: 0.9},
        "plan": {TaskType.CREATE: 0.9},
        "quality": {TaskType.CREATE: 0.9},
    }
    # Autonomous without plan in state -> skips task, quality, and plan
    state = {"_autonomous_workspace": True}
    cache = {}
    layers = builder.build_layers(
        builders=builders,
        state=state,
        task_type=TaskType.CREATE,
        layer_cache=cache,
        layer_relevance=relevance,
    )
    assert len(layers) == 0


def test_score_sort_dedup_and_assemble():
    builder = ContextBuilder()
    msg1 = SystemMessage(content="=== REPO MAP ===\nfile1.py")
    msg1.response_metadata["layer"] = "repo_map"
    msg2 = SystemMessage(content="=== TASK ===\nDo the thing")
    msg2.response_metadata["layer"] = "task"

    relevance = {
        "repo_map": {TaskType.CREATE: 0.8},
        "task": {TaskType.CREATE: 1.0},
    }
    scored = builder.score_and_sort_layers([msg1, msg2], task="Do the thing", task_type=TaskType.CREATE, relevance=relevance)
    assert len(scored) == 2

    deduped = builder.deduplicate_layers(scored)
    assert len(deduped) == 2

    assembled = builder.assemble_hierarchical(deduped, budget=5000)
    assert len(assembled) == 2

    history = [HumanMessage(content="history msg")]
    payload = builder.position_volatile_tail(assembled, history)
    assert len(payload) == 3


def test_planner_messages():
    builder = ContextBuilder()
    prompt = builder.wrap_planner_prompt("Original Prompt")
    assert "Original Prompt" in prompt

    msgs = builder.build_planner_messages("my task", "prompt")
    assert len(msgs) >= 1

"""
Phase 9.2.2.4.1 Context Gating Safety, Invalidation & Benchmark Closure Tests
=============================================================================
Validates:
1. Mandatory security-context preservation and failure behavior.
2. External workspace change invalidation (edit, create, delete, rename, git checkout, workspace switch).
3. Task escalation, failure recovery unlatching, and cache isolation.
4. Prompt-cache invariant prefix stability and volatile tail placement.
"""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import SystemMessage, HumanMessage

from src.context.core.context_engine import ContextEngine
from src.context.complexity import (
    TaskComplexity,
    classify_task_complexity,
    escalate_complexity,
    get_active_layers_for_tier,
)
from src.context.indexing.chunk_index import (
    get_index_generation,
    bump_index_generation,
    _RETRIEVAL_CACHE,
    _RETRIEVAL_CACHE_LOCK,
    build_relevant_chunks_layer,
)
from src.context.repo_map import (
    get_repo_map_generation,
    bump_repo_map_generation,
    invalidate_repo_map,
)
from src.tools.file_tools import read_file, resolve_workspace_path


# ---------------------------------------------------------------------
# 1. MANDATORY CONTEXT SAFETY
# ---------------------------------------------------------------------

def test_01_mandatory_system_message_failure_fails_safely():
    """Mandatory security context must never silently disappear."""
    engine = ContextEngine(model="test-model")
    state = {"workspace": ".", "current_task": "test task"}

    # Passing None as system_message must raise ValueError
    with pytest.raises(ValueError, match="Mandatory security context missing"):
        engine.build_ai_messages(state, None)

    # Passing empty system_message must raise ValueError
    with pytest.raises(ValueError, match="Mandatory security context missing"):
        engine.build_ai_messages(state, SystemMessage(content="   "))


def test_02_missing_workspace_restriction_blocks_tools(tmp_path):
    """Missing workspace restrictions must refuse workspace tool execution."""
    # Direct resolve_workspace_path with empty workspace must raise ValueError
    with pytest.raises(ValueError, match="Missing workspace restriction"):
        resolve_workspace_path("", "test.py")

    with pytest.raises(ValueError, match="Missing workspace restriction"):
        resolve_workspace_path(None, "test.py")

    # read_file with explicitly empty workspace restriction in config refuses execution
    res = read_file.func("sample.py", config={"configurable": {"workspace": ""}})
    assert "⛔ Tool execution refused: missing workspace restriction" in res


def test_03_unknown_layer_and_tier_classification_conservative(monkeypatch):
    """Unknown tier classification must be treated conservatively (Tier 3 fallback)."""
    monkeypatch.setenv("CRUSORAI_CONTEXT_TIER", "unrecognized_tier_value")
    tier = classify_task_complexity("some vague instruction", {})
    assert tier == TaskComplexity.TIER_3_MULTI_FILE

    monkeypatch.setenv("CRUSORAI_CONTEXT_TIER", "999")
    tier2 = classify_task_complexity("some vague instruction", {})
    assert tier2 == TaskComplexity.TIER_3_MULTI_FILE


def test_04_optional_layer_failure_gracefully_degrades(tmp_path):
    """Optional layer failures must log and continue rather than aborting the turn."""
    engine = ContextEngine(model="test-model")
    state = {"workspace": str(tmp_path), "current_task": "explain function"}
    sys_msg = SystemMessage(content="You are Crusor security persona.")

    # Mock tone layer to simulate an exception in an optional layer
    with patch.object(engine, "_tone_layer", side_effect=RuntimeError("Transient failure in tone layer")):
        msgs = engine.build_ai_messages(state, sys_msg)
        assert len(msgs) >= 1
        # System prompt with mandatory security content is preserved
        assert "You are Crusor security persona" in msgs[0].content


# ---------------------------------------------------------------------
# 2. EXTERNAL WORKSPACE INVALIDATION
# ---------------------------------------------------------------------

def test_05_external_edit_invalidates_retrieval_and_repomap(tmp_path):
    """External file edit followed by index sync bumps generation and invalidates caches."""
    ws = str(tmp_path.resolve())
    initial_gen = get_index_generation(ws)
    initial_repo_gen = get_repo_map_generation(ws)

    # Simulate retrieval cache population
    cache_key = (ws, "lookup target", initial_gen)
    with _RETRIEVAL_CACHE_LOCK:
        _RETRIEVAL_CACHE[cache_key] = "cached_chunks_v1"

    # External edit occurs -> generation is bumped
    new_gen = bump_index_generation(ws)
    assert new_gen > initial_gen

    # repo_map generation should also be invalidated
    new_repo_gen = get_repo_map_generation(ws)
    assert new_repo_gen > initial_repo_gen

    # Cached retrieval for new generation is a miss
    cache_key_v2 = (ws, "lookup target", new_gen)
    with _RETRIEVAL_CACHE_LOCK:
        hit = _RETRIEVAL_CACHE.get(cache_key_v2)
    assert hit is None


def test_06_git_branch_checkout_invalidates_layer_hashes(tmp_path):
    """Git checkout/commit modifying .git/HEAD invalidates layer dependency hashes."""
    ws = str(tmp_path.resolve())
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    head_file = git_dir / "HEAD"
    head_file.write_text("ref: refs/heads/main\n", encoding="utf-8")

    engine = ContextEngine(model="test-model")
    state = {"workspace": ws, "current_task": "lookup code"}

    hashes_turn1 = engine._compute_layer_dep_hashes(state, "lookup code")

    # Simulate git checkout to another branch
    time.sleep(0.01)
    head_file.write_text("ref: refs/heads/feat/new-architecture\n", encoding="utf-8")

    hashes_turn2 = engine._compute_layer_dep_hashes(state, "lookup code")

    assert hashes_turn1["relevant_chunks"] != hashes_turn2["relevant_chunks"]
    assert hashes_turn1["repo_map"] != hashes_turn2["repo_map"]
    assert hashes_turn1["git_context"] != hashes_turn2["git_context"]


def test_07_workspace_switch_cache_isolation(tmp_path):
    """Different workspaces cannot reuse each other's context or retrieval results."""
    ws1 = str((tmp_path / "ws1").resolve())
    ws2 = str((tmp_path / "ws2").resolve())
    os.makedirs(ws1, exist_ok=True)
    os.makedirs(ws2, exist_ok=True)

    task = "find connection pool"
    with _RETRIEVAL_CACHE_LOCK:
        _RETRIEVAL_CACHE[(ws1, task, 0)] = "ws1_specific_results"

    # Querying ws2 must miss cache
    with _RETRIEVAL_CACHE_LOCK:
        assert _RETRIEVAL_CACHE.get((ws2, task, 0)) is None

    engine = ContextEngine(model="test-model")
    hashes_ws1 = engine._compute_layer_dep_hashes({"workspace": ws1}, task)
    hashes_ws2 = engine._compute_layer_dep_hashes({"workspace": ws2}, task)

    assert hashes_ws1["repo_map"] != hashes_ws2["repo_map"]
    assert hashes_ws1["relevant_chunks"] != hashes_ws2["relevant_chunks"]
    assert hashes_ws1["conventions"] != hashes_ws2["conventions"]


# ---------------------------------------------------------------------
# 3. TASK ESCALATION AND CACHE ISOLATION
# ---------------------------------------------------------------------

def test_08_multi_file_modification_escalates_to_tier_3():
    """Simple task escalates to Tier 3 when multiple files are modified in state."""
    state_single = {"modified_files": ["src/app.py"]}
    tier_single = escalate_complexity(TaskComplexity.TIER_1_SIMPLE_LOOKUP, state_single)
    assert tier_single == TaskComplexity.TIER_1_SIMPLE_LOOKUP

    state_multi = {"modified_files": ["src/app.py", "src/auth.py"]}
    tier_multi = escalate_complexity(TaskComplexity.TIER_1_SIMPLE_LOOKUP, state_multi)
    assert tier_multi == TaskComplexity.TIER_3_MULTI_FILE


def test_09_recovery_escalates_to_tier_4_and_resolves_cleanly():
    """Failed tasks load Tier 4 recovery context; resolved failures do not latch."""
    # Failed turn
    failed_state = {"recovery_mode": True, "failed_steps": ["step 1"]}
    tier_fail = classify_task_complexity("look up error", failed_state)
    assert tier_fail == TaskComplexity.TIER_4_COMPLEX_REPO

    # Subsequent resolved turn with new simple task
    resolved_state = {"recovery_mode": False, "failed_steps": []}
    tier_resolved = classify_task_complexity("where is the config definition", resolved_state)
    assert tier_resolved == TaskComplexity.TIER_1_SIMPLE_LOOKUP


def test_10_task_change_invalidates_task_specific_layers_only():
    """Changing task invalidates task-specific layers while retaining static layers."""
    engine = ContextEngine(model="test-model")
    state = {"workspace": "/test/ws"}

    h1 = engine._compute_layer_dep_hashes(state, "task alpha")
    h2 = engine._compute_layer_dep_hashes(state, "task beta")

    # Static layers are unchanged
    assert h1["quality"] == h2["quality"]
    assert h1["repo_map"] == h2["repo_map"]
    assert h1["conventions"] == h2["conventions"]

    # Task-specific layers are invalidated
    assert h1["task"] != h2["task"]
    assert h1["relevant_chunks"] != h2["relevant_chunks"]
    assert h1["tone"] != h2["tone"]


# ---------------------------------------------------------------------
# 4. PROMPT CACHE STABILITY
# ---------------------------------------------------------------------

def test_11_prompt_cache_prefix_and_volatile_tail_structure(tmp_path):
    """Stable prefix content remains invariant while volatile state stays in the tail."""
    from langchain_core.messages import AIMessage, ToolMessage

    engine = ContextEngine(model="test-model")
    sys_msg = SystemMessage(content="BASE INVARIANT PERSONA")

    # Turn 1
    state1 = {
        "workspace": str(tmp_path),
        "current_task": "explain function",
        "messages": [HumanMessage(content="explain function")],
    }
    msgs1 = engine.build_ai_messages(state1, sys_msg)

    # Turn 2: same task and instruction, with intermediate tool execution history
    state2 = {
        "workspace": str(tmp_path),
        "current_task": "explain function",
        "messages": [
            HumanMessage(content="explain function"),
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
            ToolMessage(content="def foo(): pass", tool_call_id="c1"),
        ],
    }
    msgs2 = engine.build_ai_messages(state2, sys_msg)

    # The head system message (stable prefix) must be identical across turns
    assert msgs1[0].content == msgs2[0].content
    assert "BASE INVARIANT PERSONA" in msgs1[0].content

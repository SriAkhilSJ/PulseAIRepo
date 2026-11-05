"""
test_dynamic_context_gating.py - Test Suite for Phase 9.2.2.4:
Dynamic Context Layer Gating & Incremental Context Reuse.

Verifies:
1. Deterministic task complexity classification (Tiers 1, 2, 3, 4).
2. Conservative fallback and state-level escalation (recovery_mode, failed_steps, replan).
3. Context layer gating enforcement per tier (Tiers 1, 2, 3, 4).
4. Operational kill-switch (CRUSORAI_CONTEXT_GATING=off).
5. Dynamic context budget allocation caps by complexity tier.
6. Incremental retrieval caching in ChunkIndex with index generation invalidation.
7. Repository map efficiency (dirty flag invalidation, redundant walk elimination).
8. Granular layer caching across multi-turn runs (retaining unchanged layers when steps advance).
9. Prompt cache prefix stability & volatile-tail preservation across tiers.
10. Invariant preservation of safety, system prompt, and workspace boundaries across all tiers.
"""

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import SystemMessage, HumanMessage

from src.context.complexity import (
    TaskComplexity,
    ALL_CONTEXT_LAYERS,
    TIER_ALLOWED_LAYERS,
    TIER_CONTEXT_BUDGET_CAPS,
    classify_task_complexity,
    escalate_complexity,
    get_active_layers_for_tier,
)
from src.context.core.context_engine import ContextEngine
from src.context.task_types import TaskType
from src.context.repo_map import (
    RepoMap,
    get_repo_map,
    invalidate_repo_map,
    get_repo_map_generation,
    bump_repo_map_generation,
)
from src.context.indexing.chunk_index import (
    build_relevant_chunks_layer,
    get_index_generation,
    bump_index_generation,
    _RETRIEVAL_CACHE,
    _RETRIEVAL_CACHE_LOCK,
)


# ===========================================================================
# 1. Deterministic Task Complexity Classification
# ===========================================================================

def test_01_deterministic_classification_tiers():
    # Tier 1: Lookups, searches, explanations without mutation
    assert classify_task_complexity("Find where the User class is defined") == TaskComplexity.TIER_1_SIMPLE_LOOKUP
    assert classify_task_complexity("Where is the configuration file located?") == TaskComplexity.TIER_1_SIMPLE_LOOKUP
    assert classify_task_complexity("Explain how calculate_fee works") == TaskComplexity.TIER_1_SIMPLE_LOOKUP
    assert classify_task_complexity("Show me the read_file function implementation") == TaskComplexity.TIER_1_SIMPLE_LOOKUP
    assert classify_task_complexity("What does the ContextBudget class do?") == TaskComplexity.TIER_1_SIMPLE_LOOKUP

    # Tier 2: Local modifications
    assert classify_task_complexity("Fix the typo in auth.py") == TaskComplexity.TIER_2_LOCAL_MODIFICATION
    assert classify_task_complexity("Update the timeout parameter in client.py") == TaskComplexity.TIER_2_LOCAL_MODIFICATION
    assert classify_task_complexity("Add a unit test for parser in test_parser.py") == TaskComplexity.TIER_2_LOCAL_MODIFICATION
    assert classify_task_complexity("Patch the bug in the function validate_token") == TaskComplexity.TIER_2_LOCAL_MODIFICATION

    # Tier 3: Multi-file tasks
    assert classify_task_complexity("Implement feature across frontend and backend") == TaskComplexity.TIER_3_MULTI_FILE
    assert classify_task_complexity("Integrate the new authentication pipeline across modules") == TaskComplexity.TIER_3_MULTI_FILE
    assert classify_task_complexity("Connect models and views for the billing system") == TaskComplexity.TIER_3_MULTI_FILE

    # Tier 4: Complex repository tasks
    assert classify_task_complexity("Complete architecture redesign for the microservices") == TaskComplexity.TIER_4_COMPLEX_REPO
    assert classify_task_complexity("Database schema migration across all files") == TaskComplexity.TIER_4_COMPLEX_REPO
    assert classify_task_complexity("System-wide refactoring of the async engine") == TaskComplexity.TIER_4_COMPLEX_REPO


def test_02_conservative_fallback_and_environment_override(monkeypatch):
    # Ambiguous task defaults conservatively to Tier 3
    ambiguous = "Handle the edge cases in the data processing flow."
    assert classify_task_complexity(ambiguous) == TaskComplexity.TIER_3_MULTI_FILE

    # Force override via environment variable
    monkeypatch.setenv("CRUSORAI_FORCE_COMPLEXITY_TIER", "1")
    assert classify_task_complexity("Database schema migration across all files") == TaskComplexity.TIER_1_SIMPLE_LOOKUP

    monkeypatch.setenv("CRUSORAI_FORCE_COMPLEXITY_TIER", "4")
    assert classify_task_complexity("What is this function?") == TaskComplexity.TIER_4_COMPLEX_REPO


# ===========================================================================
# 2. State-Level Escalation and Recovery
# ===========================================================================

def test_03_state_level_escalation_on_failures_and_progress():
    # Simple lookup task normally Tier 1, but with active recovery_mode -> Tier 4
    state_failure = {
        "recovery_mode": True,
        "failed_steps": ["pytest failed on test_login"],
    }
    assert classify_task_complexity("Where is User defined?", state_failure) == TaskComplexity.TIER_4_COMPLEX_REPO

    # With replan_count > 0 -> Tier 4
    state_replan = {"replan_count": 1}
    assert classify_task_complexity("Where is User defined?", state_replan) == TaskComplexity.TIER_4_COMPLEX_REPO

    # Multi-step progress completed -> Tier 3
    state_progress = {"steps_completed": ["created file1.py", "created file2.py"]}
    assert classify_task_complexity("Where is User defined?", state_progress) == TaskComplexity.TIER_3_MULTI_FILE

    # Dynamic escalation function
    current = TaskComplexity.TIER_1_SIMPLE_LOOKUP
    escalated = escalate_complexity(current, {"failed_steps": ["err"]})
    assert escalated == TaskComplexity.TIER_4_COMPLEX_REPO

    escalated_multi = escalate_complexity(current, {"steps_completed": ["a", "b"]})
    assert escalated_multi == TaskComplexity.TIER_3_MULTI_FILE


# ===========================================================================
# 3. Context Layer Gating Enforcement
# ===========================================================================

def test_04_layer_gating_tier_allowlists():
    t1_layers = get_active_layers_for_tier(TaskComplexity.TIER_1_SIMPLE_LOOKUP)
    assert "repo_map" not in t1_layers
    assert "git_context" not in t1_layers
    assert "plan" not in t1_layers
    assert "long_term_memory" not in t1_layers
    assert "task" in t1_layers
    assert "relevant_chunks" in t1_layers
    assert "conventions" in t1_layers
    assert "quality" in t1_layers

    t2_layers = get_active_layers_for_tier(TaskComplexity.TIER_2_LOCAL_MODIFICATION)
    assert "repo_map" not in t2_layers
    assert "long_term_memory" not in t2_layers
    assert "git_context" in t2_layers
    assert "plan" in t2_layers
    assert "progress" in t2_layers

    t3_layers = get_active_layers_for_tier(TaskComplexity.TIER_3_MULTI_FILE)
    assert "repo_map" in t3_layers
    assert "git_context" in t3_layers
    assert "skills" in t3_layers
    assert "long_term_memory" not in t3_layers

    t4_layers = get_active_layers_for_tier(TaskComplexity.TIER_4_COMPLEX_REPO)
    assert t4_layers == ALL_CONTEXT_LAYERS


def test_05_layer_gating_kill_switch(monkeypatch):
    monkeypatch.setenv("CRUSORAI_CONTEXT_GATING", "off")
    t1_layers = get_active_layers_for_tier(TaskComplexity.TIER_1_SIMPLE_LOOKUP)
    assert t1_layers == ALL_CONTEXT_LAYERS
    assert "repo_map" in t1_layers
    assert "long_term_memory" in t1_layers


# ===========================================================================
# 4. Context Budget Allocation Caps
# ===========================================================================

def test_06_context_budget_allocation_caps():
    from src.context.ranking.layer_policy import allocate_budget

    max_tokens = 32000
    # Tier 1 caps context budget to 3500
    ctx_t1, hist_t1 = allocate_budget(max_tokens, TaskType.EXPLORE, complexity=TaskComplexity.TIER_1_SIMPLE_LOOKUP)
    assert ctx_t1 <= 3500
    assert hist_t1 == max_tokens - ctx_t1

    # Tier 2 caps context budget to 7000
    ctx_t2, hist_t2 = allocate_budget(max_tokens, TaskType.CREATE, complexity=TaskComplexity.TIER_2_LOCAL_MODIFICATION)
    assert ctx_t2 <= 7000
    assert hist_t2 == max_tokens - ctx_t2

    # Tier 3 caps context budget to 14000
    ctx_t3, hist_t3 = allocate_budget(max_tokens, TaskType.CREATE, complexity=TaskComplexity.TIER_3_MULTI_FILE)
    assert ctx_t3 <= 14000
    assert hist_t3 == max_tokens - ctx_t3

    # Tier 4 allows full ratio (e.g. 0.45 * 32000 = 14400)
    ctx_t4, hist_t4 = allocate_budget(max_tokens, TaskType.CREATE, complexity=TaskComplexity.TIER_4_COMPLEX_REPO)
    assert ctx_t4 == int(32000 * 0.45)


# ===========================================================================
# 5. Incremental Retrieval Caching in ChunkIndex
# ===========================================================================

def test_07_chunk_index_retrieval_caching_and_invalidation(tmp_path):
    ws = tmp_path / "ws_cache"
    ws.mkdir()
    f1 = ws / "test_file.py"
    f1.write_text("def hello_world():\n    return 'hello'\n", encoding="utf-8")

    state = {
        "workspace": str(ws),
        "current_task": "find hello_world function",
        "thread_id": "test_chunk_cache",
    }

    # 1. First retrieval call populates cache
    msg1 = build_relevant_chunks_layer(state)
    assert msg1 is not None
    assert "hello_world" in msg1.content

    # 2. Second retrieval call should hit the in-memory cache directly
    msg2 = build_relevant_chunks_layer(state)
    assert msg2 is msg1  # Exact object identity on cache hit!

    # 3. Bump index generation (e.g. after file tool mutation)
    gen_before = get_index_generation(ws)
    gen_after = bump_index_generation(ws)
    assert gen_after == gen_before + 1

    # 4. Next call should re-evaluate retrieval with fresh generation
    msg3 = build_relevant_chunks_layer(state)
    assert msg3 is not None
    assert msg3 is not msg1  # Freshly rendered after generation bump!


# ===========================================================================
# 6. RepoMap Efficiency and Walk Elimination
# ===========================================================================

def test_08_repomap_efficiency_and_dirty_invalidation(tmp_path):
    ws = tmp_path / "ws_repo"
    ws.mkdir()
    f1 = ws / "sample.py"
    f1.write_text("def sample(): pass\n", encoding="utf-8")

    rm = RepoMap(ws)
    gen_start = get_repo_map_generation(ws)

    # First get_map builds and caches
    map1 = rm.get_map()
    assert "sample.py" in map1
    assert rm._cache is not None
    assert rm._dirty is False
    gen_after_build = get_repo_map_generation(ws)

    # Within TTL and not dirty, get_map should reuse cache without disk walk
    map2 = rm.get_map()
    assert map2 == map1

    # Invalidate sets dirty flag and bumps generation
    rm.invalidate()
    assert rm._dirty is True
    assert get_repo_map_generation(ws) == gen_after_build + 1

    # _is_stale returns True immediately when dirty
    assert rm._is_stale() is True


# ===========================================================================
# 7. Granular Layer Caching Across Multi-Turn Runs
# ===========================================================================

def test_09_granular_layer_caching_across_turns(tmp_path):
    ws = tmp_path / "ws_engine"
    ws.mkdir()
    (ws / "main.py").write_text("def main(): return 0\n", encoding="utf-8")

    eng = ContextEngine(max_tokens=8000, model="gpt-4o", probe_window=False)
    sys_msg = SystemMessage(content="You are Crusor AI.")

    # Turn 1: Simple lookup task
    state_turn1 = {
        "workspace": str(ws),
        "current_task": "Find where main is defined",
        "steps_completed": [],
        "failed_steps": [],
        "thread_id": "session_granular",
    }
    msgs1 = eng.build_ai_messages(state_turn1, sys_msg)
    assert msgs1 is not None

    # Verify that repo_map was GATED OUT in Tier 1!
    assert "repo_map" not in eng._last_layers_sent
    assert "relevant_chunks" in eng._last_layers_sent

    cache_turn1 = dict(eng._layer_cache)
    chunks_msg1 = cache_turn1.get("relevant_chunks")
    assert chunks_msg1 is not None

    # Turn 2: steps_completed advances (real progress noise)
    state_turn2 = dict(state_turn1)
    state_turn2["steps_completed"] = ["located main.py"]

    msgs2 = eng.build_ai_messages(state_turn2, sys_msg)
    assert msgs2 is not None

    # Because task and index generation were unchanged, relevant_chunks retained exact identity!
    assert eng._layer_cache.get("relevant_chunks") is chunks_msg1


# ===========================================================================
# 8. Escalation End-to-End in ContextEngine
# ===========================================================================

def test_10_context_engine_escalation_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_REPO_MAP", "on")
    ws = tmp_path / "ws_escalate"
    ws.mkdir()
    (ws / "a.py").write_text("class A: pass\n", encoding="utf-8")

    eng = ContextEngine(max_tokens=8000, model="gpt-4o", probe_window=False)
    sys_msg = SystemMessage(content="You are Crusor AI.")

    # Starts as simple lookup (Tier 1 -> repo_map gated out)
    state_1 = {
        "workspace": str(ws),
        "current_task": "Find class A",
        "thread_id": "session_esc",
    }
    eng.build_ai_messages(state_1, sys_msg)
    assert "repo_map" not in eng._last_layers_sent

    # Tool encounters a failure -> triggers recovery escalation (Tier 4)
    state_2 = dict(state_1)
    state_2["recovery_mode"] = True
    state_2["failed_steps"] = ["SyntaxError in file"]

    eng.build_ai_messages(state_2, sys_msg)
    # Now in Tier 4: repo_map and recovery are active!
    assert "repo_map" in eng._last_layers_sent
    assert "recovery" in eng._last_layers_sent


# ===========================================================================
# 9. Prompt-Cache Prefix Stability & Safety Invariant Preservation
# ===========================================================================

def test_11_prompt_cache_prefix_stability_and_safety_invariant(tmp_path):
    ws = tmp_path / "ws_safety"
    ws.mkdir()
    (ws / "app.py").write_text("print('hello')\n", encoding="utf-8")

    eng = ContextEngine(max_tokens=8000, model="gpt-4o", probe_window=False)
    sys_msg = SystemMessage(content="CRITICAL SAFETY: Never access unauthorized paths.")

    state = {
        "workspace": str(ws),
        "current_task": "Where is print called?",
        "thread_id": "session_safety",
        "messages": [HumanMessage(content="Where is print called?")],
    }

    msgs = eng.build_ai_messages(state, sys_msg)
    # First message is the composed system message containing safety instructions
    first_msg = msgs[0]
    assert isinstance(first_msg, SystemMessage)
    assert "CRITICAL SAFETY: Never access unauthorized paths." in first_msg.content

    # In Tier 1, no volatile tail is emitted, keeping the prompt completely stable
    assert not any(getattr(m, "response_metadata", {}).get("volatile") for m in msgs)

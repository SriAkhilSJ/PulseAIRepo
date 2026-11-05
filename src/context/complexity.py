"""
Task Complexity Classification and Context Layer Gating (Phase 9.2.2.4)
========================================================================

Deterministic task complexity classification and layer gating for CrusorCodeAI.
Ensures the Context Engine constructs ONLY the layers required for the task,
reducing base context token consumption, retrieval overhead, and file-tree AST walks
without weakening agent intelligence, safety, or verification.
"""

from __future__ import annotations

import os
import re
from enum import Enum
from typing import Any, Optional


class TaskComplexity(Enum):
    """Deterministic complexity tiers for Context Engine layer gating."""
    TIER_1_SIMPLE_LOOKUP = 1
    TIER_2_LOCAL_MODIFICATION = 2
    TIER_3_MULTI_FILE = 3
    TIER_4_COMPLEX_REPO = 4


# All 18 canonical layers recognized by Crusor Context Engine
ALL_CONTEXT_LAYERS: frozenset[str] = frozenset({
    "repo_map",
    "relevant_chunks",
    "git_context",
    "task",
    "plan",
    "progress",
    "recovery",
    "replan",
    "attempt_history",
    "long_term_memory",
    "tool_memory",
    "ambiguity",
    "tone",
    "quality",
    "conventions",
    "memory_validation",
    "reflections",
    "skills",
})

# Layer gating allowlists per complexity tier
TIER_ALLOWED_LAYERS: dict[TaskComplexity, frozenset[str]] = {
    TaskComplexity.TIER_1_SIMPLE_LOOKUP: frozenset({
        "task",
        "relevant_chunks",
        "conventions",
        "quality",
    }),
    TaskComplexity.TIER_2_LOCAL_MODIFICATION: frozenset({
        "task",
        "relevant_chunks",
        "git_context",
        "conventions",
        "quality",
        "plan",
        "progress",
        "tone",
    }),
    TaskComplexity.TIER_3_MULTI_FILE: frozenset({
        "repo_map",
        "relevant_chunks",
        "git_context",
        "task",
        "plan",
        "progress",
        "conventions",
        "quality",
        "tone",
        "skills",
        "recovery",
        "replan",
    }),
    TaskComplexity.TIER_4_COMPLEX_REPO: ALL_CONTEXT_LAYERS,
}

# Context budget caps by complexity tier (to avoid bloating prompt when simple)
TIER_CONTEXT_BUDGET_CAPS: dict[TaskComplexity, int] = {
    TaskComplexity.TIER_1_SIMPLE_LOOKUP: 3500,
    TaskComplexity.TIER_2_LOCAL_MODIFICATION: 7000,
    TaskComplexity.TIER_3_MULTI_FILE: 14000,
    TaskComplexity.TIER_4_COMPLEX_REPO: 32000,
}

# Regex patterns for deterministic classification
_RE_TIER_4 = re.compile(
    r"\b(architecture|redesign|restructure|migration|across all (?:files|modules)|"
    r"system-wide|database schema|multi-agent|cross-module|heavy refactor)\b",
    re.IGNORECASE,
)

_RE_TIER_3 = re.compile(
    r"\b(across modules|frontend and backend|integrate|multiple files|"
    r"components and services|pipeline|models and views|end-to-end|feature across|"
    r"multi-file|several modules)\b",
    re.IGNORECASE,
)

_RE_TIER_1_SIGNALS = re.compile(
    r"\b(find|locate|where is|what is|explain|show me|read|search for|how does|"
    r"check|describe|look up|what does|inspect|display|print)\b",
    re.IGNORECASE,
)

_RE_MUTATION_SIGNALS = re.compile(
    r"\b(write|edit|fix|modify|update|create|implement|delete|refactor|add function|"
    r"add a test|patch|change|tweak|replace|remove|build|make)\b",
    re.IGNORECASE,
)

_RE_TIER_2_SIGNALS = re.compile(
    r"\b(fix|patch|modify|update|add (?:a )?(?:unit )?test|add function|change|tweak|in file|"
    r"in the function|single file|local test)\b",
    re.IGNORECASE,
)


def classify_task_complexity(
    task: str,
    state: Optional[dict[str, Any]] = None,
) -> TaskComplexity:
    """Deterministically classify task complexity tier without any LLM call."""
    # 0. Test & operator override
    override = os.environ.get("CRUSORAI_FORCE_COMPLEXITY_TIER", "").strip() or os.environ.get("CRUSORAI_CONTEXT_TIER", "").strip()
    if override:
        try:
            val = int(override)
            for tier in TaskComplexity:
                if tier.value == val:
                    return tier
        except ValueError:
            # Unknown tier classification -> treat conservatively as Tier 3
            return TaskComplexity.TIER_3_MULTI_FILE

    # 1. State-level failure & escalation triggers
    if state:
        # Failure or recovery active -> full diagnostic context required
        if state.get("recovery_mode") or state.get("failed_steps") or state.get("replan_count", 0) > 0:
            return TaskComplexity.TIER_4_COMPLEX_REPO
        if state.get("prior_attempts"):
            return TaskComplexity.TIER_4_COMPLEX_REPO

        # Multi-step progress -> at least multi-file tier
        completed = state.get("steps_completed", [])
        if len(completed) >= 2:
            return TaskComplexity.TIER_3_MULTI_FILE

    text = (task or "").strip()
    if not text:
        return TaskComplexity.TIER_1_SIMPLE_LOOKUP

    # 2. Check Tier 4 signals (Architecture, system-wide changes)
    if _RE_TIER_4.search(text):
        return TaskComplexity.TIER_4_COMPLEX_REPO

    # 3. Check Tier 3 signals (Multi-file, cross-module integration)
    if _RE_TIER_3.search(text):
        return TaskComplexity.TIER_3_MULTI_FILE

    # 4. Check Tier 1 signals (Pure lookups, searches, explanations)
    has_lookup = bool(_RE_TIER_1_SIGNALS.search(text))
    has_mutation = bool(_RE_MUTATION_SIGNALS.search(text))

    if has_lookup and not has_mutation and len(text) < 300:
        return TaskComplexity.TIER_1_SIMPLE_LOOKUP

    # 5. Check Tier 2 signals (Localized file fix / edit)
    if _RE_TIER_2_SIGNALS.search(text) and len(text) < 400:
        return TaskComplexity.TIER_2_LOCAL_MODIFICATION

    # 6. Conservative fallback: Tier 3 when uncertain
    return TaskComplexity.TIER_3_MULTI_FILE


def escalate_complexity(
    current: TaskComplexity,
    state: dict[str, Any],
) -> TaskComplexity:
    """Dynamically escalate complexity tier if execution reveals new failures or requirements."""
    if state.get("recovery_mode") or state.get("failed_steps") or state.get("replan_count", 0) > 0:
        return TaskComplexity.TIER_4_COMPLEX_REPO

    # Simple tasks escalate when multiple files are touched
    modified = state.get("modified_files") or state.get("files_modified") or []
    if len(modified) > 1 and current.value < TaskComplexity.TIER_3_MULTI_FILE.value:
        return TaskComplexity.TIER_3_MULTI_FILE

    completed = state.get("steps_completed", [])
    if len(completed) >= 2 and current.value < TaskComplexity.TIER_3_MULTI_FILE.value:
        return TaskComplexity.TIER_3_MULTI_FILE

    return current


def get_active_layers_for_tier(tier: TaskComplexity) -> frozenset[str]:
    """Return the set of active layers for a complexity tier, honoring kill-switch."""
    if os.environ.get("CRUSORAI_CONTEXT_GATING", "").strip().lower() == "off":
        return ALL_CONTEXT_LAYERS

    # Unknown tier classification -> treat conservatively with ALL_CONTEXT_LAYERS
    return TIER_ALLOWED_LAYERS.get(tier, ALL_CONTEXT_LAYERS)

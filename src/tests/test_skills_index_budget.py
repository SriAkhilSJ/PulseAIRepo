"""The skills index has a cost ceiling — pinned (2026-10-31).

Measured before this: with the installed catalog (241 SKILL.md files, 240
enabled) the rendered index was **76,270 chars = 19,078 tokens**, i.e. 86.5% of
the assembled system prompt (22,066 tokens), re-sent on EVERY provider call of
EVERY turn. `compact_categories` — upstream's names-only demotion tier — was
never driven by any caller, so the block had no ceiling.

These pins hold the three properties the fix must never lose:

1. **Discovery survives any budget** — a skill's NAME is always listed.
2. **The ceiling is respected** (entries + scaffolding, ~chars/4).
3. **0 means legacy** — the exact unbounded render, for rollback and for
   parity work.
"""
from __future__ import annotations

import pytest

from src.prompts.hermes.skills_index import (
    DEFAULT_SKILLS_INDEX_MAX_TOKENS,
    apply_skills_index_budget,
    skills_index_token_budget,
)

ENTRIES = [
    "  frontend:",
    "    - frontend-architect: " + "A" * 400,
    "    - design-system: " + "B" * 120,
    "  backend:",
    "    - api-architect: " + "C" * 300,
    "    - db-architect: " + "D" * 40,
]


def _tokens(lines: list[str]) -> int:
    return sum(len(line) + 1 for line in lines) // 4


def test_default_budget_is_finite_and_documented():
    assert DEFAULT_SKILLS_INDEX_MAX_TOKENS > 0
    assert DEFAULT_SKILLS_INDEX_MAX_TOKENS <= 8000, (
        "the ceiling must stay well under the 19k-token unbounded render"
    )


def test_env_knob_reads_per_call(monkeypatch):
    monkeypatch.setenv("CRUSORAI_SKILLS_INDEX_MAX_TOKENS", "1234")
    assert skills_index_token_budget() == 1234
    monkeypatch.setenv("CRUSORAI_SKILLS_INDEX_MAX_TOKENS", "0")
    assert skills_index_token_budget() == 0
    monkeypatch.setenv("CRUSORAI_SKILLS_INDEX_MAX_TOKENS", "not-a-number")
    assert skills_index_token_budget() == DEFAULT_SKILLS_INDEX_MAX_TOKENS
    monkeypatch.delenv("CRUSORAI_SKILLS_INDEX_MAX_TOKENS", raising=False)
    assert skills_index_token_budget() == DEFAULT_SKILLS_INDEX_MAX_TOKENS


def test_zero_budget_is_the_legacy_unbounded_render():
    out, trimmed = apply_skills_index_budget(list(ENTRIES), max_tokens=0)
    assert out == ENTRIES
    assert trimmed == 0


def test_small_catalog_is_untouched():
    """A repo with a handful of skills must render byte-identically."""
    out, trimmed = apply_skills_index_budget(list(ENTRIES), max_tokens=100_000)
    assert out == ENTRIES
    assert trimmed == 0


def test_over_budget_keeps_every_name_and_states_the_trim():
    out, trimmed = apply_skills_index_budget(list(ENTRIES), max_tokens=120)
    assert trimmed > 0
    text = "\n".join(out)
    # 1. Discovery: every skill is still findable by name.
    for name in ("frontend-architect", "design-system", "api-architect", "db-architect"):
        assert name in text, f"{name} vanished from the index"
    # 2. Honesty: the model is told the list is trimmed and how to load one.
    assert "name only" in text and "skill_view" in text
    # 3. The ceiling binds.
    assert _tokens(out) <= 120 + 12, f"budget exceeded: {_tokens(out)} tokens"


def test_budget_is_spent_cheapest_first_not_alphabetically():
    """Round-robin + shortest-description-first: the most skills get described.

    Alphabetical fill would spend the whole budget on the first category and
    leave `backend` names-only; that is the unfair (and useless) failure mode.
    """
    out, _ = apply_skills_index_budget(list(ENTRIES), max_tokens=160)
    text = "\n".join(out)
    assert "db-architect: " in text, "the cheapest entry should have been described"
    assert "frontend-architect: " not in text, "the 400-char entry cannot fit this budget"


def test_names_only_floor_still_reports_dropped_skills():
    """A budget smaller than the name list must not silently lose skills."""
    many = [f"    - skill-{i:03d}: " + "x" * 200 for i in range(120)]
    out, dropped = apply_skills_index_budget(many, max_tokens=60)
    assert dropped > 0
    assert "hub_search" in "\n".join(out)


def test_cache_key_includes_the_budget():
    """An env change must never serve a render produced under the old ceiling."""
    import inspect

    from src.prompts.hermes import skills_index as mod

    source = inspect.getsource(mod.build_skills_system_prompt)
    assert "skills_index_token_budget()" in source, (
        "the budget must be part of the cache key, or lowering it mid-process "
        "keeps serving the expensive cached render"
    )

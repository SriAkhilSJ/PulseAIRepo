"""Pulse's Hermes-parity prompt engine.

Ported from ``NousResearch/hermes-agent`` at the commit pinned in
``upstream_corpus.json`` — see ``PROVENANCE.md`` for the per-symbol map and for
what was deliberately NOT ported.

Layout mirrors upstream's ``agent/`` prompt subsystem::

    upstream                            Pulse
    agent/prompt_builder.py   (partial)  → guidance.py, context_files.py, skills_index.py
    agent/system_prompt.py               → system_prompt.py
    agent/prompt_caching.py              → src/context/prompt_cache_plan.py
    agent/prompt_cache_boundary.py       → src/context/prompt_cache_boundary.py
    agent/prompt_cache_scope.py          → src/context/prompt_cache_scope.py
    agent/plan_prompt.py / learn_prompt.py → plan_learn.py

The engine is stdlib-only and side-effect-free: it never opens a provider
connection, never mutates history, and its stable tier is byte-identical for
the life of a session (that is the contract the parity tests enforce).
"""
from __future__ import annotations

from src.prompts.hermes.plan_learn import build_learn_prompt, build_plan_prompt, plan_target_path
from src.prompts.hermes.system_prompt import (
    build_system_prompt,
    build_system_prompt_parts,
    format_tools_for_system_message,
    invalidate_system_prompt,
    reconstruct_static_prefix,
    system_prompt_stats,
)
from src.prompts.hermes.view import PulsePromptView, resolve_valid_tool_names, view_from_config

__all__ = [
    "PulsePromptView",
    "build_learn_prompt",
    "build_plan_prompt",
    "build_system_prompt",
    "build_system_prompt_parts",
    "format_tools_for_system_message",
    "invalidate_system_prompt",
    "plan_target_path",
    "reconstruct_static_prefix",
    "resolve_valid_tool_names",
    "system_prompt_stats",
    "view_from_config",
]

"""The neutral execution phase — pulse has NO phase lexicon.

Hermes runs no keyword→phase machinery at all: steering comes from STATE
(todo verification gates, budget reserves, verify-on-stop nudges) and the
system prompt. Pulse's former keyword lexicon here (plan-step words like
"build"/"browser" picking a phase, then guidance strings and — before
fa5e77e8 — tool amputation) was an invention and a hardcode of exactly the
class the owner banned; its amputation form broke the field on
2026-09-07 (a "Run the build..." step stripped the browser tools and
todo_list mid-turn).

What remains: ``ExecutionPhase`` (the value type chat_graph's STATE-driven
phases — forced delivery on an empty autonomous workspace, the
verification budget reserve — construct and consume) and ``base_phase()``,
the no-policy default. Any phase derived from WORDS must not come back;
the per-turn capability waist (toolsets.resolve_runtime_tool_names) is the
one deliberate narrowing.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPhase:
    name: str
    # None = no tool hiding (hermes discipline). Only chat_graph's
    # state-driven phases ever construct a non-None allowlist.
    allowed: frozenset[str] | None
    max_file_mutations_per_turn: int = 0
    guidance: str = ""


def base_phase() -> ExecutionPhase:
    """The no-policy phase: no guidance insertion, no budgets, no allowlist."""
    return ExecutionPhase("general", None)

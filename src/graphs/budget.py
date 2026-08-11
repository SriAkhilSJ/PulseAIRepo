# src/graphs/budget.py
"""
Agent iteration budget + LangGraph recursion-limit backstop (P0-D extraction
from chat_graph.py).

Pure: reads env + state only. The budget is the intended safety valve that
governs when a run concludes; the recursion_limit is sized well above it so
the grace path is always reachable. Depends only on state (for the type hint).
"""
from __future__ import annotations

import os

from src.graphs.state import AgentState


# D40: agent iteration budget (hermes max_iterations / iteration_budget).
# Wired at the ai_node entry: when iteration_used reaches the budget, tools
# are hidden and ONE full grace call (hermes' budget-remaining>0 OR
# _budget_grace_call loop) produces the final summary instead of cutting the
# model off. The budget is the intended safety valve; the graph
# recursion_limit is sized (via _recursion_limit) well above it so the grace
# path is always reachable. Default 30; clamped to <=45 regardless of env.
_ITERATION_BUDGET_DEFAULT = 30
_ITERATION_BUDGET_CLAMP = 45

_GRACE_NUDGE = (
    "[System: The agent iteration budget for this run is exhausted. Do NOT "
    "call any more tools. Provide your final answer now: summarize what was "
    "accomplished, what remains unfinished or blocked, and stop. If the task "
    "needs another pass, say so plainly and report the current state so the "
    "user can continue.]"
)


def _iteration_budget() -> int:
    try:
        value = int(os.environ.get("AGENT_ITERATION_BUDGET", _ITERATION_BUDGET_DEFAULT))
    except (TypeError, ValueError):
        value = _ITERATION_BUDGET_DEFAULT
    return min(max(1, value), _ITERATION_BUDGET_CLAMP)


# Each ai-node iteration costs several LangGraph recursion super-steps
# (ai_node + tools node + status/recovery nodes), so the hard
# recursion_limit must sit well above the iteration budget — otherwise
# GraphRecursionError kills runs mid-work (Test-2 retest D4 hit 50 at only
# ~16 iterations, losing 11 written files). Budget governs; this is backstop.
def _recursion_limit() -> int:
    return max(200, _iteration_budget() * 4 + 40)


def _budget_exhausted(state: AgentState) -> bool:
    used = int(state.get("iteration_used", 0))
    return used >= _iteration_budget()

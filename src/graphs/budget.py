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
# path is always reachable. Default 30; clamped to <=50 regardless of env.
# 50 gives the retest harness (scaffold + npm install + copy + typecheck with
# retries) the headroom it needs without a runaway loop burning the budget.
_ITERATION_BUDGET_DEFAULT = 30
_ITERATION_BUDGET_CLAMP = 50

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


_TOKEN_BUDGET_DEFAULT = 120_000
_TOKEN_BUDGET_CLAMP = 2_000_000
# This does not increase the cap. It marks the final bounded slice as
# verification/repair capacity so delivery and output-limit continuations do
# not consume the entire run before any executable receipt can be produced.
_VERIFICATION_TOKEN_RESERVE_DEFAULT = 30_000
_VERIFICATION_ITERATION_RESERVE_DEFAULT = 6


def _token_budget() -> int | None:
    """Known provider-token ceiling for one run; 0 disables the token cap."""
    raw = os.environ.get("AGENT_TOKEN_BUDGET", str(_TOKEN_BUDGET_DEFAULT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _TOKEN_BUDGET_DEFAULT
    if value <= 0:
        return None
    return min(max(10_000, value), _TOKEN_BUDGET_CLAMP)


def _verification_token_reserve() -> int:
    try:
        value = int(os.environ.get(
            "AGENT_VERIFICATION_TOKEN_RESERVE", _VERIFICATION_TOKEN_RESERVE_DEFAULT
        ))
    except (TypeError, ValueError):
        value = _VERIFICATION_TOKEN_RESERVE_DEFAULT
    cap = _token_budget()
    if cap is None or value <= 0:
        return 0
    return min(value, cap // 2)


def _verification_iteration_reserve() -> int:
    try:
        value = int(os.environ.get(
            "AGENT_VERIFICATION_ITERATION_RESERVE",
            _VERIFICATION_ITERATION_RESERVE_DEFAULT,
        ))
    except (TypeError, ValueError):
        value = _VERIFICATION_ITERATION_RESERVE_DEFAULT
    if value <= 0:
        return 0
    return min(value, _iteration_budget() // 2)


def _verification_reserve_reached(state: AgentState) -> bool:
    """Whether delivery entered the reserved final token/iteration slice."""
    used_iterations = int(state.get("iteration_used", 0) or 0)
    iteration_reserve = _verification_iteration_reserve()
    iteration_near = (
        iteration_reserve > 0
        and used_iterations >= _iteration_budget() - iteration_reserve
        and used_iterations < _iteration_budget()
    )

    cap = _token_budget()
    token_reserve = _verification_token_reserve()
    token_near = False
    if cap is not None and token_reserve > 0:
        usage = state.get("turn_token_usage") or state.get("token_usage", {}) or {}
        consumed = int(usage.get("total_tokens", 0) or 0)
        token_near = consumed >= max(0, cap - token_reserve) and consumed < cap
    return iteration_near or token_near


def _budget_exhausted(state: AgentState) -> bool:
    used = int(state.get("iteration_used", 0))
    if used >= _iteration_budget():
        return True
    token_cap = _token_budget()
    if token_cap is None:
        return False
    usage = state.get("turn_token_usage") or state.get("token_usage", {}) or {}
    return int(usage.get("total_tokens", 0) or 0) >= token_cap

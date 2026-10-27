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
# The configured number is an INCLUSIVE provider-call ceiling. Its final slot
# is reserved for one tool-free response, following OpenCode's max-step shape:
# work calls occupy slots 1..N-1, then slot N receives the full history plus a
# final-response request with tools disabled. This prevents a separate N+1
# "grace" request from being cancelled by an external N-call circuit breaker.
# A legacy already-exhausted checkpoint can still take one compatibility grace
# call. The graph recursion_limit remains a backstop above this budget.
# Default 45 (was 30); clamped to <=60.
# Hermes parent is unlimited (sys.maxsize) + subagents 50; 30 cut the luxury
# site build at 27/30 (trace 1089s) before screenshots. 45 gives the same
# headroom as hermes retest harness without runaway.
_ITERATION_BUDGET_DEFAULT = 45
_ITERATION_BUDGET_CLAMP = 60

# hermes agent/context_compressor.py:261 MAX_ITERATIONS_SUMMARY_REQUEST —
# VERBATIM. handle_max_iterations (agent/chat_completion_helpers.py:2119)
# appends it as a USER message on the FULL history and the summary call
# carries NO tools key (_iteration_summary_chat_kwargs :2025; the codex
# attempt literally pops "tools" :2070). Field 2026-09-09 @b75cd4c6: the old
# crusor grace (system nudge + _drop_tool_pairs) amnesia'd the model into
# "I'll start by exploring..." + a raw text tool_call AFTER 111s of real
# work — the owner's screenshot. The model must SEE its work to summarize it.
_MAX_ITERATIONS_SUMMARY_REQUEST = (
    "You've reached the maximum number of tool-calling iterations allowed. "
    "Please provide a final response summarizing what you've found and "
    "accomplished so far, without calling any more tools."
)
# OpenCode max-steps shape: reserve the configured FINAL call instead of
# spending all N calls on tools and requiring an unbudgeted N+1 farewell.
# Whether this response can be marked completed is decided independently from
# deterministic workspace/verification evidence; wording never upgrades the
# verdict.
_FINAL_RESPONSE_RESERVE_REQUEST = (
    "This is the final provider call reserved for your response. Tools are "
    "disabled. Give the user a concise final report of what was accomplished, "
    "the concrete verification evidence, and anything still incomplete. Do "
    "not describe future tool calls or claim unverified work is complete."
)
# The plan-complete wrap cut (field 2026-09-10): the model kept tooling past
# the wrap nudge and the shortcut finalized with its last act a TOOL CALL —
# no closing answer ever streamed ("stopped in middle"). The second wrap hit
# now runs hermes handle_max_iterations' SHAPE — one toolless summary call —
# with wording that names the real trigger, not the iteration budget.
_PLAN_WRAP_SUMMARY_REQUEST = (
    "Your task list is complete. Please provide a final response summarizing "
    "what you've accomplished and found so far, without calling any more tools."
)
# Legacy name (gates.py comment references it); same text.
_GRACE_NUDGE = _MAX_ITERATIONS_SUMMARY_REQUEST

# Field 2026-09-16 (hermes audit): when the TOKEN leg trips, the iterations
# wording lies to the model ("maximum number of tool-calling iterations"
# while iterations had headroom left). Same shape — one toolless summary
# call on the full history — honest trigger name.
_TOKEN_BUDGET_SUMMARY_REQUEST = (
    "You've reached this run's token budget. Please provide a final response "
    "summarizing what you've found and accomplished so far, without calling "
    "any more tools."
)


def _iteration_budget() -> int:
    try:
        value = int(os.environ.get("AGENT_ITERATION_BUDGET", _ITERATION_BUDGET_DEFAULT))
    except (TypeError, ValueError):
        value = _ITERATION_BUDGET_DEFAULT
    return min(max(1, value), _ITERATION_BUDGET_CLAMP)


def _final_response_reserve_reached(state: AgentState) -> bool:
    """Whether the next provider request is the inclusive final call.

    A budget of N permits exactly N provider requests. Once N-1 have completed,
    the remaining request is tool-free so the turn can close inside the bound.
    Already-exhausted checkpoints are handled by the legacy grace path instead.
    """
    used = int(state.get("iteration_used", 0) or 0)
    budget = _iteration_budget()
    return used < budget and used >= budget - 1


# hermes turn_iteration_prep.py::_maybe_inject_iteration_budget_warning:
# the hard wall has a SOFT checkpoint in front of it. Once the run enters
# its final slice (default 90%), one shot tells the model to land durable
# progress and head for the finish instead of hitting the wall cold mid-work
# (which is exactly when the grace summary has the least to summarize).
# AGENT_BUDGET_WARNING_RATIO=0 (or "off") disables the notice entirely.
_BUDGET_WARNING_RATIO_DEFAULT = 0.9


def _budget_warning_ratio() -> float | None:
    raw = os.environ.get("AGENT_BUDGET_WARNING_RATIO", "").strip().lower()
    if raw in {"0", "off", "none", "false"}:
        return None
    try:
        ratio = float(raw) if raw else _BUDGET_WARNING_RATIO_DEFAULT
    except ValueError:
        ratio = _BUDGET_WARNING_RATIO_DEFAULT
    if not (0 < ratio < 1):
        return None
    return ratio


def _budget_warning_threshold() -> int | None:
    """Iteration count at which the one-shot checkpoint warning fires.

    The checkpoint must fire before the reserved final-response slot:
    ``used >= min(ratio * max_total, max_total - 2)``. Budgets below three
    calls have no useful warning position: one call cannot both warn and work,
    and the final slot must remain text-only.
    """
    ratio = _budget_warning_ratio()
    budget = _iteration_budget()
    if ratio is None or budget <= 2:
        return None
    return int(min(ratio * budget, budget - 2))


# Each ai-node iteration costs several LangGraph recursion super-steps
# (ai_node + tools node + status/recovery nodes), so the hard
# recursion_limit must sit well above the iteration budget — otherwise
# GraphRecursionError kills runs mid-work (Test-2 retest D4 hit 50 at only
# ~16 iterations, losing 11 written files). Budget governs; this is backstop.
def _recursion_limit() -> int:
    return max(200, _iteration_budget() * 4 + 40)


# Field 2026-09-10: the 120k default cut a HEALTHY turn at iteration 8/30
# (grace receipt: "tokens 137,198/120,000, tripped: tokens" — the model was
# mid-fix with a plan still open). chars/4 request estimates ran ~4-8k per
# call but real provider billing runs 2-3x that once tool schemas and long
# completions count, so a full 30-iteration turn costs ~500k real tokens on
# a ~1M-token window. 600k lets the iteration budget bind first, as
# intended. AGENT_TOKEN_BUDGET=0 still disables the cap entirely.
_TOKEN_BUDGET_DEFAULT = 600_000
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


def _budget_trip_reason(state: AgentState) -> str:
    """Both budget legs with their REAL numbers, and which one tripped.

    Field 2026-09-09 x2: two turns ended in the grace after ~9-11 visible
    model calls while the print blamed "maximum iterations (30)" — the same
    message covers BOTH legs (iterations and tokens), so a token-cap trip
    masquerades as an iteration end and nobody could tell what cut the run.
    Same discipline as the bridge wall receipt: the next grace line must
    diagnose itself.
    """
    used = int(state.get("iteration_used", 0))
    budget = _iteration_budget()
    cap = _token_budget()
    usage = state.get("turn_token_usage") or state.get("token_usage", {}) or {}
    total = int(usage.get("total_tokens", 0) or 0)
    parts = [f"iterations {used}/{budget}"]
    parts.append(f"tokens {total:,}/{cap:,}" if cap is not None else "tokens uncapped")
    if used >= budget:
        parts.append("tripped: iterations")
    elif cap is not None and total >= cap:
        parts.append("tripped: tokens")
    else:
        parts.append("tripped: unknown leg")
    return ", ".join(parts)


def _budget_exhausted(state: AgentState) -> bool:
    used = int(state.get("iteration_used", 0))
    budget = _iteration_budget()
    if used >= budget:
        print(f"[budget] exhausted: iterations {used}/{budget} >= budget", flush=True)
        return True
    token_cap = _token_budget()
    if token_cap is None:
        return False
    usage = state.get("turn_token_usage") or state.get("token_usage", {}) or {}
    total = int(usage.get("total_tokens", 0) or 0)
    if total >= token_cap:
        print(f"[budget] exhausted: tokens {total:,}/{token_cap:,} >= cap", flush=True)
        return True
    return False

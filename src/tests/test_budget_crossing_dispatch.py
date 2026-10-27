"""Budget-crossing dispatch — hermes loop law, pending tools execute.

Field receipt that pinned this (owner log 2026-09-08, engine 9dc843ef,
"browser test and fixx" run): the ai call entered with tools bound one
request under the iteration budget; its own result pushed iteration_used
to the cap; the model's answer was a bound start_terminal call — the dev
server the whole task was for. should_continue checked the budget FIRST
and finalized: the call was never executed (no [tool_node] receipt, no
process id, the card stuck "Running · exit running"), and the final text
promised a browser check that never ran.

Hermes: IterationBudget.consume() (agent/iteration_budget.py) gates the
NEXT MODEL CALL, never the execution of already-emitted tool calls —
turn_iteration_prep.py:108: "Fires at the top of the NEXT iteration, so
the budget-crossing request completes first." The budget still concludes
the run: after the dispatched tools, ai_node uses the inclusive reserved
final slot without tools and the text answer finalizes.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.graphs.gates import should_continue
from src.graphs.progress_helpers import success_step_label


def _state(messages, *, iteration_used: int = 5, **extra):
    base = {
        "messages": messages,
        "iteration_used": iteration_used,
        "current_task": "answer a question about the repo",
        "execution_mode": "agent",
        "workspace": "/nonexistent-ws",
        "finish_nudges": 0,
        "verify_nudges": 0,
    }
    base.update(extra)
    return base


def _tool_call_state(name: str = "run_terminal"):
    return [HumanMessage(content="go"), AIMessage(content="", tool_calls=[
        {"name": name, "args": {"command": "npm run dev"}, "id": "c1"},
    ])]


def test_pending_tool_call_dispatches_at_budget(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "5")
    route = should_continue(_state(_tool_call_state(), iteration_used=5))
    assert route == "tools", "a bound pending call executes even at the cap"


def test_pending_tool_call_dispatches_before_reserved_final_slot(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "5")
    route = should_continue(_state(_tool_call_state(), iteration_used=4))
    assert route == "tools", "the reserve must not drop an already-emitted call"


def test_grace_text_still_finalizes_at_budget(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "5")
    route = should_continue(_state(
        [HumanMessage(content="go"), AIMessage(content="all done.")],
        iteration_used=5,
    ))
    assert route == "finalize", "the safety valve still concludes text-only turns"


def test_cancel_still_wins_over_pending_tools():
    cancelled = AIMessage(
        content="", tool_calls=[{"name": "run_terminal", "args": {}, "id": "c1"}],
    )
    cancelled.additional_kwargs["crusor_cancelled"] = True
    assert should_continue(_state([HumanMessage(content="go"), cancelled])) == "finalize"


def test_ask_mode_never_dispatches_pending_tools():
    route = should_continue(_state(
        _tool_call_state(), execution_mode="ask", iteration_used=0,
    ))
    assert route == "finalize"


def test_dispatch_precedes_budget_check_in_source():
    """Ordering regression guard: the hermes-law dispatch must sit ABOVE the
    budget block inside should_continue."""
    import inspect
    source = inspect.getsource(should_continue)
    assert source.index('if getattr(last_message, "tool_calls", None):') < source.index(
        "if _budget_exhausted(state):"
    )


def test_terminal_alias_gets_run_terminal_label():
    """Field log 2026-09-08: the alias printed the generic 'Completed tool:
    terminal' while run_terminal's honest receipt names the command."""
    label, _ = success_step_label("terminal", {"command": "npm run dev"}, "c1")
    assert label == "Ran command successfully: npm run dev"
    label, _ = success_step_label("run_terminal", {"command": "npm test"}, "c2")
    assert label == "Ran command successfully: npm test"

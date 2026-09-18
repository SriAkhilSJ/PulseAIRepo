"""Hermes-audit fixes (field 2026-09-16), three laws pinned here:

1. CHECKPOINT WARNING BEFORE THE WALL — hermes
   turn_iteration_prep.py::_maybe_inject_iteration_budget_warning: at
   ~90% of the iteration budget one shot tells the model to land durable
   progress and continue, so the run does not hit the wall cold mid-work
   (a cold wall is when the grace summary has the least to summarize).

2. HONEST TRIGGER NAME ON THE SUMMARY REQUEST — when the TOKEN leg trips,
   the farewell request must say "token budget", not "maximum number of
   tool-calling iterations" (same mislabel class the [grace] print fixed).

3. HONEST VERDICT FOR A BUDGET-CUT TURN — hermes
   turn_finalizer.py::_resolve_budget_fallback records
   max_iterations_reached(N/M): a run the VALVE ended is not "completed".
   task_completed=False + task_status="budget_exhausted" flow out through
   the bridge's turn_done.completed so the IDE shows the real outcome, and
   the transcript stamp names the escape hatch (fresh budget next message).

Pure: fake LLMs/engines, no provider keys.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import src.graphs.chat_graph as cg
from src.graphs import budget as bg


@pytest.fixture(autouse=True)
def _clean_budget_env(monkeypatch):
    monkeypatch.delenv("AGENT_BUDGET_WARNING_RATIO", raising=False)
    monkeypatch.delenv("AGENT_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("AGENT_ITERATION_BUDGET", raising=False)


# ── 1. checkpoint-warning threshold ────────────────────────────────────────


def test_warning_threshold_default_90_percent(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "30")
    assert bg._budget_warning_threshold() == 27  # min(27.0, 29)


def test_warning_threshold_stays_strictly_before_the_wall(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "10")
    assert bg._budget_warning_threshold() == 9
    monkeypatch.setenv("AGENT_BUDGET_WARNING_RATIO", "0.5")
    assert bg._budget_warning_threshold() == 5


def test_warning_disabled_and_degenerate_budgets(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "10")
    monkeypatch.setenv("AGENT_BUDGET_WARNING_RATIO", "off")
    assert bg._budget_warning_threshold() is None
    monkeypatch.setenv("AGENT_BUDGET_WARNING_RATIO", "0")
    assert bg._budget_warning_threshold() is None
    monkeypatch.delenv("AGENT_BUDGET_WARNING_RATIO", raising=False)
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "1")
    assert bg._budget_warning_threshold() is None, "a one-lap budget gets no notice"


# ── warning injection in ai_node ───────────────────────────────────────────


class _FakeLLM:
    model = "m"

    def __init__(self):
        self.bound = None
        self.sent_messages = None

    def bind_tools(self, tools):
        b = _FakeLLM()
        self.bound = b
        return b

    def invoke(self, messages, **kwargs):
        self.sent_messages = messages
        return AIMessage(content="working", id="r1")


class _FakeEngine:
    def build_ai_messages(self, state, system_message):
        return [SystemMessage(content="PERSONA")]


def _patch(monkeypatch, budget):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", str(budget))
    llm = _FakeLLM()
    monkeypatch.setattr(cg, "get_llm", lambda provider=None, model=None, **kwargs: llm)
    monkeypatch.setattr(cg, "get_context_engine", lambda config: _FakeEngine())
    monkeypatch.setattr(cg.cost_router, "route", lambda t, p: ("groq", "m"))
    return llm


def _config():
    return {"configurable": {"thread_id": "t", "provider": "groq", "model": "m"}}


def _sent_text(llm):
    msgs = llm.sent_messages or (llm.bound.sent_messages if llm.bound else None) or []
    return " ".join(str(m.content) for m in msgs)


def test_checkpoint_warning_fires_at_threshold(monkeypatch):
    llm = _patch(monkeypatch, budget=4)  # threshold = min(3.6, 3) = 3
    out = cg.ai_node(
        {"iteration_used": 3, "current_task": "fix bug", "messages": []}, _config()
    )
    text = _sent_text(llm)
    assert "ITERATION BUDGET CHECKPOINT" in text
    assert "You have used 3 of 4 iterations" in text
    assert "do not stop solely because of this warning" in text
    assert out["budget_warning_done"] == 1


def test_checkpoint_warning_silent_under_threshold(monkeypatch):
    llm = _patch(monkeypatch, budget=4)
    out = cg.ai_node(
        {"iteration_used": 2, "current_task": "fix bug", "messages": []}, _config()
    )
    assert "ITERATION BUDGET CHECKPOINT" not in _sent_text(llm)
    assert out["budget_warning_done"] == 0


def test_checkpoint_warning_is_one_shot(monkeypatch):
    """budget_warning_done from a previous lap suppresses re-injection."""
    llm = _patch(monkeypatch, budget=4)
    out = cg.ai_node(
        {
            "iteration_used": 3,
            "budget_warning_done": 1,
            "current_task": "fix bug",
            "messages": [],
        },
        _config(),
    )
    assert "ITERATION BUDGET CHECKPOINT" not in _sent_text(llm)
    assert out["budget_warning_done"] == 1


def test_checkpoint_warning_skipped_on_exhausted_and_ask(monkeypatch):
    """Exhausted laps belong to the grace request; ask has no work to
    checkpoint (hermes notice is a WORK instruction)."""
    llm = _patch(monkeypatch, budget=3)  # iteration_used=3 -> exhausted
    cg.ai_node(
        {"iteration_used": 3, "current_task": "fix bug", "messages": []}, _config()
    )
    assert "ITERATION BUDGET CHECKPOINT" not in _sent_text(llm)

    llm2 = _patch(monkeypatch, budget=4)
    cg.ai_node(
        {
            "iteration_used": 3,
            "execution_mode": "ask",
            "current_task": "what is this",
            "messages": [],
        },
        _config(),
    )
    assert "ITERATION BUDGET CHECKPOINT" not in _sent_text(llm2)


# ── 2. honest trigger name on the summary request ──────────────────────────


def test_token_leg_summary_request_names_the_token_budget(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "30")
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "10000")
    llm = _patch(monkeypatch, budget=30)
    out = cg.ai_node(
        {
            "iteration_used": 5,  # iterations have headroom...
            "turn_token_usage": {"total_tokens": 12_000},  # ...tokens tripped (cap clamps to >=10k)
            "grace_done": 0,
            "current_task": "fix bug",
            "messages": [HumanMessage(content="fix bug")],
        },
        _config(),
    )
    assert out["grace_done"] == 1
    sent = llm.sent_messages  # grace call served by the UNBOUND proxy
    request = [m for m in sent if m.type == "human" and "budget" in str(m.content).lower()]
    assert request and "token budget" in str(request[-1].content)
    assert "tool-calling iterations" not in str(request[-1].content), (
        "the iterations wording lies on a token-cap trip"
    )


def test_iteration_leg_summary_request_stays_hermes_verbatim(monkeypatch):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "2")
    llm = _patch(monkeypatch, budget=2)
    cg.ai_node(
        {
            "iteration_used": 2,
            "grace_done": 0,
            "current_task": "fix bug",
            "messages": [HumanMessage(content="fix bug")],
        },
        _config(),
    )
    sent = llm.sent_messages
    assert str(sent[-1].content) == bg._MAX_ITERATIONS_SUMMARY_REQUEST


# ── 3. honest verdict for a budget-cut turn ────────────────────────────────


@pytest.fixture()
def _no_memory(monkeypatch):
    monkeypatch.setattr(cg, "memory_manager", None)


def _final_state(**extra):
    state = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="I reached the iteration limit..."),
        ],
        "current_task": "hi",
        "steps_completed": [],
        "failed_steps": [],
        "plan": [],
    }
    state.update(extra)
    return state


def test_budget_cut_turn_finalizes_not_completed(monkeypatch, _no_memory):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "2")
    out = cg.finalize_node(_final_state(iteration_used=2, grace_done=1), {"configurable": {}})
    assert out["task_completed"] is False
    assert out["task_status"] == "budget_exhausted"
    assert len(out["messages"]) == 1
    stamp = out["messages"][0].content
    assert "Ended on budget" in stamp
    assert "fresh budget" in stamp, "the stamp must name the escape hatch"


def test_budget_cut_verdict_survives_even_without_work(monkeypatch, _no_memory):
    """The old honesty gate only fired for UNVERIFIED CODE — a budget-cut
    run that never wrote a file finalized 'completed'."""
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "3")
    out = cg.finalize_node(_final_state(iteration_used=3, grace_done=1), {"configurable": {}})
    assert out["task_completed"] is False
    assert out["task_status"] == "budget_exhausted"


def test_plan_wrap_cut_is_not_budget_cut(monkeypatch, _no_memory):
    """The wrap leg fires when the work IS done — exempt from the valve's
    verdict even if the budget happens to be spent too."""
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "2")
    out = cg.finalize_node(
        _final_state(iteration_used=2, grace_done=1, wrap_summary=1), {"configurable": {}}
    )
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_normal_turn_verdict_unchanged(monkeypatch, _no_memory):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "30")
    out = cg.finalize_node(_final_state(iteration_used=1), {"configurable": {}})
    assert out["task_completed"] is True
    assert out["task_status"] == "completed"
    assert out["messages"] == []


def test_token_leg_cut_is_also_a_budget_cut(monkeypatch, _no_memory):
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "30")
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "10000")
    out = cg.finalize_node(
        _final_state(iteration_used=5, turn_token_usage={"total_tokens": 12_000}),
        {"configurable": {}},
    )
    assert out["task_completed"] is False
    assert out["task_status"] == "budget_exhausted"

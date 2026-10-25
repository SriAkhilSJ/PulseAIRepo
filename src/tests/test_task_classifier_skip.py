"""Pins for D30 (§46): task-classifier quick path — slam-dunk messages
(acks, explicit resets) skip the aux-LLM call entirely; everything with
any ambiguity still pays it, exactly like before.

All offline: the aux LLM is faked/exploded — a quick-path turn must not
even CONSTRUCT the client.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.graphs.chat_graph as cg


def _state(msg: str, task: str = "build a login page") -> dict:
    return {
        "current_task": task,
        "latest_instruction": msg,
        "token_usage": {"calls": 1, "prompt_tokens": 10},
    }


def _cfg() -> dict:
    return {"configurable": {"provider": "p", "model": "m", "workspace": "."}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("CRUSORAI_TASK_CLASSIFIER", raising=False)


def _explode(*_a, **_kw):
    raise AssertionError("aux LLM must not even be constructed on this path")


# ----------------------------------------------------------- ack => continue

ACKS = [
    # only acks that TODAY reach the LLM — exact plan-approval words
    # ("yes", "proceed", "go ahead", "continue") are claimed by the
    # EARLIER approval branch (pinned below, quick path must not hijack).
    "ok", "okay", "okk", "okkk", "yes!", "yess", "yahh", "yep",
    "go", "do it", "sure", "sounds good",
    "looks good", "go for it", "ok go", "thanks", "thank you",
    "perfect 👍", "great", "cool", "nice", "bet", "lgtm", "roger",
    "aight", "alright then", "✅", "🔥", "y",
]


@pytest.mark.parametrize("msg", ACKS)
def test_ack_messages_skip_llm_and_continue(msg, monkeypatch):
    monkeypatch.setattr(cg, "_task_manager_llm", _explode)
    out = cg.task_manager_node(_state(msg), _cfg())
    assert out["task_action"] == "continue"
    assert out["current_task"] == "build a login page"  # text unchanged
    assert set(out) == {
        "current_task", "task_action", "token_usage", "workspace",
        # Turn-scoped safety budgets are RESET here: an ack re-prompt after
        # a budget-exhausted turn must not inherit the spent budget (which
        # forced the next turn toolless into an instant finalize).
        "turn_token_usage", "iteration_used", "grace_done",
        "budget_warning_done",
        "incomplete_response_retries", "plan_wrap_nudges", "wrap_summary",
        # Completion/verification/stall valves are turn-scoped too. Reusing
        # their spent values made later prompts in the same session skip
        # gates and inherit the prior turn's nudge marker.
        "finish_nudges", "verify_nudges", "stall_continuations",
        "nudged_at_msg_count",
        # Receipt accounting is also turn-scoped; prior executions must never
        # be rendered as belonging to this acknowledgement/follow-up turn.
        "turn_tool_execution_count", "turn_tool_execution_names",
    }
    assert out["token_usage"]["calls"] == 1  # no LLM call recorded
    assert out["iteration_used"] == 0
    assert out["grace_done"] == 0
    assert out["budget_warning_done"] == 0
    assert out["finish_nudges"] == 0
    assert out["verify_nudges"] == 0
    assert out["stall_continuations"] == 0
    assert out["nudged_at_msg_count"] == -1
    assert out["turn_tool_execution_count"] == 0
    assert out["turn_tool_execution_names"] == []


def test_ack_after_exhausted_turn_gets_fresh_budget(monkeypatch):
    """Regression (field report: agent "acting dumb" on re-prompt). After a
    turn ended on the iteration budget, the checkpoint carries
    iteration_used>=budget + grace_done=1. A bare-ack re-prompt used to
    skip the reset (quick-path return), so the next turn entered ai_node
    already budget-exhausted: tools unbound, one toolless lap, instant
    finalize. Every new user turn must get a fresh turn-scoped budget."""
    monkeypatch.setattr(cg, "_task_manager_llm", _explode)
    st = _state("ok")
    st["iteration_used"] = 30
    st["grace_done"] = 1
    st["turn_token_usage"] = {"total_tokens": 500_000}
    st["incomplete_response_retries"] = 2
    st["plan_wrap_nudges"] = 1
    st["wrap_summary"] = 1
    st["finish_nudges"] = 2
    st["verify_nudges"] = 2
    st["stall_continuations"] = 2
    st["nudged_at_msg_count"] = 99
    out = cg.task_manager_node(st, _cfg())
    assert out["task_action"] == "continue"
    assert out["iteration_used"] == 0
    assert out["grace_done"] == 0
    assert out["budget_warning_done"] == 0
    assert out["wrap_summary"] == 0
    assert out["plan_wrap_nudges"] == 0
    assert out["incomplete_response_retries"] == 0
    assert out["finish_nudges"] == 0
    assert out["verify_nudges"] == 0
    assert out["stall_continuations"] == 0
    assert out["nudged_at_msg_count"] == -1
    assert out["turn_token_usage"] == cg._zero_token_usage()


def test_reset_after_exhausted_turn_gets_fresh_budget(monkeypatch):
    """Same law for the quick explicit-reset path."""
    monkeypatch.setattr(cg, "_task_manager_llm", _explode)
    st = _state("new task: add OAuth to the API")
    st["iteration_used"] = 50
    st["grace_done"] = 1
    out = cg.task_manager_node(st, _cfg())
    assert out["task_action"] == "new"
    assert out["iteration_used"] == 0
    assert out["grace_done"] == 0


# ------------------------------------------------------------- reset => new

NEW_CASES = [
    ("new task: add OAuth to the API", "add OAuth to the API"),
    ("New Task build a discord bot", "build a discord bot"),
    ("different task: fix the navbar", "fix the navbar"),
    ("start over with a CLI tool", "a CLI tool"),
    ("forget the previous task, move to docker setup", "move to docker setup"),
    ("forget this task", "forget this task"),
    ("scrap that, do a terraform module", "do a terraform module"),
]


@pytest.mark.parametrize("msg,expected_task", NEW_CASES)
def test_explicit_reset_skips_llm_and_starts_new(msg, expected_task, monkeypatch):
    monkeypatch.setattr(cg, "_task_manager_llm", _explode)
    out = cg.task_manager_node(_state(msg), _cfg())
    assert out["task_action"] == "new"
    assert out["current_task"] == expected_task
    assert out["task_status"] == "in_progress"
    assert out["plan"] == [] and out["steps_completed"] == []
    # zero usage recorded — the quick path pays NOTHING (a real TokenUsage
    # zero-object, same type the LLM branch would merge into)
    assert out["token_usage"] == cg._zero_token_usage()


# ---------------------------------------------------- ambiguity pays the LLM

NEEDS_LLM = [
    "actually can you refactor the auth instead",
    "no, change the color to red",
    "explain how the login flow works",
    "why did the test fail?",
    "now add OAuth support to the login you just built",
    "hmm maybe we should use sessions instead of JWT",
    "the button looks broken",
    "ok but remove the sidebar",          # ack token + danger token ("remove")
    "yes, wait",                          # ack + danger ("wait")
    "yes please",                         # contains reserved approval word
    "go ahead bro",                       # contains reserved approval phrase
    "new taskbar styling in the editor",  # word-boundary guard
    "ok\nnow also add tests",             # multi-line never slam-dunks
    "",
]


@pytest.mark.parametrize("msg", NEEDS_LLM)
def test_ambiguous_messages_return_no_quick_decision(msg, monkeypatch):
    monkeypatch.delenv("CRUSORAI_TASK_CLASSIFIER", raising=False)
    assert cg._quick_task_decision("build a login page", msg) is None or msg == ""


def test_ambiguous_by_default_skips_llm_opt_in_consults_once(monkeypatch):
    """Hermes-parity default: an ambiguous instruction pays NO classifier
    round-trip (field: "hello" paid one and the answer was unparseable).
    CRUSORAI_TASK_CLASSIFIER=on restores the consult-exactly-once lane."""

    class FakeLLM:
        # The classifier lane invokes RAW since the prose-salvage port (the
        # strict with_structured_output chain died on prose-obedient models):
        # the fake returns the decision as JSON, which _salvage_task_decision
        # parses -- but the node MUST still consult the LLM exactly once.
        def invoke(self, _msgs):
            calls["n"] += 1
            from types import SimpleNamespace

            return SimpleNamespace(
                content='{"action": "continue", "updated_task": '
                        '"build a login page with OAuth"}'
            )

    calls = {"n": 0}
    st = _state("now please also add OAuth to that login")
    st["token_usage"] = cg._zero_token_usage()

    # DEFAULT: no round-trip at all.
    monkeypatch.setattr(cg, "_task_manager_llm", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("default must not construct the classifier")))
    out = cg.task_manager_node(st, _cfg())
    assert out["task_action"] == "continue"
    assert out["current_task"] == "build a login page", "task label preserved verbatim on skip"

    # OPT-IN: consult the LLM exactly once.
    monkeypatch.setenv("CRUSORAI_TASK_CLASSIFIER", "on")
    monkeypatch.setattr(cg, "_task_manager_llm", lambda *a, **k: FakeLLM())
    # record_call must return the REAL TokenUsage dataclass — the node
    # merges it with `+`, which reads .prompt_tokens off the addition
    # (CG's _zero_token_usage is a plain dict and would break the merge).
    from src.context.token_tracker import TokenUsage
    monkeypatch.setattr(cg.TokenTracker, "record_call",
                        staticmethod(lambda *a, **k: TokenUsage(calls_made=1)))
    out = cg.task_manager_node(_state("now please also add OAuth to that login"), _cfg())
    assert calls["n"] == 1, "opt-in lane must consult the LLM exactly once"
    assert out["task_action"] == "continue"
    assert out["current_task"] == "build a login page with OAuth"


# ------------------------------------------- approval branches NOT hijacked

def test_approval_words_still_route_to_approval_branch(monkeypatch):
    """Bare approval words were claimed by the plan-approval branch LONG
    before the LLM classifier — the D30 quick path sits AFTER it and must
    never hijack the routing (order pinned)."""
    monkeypatch.setattr(cg, "_task_manager_llm", _explode)
    for word in ("yes", "proceed", "go ahead", "continue", "approve"):
        out = cg.task_manager_node(_state(word), _cfg())
        assert out["task_action"] == "approval_without_plan", word


def test_approval_with_existing_plan_executes_it(monkeypatch):
    monkeypatch.setattr(cg, "_task_manager_llm", _explode)
    st = _state("yes")
    st["plan_created"] = True
    st["plan"] = [{"id": 1, "description": "step", "status": "pending"}]
    st["plan_goal"] = "build a login page"
    out = cg.task_manager_node(st, _cfg())
    assert out["task_action"] == "execute_approved_plan"
    assert out["plan_approved"] is True


# ------------------------------------------------------- kill-switch + edge

def test_kill_switch_restores_always_llm(monkeypatch):
    monkeypatch.setenv("CRUSORAI_TASK_CLASSIFIER", "llm")
    assert cg._quick_task_decision("task", "ok go") is None


def test_first_turn_branch_untouched(monkeypatch):
    """No active task => first-turn initialization path (pre-existing
    behavior), never consults quick path or LLM."""
    monkeypatch.setattr(cg, "_task_manager_llm", _explode)
    st = _state("build something")
    st["current_task"] = ""
    out = cg.task_manager_node(st, _cfg())
    assert out["task_action"] == "new"
    assert out["current_task"] == "build something"

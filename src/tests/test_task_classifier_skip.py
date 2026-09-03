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
    monkeypatch.delenv("PULSEAI_TASK_CLASSIFIER", raising=False)


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
    assert set(out) == {"current_task", "task_action", "token_usage", "workspace"}
    assert out["token_usage"]["calls"] == 1  # no LLM call recorded


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
    monkeypatch.delenv("PULSEAI_TASK_CLASSIFIER", raising=False)
    assert cg._quick_task_decision("build a login page", msg) is None or msg == ""


def test_llm_path_still_taken_for_ambiguous(monkeypatch):
    calls = {"n": 0}

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

    monkeypatch.setattr(cg, "_task_manager_llm", lambda *a, **k: FakeLLM())
    # record_call must return the REAL TokenUsage dataclass — the node
    # merges it with `+`, which reads .prompt_tokens off the addition
    # (CG's _zero_token_usage is a plain dict and would break the merge).
    from src.context.token_tracker import TokenUsage
    monkeypatch.setattr(cg.TokenTracker, "record_call",
                        staticmethod(lambda *a, **k: TokenUsage(calls_made=1)))
    st = _state("now please also add OAuth to that login")
    st["token_usage"] = cg._zero_token_usage()
    out = cg.task_manager_node(st, _cfg())
    assert calls["n"] == 1, "ambiguous message must still consult the LLM"
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
    monkeypatch.setenv("PULSEAI_TASK_CLASSIFIER", "llm")
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

"""Pins for the ask-mode classifier gate (hermes pipeline parity).

hermes' run_conversation performs ZERO model calls before the main one.
Pulse's ask mode paid a classifier round-trip whose verdict after_task_manager
throws away (it returns "ai" before reading task_action) — the owner's field
log showed 14s of "Waiting on the model" before a plain listing request.

Contract (PULSEAI_TASK_CLASSIFIER read per call):
  unset -> ask skips the classifier, execute/plan keep it (aux-budgeted)
  "on"  -> classify in every mode (legacy)
  "off" -> classify in no mode (quick free decision still runs first)
"""

from __future__ import annotations

import pytest

import src.graphs.chat_graph as cg


def _state(mode: str) -> dict:
    return {
        "execution_mode": mode,
        "current_task": "list the folders of the workspace",
        "latest_instruction": "what did we do last?",
        "messages": [],
        "token_usage": {"input": 1},
    }


def _cfg() -> dict:
    return {"configurable": {"thread_id": "t-classifier-gate", "workspace": "."}}


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """Any classifier construction or invocation in a skipped lane is a bug."""
    monkeypatch.setattr(cg, "_task_manager_llm", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("classifier LLM constructed on a skip path")))


def test_ask_mode_skips_the_classifier_by_default(monkeypatch):
    monkeypatch.setattr(cg, "_invoke_task_decision", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("ask mode must not pay the classifier round-trip")))

    out = cg.task_manager_node(_state("ask"), _cfg())

    assert out["task_action"] == "continue"
    assert out["current_task"] == "list the folders of the workspace"
    assert out["iteration_used"] == 0


def test_env_on_restores_classification_in_ask_mode(monkeypatch):
    monkeypatch.setenv("PULSEAI_TASK_CLASSIFIER", "on")
    monkeypatch.setattr(
        cg, "_task_manager_llm", lambda *a, **k: object()
    )
    monkeypatch.setattr(
        cg, "_invoke_task_decision",
        lambda llm, messages: cg.TaskDecision(action="new", updated_task="brand new task"),
    )

    out = cg.task_manager_node(_state("ask"), _cfg())

    assert out["task_action"] == "new"
    assert out["current_task"] == "brand new task"


def test_execute_mode_still_classifies_by_default(monkeypatch):
    monkeypatch.setattr(cg, "_task_manager_llm", lambda *a, **k: object())
    seen = {}

    def fake_invoke(llm, messages):
        seen["called"] = True
        return cg.TaskDecision(action="continue", updated_task="list the folders of the workspace, now with details")

    monkeypatch.setattr(cg, "_invoke_task_decision", fake_invoke)

    out = cg.task_manager_node(_state("agent"), _cfg())

    assert seen["called"], "execute mode keeps the (bounded) classifier"
    assert out["task_action"] == "continue"
    assert "now with details" in out["current_task"]


def test_env_off_skips_even_in_execute_mode(monkeypatch):
    monkeypatch.setenv("PULSEAI_TASK_CLASSIFIER", "off")
    monkeypatch.setattr(cg, "_invoke_task_decision", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("PULSEAI_TASK_CLASSIFIER=off must skip the round-trip")))

    out = cg.task_manager_node(_state("agent"), _cfg())

    assert out["task_action"] == "continue"


def test_quick_decision_still_wins_before_the_gate(monkeypatch):
    """D30 acks stay free AND unaffected by the mode gate."""
    monkeypatch.setattr(cg, "_invoke_task_decision", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("an ack must never reach the classifier")))

    state = _state("agent")
    state["latest_instruction"] = "ok thanks"

    out = cg.task_manager_node(state, _cfg())

    assert out["task_action"] == "continue"
    assert out["current_task"] == "list the folders of the workspace"

"""Pins for the hermes-parity classifier gate (post field-proof flip).

Field proof (owner agent-mode run): "hello" paid a classifier round-trip on
the main-fallback route that returned an UNPARSEABLE answer and would have
been used only as "continue" anyway. Hermes' run_conversation performs ZERO
model calls before the main one — that is now the default in every mode.

Contract (PULSEAI_TASK_CLASSIFIER read per call):
  unset/off -> no classifier round-trip in any mode (free D30 quick decision
               still owns acks and explicit resets)
  "on"      -> classify in every mode (legacy), on the bounded aux budget
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


def _forbid_classifier(monkeypatch):
    monkeypatch.setattr(cg, "_task_manager_llm", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("classifier LLM constructed on a skip path")))
    monkeypatch.setattr(cg, "_invoke_task_decision", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("classifier round-trip paid on a skip path")))


def test_ask_mode_skips_by_default(monkeypatch):
    _forbid_classifier(monkeypatch)
    out = cg.task_manager_node(_state("ask"), _cfg())
    assert out["task_action"] == "continue"
    assert out["current_task"] == "list the folders of the workspace"


def test_agent_mode_skips_by_default_too(monkeypatch):
    """The field-proof lane: agent mode paid the call and threw the answer away."""
    _forbid_classifier(monkeypatch)
    out = cg.task_manager_node(_state("agent"), _cfg())
    assert out["task_action"] == "continue"
    assert out["current_task"] == "list the folders of the workspace"


def test_env_on_restores_classification(monkeypatch):
    monkeypatch.setenv("PULSEAI_TASK_CLASSIFIER", "on")
    monkeypatch.setattr(cg, "_task_manager_llm", lambda *a, **k: object())
    monkeypatch.setattr(
        cg, "_invoke_task_decision",
        lambda llm, messages: cg.TaskDecision(action="new", updated_task="brand new task"),
    )

    out = cg.task_manager_node(_state("agent"), _cfg())

    assert out["task_action"] == "new"
    assert out["current_task"] == "brand new task"


def test_env_off_is_an_explicit_alias_of_the_default(monkeypatch):
    monkeypatch.setenv("PULSEAI_TASK_CLASSIFIER", "off")
    _forbid_classifier(monkeypatch)
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

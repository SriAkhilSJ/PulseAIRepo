"""Pins on the opt-in tool-schema waist (`CRUSORAI_TOOL_WAIST`).

Why this file exists (measured 2026-10-31): the registry default binds 68 tool
schemas on every provider call = 25,382 tokens of JSON, which is 4.3x the whole
budgeted system prompt (5,840). That is the largest single line item in a turn.
`resolve_runtime_profile()` already computes a deterministic capability set for
sub-agent children (`scope_capabilities_strict`); the waist applies the same
resolver to the parent turn when a deployment asks for it.

These pins protect the two properties that matter:
  1. the default is byte-for-byte unchanged (no silent behaviour change), and
  2. narrowing never drops below a usable floor and never breaks binding.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

from src.graphs import chat_graph


def _bind(task: str = "build and verify a small web app"):
    cfg = {"configurable": {"thread_id": "waist-test", "workspace": "."}}
    state = {"current_task": task, "messages": [], "workspace": "."}
    return [t.name for t in chat_graph._resolve_bound_tools(state, cfg)]


def test_default_binds_the_full_registry(monkeypatch):
    """Default = the registry snapshot. Availability checks (check_fn) may still
    hide one tool (e.g. typecheck_workspace with no tsconfig), so the pin is a
    lower bound plus "the waist did nothing"."""
    monkeypatch.delenv("CRUSORAI_TOOL_WAIST", raising=False)
    names = _bind()
    assert len(names) >= len(chat_graph.tools) - 2
    assert set(names) <= {t.name for t in chat_graph.tools}


def test_unrecognised_value_is_treated_as_all(monkeypatch):
    monkeypatch.delenv("CRUSORAI_TOOL_WAIST", raising=False)
    baseline = _bind()
    monkeypatch.setenv("CRUSORAI_TOOL_WAIST", "definitely-not-a-mode")
    assert _bind() == baseline


def test_profile_waist_narrows_but_keeps_a_usable_floor(monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOOL_WAIST", "profile")
    names = _bind()
    assert 8 <= len(names) < len(chat_graph.tools)


def test_profile_waist_keeps_the_universal_core(monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOOL_WAIST", "profile")
    names = set(_bind("hi"))
    # _CORE_TOOLS: the task list and ask-the-user pair are never posture-gated.
    for tool in ("think", "verify", "todo_list", "clarify"):
        assert tool in names, f"{tool} must survive the waist"


def test_profile_waist_is_order_stable(monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOOL_WAIST", "profile")
    assert _bind("fix the failing test in parser.py") == _bind(
        "fix the failing test in parser.py"
    )


def test_waist_failure_cannot_break_binding(monkeypatch):
    monkeypatch.delenv("CRUSORAI_TOOL_WAIST", raising=False)
    baseline = _bind()
    monkeypatch.setenv("CRUSORAI_TOOL_WAIST", "profile")
    with mock.patch(
        "src.agents.runtime_profile.resolve_runtime_profile",
        side_effect=RuntimeError("resolver exploded"),
    ):
        names = _bind()
    assert names == baseline


def test_strict_child_scope_still_wins_under_the_waist(monkeypatch):
    """A sub-agent's explicit scope is a contract: the waist must not widen it."""
    monkeypatch.setenv("CRUSORAI_TOOL_WAIST", "profile")
    cfg = {
        "configurable": {
            "thread_id": "waist-test",
            "workspace": ".",
            "scope_capabilities_strict": True,
        }
    }
    state = {"current_task": "build and verify a small web app", "messages": [],
             "workspace": "."}
    child = [t.name for t in chat_graph._resolve_bound_tools(state, cfg)]
    parent = _bind("build and verify a small web app")
    assert set(child) <= set(parent)

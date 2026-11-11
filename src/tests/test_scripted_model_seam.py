"""The provider-free scripted model seam (desktop Phase 2 r2).

The seam is the single substitution point for the model client. These tests
pin its activation gate, its tool-call shape (finish_reason=tool_calls, the
graph only executes calls with that signal), its exhaustion behaviour and its
no-network nature.
"""
from __future__ import annotations

import json

import pytest

from src.llm import factory
from src.llm.scripted_model import ScriptedChatModel, scripted_model_active


def _script() -> str:
    return json.dumps([
        {
            "tool_calls": [{
                "name": "write_file",
                "args": {"path": "notes.md", "content": "hello\n"},
                "id": "call-1",
            }]
        },
        {"content": "done"},
    ])


def test_seam_is_off_unless_both_gates_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRUSORAI_TEST_MODE", raising=False)
    monkeypatch.delenv("CRUSORAI_TEST_LLM_SCRIPT", raising=False)
    assert scripted_model_active() is False
    monkeypatch.setenv("CRUSORAI_TEST_MODE", "1")
    assert scripted_model_active() is False, "the script is the second gate"
    monkeypatch.setenv("CRUSORAI_TEST_LLM_SCRIPT", _script())
    assert scripted_model_active() is True


def test_factory_returns_the_scripted_model_when_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUSORAI_TEST_MODE", "1")
    monkeypatch.setenv("CRUSORAI_TEST_LLM_SCRIPT", _script())
    llm = factory.get_llm(provider="custom", model="z-ai/glm-5.3-flash")
    assert isinstance(llm, ScriptedChatModel)
    # bind_tools must be callable (the graph binds before invoking).
    bound = llm.bind_tools([{"name": "write_file"}])
    first = bound.invoke([])
    assert first.tool_calls and first.tool_calls[0]["name"] == "write_file"
    assert first.tool_calls[0]["args"]["path"] == "notes.md"
    assert first.response_metadata.get("finish_reason") == "tool_calls"
    second = bound.invoke([])
    assert second.content == "done" and not second.tool_calls
    third = bound.invoke([])
    assert third.content == "Scripted turn complete." and not third.tool_calls, (
        "an exhausted script must never replay a tool call (no fake loop)"
    )


def test_malformed_script_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUSORAI_TEST_MODE", "1")
    monkeypatch.setenv("CRUSORAI_TEST_LLM_SCRIPT", "not-json")
    with pytest.raises(Exception):
        factory.get_llm(provider="custom", model="x")

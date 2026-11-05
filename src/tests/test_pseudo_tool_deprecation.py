"""Tests for Phase 9.2.2.1: Pseudo-Tool Deprecation & LLM Invocation Optimization.

Validates that think and verify are deprecated from model-facing schemas,
native reasoning remains supported, evidence-based verification is enforced,
and backward compatibility is preserved.
"""
import os
import pytest
from unittest.mock import patch

from src.graphs.chat_graph import (
    _resolve_bound_tools,
    _READ_ONLY_INTEREST_TOOLS,
    think,
    verify,
)
from src.tools.toolsets import resolve_runtime_tool_names
from src.agents.runtime_profile import resolve_runtime_profile
from src.prompts.claude_persona import CLAUDE_SYSTEM_PERSONA
from src.agents.planner import _receipt_name


def test_pseudo_tools_not_in_bound_tools_by_default(tmp_path):
    """By default, think and verify MUST NOT be exposed in model-bound tools."""
    state = {"current_task": "fix auth.py bug"}
    config = {"configurable": {"workspace": str(tmp_path), "thread_id": "t-deprecate"}}
    bound = _resolve_bound_tools(state, config)
    names = {t.name for t in bound}
    assert "think" not in names, "think should not be in model-bound tools"
    assert "verify" not in names, "verify should not be in model-bound tools"
    assert "todo_list" in names
    assert "clarify" in names


def test_pseudo_tools_opt_in_environment_flag(tmp_path, monkeypatch):
    """When CRUSORAI_ENABLE_PSEUDO_TOOLS=1, think and verify can be bound for legacy opt-in."""
    monkeypatch.setenv("CRUSORAI_ENABLE_PSEUDO_TOOLS", "1")
    state = {"current_task": "test legacy"}
    config = {"configurable": {"workspace": str(tmp_path), "thread_id": "t-legacy"}}
    bound = _resolve_bound_tools(state, config)
    names = {t.name for t in bound}
    assert "think" in names
    assert "verify" in names


def test_core_toolset_excludes_pseudo_tools_by_default():
    """Universal core tools must contain only real action/dialogue tools (todo_list, clarify)."""
    profile = resolve_runtime_profile("simple chat")
    tools = set(resolve_runtime_tool_names(profile))
    assert "think" not in tools
    assert "verify" not in tools
    assert "todo_list" in tools
    assert "clarify" in tools


def test_read_only_interest_tools_excludes_pseudo_tools():
    """Read-only and informational tasks must not expose think or verify."""
    assert "think" not in _READ_ONLY_INTEREST_TOOLS
    assert "verify" not in _READ_ONLY_INTEREST_TOOLS
    assert "clarify" in _READ_ONLY_INTEREST_TOOLS
    assert "read_file" in _READ_ONLY_INTEREST_TOOLS


def test_think_tool_backward_compatibility():
    """think() callable remains available for legacy transcript replay."""
    result = think.invoke({"reasoning": "Analyzing codebase structure"})
    assert "Thinking:" in result
    assert "Analyzing codebase structure" in result


def test_verify_tool_evidence_based_failure_detection():
    """verify() rejects claims of success when actual_result exhibits error evidence."""
    # Model self-asserted success=True, but actual_result has exit code 1 / error
    result = verify.invoke({
        "step_description": "Run pytest suite",
        "expected_result": "All tests pass",
        "actual_result": "FAILED: 2 failed, 10 passed (exit code 1)",
        "success": True,
    })
    assert "didn't match what I expected" in result or "Evidence indicates failure" in result
    assert "Run pytest suite" in result


def test_verify_tool_evidence_based_success():
    """verify() produces clean verified receipt when results match expectations without errors."""
    result = verify.invoke({
        "step_description": "Run pytest suite",
        "expected_result": "126 passed",
        "actual_result": "126 passed in 9.5s",
        "success": True,
    })
    assert "Verified with evidence" in result
    assert "Run pytest suite" in result


def test_claude_persona_contains_no_pseudo_tool_directives():
    """System prompts must guide internal reasoning, not external think() or verify() tool calls."""
    assert "use the `think()` tool" not in CLAUDE_SYSTEM_PERSONA
    assert "Use `verify()` when" not in CLAUDE_SYSTEM_PERSONA
    assert "Plan & Reason Internally" in CLAUDE_SYSTEM_PERSONA
    assert "Verify with Concrete Evidence" in CLAUDE_SYSTEM_PERSONA


def test_planner_receipt_mapping_satisfied_by_real_evidence():
    """Terminal and static verifiers automatically supply the 'verify' plan receipt."""
    terminal_receipts = _receipt_name("terminal")
    assert "verify" in terminal_receipts

    typecheck_receipts = _receipt_name("typecheck_workspace")
    assert "verify" in typecheck_receipts

    ui_receipts = _receipt_name("verify_ui_workspace")
    assert "verify" in ui_receipts


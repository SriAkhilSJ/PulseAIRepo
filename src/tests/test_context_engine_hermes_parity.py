"""
Tests for Hermes parity in PulseAI's Context Engine.
====================================================
Validates the ContextEngineBase contract, token tracking, dual threshold
compaction, mechanical anchor extraction, verbatim user preservation,
lean tail mode, micro-compaction, engine tools, and pluggable registry.
"""

from __future__ import annotations

import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.base import ContextEngineBase
from src.context.context_engine import ContextEngine
from src.context.compaction import (
    COMPACTION_SUMMARY_PREFIX,
    HistoryCompactor,
    align_boundary_backward,
    align_boundary_forward,
    build_anchor_index,
    build_recovery_footer,
    build_verbatim_user_section,
    demote_stale_tail_tools,
    micro_compact,
    sanitize_tool_pairs,
)
from src.context.registry import (
    create_context_engine,
    get_context_engine_class,
    list_context_engines,
    register_context_engine,
)


class TestContextEngineBaseContract:
    """Verify that ContextEngine satisfies the Hermes ContextEngineBase ABC."""

    def test_engine_satisfies_abc(self):
        eng = ContextEngine(max_tokens=4000, model="gpt-4o-mini", probe_window=False)
        assert isinstance(eng, ContextEngineBase)
        assert eng.name == "pulse"

    def test_subclass_missing_methods_raises(self):
        class IncompleteEngine(ContextEngineBase):
            @property
            def name(self) -> str:
                return "incomplete"

        with pytest.raises(TypeError):
            IncompleteEngine()

    def test_token_tracking_from_response(self):
        eng = ContextEngine(max_tokens=8000, model="gpt-4o-mini", probe_window=False)
        usage = {
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "total_tokens": 1500,
            "cache_read_tokens": 800,
            "cache_write_tokens": 400,
            "reasoning_tokens": 50,
        }
        eng.update_from_response(usage)
        assert eng.last_prompt_tokens == 1200
        assert eng.last_completion_tokens == 300
        assert eng.last_total_tokens == 1500
        assert eng.last_cache_read_tokens == 800
        assert eng.last_cache_write_tokens == 400
        assert eng.last_reasoning_tokens == 50

    def test_should_compress_and_should_compress_info(self):
        eng = ContextEngine(max_tokens=1000, model="gpt-4o-mini", probe_window=False)
        eng.threshold_tokens = 500

        # Below threshold
        eng.last_prompt_tokens = 400
        assert eng.should_compress() is False
        should, reason = eng.should_compress_info()
        assert should is False
        assert reason is None

        # At or above threshold
        eng.last_prompt_tokens = 600
        assert eng.should_compress() is True
        should, reason = eng.should_compress_info()
        assert should is True
        assert "reached threshold" in reason

    def test_on_session_reset_clears_state(self):
        eng = ContextEngine(max_tokens=4000, model="gpt-4o-mini", probe_window=False)
        eng.last_prompt_tokens = 3000
        eng.compression_count = 2
        eng.on_session_reset()
        assert eng.last_prompt_tokens == 0
        assert eng.compression_count == 0

    def test_get_status_payload(self):
        eng = ContextEngine(max_tokens=4000, model="gpt-4o-mini", probe_window=False)
        eng.last_prompt_tokens = 1000
        status = eng.get_status()
        assert status["name"] == "pulse"
        assert status["last_prompt_tokens"] == 1000
        assert "usage_percent" in status
        assert "compaction_stats" in status
        assert "cache_audit_stats" in status


class TestMechanicalAnchorHarvesting:
    """Verify deterministic, regex-based anchor harvesting (LLM-free)."""

    def test_harvest_files_commits_errors_prs_urls(self):
        turns = [
            HumanMessage(content="Please review PR #456 and commit a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"),
            AIMessage(content="I inspected src/context/context_engine.py and found error TS2304: Cannot find name 'x'."),
            ToolMessage(content="Reference https://github.com/NousResearch/hermes-agent.git for fix.", tool_call_id="c1", name="terminal"),
        ]
        anchor_text = build_anchor_index(turns)
        assert "### Technical Anchor Index" in anchor_text
        assert "PRs/issues: #456" in anchor_text
        assert "commits: a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" in anchor_text
        assert "src/context/context_engine.py" in anchor_text
        assert "TS2304" in anchor_text
        assert "https://github.com/NousResearch/hermes-agent.git" in anchor_text

    def test_empty_turns_returns_empty_anchor(self):
        assert build_anchor_index([]) == ""
        assert build_anchor_index([HumanMessage(content="hello")]) == ""


class TestVerbatimUserSection:
    """Verify that real user instructions are preserved verbatim."""

    def test_user_messages_quoted_verbatim(self):
        turns = [
            HumanMessage(content="Do not modify the database schema under any circumstance."),
            AIMessage(content="Understood.", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
            ToolMessage(content="ok", tool_call_id="1", name="t"),
            HumanMessage(content="Use PostgreSQL connection pool instead of SQLite."),
        ]
        user_section = build_verbatim_user_section(turns)
        assert "### Real User Instructions (Verbatim)" in user_section
        assert "> Do not modify the database schema" in user_section
        assert "> Use PostgreSQL connection pool" in user_section
        assert "These are the user's actual words and override any paraphrase" in user_section


class TestRecoveryFooter:
    """Verify explicit session search pointers in summaries."""

    def test_footer_contains_session_search_pointer(self):
        footer = build_recovery_footer("sess-xyz-123", 14)
        assert "### Preserved Session Detail & Recovery" in footer
        assert "14 compacted message(s)" in footer
        assert "session_search(query='<keywords>', session_id='sess-xyz-123')" in footer


class TestToolPairAlignmentAndSanitization:
    """Verify tool call / result pairing integrity."""

    def test_align_boundary_backward_keeps_pair_together(self):
        history = [
            HumanMessage(content="start"),
            AIMessage(content="running", tool_calls=[{"name": "run", "args": {}, "id": "call-1"}]),
            ToolMessage(content="output 1", tool_call_id="call-1", name="run"),
            ToolMessage(content="output 2", tool_call_id="call-1", name="run"),
            HumanMessage(content="next"),
        ]
        # Cutting at index 3 (second ToolMessage) must walk back to index 1 (the AIMessage)
        aligned = align_boundary_backward(history, 3)
        assert aligned == 1

    def test_sanitize_tool_pairs_removes_orphan_tool_results(self):
        messages = [
            ToolMessage(content="orphan tool result", tool_call_id="unknown-call", name="tool"),
            HumanMessage(content="hello"),
        ]
        sanitized = sanitize_tool_pairs(messages)
        assert len(sanitized) == 1
        assert isinstance(sanitized[0], HumanMessage)

    def test_sanitize_tool_pairs_injects_stub_for_unanswered_calls(self):
        messages = [
            AIMessage(content="call tool", tool_calls=[{"name": "test_tool", "args": {}, "id": "call-unanswered"}]),
            HumanMessage(content="follow up"),
        ]
        sanitized = sanitize_tool_pairs(messages)
        # Should insert stub ToolMessage for the unanswered call
        assert len(sanitized) == 3
        assert isinstance(sanitized[1], ToolMessage)
        assert sanitized[1].tool_call_id == "call-unanswered"


class TestLeanTailMode:
    """Verify stale tool demotion in lean tail mode."""

    def test_demote_stale_tail_tools_preserves_recent_rounds(self):
        history = [
            HumanMessage(content="q1"),
            ToolMessage(content="old dump " * 50, tool_call_id="c1", name="terminal"),
            HumanMessage(content="q2"),
            ToolMessage(content="recent dump 1 " * 50, tool_call_id="c2", name="read_file"),
            ToolMessage(content="recent dump 2 " * 50, tool_call_id="c3", name="write_file"),
        ]
        # Keep 1 tool round: the latest round (c2, c3) is kept verbatim, c1 is demoted
        demoted_msgs, count = demote_stale_tail_tools(history, tail_start=0, keep_rounds=1, session_id="test-sess")
        assert count == 1
        assert "cleared in lean tail mode" in demoted_msgs[1].content
        assert "recent dump 1" in demoted_msgs[3].content
        assert "recent dump 2" in demoted_msgs[4].content


class TestMicroCompaction:
    """Verify amortized turn-by-turn micro compaction."""

    def test_micro_compact_folds_one_exchange(self):
        history = [
            HumanMessage(content="setup"),
            AIMessage(content="step 1", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
            ToolMessage(content="result 1", tool_call_id="1", name="t"),
            HumanMessage(content="step 2"),
            AIMessage(content="doing step 2"),
            HumanMessage(content="finish"),
        ]
        compacted, summary, did_compact = micro_compact(history, running_summary="")
        assert did_compact is True
        assert len(compacted) < len(history)
        # Verify user messages survived
        user_msgs = [m.content for m in compacted if isinstance(m, HumanMessage)]
        assert user_msgs == ["setup", "step 2", "finish"]
        assert any(isinstance(m, SystemMessage) and getattr(m, "response_metadata", {}).get("micro") for m in compacted)


class TestContextEngineTools:
    """Verify engine-provided tools (context_search, context_status)."""

    def test_get_tool_schemas(self):
        eng = ContextEngine(max_tokens=4000, model="gpt-4o-mini", probe_window=False)
        schemas = eng.get_tool_schemas()
        names = {s["name"] for s in schemas}
        assert "context_search" in names
        assert "context_status" in names

    def test_handle_tool_call_context_status(self):
        eng = ContextEngine(max_tokens=4000, model="gpt-4o-mini", probe_window=False)
        eng.last_prompt_tokens = 500
        raw = eng.handle_tool_call("context_status", {})
        data = json.loads(raw)
        assert data["name"] == "pulse"
        assert data["last_prompt_tokens"] == 500

    def test_handle_tool_call_context_search(self):
        eng = ContextEngine(max_tokens=4000, model="gpt-4o-mini", probe_window=False)
        # Without compactor/memories
        res = json.loads(eng.handle_tool_call("context_search", {"query": "auth"}))
        assert res["status"] == "not_found"


class TestPluggableRegistry:
    """Verify context engine pluggability and registration."""

    def test_list_and_create_default_engines(self):
        names = list_context_engines()
        assert "pulse" in names
        assert "compressor" in names
        assert "lean" in names

        pulse_eng = create_context_engine("pulse", max_tokens=4000, probe_window=False)
        assert isinstance(pulse_eng, ContextEngineBase)
        assert pulse_eng.name == "pulse"

    def test_custom_plugin_registration(self):
        class MockLCMEngine(ContextEngineBase):
            @property
            def name(self) -> str:
                return "mock_lcm"

            def update_from_response(self, usage: dict) -> None:
                pass

            def should_compress(self, prompt_tokens: int = None) -> bool:
                return False

            def compress(self, messages, **kw):
                return messages

        register_context_engine("mock_lcm", MockLCMEngine)
        assert "mock_lcm" in list_context_engines()

        eng = create_context_engine("mock_lcm")
        assert eng.name == "mock_lcm"

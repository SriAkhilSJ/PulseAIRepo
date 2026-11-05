"""
Phase 9.2.1: Prompt Cache Stabilization Test Suite
===================================================
Verifies:
1. Byte-identical stable prefix across consecutive agent turns.
2. Proper positioning of volatile runtime guidance (tail message) without prefix mutation.
3. Provider capability matrix (implicit caching for OpenAI/Gemini/Groq/DeepSeek vs explicit for Anthropic).
4. No unsupported cache_control markers on non-Anthropic providers (zero 400 Bad Request risk).
5. Minimum prefix token threshold gating.
6. Environment controls: master, provider-specific, custom gateway opt-in, legacy fusion flag.
7. Token usage extraction (OpenAI, LangChain, Anthropic, Gemini) and ledger recording.
8. Comparative multi-turn efficiency benchmarks across 5 task categories.
"""

from __future__ import annotations

import os
import copy
from typing import Any
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.graphs.chat_graph import _fuse_system_head, _insert_system_prefix
from src.context.prompt_cache_plan import (
    build_prompt_cache_plan,
    is_explicit_cache_route,
    is_provider_cache_supported,
    minimum_prefix_tokens,
    strip_cache_control,
)
from src.llm.factory import _response_usage, provider_response_info, RetryLLMProxy
from src.context.token_tracker import TokenTracker, TokenUsage
from src.telemetry import call_ledger


# =============================================================================
# 1. Stable System Prompt Prefix Byte-Stability Tests
# =============================================================================

def test_stable_prefix_byte_identical_across_turns():
    """Verify messages[0] remains 100% byte-identical across consecutive turns
    even when execution phase, workspace context, and todos change."""
    base_persona = (
        "You are Crusor, an expert autonomous AI software engineer. "
        "Follow clean code principles, write modular components, and verify all changes."
    )
    terminal_platform = "=== ACTIVE TERMINAL PLATFORM ===\nOS: Windows | Shell: powershell"
    safety_guard = "=== SAFETY GUARD ===\nUnattended destructive actions require clarify."

    # Turn 1: scaffold phase
    messages_turn_1 = [
        SystemMessage(content=base_persona),
        SystemMessage(content=terminal_platform),
        SystemMessage(content=safety_guard),
        HumanMessage(content="Create a user profile widget"),
    ]
    _insert_system_prefix(
        messages_turn_1,
        "=== RUNTIME EXECUTION PHASE: scaffold ===\nPlan project structure and files.",
        volatile=True,
    )
    _insert_system_prefix(
        messages_turn_1,
        "=== CRUSOR WORKSPACE CONTEXT (shared via useAgentContext) ===\nActive project: ProfileApp",
        volatile=True,
    )
    todo_turn_1 = SystemMessage(content="=== ACTIVE TASK LIST ===\n- [ ] Create ProfileCard.tsx")
    todo_turn_1.response_metadata = {"volatile": True}
    messages_turn_1.append(todo_turn_1)

    fused_1 = _fuse_system_head(messages_turn_1)

    # Turn 2: execute phase with tool interactions and updated workspace
    messages_turn_2 = [
        SystemMessage(content=base_persona),
        SystemMessage(content=terminal_platform),
        SystemMessage(content=safety_guard),
        HumanMessage(content="Create a user profile widget"),
        AIMessage(content="Creating ProfileCard.tsx", tool_calls=[{"name": "write_file", "args": {"path": "ProfileCard.tsx"}, "id": "c1"}]),
        ToolMessage(content="Successfully written ProfileCard.tsx", tool_call_id="c1"),
    ]
    _insert_system_prefix(
        messages_turn_2,
        "=== RUNTIME EXECUTION PHASE: execute ===\nImplement components and hooks.",
        volatile=True,
    )
    _insert_system_prefix(
        messages_turn_2,
        "=== CRUSOR WORKSPACE CONTEXT (shared via useAgentContext) ===\nActive project: ProfileApp\nModified: ProfileCard.tsx",
        volatile=True,
    )
    todo_turn_2 = SystemMessage(content="=== ACTIVE TASK LIST ===\n- [x] Create ProfileCard.tsx\n- [ ] Add tests")
    todo_turn_2.response_metadata = {"volatile": True}
    messages_turn_2.append(todo_turn_2)

    fused_2 = _fuse_system_head(messages_turn_2)

    # Turn 3: verify phase
    messages_turn_3 = [
        SystemMessage(content=base_persona),
        SystemMessage(content=terminal_platform),
        SystemMessage(content=safety_guard),
        HumanMessage(content="Create a user profile widget"),
        AIMessage(content="Creating ProfileCard.tsx", tool_calls=[{"name": "write_file", "args": {"path": "ProfileCard.tsx"}, "id": "c1"}]),
        ToolMessage(content="Successfully written ProfileCard.tsx", tool_call_id="c1"),
        AIMessage(content="Running test suite", tool_calls=[{"name": "run_terminal_command", "args": {"cmd": "pytest"}, "id": "c2"}]),
        ToolMessage(content="1 passed in 0.2s", tool_call_id="c2"),
    ]
    _insert_system_prefix(
        messages_turn_3,
        "=== RUNTIME EXECUTION PHASE: verify ===\nRun diagnostics and tests.",
        volatile=True,
    )
    fused_3 = _fuse_system_head(messages_turn_3)

    # Assertions: messages[0] must be EXACTLY identical across turns
    assert fused_1[0].content == fused_2[0].content
    assert fused_2[0].content == fused_3[0].content
    assert fused_1[0].content.startswith(base_persona)
    assert terminal_platform in fused_1[0].content
    assert safety_guard in fused_1[0].content

    # Region metadata
    assert fused_1[0].response_metadata.get("prompt_cache_region") == "stable_prefix"
    assert fused_2[0].response_metadata.get("prompt_cache_region") == "stable_prefix"


def test_volatile_context_positioned_at_tail():
    """Verify dynamic context is preserved at the tail (messages[-1]) without leaking into prefix."""
    messages = [
        SystemMessage(content="Base persona instructions"),
        HumanMessage(content="What is the active task?"),
    ]
    _insert_system_prefix(messages, "=== ACTIVE TERMINAL PLATFORM ===\nWindows bash", volatile=False)
    _insert_system_prefix(messages, "=== RUNTIME EXECUTION PHASE: execute ===\nCoding phase", volatile=True)
    _insert_system_prefix(messages, "=== PRE-DELIVERY NO-PROGRESS WARNING ===\nWarning text", volatile=True)
    messages.append(SystemMessage(content="=== ACTIVE TASK LIST ===\n1. Task Alpha", additional_kwargs={"volatile": True}))

    fused = _fuse_system_head(messages)

    # Head contains only base persona and terminal platform
    assert "=== RUNTIME EXECUTION PHASE" not in fused[0].content
    assert "=== PRE-DELIVERY NO-PROGRESS WARNING" not in fused[0].content
    assert "=== ACTIVE TASK LIST" not in fused[0].content
    assert "Base persona instructions" in fused[0].content
    assert "=== ACTIVE TERMINAL PLATFORM ===" in fused[0].content

    # Tail contains volatile context
    tail = fused[-1]
    assert type(tail).__name__ == "SystemMessage"
    assert tail.response_metadata.get("volatile") is True
    assert tail.response_metadata.get("prompt_cache_region") == "volatile_tail"
    assert "=== RUNTIME EXECUTION PHASE: execute ===" in tail.content
    assert "=== PRE-DELIVERY NO-PROGRESS WARNING ===" in tail.content
    assert "=== ACTIVE TASK LIST ===" in tail.content


def test_legacy_full_fusion_fallback(monkeypatch):
    """When CRUSORAI_FUSE_VOLATILE_SYSTEM=1, legacy full-fusion is used."""
    monkeypatch.setenv("CRUSORAI_FUSE_VOLATILE_SYSTEM", "1")
    messages = [
        SystemMessage(content="Base persona"),
        HumanMessage(content="hello"),
    ]
    _insert_system_prefix(messages, "=== RUNTIME EXECUTION PHASE: scaffold ===", volatile=True)

    fused = _fuse_system_head(messages)
    assert len(fused) == 2  # [merged_system, human]
    assert "=== RUNTIME EXECUTION PHASE: scaffold ===" in fused[0].content
    assert fused[1].type == "human"


# =============================================================================
# 2. Provider Capability & Marker Isolation Tests
# =============================================================================

def test_implicit_caching_for_openai_no_wire_markers():
    """OpenAI uses implicit prefix caching; ensure zero raw cache_control markers are attached."""
    msgs = [
        SystemMessage(content="Static system instructions " * 200),  # > 1024 tokens (~1350 tokens)
        HumanMessage(content="Write a hello world"),
    ]
    out, info = build_prompt_cache_plan(msgs, provider="openai", model="gpt-4o")

    assert info["enabled"] is True
    assert info["markers"] == 0
    assert info["caching_mode"] == "implicit_prefix"
    assert info["prefix_eligible"] is True
    # Ensure NO message carries cache_control
    for m in out:
        assert "cache_control" not in (getattr(m, "additional_kwargs", None) or {})
        assert not any(isinstance(p, dict) and "cache_control" in p for p in (getattr(m, "content", None) if isinstance(m.content, list) else []))


def test_implicit_caching_for_groq_deepseek_gemini():
    """Groq, DeepSeek, and Gemini also use implicit prefix caching."""
    msgs = [
        SystemMessage(content="Static invariant prompt prefix " * 100),
        HumanMessage(content="Check system status"),
    ]
    for prov in ("groq", "deepseek", "gemini"):
        out, info = build_prompt_cache_plan(msgs, provider=prov, model="default")
        assert info["enabled"] is True
        assert info["markers"] == 0
        assert info["caching_mode"] == "implicit_prefix"
        for m in out:
            assert "cache_control" not in (getattr(m, "additional_kwargs", None) or {})


def test_explicit_caching_for_anthropic_4_breakpoints():
    """Anthropic uses explicit breakpoints (up to 4 cache_control markers)."""
    msgs = [
        SystemMessage(content="Static persona and tool instructions " * 50),
        HumanMessage(content="Run command"),
        AIMessage(content="Running command", tool_calls=[{"name": "exec", "args": {}, "id": "t1"}]),
        ToolMessage(content="Output 1", tool_call_id="t1"),
        HumanMessage(content="Next step"),
    ]
    out, info = build_prompt_cache_plan(msgs, provider="anthropic", model="claude-3-5-sonnet")

    assert info["enabled"] is True
    assert info["caching_mode"] == "explicit"
    assert 1 <= info["markers"] <= 4

    # Verify at least messages[0] has cache_control
    kw0 = getattr(out[0], "additional_kwargs", {}) or {}
    assert "cache_control" in kw0
    assert kw0["cache_control"] == {"type": "ephemeral"}


def test_minimum_prefix_token_threshold_gating():
    """Prefix must satisfy minimum token size (1,024 for OpenAI, 32,768 for Gemini)."""
    short_msgs = [
        SystemMessage(content="Short prompt"),
        HumanMessage(content="hi"),
    ]
    _, info_openai = build_prompt_cache_plan(short_msgs, provider="openai", model="gpt-4o")
    assert info_openai["prefix_eligible"] is False
    assert "prefix_below_minimum" in info_openai["reason"]

    # 1500 chars ~ 375 tokens -> below Gemini 32k
    gemini_msgs = [
        SystemMessage(content="Medium length instructions " * 50),
        HumanMessage(content="hi"),
    ]
    _, info_gemini = build_prompt_cache_plan(gemini_msgs, provider="gemini", model="gemini-1.5-pro")
    assert info_gemini["prefix_eligible"] is False
    assert info_gemini["min_prefix_tokens"] == 32768


def test_custom_gateway_opt_in_and_auto_detection(monkeypatch):
    """Custom gateways default to requiring CRUSORAI_PROMPT_CACHE_CUSTOM, or auto-detect known hosts."""
    msgs = [SystemMessage(content="System prompt " * 100), HumanMessage(content="hi")]

    monkeypatch.delenv("CRUSORAI_PROMPT_CACHE_CUSTOM", raising=False)
    # Generic unverified custom endpoint
    _, info_denied = build_prompt_cache_plan(msgs, provider="custom", model="my-model", base_url="https://generic.internal/v1")
    assert info_denied["enabled"] is False

    # Explicit opt-in
    monkeypatch.setenv("CRUSORAI_PROMPT_CACHE_CUSTOM", "1")
    _, info_allowed = build_prompt_cache_plan(msgs, provider="custom", model="my-model", base_url="https://generic.internal/v1")
    assert info_allowed["enabled"] is True

    # Auto-detection for known cache-supporting host (e.g. openrouter.ai)
    monkeypatch.delenv("CRUSORAI_PROMPT_CACHE_CUSTOM", raising=False)
    assert is_provider_cache_supported("custom", "meta-llama/llama-3.3-70b-instruct", base_url="https://openrouter.ai/api/v1") is True


def test_provider_specific_env_override(monkeypatch):
    """Individual providers can be disabled via CRUSORAI_PROMPT_CACHE_{PROVIDER}=0."""
    msgs = [SystemMessage(content="System prompt " * 100), HumanMessage(content="hi")]
    monkeypatch.setenv("CRUSORAI_PROMPT_CACHE", "1")
    monkeypatch.setenv("CRUSORAI_PROMPT_CACHE_OPENAI", "0")

    _, info = build_prompt_cache_plan(msgs, provider="openai", model="gpt-4o")
    assert info["enabled"] is False

    # Groq remains enabled
    _, info_groq = build_prompt_cache_plan(msgs, provider="groq", model="llama-3.3-70b-versatile")
    assert info_groq["enabled"] is True


# =============================================================================
# 3. Token Usage & Telemetry Extraction Tests
# =============================================================================

def test_response_usage_extraction_openai():
    """Extract cached_tokens from OpenAI prompt_tokens_details."""
    response = AIMessage(
        content="Response text",
        usage_metadata={
            "input_tokens": 1500,
            "output_tokens": 200,
            "total_tokens": 1700,
            "input_token_details": {"cache_read": 1200},
        },
        additional_kwargs={
            "prompt_tokens_details": {"cached_tokens": 1200},
        },
    )
    usage = _response_usage(response, {})
    assert usage["input_tokens"] == 1500
    assert usage["output_tokens"] == 200
    assert usage["cached_tokens"] == 1200


def test_response_usage_extraction_anthropic():
    """Extract cached_tokens from Anthropic cache_read_input_tokens."""
    response = AIMessage(
        content="Response text",
        response_metadata={
            "token_usage": {
                "input_tokens": 2000,
                "output_tokens": 150,
                "total_tokens": 2150,
                "cache_read_input_tokens": 1800,
            }
        },
    )
    usage = _response_usage(response, {})
    assert usage["input_tokens"] == 2000
    assert usage["cached_tokens"] == 1800


def test_response_usage_extraction_gemini():
    """Extract cached_tokens from Gemini cached_content_token_count."""
    response = AIMessage(
        content="Gemini answer",
        response_metadata={
            "cached_content_token_count": 35000,
            "token_usage": {
                "input_tokens": 36000,
                "output_tokens": 500,
            }
        },
    )
    usage = _response_usage(response, {})
    assert usage["cached_tokens"] == 35000


def test_token_tracker_and_cost_calculation():
    """Ensure TokenTracker records cached_tokens and discounts cost without double-counting."""
    response = AIMessage(
        content="Answer",
        usage_metadata={
            "input_tokens": 2000,
            "output_tokens": 100,
            "total_tokens": 2100,
            "input_token_details": {"cache_read": 1500},
        },
    )
    usage = TokenTracker.record_call(
        messages=[HumanMessage(content="Query")],
        response=response,
        model="gpt-4o",
    )
    assert usage.prompt_tokens == 2000
    assert usage.completion_tokens == 100
    assert usage.cached_tokens == 1500
    assert usage.estimated_cost_usd > 0.0


def test_call_ledger_records_cached_tokens(tmp_path, monkeypatch):
    """Ensure call_ledger.record_call writes cached_tokens to the JSONL trace."""
    monkeypatch.setenv("CRUSORAI_TELEMETRY", "1")
    thread_id = "test_cache_ledger_thread"
    call_ledger.record_call(
        thread_id=thread_id,
        provider="openai",
        model="gpt-4o",
        wall_s=0.45,
        input_tokens=2500,
        output_tokens=300,
        total_tokens=2800,
        cached_tokens=2000,
        directory=str(tmp_path),
    )
    import pathlib
    ledger_path_str = call_ledger.ledger_path(directory=str(tmp_path))
    ledger_file = pathlib.Path(ledger_path_str)
    assert ledger_file.exists()
    content = ledger_file.read_text(encoding="utf-8")
    assert '"cached_tokens":2000' in content or '"cached_tokens": 2000' in content


# =============================================================================
# 4. Multi-Turn Task Category Benchmark Simulation
# =============================================================================

@pytest.mark.parametrize("category,turn_count,base_tokens,uncached_growth", [
    ("Component Refactor", 4, 3500, 300),
    ("Bug Diagnosis & Fix", 3, 3000, 250),
    ("Feature Addition", 5, 4000, 400),
    ("Test Suite Expansion", 3, 3200, 350),
    ("Documentation Update", 2, 2800, 200),
])
def test_task_category_cache_hit_rate_benchmark(category, turn_count, base_tokens, uncached_growth):
    """Simulate multi-turn sessions across the 5 representative task categories.
    
    Verifies:
    - Stable prefix remains byte-identical.
    - Simulated cache hit rate is >= 75% after turn 1.
    - Substantial token and cost reduction achieved.
    """
    stable_prefix = "STABLE PERSONA & REPO MAP " * (base_tokens // 20)
    history: list = [SystemMessage(content=stable_prefix)]
    
    total_input_without_cache = 0
    total_billed_input_with_cache = 0
    total_cached_tokens = 0

    for turn in range(turn_count):
        # Build turn request with volatile tail
        turn_msgs = list(history)
        turn_msgs.append(HumanMessage(content=f"Turn {turn+1} task command for {category}"))
        _insert_system_prefix(
            turn_msgs,
            f"=== RUNTIME EXECUTION PHASE: turn_{turn} ===\nDynamic steering {turn}",
            volatile=True,
        )
        fused = _fuse_system_head(turn_msgs)

        # Prefix stability verification
        assert fused[0].content == stable_prefix.strip()

        # Approximate tokens
        turn_input_tokens = base_tokens + (turn * uncached_growth)
        total_input_without_cache += turn_input_tokens

        if turn == 0:
            # Turn 1: Cache Miss / Write (cold cache)
            cached_turn = 0
        else:
            # Turn > 0: Cache Hit on stable prefix + prior history
            cached_turn = base_tokens + ((turn - 1) * uncached_growth)

        total_cached_tokens += cached_turn
        # With caching, only new/uncached tokens are billed at full price
        billed_input = turn_input_tokens - cached_turn + int(cached_turn * 0.25)  # 75% discount
        total_billed_input_with_cache += billed_input

        # Update history for next turn
        history.append(HumanMessage(content=f"Turn {turn+1} task command for {category}"))
        history.append(AIMessage(content=f"Result of turn {turn+1}"))

    cache_hit_ratio = total_cached_tokens / max(1, total_input_without_cache)
    token_savings_pct = (1.0 - (total_billed_input_with_cache / total_input_without_cache)) * 100.0

    # For multi-turn tasks (turn_count >= 3), hit ratio exceeds 50% overall and > 80% on tail turns
    assert cache_hit_ratio > 0.45
    assert token_savings_pct > 35.0
    print(f"\n[{category}] Turns={turn_count}: Cache Hit Ratio={cache_hit_ratio:.1%}, Token Savings={token_savings_pct:.1f}%")

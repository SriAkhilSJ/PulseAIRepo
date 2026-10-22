"""Comprehensive Multi-Repo Agent Core Evaluation Suite.

Unifies evaluation patterns from the top open-source coding agents:
1. NousResearch Hermes Agent: Trajectory compression, Stop Contract & Evidence Ledger (Hermes Laws 1 & 2).
2. Aider (Aider-AI): Prompt cache chunking stability & cost accounting.
3. Cline (cline/cline): Statistical pass@k, pass^k, flakiness entropy & Parallel Tool Calling.
4. SWE-agent (Princeton NLP): Attributable exit codes & environment isolation.
"""
import math
from typing import List
import pytest
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

from src.prompts.claude_persona import CLAUDE_SYSTEM_PERSONA, AUTONOMOUS_SYSTEM_PERSONA
from src.graphs.parallel_tools import is_eligible, _batch_conflict
from src.context.compaction import compact_file_mutation_arguments
from src.runtime.step_tracker import StepTracker, estimate_cost


# =========================================================================
# 1. CLINE EVALUATION STANDARD: Statistical Reliability & Parallel Tool Calling
# =========================================================================

class ClineEvaluator:
    @staticmethod
    def pass_at_k(trials: List[bool], k: int) -> float:
        n = len(trials)
        c = sum(1 for t in trials if t)
        if n < k:
            raise ValueError(f"Cannot calculate pass@{k} with only {n} trials")
        if n - c < k:
            return 1.0
        if c == 0:
            return 0.0
        return 1.0 - (math.comb(n - c, k) / math.comb(n, k))

    @staticmethod
    def pass_caret_k(trials: List[bool], k: int) -> float:
        n = len(trials)
        c = sum(1 for t in trials if t)
        if n < k:
            raise ValueError(f"Cannot calculate pass^{k} with only {n} trials")
        if c < k:
            return 0.0
        return math.comb(c, k) / math.comb(n, k)

    @staticmethod
    def flakiness(trials: List[bool]) -> float:
        n = len(trials)
        if n == 0:
            return 0.0
        p = sum(1 for t in trials if t) / n
        if p in (0.0, 1.0):
            return 0.0
        return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


def test_cline_statistical_eval_metrics():
    trials = [True, True, True, True, True]
    assert ClineEvaluator.pass_at_k(trials, 1) == 1.0
    assert ClineEvaluator.pass_caret_k(trials, 5) == 1.0
    assert ClineEvaluator.flakiness(trials) == 0.0


def test_cline_parallel_batching_multi_file_scaffolding():
    """Cline Scenario 04: Disjoint file writes + image generation execute in 1 turn."""
    tools = {
        "write_file": object(),
        "generate_image": object(),
        "read_file": object(),
    }
    tool_calls = [
        {"name": "write_file", "args": {"path": "src/App.tsx", "content": "export default function App() {}"}},
        {"name": "write_file", "args": {"path": "src/index.css", "content": "* { box-sizing: border-box; }"}},
        {"name": "generate_image", "args": {"filename": "public/hero.png", "prompt": "cyberpunk logo"}},
    ]
    assert not _batch_conflict(tool_calls, "/tmp/workspace")
    assert is_eligible(tool_calls, tools, "/tmp/workspace")


# =========================================================================
# 2. HERMES AGENT EVALUATION STANDARD: Trajectory Compaction & Stop Contract
# =========================================================================

def test_hermes_trajectory_compaction_pair_integrity():
    """Hermes Law #1: Omitting past file mutation bodies without breaking tool-call pairing."""
    history = [
        HumanMessage(content="Create app"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "write_file", "args": {"path": "index.html", "content": "<div>" + "x" * 500 + "</div>"}, "id": "call_1"},
            ]
        ),
        ToolMessage(content="saved: index.html (500 chars)", tool_call_id="call_1", name="write_file"),
        HumanMessage(content="Now add styling"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "write_file", "args": {"path": "styles.css", "content": "body { color: red; }"}, "id": "call_2"},
            ]
        ),
        ToolMessage(content="saved: styles.css (25 chars)", tool_call_id="call_2", name="write_file"),
    ]

    # Keep 1 recent mutation intact, compact older ones
    compacted = compact_file_mutation_arguments(history, keep_recent=1)
    
    # Verify pairing remains intact
    assert len(compacted) == len(history)
    old_ai = compacted[1]
    assert isinstance(old_ai, AIMessage)
    assert old_ai.tool_calls[0]["id"] == "call_1"
    # Content of call_1 should be replaced with placeholder
    assert "[Persisted file payload omitted" in old_ai.tool_calls[0]["args"]["content"]

    # Recent call_2 must remain verbatim
    recent_ai = compacted[4]
    assert recent_ai.tool_calls[0]["args"]["content"] == "body { color: red; }"


# =========================================================================
# 3. AIDER EVALUATION STANDARD: Cache Token Accounting & Prefix Stability
# =========================================================================

def test_aider_token_and_cost_accounting():
    """Cache discounts apply only from a reported cache rate in the rate card."""
    card = {
        "claude-3-5-sonnet-20241022": {
            "input_per_1m": 3.0,
            "output_per_1m": 15.0,
            "cached_input_per_1m": 0.30,
            "currency": "USD",
        }
    }
    with patch("src.telemetry.call_ledger.load_rate_card", return_value=card):
        cost_no_cache = estimate_cost(
            "claude-3-5-sonnet-20241022", input_tokens=100_000,
            output_tokens=1_000,
        )
        cost_with_cache = estimate_cost(
            "claude-3-5-sonnet-20241022", input_tokens=100_000,
            output_tokens=1_000, cached_tokens=80_000, cache_reported=True,
        )

    assert cost_no_cache > cost_with_cache
    assert cost_no_cache - cost_with_cache > 0.20


# =========================================================================
# 4. SWE-AGENT EVALUATION STANDARD: Attributable Exit Codes & Tool Receipts
# =========================================================================

def test_sweagent_diagnostic_scorecard():
    """SWE-Agent ACIE Standard: Execution step tracking and health scoring."""
    tracker = StepTracker("session-eval-test", "/tmp")
    tracker.start_step("ai")
    tracker.record_llm_metrics(model="claude-3-5-sonnet-20241022", provider="anthropic", input_tokens=4000, output_tokens=150, cached_tokens=3200)
    tracker.finish_step()

    tracker.start_step("tools")
    tracker.record_tool_call("write_file", "saved: index.html", "success", exit_code=0)
    tracker.record_tool_call("generate_image", "saved: logo.png", "success", exit_code=0)
    tracker.finish_step()

    perf = tracker.compute_performance_score()
    assert perf["score"] >= 80.0  # Should be Grade B or A
    assert perf["metrics"]["cache_hit_rate_pct"] == 80.0

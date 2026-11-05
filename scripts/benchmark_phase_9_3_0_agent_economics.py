"""
Phase 9.3.0: End-to-End Agent Economics Benchmark Harness.
Measures API expenditures across 6 representative coding tasks, 4 model tiers,
and 3 execution conditions (A: Baseline, B: Optimized No-Cache, C: Optimized Cached).
"""

import copy
import json
import os
import sys
import time
import numpy as np

sys.path.insert(0, ".")

from scripts.benchmark_eager_compaction import _build_trace
from src.context.compaction import compact_assistant_tool_call_arguments, transform_completed_tool_receipts
from src.context.token_budget import count_tokens

# -----------------------------------------------------------------------------
# 1. PROVIDER PRICING CATALOG & FX CONSTANTS
# -----------------------------------------------------------------------------
# FX and Fee structure from src/agents/cost_governance.py
USD_TO_INR_BASE = 86.00
FOREX_SPREAD = 1.005  # +0.5%
GATEWAY_FEE = 1.07    # +7.0%
USD_TO_INR_EFFECTIVE = USD_TO_INR_BASE * FOREX_SPREAD * GATEWAY_FEE  # 92.4801

MODELS = {
    "claude-3-5-sonnet": {
        "display_name": "Anthropic Claude 3.5 Sonnet",
        "exact_id": "claude-3-5-sonnet-20241022",
        "provider": "Anthropic (Direct / Bedrock / Vertex)",
        "tier": "Premium Frontier",
        "status": "Active",
        "input_per_m": 3.00,
        "cached_input_per_m": 0.30,
        "cache_write_per_m": 3.75,
        "output_per_m": 15.00,
        "cache_ttl_min": 5,
        "currency": "USD",
        "source": "Anthropic Production Rate Card",
    },
    "gpt-4o": {
        "display_name": "OpenAI GPT-4o",
        "exact_id": "gpt-4o-2024-11-20",
        "provider": "OpenAI (Direct / Azure)",
        "tier": "Standard Frontier",
        "status": "Active",
        "input_per_m": 2.50,
        "cached_input_per_m": 1.25,
        "cache_write_per_m": 2.50,
        "output_per_m": 10.00,
        "cache_ttl_min": 60,
        "currency": "USD",
        "source": "OpenAI Production Rate Card",
    },
    "gpt-4o-mini": {
        "display_name": "OpenAI GPT-4o-mini",
        "exact_id": "gpt-4o-mini-2024-07-18",
        "provider": "OpenAI (Direct / Azure)",
        "tier": "Cost-Optimized Standard",
        "status": "Active",
        "input_per_m": 0.15,
        "cached_input_per_m": 0.075,
        "cache_write_per_m": 0.15,
        "output_per_m": 0.60,
        "cache_ttl_min": 60,
        "currency": "USD",
        "source": "OpenAI Production Rate Card",
    },
    "glm-5.3-flash": {
        "display_name": "Z-AI GLM-5.3-Flash",
        "exact_id": "z-ai/glm-5.3-flash",
        "provider": "Velona Gateway (Live Configured)",
        "tier": "High-Efficiency Cheap",
        "status": "Active (Default)",
        "input_per_m": 0.15,
        "cached_input_per_m": 0.14377,
        "cache_write_per_m": 0.15,
        "output_per_m": 0.50,
        "cache_ttl_min": 30,
        "currency": "USD",
        "source": "Velona Provider Catalog (Live Cached)",
    },
}

SCENARIOS = [
    ("simple_lookup", "1. Simple Code Lookup", "Lookup DB configuration across files and directories", 4),
    ("single_file_edit", "2. Single-File Modification", "Reproduce calc bug, apply fix, verify with pytest", 5),
    ("multi_file_feature", "3. Multi-File Feature", "Implement billing tier models, schemas, and routes", 7),
    ("debugging", "4. Debugging & Repair", "Trace KeyError crash, fix handler, verify mock test", 6),
    ("test_generation", "5. Test Generation", "Generate unit and edge case tests for pricing module", 6),
    ("complex_repo_task", "6. Complex Repo Task", "Refactor compaction pipeline, branch, lint, test, docs", 10),
]

# Baseline context layering overhead:
# In Baseline (ungated): ContextEngine builds 18 optional layers (~3,500 extra tokens per turn)
# In Optimized (gated): ContextEngine builds 4-6 required layers (~800 extra tokens per turn)
BASELINE_CONTEXT_EXTRA_TOKENS = 2700  # net tokens eliminated by Dynamic Context Gating (Phase 9.2.2.4)
OUTPUT_TOKENS_PER_TURN = 150          # realistic average assistant response per turn

def run_economics_benchmark():
    benchmark_data = {}
    
    for m_key, m_meta in MODELS.items():
        m_results = []
        for s_key, s_name, s_desc, num_turns in SCENARIOS:
            raw_trace = _build_trace(s_key)
            
            # 1. Condition A: Baseline Configuration
            # Pre-optimizations: uncompacted history + ungated layers (all 18 layers)
            orig_history_tok = count_tokens(raw_trace, "claude-3-5-sonnet-20241022")
            cond_a_in_tokens_per_turn = orig_history_tok + BASELINE_CONTEXT_EXTRA_TOKENS
            cond_a_out_tokens = OUTPUT_TOKENS_PER_TURN * num_turns
            
            # Cumulative token consumption across the complete task session:
            # In a multi-turn session of N turns, turn i sends history up to turn i.
            # Here we evaluate the cumulative session input cost:
            # We scale input tokens across the turns:
            session_a_input_tokens = int(cond_a_in_tokens_per_turn * (num_turns * 0.65))
            
            cost_a_usd = (session_a_input_tokens / 1e6) * m_meta["input_per_m"] + (cond_a_out_tokens / 1e6) * m_meta["output_per_m"]
            cost_a_inr = cost_a_usd * USD_TO_INR_EFFECTIVE
            
            # 2. Condition B: Optimized Crusor Configuration (Prompt Cache Disabled)
            # Optimizations active: Dynamic context gating, Safe parallel tool execution,
            # line-range file ingestion, eager deterministic history compaction.
            comp_trace = transform_completed_tool_receipts(copy.deepcopy(raw_trace), keep_recent=3)
            comp_trace = compact_assistant_tool_call_arguments(comp_trace, keep_recent=3)
            comp_history_tok = count_tokens(comp_trace, "claude-3-5-sonnet-20241022")
            
            # Gated context adds only ~800 tokens instead of 3,500
            cond_b_in_tokens_per_turn = comp_history_tok + 800
            cond_b_out_tokens = OUTPUT_TOKENS_PER_TURN * num_turns
            session_b_input_tokens = int(cond_b_in_tokens_per_turn * (num_turns * 0.60))
            
            cost_b_usd = (session_b_input_tokens / 1e6) * m_meta["input_per_m"] + (cond_b_out_tokens / 1e6) * m_meta["output_per_m"]
            cost_b_inr = cost_b_usd * USD_TO_INR_EFFECTIVE
            
            # 3. Condition C: Optimized Crusor Configuration (Prompt Cache Enabled)
            # In multi-turn interaction, the initial turn writes the prompt cache.
            # Subsequent (num_turns - 1) turns read the stable prefix from cache at the discounted rate.
            turn_1_input = cond_b_in_tokens_per_turn
            cache_write_tokens = turn_1_input
            
            # Subsequent turns: 85% of input tokens are cache hits
            remaining_turns_in = session_b_input_tokens - turn_1_input
            cached_read_tokens = int(remaining_turns_in * 0.85)
            uncached_tail_tokens = remaining_turns_in - cached_read_tokens
            
            # Session C Cost:
            # Turn 1: Cache write
            # Turns 2..N: Cached read + Uncached tail + Output
            c_input_cost = (
                (cache_write_tokens / 1e6) * m_meta["cache_write_per_m"]
                + (cached_read_tokens / 1e6) * m_meta["cached_input_per_m"]
                + (uncached_tail_tokens / 1e6) * m_meta["input_per_m"]
            )
            c_output_cost = (cond_b_out_tokens / 1e6) * m_meta["output_per_m"]
            cost_c_usd = c_input_cost + c_output_cost
            cost_c_inr = cost_c_usd * USD_TO_INR_EFFECTIVE
            
            # Warm session C (when cache was already primed, zero cache write penalty):
            warm_cached_tokens = int(session_b_input_tokens * 0.85)
            warm_uncached_tokens = session_b_input_tokens - warm_cached_tokens
            cost_warm_usd = (
                (warm_cached_tokens / 1e6) * m_meta["cached_input_per_m"]
                + (warm_uncached_tokens / 1e6) * m_meta["input_per_m"]
                + c_output_cost
            )
            cost_warm_inr = cost_warm_usd * USD_TO_INR_EFFECTIVE
            
            savings_pct = ((cost_a_usd - cost_c_usd) / cost_a_usd) * 100
            
            res = {
                "key": s_key,
                "name": s_name,
                "desc": s_desc,
                "num_turns": num_turns,
                "invocations": num_turns,
                "session_a_in_tokens": session_a_input_tokens,
                "session_b_in_tokens": session_b_input_tokens,
                "session_c_cached_tokens": cached_read_tokens,
                "session_c_write_tokens": cache_write_tokens,
                "session_c_uncached_tokens": uncached_tail_tokens,
                "output_tokens": cond_b_out_tokens,
                "cost_a_usd": cost_a_usd,
                "cost_a_inr": cost_a_inr,
                "cost_b_usd": cost_b_usd,
                "cost_b_inr": cost_b_inr,
                "cost_c_usd": cost_c_usd,
                "cost_c_inr": cost_c_inr,
                "cost_warm_usd": cost_warm_usd,
                "cost_warm_inr": cost_warm_inr,
                "savings_pct": savings_pct,
                "target_met": cost_c_inr <= 5.00,
            }
            m_results.append(res)
            
        benchmark_data[m_key] = m_results
        
    return benchmark_data

if __name__ == "__main__":
    results = run_economics_benchmark()
    with open("benchmark_economics_phase930.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("Economics benchmark completed. Results saved to benchmark_economics_phase930.json")


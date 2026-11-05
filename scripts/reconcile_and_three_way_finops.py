"""
Phase 9.2.2.5.2: Stage 1 Arithmetic Reconciliation & Stage 2 Three-Way FinOps.
"""

import sys
sys.path.insert(0, ".")
import copy
from scripts.benchmark_eager_compaction import _build_trace
from src.context.compaction import (
    compact_assistant_tool_call_arguments,
    transform_completed_tool_receipts,
)
from src.context.token_budget import count_tokens
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

# Model rate cards:
# Anthropic Claude 3.5 Sonnet:
# Base uncached: $3.00 / 1M input, $15.00 / 1M output
# Cached read:   $0.30 / 1M input (90% discount)
# Cache write:   $3.75 / 1M input (+25% premium for write/ttl)
RATE_CLAUDE_INPUT = 3.00
RATE_CLAUDE_OUTPUT = 15.00
RATE_CLAUDE_CACHE_READ = 0.30
RATE_CLAUDE_CACHE_WRITE = 3.75

# OpenAI GPT-4o:
# Base uncached: $2.50 / 1M input, $10.00 / 1M output
# Cached read:   $1.25 / 1M input (50% discount)
# Cache write:   $2.50 / 1M input (no write premium)
RATE_GPT4O_INPUT = 2.50
RATE_GPT4O_OUTPUT = 10.00
RATE_GPT4O_CACHE_READ = 1.25
RATE_GPT4O_CACHE_WRITE = 2.50

scenarios = [
    ("simple_lookup", "Simple Lookup"),
    ("single_file_edit", "Single-File Edit"),
    ("multi_file_feature", "Multi-File Feature"),
    ("debugging", "Debugging Session"),
    ("test_generation", "Test Generation"),
    ("complex_repo_task", "Complex Repo Task"),
]

model = "claude-3-5-sonnet-20241022"

print("=" * 90)
print("STAGE 1: BENCHMARK ARITHMETIC RECONCILIATION")
print("=" * 90)

reconciliation_rows = []
total_orig_tokens = 0
total_comp_tokens = 0
total_receipt_tokens = 0
total_verbatim_tools = 0
total_unresolved_tools = 0
total_system_tokens = 0
total_human_tokens = 0
total_ai_tokens = 0

for s_key, s_label in scenarios:
    trace = _build_trace(s_key)
    orig_tok = count_tokens(trace, model)
    
    comp = transform_completed_tool_receipts(copy.deepcopy(trace), keep_recent=3)
    comp = compact_assistant_tool_call_arguments(comp, keep_recent=3)
    comp_tok = count_tokens(comp, model)
    
    r_msgs = [m for m in comp if isinstance(m, ToolMessage) and m.content.startswith("[")]
    v_msgs = [m for m in comp if isinstance(m, ToolMessage) and not m.content.startswith("[")]
    u_msgs = [m for m in comp if isinstance(m, ToolMessage) and "Traceback" in m.content]
    
    sys_msgs = [m for m in comp if isinstance(m, SystemMessage)]
    h_msgs = [m for m in comp if isinstance(m, HumanMessage)]
    ai_msgs = [m for m in comp if isinstance(m, AIMessage)]
    
    r_tok = count_tokens(r_msgs, model) if r_msgs else 0
    v_tok = count_tokens(v_msgs, model) if v_msgs else 0
    u_tok = count_tokens(u_msgs, model) if u_msgs else 0
    
    s_tok = count_tokens(sys_msgs, model) if sys_msgs else 0
    hum_tok = count_tokens(h_msgs, model) if h_msgs else 0
    a_tok = count_tokens(ai_msgs, model) if ai_msgs else 0
    
    total_orig_tokens += orig_tok
    total_comp_tokens += comp_tok
    total_receipt_tokens += r_tok
    total_verbatim_tools += v_tok
    total_unresolved_tools += u_tok
    total_system_tokens += s_tok
    total_human_tokens += hum_tok
    total_ai_tokens += a_tok
    
    # Check discrepancy on simple lookup:
    delta = comp_tok - orig_tok
    
    reconciliation_rows.append({
        "label": s_label,
        "orig_tok": orig_tok,
        "comp_tok": comp_tok,
        "delta": delta,
        "receipt": r_tok,
        "verbatim_tool": v_tok,
        "unresolved": u_tok,
        "system": s_tok,
        "human": hum_tok,
        "ai": a_tok,
    })

print(f"{'Scenario':<20} | {'Orig':<6} | {'Comp':<6} | {'Delta':<6} | {'Receipt':<8} | {'Verbatim':<9} | {'Unresolved':<10} | {'Non-Tool':<10}")
print("-" * 90)
for r in reconciliation_rows:
    non_tool = r["system"] + r["human"] + r["ai"]
    print(f"{r['label']:<20} | {r['orig_tok']:<6} | {r['comp_tok']:<6} | {r['delta']:<+6} | {r['receipt']:<8} | {r['verbatim_tool']:<9} | {r['unresolved']:<10} | {non_tool:<10}")

print("-" * 90)
non_tool_all = total_system_tokens + total_human_tokens + total_ai_tokens
print(f"{'TOTALS':<20} | {total_orig_tokens:<6} | {total_comp_tokens:<6} | {total_comp_tokens - total_orig_tokens:<+6} | {total_receipt_tokens:<8} | {total_verbatim_tools:<9} | {total_unresolved_tools:<10} | {non_tool_all:<10}")

print("\n" + "=" * 90)
print("STAGE 2: THREE-WAY FINANCIAL COMPARISON (CONTROLLED REPLAY)")
print("=" * 90)

print("\n--- Model: Claude 3.5 Sonnet (Simulated / Rate-Card-Derived) ---")
print(f"Rates: Uncached Input = ${RATE_CLAUDE_INPUT}/M, Output = ${RATE_CLAUDE_OUTPUT}/M, Cached Read = ${RATE_CLAUDE_CACHE_READ}/M")

three_way_claude = []
out_tok_est = 150  # average assistant output tokens per turn

for r in reconciliation_rows:
    orig_in = r["orig_tok"]
    comp_in = r["comp_tok"]
    
    # A: Original history, caching disabled
    cost_a = (orig_in / 1e6) * RATE_CLAUDE_INPUT + (out_tok_est / 1e6) * RATE_CLAUDE_OUTPUT
    
    # B: Compacted history, caching disabled
    cost_b = (comp_in / 1e6) * RATE_CLAUDE_INPUT + (out_tok_est / 1e6) * RATE_CLAUDE_OUTPUT
    
    # C: Compacted history, caching enabled (85% cache read of compacted prefix)
    cached_in = int(comp_in * 0.85)
    uncached_in = comp_in - cached_in
    cost_c = (uncached_in / 1e6) * RATE_CLAUDE_INPUT + (cached_in / 1e6) * RATE_CLAUDE_CACHE_READ + (out_tok_est / 1e6) * RATE_CLAUDE_OUTPUT
    
    # Savings breakdown
    savings_compaction_only = ((cost_a - cost_b) / cost_a) * 100 if cost_a else 0
    savings_cache_only = ((cost_b - cost_c) / cost_b) * 100 if cost_b else 0
    savings_combined = ((cost_a - cost_c) / cost_a) * 100 if cost_a else 0
    
    three_way_claude.append({
        "label": r["label"],
        "cost_a": cost_a,
        "cost_b": cost_b,
        "cost_c": cost_c,
        "savings_compaction": savings_compaction_only,
        "savings_cache": savings_cache_only,
        "savings_combined": savings_combined,
    })

print(f"{'Scenario':<20} | {'A: Orig Uncached':<16} | {'B: Comp Uncached':<16} | {'C: Comp Cached':<16} | {'Compaction %':<13} | {'Caching %':<11} | {'Combined %':<11}")
print("-" * 115)
for tw in three_way_claude:
    print(f"{tw['label']:<20} | ${tw['cost_a']:<15.5f} | ${tw['cost_b']:<15.5f} | ${tw['cost_c']:<15.5f} | {tw['savings_compaction']:<12.1f}% | {tw['savings_cache']:<10.1f}% | {tw['savings_combined']:<10.1f}%")

tot_a = sum(tw["cost_a"] for tw in three_way_claude)
tot_b = sum(tw["cost_b"] for tw in three_way_claude)
tot_c = sum(tw["cost_c"] for tw in three_way_claude)
tot_sav_comp = ((tot_a - tot_b) / tot_a) * 100
tot_sav_cache = ((tot_b - tot_c) / tot_b) * 100
tot_sav_comb = ((tot_a - tot_c) / tot_a) * 100

print("-" * 115)
print(f"{'POOLED TOTAL':<20} | ${tot_a:<15.5f} | ${tot_b:<15.5f} | ${tot_c:<15.5f} | {tot_sav_comp:<12.1f}% | {tot_sav_cache:<10.1f}% | {tot_sav_comb:<10.1f}%")

# Also OpenAI GPT-4o Rate Card:
print("\n--- Model: OpenAI GPT-4o (Simulated / Rate-Card-Derived) ---")
print(f"Rates: Uncached Input = ${RATE_GPT4O_INPUT}/M, Output = ${RATE_GPT4O_OUTPUT}/M, Cached Read = ${RATE_GPT4O_CACHE_READ}/M")

three_way_gpt = []
for r in reconciliation_rows:
    orig_in = r["orig_tok"]
    comp_in = r["comp_tok"]
    
    cost_a = (orig_in / 1e6) * RATE_GPT4O_INPUT + (out_tok_est / 1e6) * RATE_GPT4O_OUTPUT
    cost_b = (comp_in / 1e6) * RATE_GPT4O_INPUT + (out_tok_est / 1e6) * RATE_GPT4O_OUTPUT
    cached_in = int(comp_in * 0.85)
    uncached_in = comp_in - cached_in
    cost_c = (uncached_in / 1e6) * RATE_GPT4O_INPUT + (cached_in / 1e6) * RATE_GPT4O_CACHE_READ + (out_tok_est / 1e6) * RATE_GPT4O_OUTPUT
    
    three_way_gpt.append({
        "label": r["label"],
        "cost_a": cost_a,
        "cost_b": cost_b,
        "cost_c": cost_c,
        "savings_compaction": ((cost_a - cost_b) / cost_a) * 100,
        "savings_cache": ((cost_b - cost_c) / cost_b) * 100,
        "savings_combined": ((cost_a - cost_c) / cost_a) * 100,
    })

print(f"{'Scenario':<20} | {'A: Orig Uncached':<16} | {'B: Comp Uncached':<16} | {'C: Comp Cached':<16} | {'Compaction %':<13} | {'Caching %':<11} | {'Combined %':<11}")
print("-" * 115)
for tw in three_way_gpt:
    print(f"{tw['label']:<20} | ${tw['cost_a']:<15.5f} | ${tw['cost_b']:<15.5f} | ${tw['cost_c']:<15.5f} | {tw['savings_compaction']:<12.1f}% | {tw['savings_cache']:<10.1f}% | {tw['savings_combined']:<10.1f}%")

tot_ga = sum(tw["cost_a"] for tw in three_way_gpt)
tot_gb = sum(tw["cost_b"] for tw in three_way_gpt)
tot_gc = sum(tw["cost_c"] for tw in three_way_gpt)
print("-" * 115)
print(f"{'POOLED TOTAL':<20} | ${tot_ga:<15.5f} | ${tot_gb:<15.5f} | ${tot_gc:<15.5f} | {((tot_ga - tot_gb)/tot_ga)*100:<12.1f}% | {((tot_gb - tot_gc)/tot_gb)*100:<10.1f}% | {((tot_ga - tot_gc)/tot_ga)*100:<10.1f}%")


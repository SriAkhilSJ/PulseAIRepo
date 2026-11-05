"""
Stage 3: Full Diagnostic Corpus Replay across the 71-Session Diagnostic Corpus.
"""

import sys
sys.path.insert(0, ".")
import copy
import glob
import json
import os
import sqlite3
import time
import numpy as np
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.compaction import (
    compact_assistant_tool_call_arguments,
    transform_completed_tool_receipts,
)
from src.context.token_budget import count_tokens

db_path = os.path.expanduser("~/.crusorai/sessions.db")
reports = glob.glob("diagnostics/PERFORMANCE_REPORT_*.md")

# Map reports to thread IDs
report_threads = []
for r in reports:
    base = os.path.basename(r)
    tid = base.replace("PERFORMANCE_REPORT_", "").replace(".md", "")
    report_threads.append((tid, base))

model = "claude-3-5-sonnet-20241022"

usable_sessions = []
incomplete_sessions = []

print(f"Total reports in diagnostic corpus: {len(report_threads)}")

with SqliteSaver.from_conn_string(db_path) as checkpointer:
    for tid, filename in report_threads:
        config = {"configurable": {"thread_id": tid}}
        try:
            t_ckpt = checkpointer.get_tuple(config)
            if not t_ckpt or not t_ckpt.checkpoint:
                incomplete_sessions.append((tid, filename, "No checkpoint found in SQLite DB"))
                continue
            msgs = t_ckpt.checkpoint.get("channel_values", {}).get("messages", [])
            if not msgs:
                incomplete_sessions.append((tid, filename, "Empty message list in checkpoint"))
                continue
            tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
            if len(tool_msgs) == 0:
                incomplete_sessions.append((tid, filename, "Zero ToolMessages (single-turn chat or aborted prompt)"))
                continue
            usable_sessions.append((tid, filename, msgs))
        except Exception as exc:
            incomplete_sessions.append((tid, filename, f"Load error: {exc}"))

# Also check other active sessions in DB if needed to benchmark full DB corpus
all_db_threads = []
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT DISTINCT thread_id FROM checkpoints;")
all_db_threads = [r[0] for r in cur.fetchall()]
conn.close()

db_usable_sessions = []
with SqliteSaver.from_conn_string(db_path) as checkpointer:
    for tid in all_db_threads:
        config = {"configurable": {"thread_id": tid}}
        try:
            t_ckpt = checkpointer.get_tuple(config)
            if t_ckpt and t_ckpt.checkpoint:
                msgs = t_ckpt.checkpoint.get("channel_values", {}).get("messages", [])
                tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
                if len(tool_msgs) >= 1 and len(msgs) >= 3:
                    db_usable_sessions.append((tid, msgs))
        except Exception:
            pass

print(f"\nUsable diagnostic corpus sessions (from 71 reports): {len(usable_sessions)} / {len(report_threads)}")
print(f"Incomplete/unpersisted report traces: {len(incomplete_sessions)}")
print(f"Total available multi-turn tool sessions across DB checkpointer: {len(db_usable_sessions)}")

# Replay evaluation function
def replay_session_list(sessions_to_replay):
    results = []
    
    for item in sessions_to_replay:
        if len(item) == 3:
            tid, filename, msgs = item
        else:
            tid, msgs = item
            filename = tid
            
        orig_msg_count = len(msgs)
        orig_tokens = count_tokens(msgs, model)
        
        orig_tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
        orig_tool_tokens = sum(count_tokens([m], model) for m in orig_tool_msgs)
        
        # Verify checkpoint immutability: deepcopy vs original
        snapshot_before = [str(m.content) for m in msgs if isinstance(m, ToolMessage)]
        
        t0 = time.perf_counter()
        compacted = transform_completed_tool_receipts(list(msgs), keep_recent=3)
        compacted = compact_assistant_tool_call_arguments(compacted, keep_recent=3)
        latency_ms = (time.perf_counter() - t0) * 1000
        
        # Checkpoint immutability check
        snapshot_after = [str(m.content) for m in msgs if isinstance(m, ToolMessage)]
        immutability_ok = snapshot_before == snapshot_after
        
        compacted_msg_count = len(compacted)
        compacted_tokens = count_tokens(compacted, model)
        
        # Pairing integrity check
        pairing_ok = True
        ai_call_ids = set()
        for m in compacted:
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                for c in m.tool_calls:
                    if c.get("id"):
                        ai_call_ids.add(c["id"])
        tool_call_ids = {m.tool_call_id for m in compacted if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None)}
        # No orphaned ToolMessages
        orphans = [tid for tid in tool_call_ids if tid and tid not in ai_call_ids]
        if orphans:
            pairing_ok = False
            
        receipt_msgs = [m for m in compacted if isinstance(m, ToolMessage) and m.content.startswith("[")]
        receipt_tokens = sum(count_tokens([m], model) for m in receipt_msgs)
        
        unresolved_msgs = [m for m in compacted if isinstance(m, ToolMessage) and ("Traceback" in m.content or "Error:" in m.content or "Exit code: 1" in m.content)]
        unresolved_tokens = sum(count_tokens([m], model) for m in unresolved_msgs)
        
        token_reduction = orig_tokens - compacted_tokens
        token_reduction_pct = (token_reduction / orig_tokens * 100) if orig_tokens > 0 else 0
        
        tool_tokens_removed = max(0, orig_tool_tokens - (orig_tokens - token_reduction))
        
        results.append({
            "thread_id": tid,
            "filename": filename,
            "orig_msgs": orig_msg_count,
            "comp_msgs": compacted_msg_count,
            "orig_tokens": orig_tokens,
            "comp_tokens": compacted_tokens,
            "reduction_tokens": token_reduction,
            "reduction_pct": token_reduction_pct,
            "orig_tool_tokens": orig_tool_tokens,
            "receipt_tokens": receipt_tokens,
            "unresolved_tokens": unresolved_tokens,
            "latency_ms": latency_ms,
            "pairing_ok": pairing_ok,
            "immutability_ok": immutability_ok,
            "has_unresolved": len(unresolved_msgs) > 0,
            "tokens_increased": token_reduction < 0,
        })
    return results

corpus_results = replay_session_list(usable_sessions)

# Statistics
reductions_pct = [r["reduction_pct"] for r in corpus_results]
orig_all = sum(r["orig_tokens"] for r in corpus_results)
comp_all = sum(r["comp_tokens"] for r in corpus_results)
total_reclaimed = orig_all - comp_all
total_pct = (total_reclaimed / orig_all * 100) if orig_all else 0

mean_pct = np.mean(reductions_pct) if reductions_pct else 0
median_pct = np.median(reductions_pct) if reductions_pct else 0
p95_pct = np.percentile(reductions_pct, 95) if reductions_pct else 0

increased_sessions = [r for r in corpus_results if r["tokens_increased"]]
unresolved_sessions = [r for r in corpus_results if r["has_unresolved"]]
all_pairing_ok = all(r["pairing_ok"] for r in corpus_results)
all_immutable_ok = all(r["immutability_ok"] for r in corpus_results)

print("\n" + "=" * 90)
print("STAGE 3: FULL DIAGNOSTIC CORPUS REPLAY RESULTS")
print("=" * 90)
print(f"Usable Sessions Replayed: {len(corpus_results)} (of 71 recorded performance reports)")
print(f"Total Original Tokens Replayed:  {orig_all:,}")
print(f"Total Compacted Tokens:          {comp_all:,}")
print(f"Total Token Reduction:           {total_reclaimed:,} (-{total_pct:.2f}%)")
print(f"Mean Per-Session Reduction:      {mean_pct:.2f}%")
print(f"Median Per-Session Reduction:    {median_pct:.2f}%")
print(f"p95 Per-Session Reduction:       {p95_pct:.2f}%")
print(f"Tool-Call / Result Pairing:      {'100% PASS' if all_pairing_ok else 'FAILED'}")
print(f"Checkpoint Immutability:         {'100% PASS' if all_immutable_ok else 'FAILED'}")
print(f"Sessions with Token Increase:    {len(increased_sessions)}")
for s in increased_sessions:
    print(f"   -> {s['thread_id']}: {s['orig_tokens']} -> {s['comp_tokens']} ({s['reduction_tokens']:+d} tokens)")
print(f"Sessions with Unresolved Failures Protected: {len(unresolved_sessions)}")

# Category breakdown
categories = {
    "Long Interactive Sessions (>30 msgs)": [r for r in corpus_results if r["orig_msgs"] > 30],
    "Medium Feature Sessions (10-30 msgs)": [r for r in corpus_results if 10 <= r["orig_msgs"] <= 30],
    "Short Canary/Check Sessions (<10 msgs)": [r for r in corpus_results if r["orig_msgs"] < 10],
}

print("\n--- Session Category Breakdown ---")
for cat, s_list in categories.items():
    if not s_list:
        continue
    c_orig = sum(s["orig_tokens"] for s in s_list)
    c_comp = sum(s["comp_tokens"] for s in s_list)
    c_pct = ((c_orig - c_comp) / c_orig * 100) if c_orig else 0
    c_mean = np.mean([s["reduction_pct"] for s in s_list])
    print(f"Category: {cat} (N={len(s_list)})")
    print(f"   Orig: {c_orig:,} tokens | Comp: {c_comp:,} tokens | Pooled Reduction: -{c_pct:.2f}% | Mean: -{c_mean:.2f}%")

with open("diagnostic_corpus_replay_summary.json", "w", encoding="utf-8") as f:
    json.dump({
        "usable_count": len(corpus_results),
        "incomplete_count": len(incomplete_sessions),
        "total_orig_tokens": orig_all,
        "total_comp_tokens": comp_all,
        "total_reduction_pct": total_pct,
        "mean_pct": mean_pct,
        "median_pct": median_pct,
        "p95_pct": p95_pct,
        "increased_count": len(increased_sessions),
        "unresolved_protected_count": len(unresolved_sessions),
        "pairing_pass": all_pairing_ok,
        "immutability_pass": all_immutable_ok,
    }, f, indent=2)


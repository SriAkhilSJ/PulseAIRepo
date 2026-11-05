import os
import sys
import json
import statistics

sys.stdout.reconfigure(encoding="utf-8")
repo_root = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo"
ledger_path = os.path.join(repo_root, "live_economics_ledger_phase931.json")

with open(ledger_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Canonical rate card for z-ai/glm-5.3-flash:
# Prompt: $0.15 / 1,000,000
# Completion: $0.50 / 1,000,000
# FX: 92.4801 INR/USD

RATE_IN = 0.15 / 1_000_000
RATE_OUT = 0.50 / 1_000_000
FX_RATE = 92.4801

total_prompt_tokens = 0
total_completion_tokens = 0
total_cached_tokens = 0
total_tokens_all = 0
total_usd = 0.0
session_costs_usd = []
session_costs_inr = []

print("=== PER-SESSION BREAKDOWN ===")
for idx, s in enumerate(data, 1):
    s_in = 0
    s_out = 0
    s_cached = 0
    s_tot = 0
    s_usd = 0.0
    
    turns = s.get("turn_telemetry", [])
    print(f"\n--- Session {idx}: {s['session_id']} | Task: {s['task_id']} | Turns: {len(turns)} ---")
    for t_idx, t in enumerate(turns, 1):
        inp = t.get("prompt_tokens") or 0
        out = t.get("completion_tokens") or 0
        cached = t.get("cached_tokens") or 0
        tot = t.get("total_tokens") or (inp + out)
        req_id = t.get("provider_request_id")
        
        # Exact cost calculation
        cost_usd = inp * RATE_IN + out * RATE_OUT
        cost_inr = cost_usd * FX_RATE
        
        s_in += inp
        s_out += out
        s_cached += cached
        s_tot += tot
        s_usd += cost_usd
        
        print(f"  Req {t_idx} [{req_id}]: prompt={inp}, comp={out}, cached={cached}, total={tot} | USD=${cost_usd:.8f}, INR={cost_inr:.8f}")
    
    s_inr = s_usd * FX_RATE
    session_costs_usd.append(s_usd)
    session_costs_inr.append(s_inr)
    total_prompt_tokens += s_in
    total_completion_tokens += s_out
    total_cached_tokens += s_cached
    total_tokens_all += s_tot
    total_usd += s_usd
    
    print(f"  Session Totals: prompt={s_in}, comp={s_out}, cached={s_cached}, total={s_tot}")
    print(f"  Recorded in JSON: USD={s.get('total_task_usd')}, INR={s.get('total_task_inr')}")
    print(f"  Exact Recalculated: USD=${s_usd:.8f}, INR={s_inr:.8f}")

total_inr = total_usd * FX_RATE
mean_usd = total_usd / len(data)
mean_inr = total_inr / len(data)
median_usd = statistics.median(session_costs_usd)
median_inr = statistics.median(session_costs_inr)

cache_hit_pct = (total_cached_tokens / total_prompt_tokens * 100) if total_prompt_tokens > 0 else 0.0

print("\n" + "="*60)
print("AGGREGATE FINANCIAL RECONCILIATION:")
print(f"Total Requests (Turns across 6 sessions): {sum(len(s.get('turn_telemetry', [])) for s in data)}")
print(f"Total Prompt Tokens: {total_prompt_tokens}")
print(f"Total Completion Tokens: {total_completion_tokens}")
print(f"Total Tokens: {total_tokens_all}")
print(f"Total Cached Prompt Tokens: {total_cached_tokens}")
print(f"Cache-Hit Ratio (cached / prompt): {cache_hit_pct:.4f}% ({total_cached_tokens} / {total_prompt_tokens})")
print(f"Total Expenditure (USD): ${total_usd:.8f}")
print(f"Total Expenditure (INR): ₹{total_inr:.8f}")
print(f"Mean Per-Attempt Expenditure (USD): ${mean_usd:.8f}")
print(f"Mean Per-Attempt Expenditure (INR): ₹{mean_inr:.8f}")
print(f"Median Per-Attempt Expenditure (USD): ${median_usd:.8f}")
print(f"Median Per-Attempt Expenditure (INR): ₹{median_inr:.8f}")
print("="*60)

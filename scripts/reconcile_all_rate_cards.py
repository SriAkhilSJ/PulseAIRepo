import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import json
import csv
from decimal import Decimal, ROUND_HALF_UP

FX_EFFECTIVE = Decimal("92.4801")

# Rate Cards ($ per 1M tokens -> Decimal per token)
# Rate Card A: Velona Conservative Uncached (Used in benchmark runner)
RCA_INPUT = Decimal("0.15") / Decimal("1000000")
RCA_CACHED = Decimal("0.15") / Decimal("1000000")  # 0% discount
RCA_OUTPUT = Decimal("0.50") / Decimal("1000000")

# Rate Card B: Velona Catalog Cached ($0.15 / $0.14377 / $0.50)
RCB_INPUT = Decimal("0.15") / Decimal("1000000")
RCB_CACHED = Decimal("0.14377") / Decimal("1000000")
RCB_OUTPUT = Decimal("0.50") / Decimal("1000000")

# Rate Card C: Upstream GLM-5 Direct ($0.14 / $0.028 / $0.28)
RCC_INPUT = Decimal("0.14") / Decimal("1000000")
RCC_CACHED = Decimal("0.028") / Decimal("1000000")
RCC_OUTPUT = Decimal("0.28") / Decimal("1000000")

with open('live_economics_ledger_phase931.json', 'r', encoding='utf-8') as f:
    sessions = json.load(f)

table_rows = []
tot_prompt = 0
tot_comp = 0
tot_cached = 0
tot_uncached = 0
tot_tokens = 0

tot_rca_usd = Decimal("0")
tot_rcb_usd = Decimal("0")
tot_rcc_usd = Decimal("0")

ledger_id = 1
for s_idx, s in enumerate(sessions):
    s_id = s.get("session_id")
    t_id = s.get("task_id")
    trial_idx = s.get("trial_index")
    for t in s.get("turn_telemetry", []):
        p = t.get("prompt_tokens", 0)
        c = t.get("completion_tokens", 0)
        ca = t.get("cached_tokens", 0) or 0
        cw = 0  # cache_write_tokens is null / 0
        uncached = p - ca - cw
        tot = t.get("total_tokens", 0)

        tot_prompt += p
        tot_comp += c
        tot_cached += ca
        tot_uncached += uncached
        tot_tokens += tot

        # Rate Card A cost
        cost_a_usd = (Decimal(p) * RCA_INPUT) + (Decimal(c) * RCA_OUTPUT)
        # Rate Card B cost
        cost_b_usd = (Decimal(uncached) * RCB_INPUT) + (Decimal(ca) * RCB_CACHED) + (Decimal(c) * RCB_OUTPUT)
        # Rate Card C cost
        cost_c_usd = (Decimal(uncached) * RCC_INPUT) + (Decimal(ca) * RCC_CACHED) + (Decimal(c) * RCC_OUTPUT)

        cost_a_inr = cost_a_usd * FX_EFFECTIVE
        cost_b_inr = cost_b_usd * FX_EFFECTIVE
        cost_c_inr = cost_c_usd * FX_EFFECTIVE

        tot_rca_usd += cost_a_usd
        tot_rcb_usd += cost_b_usd
        tot_rcc_usd += cost_c_usd

        row = {
            "ledger_id": f"LEDGER-931-{ledger_id:02d}",
            "session_id": s_id,
            "task_id": t_id,
            "trial_index": trial_idx,
            "turn_number": t.get("turn_number"),
            "provider_request_id": t.get("provider_request_id") or "UNKNOWN",
            "requested_model": t.get("requested_model"),
            "returned_model": t.get("returned_model"),
            "http_status": 200,
            "prompt_tokens": p,
            "completion_tokens": c,
            "cached_tokens": ca,
            "uncached_prompt_tokens": uncached,
            "cache_write_tokens": 0,
            "total_tokens": tot,
            "latency_ms": t.get("latency_ms"),
            "cost_rca_usd": float(cost_a_usd),
            "cost_rca_inr": float(cost_a_inr),
            "cost_rcb_usd": float(cost_b_usd),
            "cost_rcb_inr": float(cost_b_inr),
            "cost_rcc_usd": float(cost_c_usd),
            "cost_rcc_inr": float(cost_c_inr),
        }
        table_rows.append(row)
        ledger_id += 1

print(f"Total Rows: {len(table_rows)}")
print(f"Prompt Tokens: {tot_prompt}")
print(f"Completion Tokens: {tot_comp}")
print(f"Cached Tokens: {tot_cached} ({tot_cached/tot_prompt*100:.2f}%)")
print(f"Uncached Prompt Tokens: {tot_uncached}")
print(f"Total Tokens: {tot_tokens}")
print(f"Rate Card A (Velona Conservative): ${tot_rca_usd:.8f} USD | ₹{tot_rca_usd*FX_EFFECTIVE:.8f} INR")
print(f"Rate Card B (Velona Catalog Cached): ${tot_rcb_usd:.8f} USD | ₹{tot_rcb_usd*FX_EFFECTIVE:.8f} INR")
print(f"Rate Card C (Upstream GLM-5 Direct): ${tot_rcc_usd:.8f} USD | ₹{tot_rcc_usd*FX_EFFECTIVE:.8f} INR")

# Save rich reconciled ledger
with open("reconciled_phase931_request_ledger.json", "w", encoding="utf-8") as f:
    json.dump(table_rows, f, indent=2)

with open("reconciled_phase931_request_ledger.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(table_rows[0].keys()))
    writer.writeheader()
    writer.writerows(table_rows)

print("Saved reconciled_phase931_request_ledger.json and .csv")

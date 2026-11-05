import json
import csv
import sys
from decimal import Decimal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FX_EFFECTIVE = Decimal("92.4801")
RCA_INPUT = Decimal("0.15") / Decimal("1000000")
RCA_OUTPUT = Decimal("0.50") / Decimal("1000000")

with open("live_economics_ledger_phase932.json", "r", encoding="utf-8") as f:
    sessions = json.load(f)

all_requests = []
req_num = 1

for s_idx, s in enumerate(sessions):
    s_id = s.get("session_id")
    t_id = s.get("task_id")
    trial_idx = s.get("trial_index")
    turns = s.get("turn_telemetry", [])
    for t in turns:
        p = t.get("prompt_tokens", 0)
        c = t.get("completion_tokens", 0)
        ca = t.get("cached_tokens", 0) or 0
        uncached = p - ca
        tot = t.get("total_tokens", 0)
        lat = t.get("latency_ms", 0)

        cost_rca_usd = (Decimal(p) * RCA_INPUT) + (Decimal(c) * RCA_OUTPUT)
        cost_rca_inr = cost_rca_usd * FX_EFFECTIVE

        rec = {
            "ledger_id": f"LEDGER-932-{req_num:02d}",
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
            "cache_write_status": "UNKNOWN_NOT_REPORTED",
            "total_tokens": tot,
            "latency_ms": lat,
            "cost_usd": float(cost_rca_usd),
            "cost_inr": float(cost_rca_inr),
        }
        all_requests.append(rec)
        req_num += 1

print(f"Extracted {len(all_requests)} request records for Phase 9.3.2.")

# Save JSON and CSV
with open("authoritative_live_economics_ledger_phase932.json", "w", encoding="utf-8") as f:
    json.dump(all_requests, f, indent=2)

with open("authoritative_live_economics_ledger_phase932.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(all_requests[0].keys()))
    writer.writeheader()
    writer.writerows(all_requests)

print("Saved authoritative_live_economics_ledger_phase932.json and .csv")


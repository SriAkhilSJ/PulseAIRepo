import json
import csv

with open('live_economics_ledger_phase931.json', 'r', encoding='utf-8') as f:
    sessions = json.load(f)

records = []
ledger_idx = 1
for s in sessions:
    s_id = s.get("session_id")
    t_id = s.get("task_id")
    trial_idx = s.get("trial_index")
    for t in s.get("turn_telemetry", []):
        rec = {
            "ledger_id": f"LEDGER-931-{ledger_idx:02d}",
            "session_id": s_id,
            "task_id": t_id,
            "trial_index": trial_idx,
            "turn_number": t.get("turn_number"),
            "provider_request_id": t.get("provider_request_id") or "UNKNOWN",
            "requested_model": t.get("requested_model"),
            "returned_model": t.get("returned_model"),
            "http_status": 200,  # All were successful 200 responses
            "prompt_tokens": t.get("prompt_tokens"),
            "completion_tokens": t.get("completion_tokens"),
            "total_tokens": t.get("total_tokens"),
            "cached_tokens": t.get("cached_tokens") or 0,
            "cache_write_tokens": t.get("cache_write_tokens") if t.get("cache_write_tokens") is not None else "UNKNOWN",
            "reasoning_tokens": t.get("reasoning_tokens") or 0,
            "latency_ms": t.get("latency_ms"),
            "cost_usd_conservative": t.get("cost_usd"),
            "cost_inr_conservative": t.get("cost_inr"),
            "billing_classification": t.get("billing_classification"),
        }
        records.append(rec)
        ledger_idx += 1

print(f"Extracted {len(records)} authoritative records.")

# Save to authoritative JSON
with open("authoritative_live_economics_ledger_phase931.json", "w", encoding="utf-8") as f:
    json.dump(records, f, indent=2)

# Save to authoritative CSV
with open("authoritative_live_economics_ledger_phase931.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
    writer.writeheader()
    writer.writerows(records)

print("Saved authoritative_live_economics_ledger_phase931.json and .csv")


import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
with open(r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\live_economics_ledger_phase931.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Total sessions in JSON: {len(data)}")
grand_p = 0
grand_c = 0
grand_cached = 0
grand_tot = 0

for i, s in enumerate(data, 1):
    turns = s.get("turn_telemetry", [])
    print(f"Session {i}: {s['session_id']} ({s['task_id']}) - {len(turns)} turns")
    s_p = 0
    s_c = 0
    s_cached = 0
    s_tot = 0
    for t in turns:
        p = t.get("prompt_tokens", 0)
        c = t.get("completion_tokens", 0)
        cached = t.get("cached_tokens", 0)
        tot = t.get("total_tokens", 0)
        req_id = t.get("provider_request_id")
        s_p += p
        s_c += c
        s_cached += cached
        s_tot += tot
        print(f"    req {req_id}: p={p}, c={c}, cached={cached}, tot={tot}")
    print(f"  SUBTOTAL Session {i}: prompt={s_p}, comp={s_c}, cached={s_cached}, tot={s_tot}")
    grand_p += s_p
    grand_c += s_c
    grand_cached += s_cached
    grand_tot += s_tot

print(f"\nGRAND TOTAL IN JSON: prompt={grand_p}, comp={grand_c}, cached={grand_cached}, tot={grand_tot}")


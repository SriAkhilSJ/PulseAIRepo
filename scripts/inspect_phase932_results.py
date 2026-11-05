import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

with open("live_economics_ledger_phase932.json", "r", encoding="utf-8") as f:
    sessions = json.load(f)

print(f"Total sessions: {len(sessions)}")
tot_turns = 0
tot_prompt = 0
tot_comp = 0
tot_cached = 0
tot_cost_usd = 0.0
tot_cost_inr = 0.0

for i, s in enumerate(sessions):
    turns = s.get("turn_telemetry", [])
    tot_turns += len(turns)
    p = sum(t["prompt_tokens"] for t in turns)
    c = sum(t["completion_tokens"] for t in turns)
    ca = sum(t.get("cached_tokens", 0) or 0 for t in turns)
    tot_prompt += p
    tot_comp += c
    tot_cached += ca
    tot_cost_usd += s["total_task_usd"]
    tot_cost_inr += s["total_task_inr"]
    s_id = s.get("session_id")
    t_id = s.get("task_id")
    passed = s.get("verification_passed")
    inr = s.get("total_task_inr")
    reason = s.get("verification_reason")
    print(f"\nSession {i+1} [{s_id}] ({t_id}):")
    print(f"  Turns: {len(turns)} | Passed: {passed} | Spend: ₹{inr:.4f} INR")
    print(f"  Reason: {reason[:120]}")
    print(f"  Final response length: {len(s.get('final_response', ''))}")
    if len(s.get("final_response", "")) > 0:
        print(f"  Final response preview: {repr(s.get('final_response', '')[:150])}")
    for t_idx, t in enumerate(turns):
        print(f"    Turn {t.get('turn_number')}: req_id={t.get('provider_request_id')} | p={t.get('prompt_tokens')} | c={t.get('completion_tokens')} | ca={t.get('cached_tokens')} | lat={t.get('latency_ms')}ms")

print(f"\n========================================================")
print(f"Total Turns: {tot_turns}")
print(f"Total Prompt: {tot_prompt}")
print(f"Total Completion: {tot_comp}")
print(f"Total Cached: {tot_cached} ({tot_cached/tot_prompt*100:.2f}%)")
print(f"Total Tokens: {tot_prompt + tot_comp}")
print(f"Total Cost USD: ${tot_cost_usd:.8f}")
print(f"Total Cost INR: ₹{tot_cost_inr:.8f}")
print(f"========================================================")


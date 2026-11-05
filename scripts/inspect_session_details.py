import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8")
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ledger_path = os.path.join(repo_root, "live_economics_ledger_phase931.json")
with open(ledger_path, "r", encoding="utf-8") as f:
    data = json.load(f)

for i, s in enumerate(data):
    print(f"=== SESSION {i+1}: {s.get('session_id')} | {s.get('task_id')} | verified: {s.get('verification_passed')} ===")
    print("Reason:", s.get('verification_reason'))
    print("Turns:", s.get('turns_count'))
    print("Total INR:", s.get('total_task_inr'), "Total USD:", s.get('total_task_usd'))
    print("Final response snippet:", repr(s.get('final_response', '')[:200]))
    for t in s.get('turn_telemetry', []):
        print(f"  turn {t.get('turn')}: tool_calls={t.get('tool_calls')} in={t.get('input_tokens')} out={t.get('output_tokens')} cost_inr={t.get('cost_inr')}")

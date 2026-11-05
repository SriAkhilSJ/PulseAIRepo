import json

with open('live_economics_ledger_phase931.json', 'r', encoding='utf-8') as f:
    sessions = json.load(f)

for i, s in enumerate(sessions):
    turns = s['turn_telemetry']
    p = sum(t['prompt_tokens'] for t in turns)
    c = sum(t['completion_tokens'] for t in turns)
    ca = sum(t['cached_tokens'] for t in turns)
    tot = sum(t['total_tokens'] for t in turns)
    cost = sum(t['cost_usd'] for t in turns)
    cost_inr = sum(t['cost_inr'] for t in turns)
    s_id = s.get("session_id")
    print(f"Session {i+1} ({s_id}):")
    print(f"  Turns: {len(turns)}, Prompt: {p}, Comp: {c}, Cached: {ca}, Total: {tot}, USD: {cost:.8f}, INR: {cost_inr:.8f}")


import json

with open('live_economics_ledger_phase931.json', 'r') as f:
    sessions = json.load(f)

total_turns = 0
all_turns = []
print(f"Total sessions: {len(sessions)}")
for s_idx, s in enumerate(sessions):
    turns = s.get('turn_telemetry', [])
    print(f"Session {s_idx+1}: {s.get('session_id')} | task={s.get('task_id')} | turns_count={s.get('turns_count')} | telemetry_turns={len(turns)}")
    total_turns += len(turns)
    for t_idx, t in enumerate(turns):
        all_turns.append(t)
        print(f"  Turn {t.get('turn_number')}: req_id={t.get('provider_request_id')} | prompt={t.get('prompt_tokens')} | comp={t.get('completion_tokens')} | cached={t.get('cached_tokens')} | total={t.get('total_tokens')} | cost_usd={t.get('cost_usd')}")

print(f"\nTotal turns across all sessions: {total_turns}")

# Sum of all turns in raw JSON:
p_sum = sum(t.get('prompt_tokens', 0) for t in all_turns)
c_sum = sum(t.get('completion_tokens', 0) for t in all_turns)
cached_sum = sum(t.get('cached_tokens', 0) for t in all_turns)
total_sum = sum(t.get('total_tokens', 0) for t in all_turns)
usd_sum = sum(t.get('cost_usd', 0) for t in all_turns)
inr_sum = sum(t.get('cost_inr', 0) for t in all_turns)

print(f"\nRaw JSON Aggregates (all {len(all_turns)} turns):")
print(f"Prompt Tokens: {p_sum}")
print(f"Completion Tokens: {c_sum}")
print(f"Cached Tokens: {cached_sum}")
print(f"Total Tokens: {total_sum}")
print(f"Total Cost USD: {usd_sum:.8f}")
print(f"Total Cost INR: {inr_sum:.8f}")


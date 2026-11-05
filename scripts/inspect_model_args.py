import json

with open("live_economics_ledger_phase931.json", "r", encoding="utf-8") as f:
    sessions = json.load(f)

for s in sessions:
    if s["task_id"] == "task-2-bug-correction":
        print(f"\n=================== Session: {s['session_id']} (Trial {s['trial_index']}) ===================")
        # Check messages or requests
        # In run_agent_task, messages weren't saved in json, but let's check what was logged
        print("Turns count:", s["turns_count"])
        print("Final response:", s["final_response"])


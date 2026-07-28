import json
import os

# Try to use nonexistent_29e4_json; fall back if unavailable
json_path = "nonexistent_29e4_json"
if os.path.exists(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)
    source = "nonexistent_29e4_json"
else:
    data = {"status": "working", "fallback": True}
    source = "fallback (nonexistent_29e4_json unavailable)"

with open("replan_output.json", "w") as f:
    json.dump(data, f)

print(f"done (source: {source})")
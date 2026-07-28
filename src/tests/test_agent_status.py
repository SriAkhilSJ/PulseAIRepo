from src.agents.agent_status import build_agent_status


state = {
    "current_task": "Fix the runtime error",

    "plan": [
        {
            "id": 1,
            "description": "Inspect the file",
            "status": "completed",
        },
        {
            "id": 2,
            "description": "Fix the error",
            "status": "in_progress",
        },
        {
            "id": 3,
            "description": "Verify the fix",
            "status": "pending",
        },
    ],

    "execution_trace": [
        {
            "type": "tool",
            "tool": "read_file",
            "args": {
                "path": "generated/test.py",
            },
            "status": "success",
            "result": "file contents",
        },
        {
            "type": "tool",
            "tool": "run_terminal",
            "args": {
                "command": "python generated/test.py",
            },
            "status": "failed",
            "result": "ZeroDivisionError",
        },
    ],

    "failed_steps": [
        "Command failed: python generated/test.py"
    ],

    "recovery_mode": True,
    "recovery_attempts": 1,

    "replan_needed": False,
    "replan_count": 0,
}


snapshot = build_agent_status(state)


print("\n=== AGENT STATUS ===")

print("Task:", snapshot["task"])
print("Status:", snapshot["status"])

print(
    "Plan:",
    snapshot["plan"]["completed"],
    "/",
    snapshot["plan"]["total"],
)

print(
    "Active step:",
    snapshot["plan"]["active_step"],
)

print(
    "Last action:",
    snapshot["last_action"],
)

print(
    "Recovery:",
    snapshot["recovery"],
)

print(
    "Replan:",
    snapshot["replan"],
)

print(
    "Failures:",
    snapshot["failures"],
)

print(
    "Trace count:",
    snapshot["trace_count"],
)


assert snapshot["task"] == (
    "Fix the runtime error"
)

assert snapshot["status"] == "recovering"

assert snapshot["plan"]["total"] == 3
assert snapshot["plan"]["completed"] == 1

assert (
    snapshot["plan"]["active_step"]["id"]
    == 2
)

assert (
    snapshot["last_action"]["tool"]
    == "run_terminal"
)

assert (
    snapshot["last_action"]["status"]
    == "failed"
)

assert snapshot["recovery"]["active"] is True
assert snapshot["recovery"]["attempts"] == 1

assert snapshot["replan"]["count"] == 0

assert snapshot["failures"]["count"] == 1

assert snapshot["trace_count"] == 2


print("\nAGENT STATUS TEST PASSED")

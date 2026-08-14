from pathlib import Path

from src.graphs.chat_graph import (
    get_agent_status,
    invoke_agent,
)
from src.config.settings import (
    LLM_MODEL,
    LLM_PROVIDER,
)


TARGET = Path(
    "generated/status_checkpoint_test.py"
)

THREAD_ID = "agent-status-checkpoint-test"


# Start clean.
TARGET.parent.mkdir(
    parents=True,
    exist_ok=True,
)

if TARGET.exists():
    TARGET.unlink()


print("\n=== RUN REAL AGENT ===")

response = invoke_agent(
    message=(
        "Create generated/status_checkpoint_test.py "
        "that prints STATUS CHECKPOINT WORKS. "
        "Run it and verify the output."
    ),
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="agent",
)

print(response)


print("\n=== READ CHECKPOINT STATUS ===")

status = get_agent_status(
    thread_id=THREAD_ID,
)

print("Task:", status["task"])
print("Status:", status["status"])

print(
    "Plan:",
    status["plan"]["completed"],
    "/",
    status["plan"]["total"],
)

assert status["status"] == "completed", (
    "Successfully finished task was not marked completed."
)

assert (
    status["plan"]["completed"]
    == status["plan"]["total"]
), (
    "Completed task left unfinished plan steps."
)

print(
    "Last action:",
    status["last_action"],
)

print(
    "Recovery:",
    status["recovery"],
)

print(
    "Replan:",
    status["replan"],
)

print(
    "Trace count:",
    status["trace_count"],
)


print("\n=== VERIFY ===")

assert TARGET.exists(), (
    "Agent did not create the target file."
)

assert status["task"], (
    "Checkpoint did not preserve current_task."
)

assert status["trace_count"] > 0, (
    "Checkpoint did not preserve execution_trace."
)

assert status["last_action"] is not None, (
    "Checkpoint has no last tool action."
)

assert status["last_action"]["status"] == "success", (
    "Last recorded action was not successful."
)

assert status["recovery"]["active"] is False, (
    "Agent remained in recovery mode after success."
)

assert status["status"] == "completed", (
    "Successfully finished task was not marked completed."
)

assert (
    status["plan"]["completed"]
    == status["plan"]["total"]
), (
    "Completed task left unfinished plan steps."
)


print("\nAGENT CHECKPOINT STATUS TEST PASSED")

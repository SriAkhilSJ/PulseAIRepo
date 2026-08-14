from pathlib import Path

from src.graphs.chat_graph import (
    get_agent_status,
    invoke_agent,
)
from src.config.settings import LLM_PROVIDER, LLM_MODEL


TARGET = Path("generated/cancel_test.py")
THREAD_ID = "plan-cancel-test"


if TARGET.exists():
    TARGET.unlink()


print("\n=== 1. CREATE PLAN ===")

response = invoke_agent(
    message=(
        "Create generated/cancel_test.py that prints "
        "'SHOULD NOT RUN'. Run it and verify."
    ),
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="plan",
)

print(response)

assert not TARGET.exists()
print("File after planning:", TARGET.exists())


print("\n=== 2. CANCEL PLAN ===")

response = invoke_agent(
    message="cancel",
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="plan",
)

print(response)

status = get_agent_status(thread_id=THREAD_ID)
assert status["task"] == "", (
    "Cancelled plan should clear the active task."
)
assert status["status"] == "idle", (
    "Cancelled plan should not leave the agent in an active state."
)

assert not TARGET.exists()
print("File after cancellation:", TARGET.exists())


print("\n=== 3. TRY APPROVAL AFTER CANCEL ===")

response = invoke_agent(
    message="approve",
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="agent",
)

print(response)

assert not TARGET.exists(), (
    "Cancelled plan was resurrected by approval."
)

print("File after approval attempt:", TARGET.exists())

print("\nPLAN CANCELLATION TEST PASSED")

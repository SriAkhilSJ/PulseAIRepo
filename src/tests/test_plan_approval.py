from pathlib import Path

from src.graphs.chat_graph import invoke_agent
from src.config.settings import LLM_PROVIDER, LLM_MODEL


TARGET = Path("generated/approved_plan_test.py")
THREAD_ID = "plan-approval-test"


# Start clean.
if TARGET.exists():
    TARGET.unlink()


print("\n=== 1. PLAN MODE ===")

plan_response = invoke_agent(
    message=(
        "Create generated/approved_plan_test.py "
        "that prints 'APPROVED PLAN WORKS'. "
        "Run it and verify the output."
    ),
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="plan",
)

print(plan_response)


# Planning must NOT modify the filesystem.
assert not TARGET.exists(), (
    "Plan Mode executed tools before approval."
)

print("\nFile after planning:", TARGET.exists())


print("\n=== 2. APPROVE PLAN ===")

approval_response = invoke_agent(
    message="approve",
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="agent",
)

print(approval_response)


print("\n=== 3. VERIFY EXECUTION ===")

assert TARGET.exists(), (
    "Approved plan did not create the expected file."
)

content = TARGET.read_text(
    encoding="utf-8"
)

print("File exists:", TARGET.exists())
print("File content:")
print(content)


assert "APPROVED PLAN WORKS" in content, (
    "Generated file does not contain expected code."
)


print("\nPLAN APPROVAL TEST PASSED")
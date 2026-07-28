from pathlib import Path

from src.graphs.chat_graph import invoke_agent
from src.config.settings import LLM_PROVIDER, LLM_MODEL


TARGET = Path("generated/revision_test.py")
THREAD_ID = "plan-revision-test"


# Start clean.
if TARGET.exists():
    TARGET.unlink()


print("\n=== 1. CREATE ORIGINAL PLAN ===")

original = invoke_agent(
    message=(
        "Create generated/revision_test.py that prints "
        "'ORIGINAL PLAN'. Run it and verify."
    ),
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="plan",
)

print(original)

assert not TARGET.exists(), (
    "Plan Mode executed before approval."
)

print("File after original plan:", TARGET.exists())


print("\n=== 2. REVISE PLAN ===")

revised = invoke_agent(
    message=(
        "Change the plan so the script prints "
        "'REVISED PLAN WORKS' instead."
    ),
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="plan",
)

print(revised)

# Revision must still be preview-only.
assert not TARGET.exists(), (
    "Plan revision executed tools before approval."
)

assert "REVISED PLAN WORKS" in revised.upper(), (
    "Revised plan does not reflect the requested change."
)

print("File after revision:", TARGET.exists())


print("\n=== 3. APPROVE REVISED PLAN ===")

approved = invoke_agent(
    message="approve",
    thread_id=THREAD_ID,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    workspace=".",
    execution_mode="agent",
)

print(approved)


print("\n=== 4. VERIFY ===")

assert TARGET.exists(), (
    "Approved revised plan did not create the file."
)

content = TARGET.read_text(
    encoding="utf-8"
)

print("File exists:", TARGET.exists())
print("File content:")
print(content)

assert "REVISED PLAN WORKS" in content, (
    "Agent executed the original plan instead "
    "of the revised plan."
)

assert "ORIGINAL PLAN" not in content, (
    "Original plan content survived after revision."
)


print("\nPLAN REVISION TEST PASSED")
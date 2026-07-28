from src.agents.planner import should_replan, create_replan
from src.config.settings import LLM_PROVIDER, LLM_MODEL


task = (
    "Build a report from a remote API and save the result locally."
)

current_plan = [
    {
        "id": 1,
        "description": "Fetch the required data from the remote API.",
        "status": "in_progress",
    },
    {
        "id": 2,
        "description": "Process the API response.",
        "status": "pending",
    },
    {
        "id": 3,
        "description": "Save the processed report.",
        "status": "pending",
    },
]

failure = (
    "The required remote API is permanently unavailable in this "
    "environment. The task must use locally available data instead."
)


print("\n=== SHOULD REPLAN ===")

needs_replan = should_replan(
    task=task,
    plan=current_plan,
    failure=failure,
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
)

print("Decision:", needs_replan)

assert needs_replan is True, (
    "Expected should_replan() to return True"
)


print("\n=== CREATE REPLAN ===")

new_plan = create_replan(
    task=task,
    plan=current_plan,
    failed_steps=[failure],
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
)

print(new_plan.model_dump_json(indent=2))

assert new_plan.steps, "Replanner returned no steps"

print("\nREPLANNER TEST PASSED")
from src.graphs.chat_graph import (
    after_progress,
    replanner_node,
)

from src.config.settings import (
    LLM_PROVIDER,
    LLM_MODEL,
)


state = {
    "current_task": (
        "Build a report from a remote API "
        "and save it locally."
    ),

    "plan": [
        {
            "id": 1,
            "description": (
                "Fetch the required data "
                "from the remote API."
            ),
            "status": "in_progress",
        },
        {
            "id": 2,
            "description": "Process the API response.",
            "status": "pending",
        },
        {
            "id": 3,
            "description": "Save the report.",
            "status": "pending",
        },
    ],

    "failed_steps": [
        (
            "The required remote API is permanently "
            "unavailable. Use locally available data instead."
        )
    ],

    "replan_needed": True,
    "replan_count": 0,
    "recovery_attempts": 1,
    "recovery_mode": True,
}


config = {
    "configurable": {
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
        "thread_id": "replan-graph-test",
        "workspace": ".",
    }
}


print("\n=== ROUTING TEST ===")

route = after_progress(state)

print("Route:", route)

assert route == "replanner", (
    f"Expected 'replanner', got {route!r}"
)


print("\n=== REPLANNER NODE TEST ===")

result = replanner_node(
    state,
    config,
)

print("Replan count:", result["replan_count"])
print("Replan needed:", result["replan_needed"])

assert result["replan_count"] == 1, (
    "Expected replan_count to become 1"
)

assert result["replan_needed"] is False, (
    "Expected replan_needed to reset to False"
)

new_plan = result["plan"]

assert new_plan, "Expected a new plan"

print("\n=== NEW PLAN ===")

for step in new_plan:
    print(
        f"{step['id']}. "
        f"[{step['status']}] "
        f"{step['description']}"
    )


# The new plan should contain exactly one active step.
in_progress = [
    step
    for step in new_plan
    if step["status"] == "in_progress"
]

assert len(in_progress) == 1, (
    "Expected exactly one in_progress step"
)


# Make sure the replanner changed strategy.
plan_text = " ".join(
    step["description"].lower()
    for step in new_plan
)

assert (
    "local" in plan_text
    or "file" in plan_text
    or "available data" in plan_text
), "Expected revised plan to use a local-data strategy"


print("\nREPLAN GRAPH TEST PASSED")
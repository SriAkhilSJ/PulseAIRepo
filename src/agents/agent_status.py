from typing import Any


def build_agent_status(
    state: dict[str, Any],
    memory_count: int = 0,
) -> dict[str, Any]:
    """Build a read-only snapshot of the current agent state."""

    plan = state.get("plan") or []
    trace = state.get("execution_trace") or []

    active_step = next(
        (
            step
            for step in plan
            if step.get("status") == "in_progress"
        ),
        None,
    )

    completed_steps = sum(
        1
        for step in plan
        if step.get("status") == "completed"
    )

    failed_steps = state.get("failed_steps") or []

    last_action = trace[-1] if trace else None

    # Determine high-level task status.
    if state.get("replan_needed"):
        status = "replanning"

    elif state.get("recovery_mode"):
        status = "recovering"

    elif state.get("task_completed"):
        status = "completed"

    elif active_step:
        status = "in_progress"

    elif plan:
        status = "planned"

    elif state.get("current_task"):
        status = "in_progress"

    else:
        status = "idle"

    return {
        "task": state.get("current_task"),
        "status": status,

        "plan": {
            "total": len(plan),
            "completed": completed_steps,
            "active_step": active_step,
            "steps": plan,
        },

        "last_action": last_action,

        "recovery": {
            "active": bool(
                state.get("recovery_mode")
            ),
            "attempts": state.get(
                "recovery_attempts",
                0,
            ),
            "limit": 3,
        },

        "replan": {
            "needed": bool(
                state.get("replan_needed")
            ),
            "count": state.get(
                "replan_count",
                0,
            ),
            "limit": 2,
        },

        "failures": {
            "count": len(failed_steps),
            "latest": (
                failed_steps[-1]
                if failed_steps
                else None
            ),
        },

        "trace_count": len(trace),

        "memory": {
            "stored_memories": memory_count,
        },

        "cost": state.get("token_usage", {}),
    }

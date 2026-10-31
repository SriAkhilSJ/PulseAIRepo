"""
progress_guard.py - Progress-Aware Loop Detection Engine.

Pillar 2 of the Hardened Production Architecture.
Replaces brittle frequency counters with multi-vector state-delta tracking:
Loop Condition = (Op Repeated >= 3) and (Delta Revision == 0) and (Delta Debt == 0) and (Delta Information == 0)
"""

from __future__ import annotations

from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.runtime.run_state_ledger import AgentRunState


def evaluate_operation_progress(
    state: AgentRunState, tool_name: str, target: str
) -> Optional[Dict[str, Any]]:
    """Intercepts execution only when repetitive calls yield zero progress."""
    if state is None:
        return None

    # Inspect the trailing window of operations
    recent = state.execution_history[-8:]
    normalized_target = str(target or "").strip().lower()

    matches = [
        r
        for r in recent
        if r.tool_name == tool_name
        and str(r.target or "").strip().lower() == normalized_target
    ]

    if len(matches) >= 3:
        has_mutation = any(r.state_mutated for r in matches)
        has_new_info = any(r.new_information_provided for r in matches)

        # Loop detected if no mutation occurred and no new diagnostic entropy / data was provided
        if not has_mutation and not has_new_info:
            return {
                "status": "loop_detected",
                "tool": tool_name,
                "target": target,
                "count": len(matches),
                "reason": (
                    f"Tool '{tool_name}' on '{target}' executed {len(matches)} times "
                    f"without modifying workspace state or discovering new information."
                ),
                "required_action": (
                    "Switch strategy immediately: apply targeted file edits, execute "
                    "verification tests, or synthesize final deliverables."
                ),
            }

    # Also detect general stagnation: 6+ actions anywhere with zero mutation or info
    if state.actions_since_last_progress >= 6:
        return {
            "status": "stagnation_detected",
            "tool": tool_name,
            "target": target,
            "count": state.actions_since_last_progress,
            "reason": (
                f"Agent has taken {state.actions_since_last_progress} consecutive actions "
                f"without mutating project state or resolving verification debt."
            ),
            "required_action": (
                "Transition from exploration to implementation: edit files or run tests."
            ),
        }

    # Detect Inspection Sprawl / Procrastination Loop (SWE-agent & Devin parity)
    # When code has already been written, prevent the agent from getting trapped in
    # endless read/search loops instead of advancing to server entrypoint and frontend.
    recent_tools = [r.tool_name for r in state.execution_history[-5:]]
    inspection_tools = {"search_files", "read_file", "list_files", "execute_code"}
    if (
        len(recent_tools) >= 5
        and all(t in inspection_tools for t in recent_tools)
        and state.current_revision >= 2
    ):
        return {
            "status": "inspection_sprawl_detected",
            "tool": tool_name,
            "target": target,
            "count": len(recent_tools),
            "reason": (
                "Inspection sprawl detected: 5 consecutive read/search calls executed "
                "after code has already been scaffolded. Stop searching internal symbols."
            ),
            "required_action": (
                "Advance to the next milestone immediately: write the runnable server "
                "entrypoint (server.py / app.py), scaffold the frontend UI, or run tests."
            ),
        }

    return None

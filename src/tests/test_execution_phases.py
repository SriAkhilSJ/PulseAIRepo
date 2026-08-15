from src.runtime.execution_phases import derive_execution_phase, filter_tool_names
from src.agents.planner import required_tool_receipts
from src.graphs.budget import _budget_exhausted


def _state(description: str):
    return {"plan": [{"description": description, "status": "in_progress"}]}


def test_setup_phase_hides_inspection_tools():
    phase = derive_execution_phase(_state("Scaffold a fresh Next.js project"))
    assert phase.name == "setup"
    names = filter_tool_names(
        ["think", "read_file", "list_files", "scaffold_nextjs", "ask_user"], phase
    )
    assert names == ["scaffold_nextjs", "ask_user"]


def test_delivery_phase_exposes_only_mutations_and_bounds_batch():
    phase = derive_execution_phase(_state(
        "Create `src/a.tsx` and `src/b.tsx` reusable components"
    ))
    assert phase.name == "deliver"
    assert phase.max_file_mutations_per_turn == 2
    names = filter_tool_names(
        ["think", "read_file", "run_terminal", "write_file", "edit_file", "copy_file"],
        phase,
    )
    assert names == ["write_file", "edit_file", "copy_file"]


def test_static_phase_allows_diagnostic_repair_not_scaffold():
    phase = derive_execution_phase(_state("Run typecheck and fix every error"))
    assert phase.name == "static_verify"
    names = filter_tool_names(
        ["scaffold_nextjs", "typecheck_workspace", "read_file", "edit_file"], phase
    )
    assert names == ["typecheck_workspace", "read_file", "edit_file"]


def test_visual_phase_prefers_composite_but_keeps_targeted_repair_tools():
    phase = derive_execution_phase(_state("Verify four browser routes and screenshots"))
    assert phase.name == "visual_verify"
    names = filter_tool_names(
        ["verify_ui_routes", "browser_snapshot", "read_file", "edit_file", "scaffold_nextjs"],
        phase,
    )
    assert names == ["verify_ui_routes", "browser_snapshot", "read_file", "edit_file"]


def test_named_multi_file_step_requires_each_mutation_receipt():
    req = required_tool_receipts(
        "Create `src/a.tsx`, `src/b.tsx`, `src/c.css`, and `src/d.ts`"
    )
    assert req["__file_mutation__"] == 4


def test_turn_token_budget_does_not_use_cumulative_session_usage(monkeypatch):
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "10000")
    state = {
        "iteration_used": 0,
        "token_usage": {"total_tokens": 500000},
        "turn_token_usage": {"total_tokens": 9000},
    }
    assert _budget_exhausted(state) is False
    state["turn_token_usage"]["total_tokens"] = 10000
    assert _budget_exhausted(state) is True

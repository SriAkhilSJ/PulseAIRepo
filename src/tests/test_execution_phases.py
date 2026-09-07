"""Execution-phase contracts: guidance and budgets, NEVER tool amputation.

Hermes source of truth: the 288-run core_tool_deferral battery (PR #97979)
— hiding tools from the model is a loss, not focus — plus the pulse field
proof 2026-09-07 (build 9756690d): a "do browser testing" turn died because
a plan step reading "Run the build..." stripped the browser tools and
todo_list mid-turn. The former keyword allowlist filters are gone; phases
steer through guidance text and mutation budgets only.
"""
from __future__ import annotations

import pytest

from src.runtime.execution_phases import ExecutionPhase, derive_execution_phase


def _state(description: str):
    return {"plan": [{"description": description, "status": "in_progress"}]}


# ---------------------------------------------------------------------------
# The core contract: keyword phases NEVER hide tools (allowed is None)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description,expected_phase", [
    ("Verify four browser routes and screenshots", "visual_verify"),
    ("Run typecheck and fix every error", "static_verify"),
    ("Run the build to ensure no errors", "static_verify"),
    ("Scaffold a fresh Next.js project", "setup"),
    ("Install dependencies", "setup"),
    ("Create `src/a.tsx` and `src/b.tsx` reusable components", "deliver"),
])
def test_keyword_phases_carry_guidance_but_never_an_allowlist(description, expected_phase):
    """FIELD REGRESSION 2026-09-07: the old phases stripped browser tools and
    todo_list based on these words. allowed=None is the no-amputation pin —
    binding and the tool node both treat None as no policy."""
    phase = derive_execution_phase(_state(description))
    assert phase.name == expected_phase
    assert phase.allowed is None
    assert phase.guidance, "the nudge is the whole point"


def test_browser_task_with_a_build_step_in_progress_keeps_browser_tools():
    """The exact field shape: task 'browser testing', active step 'Run the
    build to ensure no errors'. The phase may SAY build-first; it may not
    take the browser away."""
    state = {
        "current_task": "test2 folder plz do browser testing",
        "plan": [{"description": "Run the build to ensure no errors", "status": "in_progress"}],
    }
    phase = derive_execution_phase(state)
    assert phase.name == "static_verify"
    assert phase.allowed is None
    # guidance still steers toward the eventual browser proof
    assert "browser" in phase.guidance.lower()


def test_no_active_step_is_general_with_no_policy():
    phase = derive_execution_phase({"plan": []})
    assert phase.name == "general"
    assert phase.allowed is None
    assert phase.guidance == ""


def test_guidance_env_off_returns_general(monkeypatch):
    monkeypatch.setenv("PULSEAI_PHASE_GUIDANCE", "off")
    phase = derive_execution_phase(_state("Run the build"))
    assert phase.name == "general"
    assert phase.allowed is None


def test_phase_env_rename_is_the_only_knob():
    """The old PULSEAI_PHASE_GUARD guarded tools; the surviving knob gates
    guidance only. Architecture pin: the old name must not linger."""
    import inspect
    from src.runtime import execution_phases as ep
    source = inspect.getsource(ep)
    assert "PULSEAI_PHASE_GUARD" not in source
    assert "PULSEAI_PHASE_GUIDANCE" in source
    # the retired amputation machinery stays dead
    assert not hasattr(ep, "filter_tool_names")
    assert not hasattr(ep, "phase_allows")
    assert "browser_select" not in source, "retired puppeteer-era ghost names"


# ---------------------------------------------------------------------------
# Budgets survive (they bound mutations; they hide nothing)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description", [
    ("Create `src/a.tsx` and `src/b.tsx` reusable components"),
    ("Verify four browser routes and screenshots"),
    ("Run typecheck and fix every error"),
])
def test_mutation_budgets_still_apply(description):
    phase = derive_execution_phase(_state(description))
    assert phase.max_file_mutations_per_turn == 2


# ---------------------------------------------------------------------------
# chat_graph binding: the phase object flows, the tools survive
# ---------------------------------------------------------------------------

def test_resolve_bound_tools_never_strips_for_plan_words(tmp_path):
    """End-to-end through the graph's real binding: a browser-testing task
    whose active step says 'build' must still bind the browser tools AND the
    planning tools (todo_list) — the field turn lost both."""
    from src.graphs.chat_graph import _resolve_bound_tools

    state = {
        "current_task": "test2 folder plz do browser testing",
        "plan": [{"description": "Run the build to ensure no errors", "status": "in_progress"}],
    }
    config = {"configurable": {
        "thread_id": "field-regression",
        "workspace": str(tmp_path),  # no tsconfig -> typecheck hidden, unrelated
    }}
    bound = _resolve_bound_tools(state, config)
    names = {t.name for t in bound}
    assert "browser_navigate" in names
    assert "browser_screenshot" in names
    assert "todo_list" in names
    assert "think" in names
    # the guidance still rode into the config for the system prompt
    assert config["configurable"]["execution_phase"] == "static_verify"
    assert "browser" in str(config["configurable"]["phase_guidance"]).lower()
    # and no execution-time policy may deny them either
    assert config["configurable"]["phase_allowed_tools"] is None


def test_state_driven_forced_delivery_phase_keeps_its_allowlist(tmp_path, monkeypatch):
    """The two STATE-driven phases (empty autonomous workspace, verification
    reserve) keep their enforcement — they key on state, not step words."""
    from src.graphs.chat_graph import _resolve_bound_tools

    monkeypatch.setenv("PULSEAI_MEMORY", "OFF")
    state = {
        "current_task": "build me a landing page app",
        "plan": [],
        # an effectively-empty workspace with a file-delivery requirement
        "latest_instruction": "build me a landing page app",
    }
    config = {"configurable": {
        "thread_id": "autonomous-regression",
        "workspace": str(tmp_path),
        "approval_policy": "workspace_session",  # autonomous surface
    }}
    bound = _resolve_bound_tools(state, config)
    names = {t.name for t in bound}
    # the forced-delivery phase may narrow to delivery tools (state-driven)
    assert config["configurable"]["execution_phase"] in {"forced_delivery", "general"}
    if config["configurable"]["execution_phase"] == "forced_delivery":
        assert names <= {"write_file", "edit_file", "copy_file"}

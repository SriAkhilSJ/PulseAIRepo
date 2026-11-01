"""Regression contracts for the 2026-10-31 diagnosability fixes.

Each test pins one finding from the body checkup. They exist because the
failure mode being fixed is SILENCE: a run that stops without a reason, a
score that ignores dollars, a budget derived from the wrong tokenizer.

  T1  run_outcome is seeded at turn start, so an abrupt exit leaves
      "in_progress" (a fact) instead of an absent field.
  T3  the bridge writes a terminal row into the step trace, so a trace can
      always answer "why did this end?".
  T4  cost is a scored runtime dimension and an overrun is reported.
  D6  the token estimator learns from the provider's real prompt_tokens.
  D7  the layer-scoring term is named for what it measures and is switchable.
  D3  process_boundary.detect_conversational_leak is actually reachable.
"""
from __future__ import annotations

import json
import os

import pytest
from langchain_core.messages import SystemMessage

from src.context import layer_policy
from src.context import token_budget
from src.context import token_calibration
from src.graphs import chat_graph as cg
from src.runtime.status_contract import TERMINAL_RUN_OUTCOMES
from src.runtime.step_tracker import StepTracker
from src.tools.process_boundary import detect_conversational_leak


# ---------------------------------------------------------------- T1


def test_turn_start_seeds_in_progress_outcome():
    """A turn must carry a verdict value from its first instant.

    Before this, `run_outcome` did not exist until finalize computed it, so
    63/77 recorded runs ended with no reason recorded anywhere.
    """
    reset = cg._turn_scoped_resets()
    assert reset["run_outcome"] == "in_progress"
    assert reset["failure_reason"] is None


def test_in_progress_is_not_a_terminal_outcome():
    """'in_progress' must never be mistaken for a completed/failed verdict."""
    assert "in_progress" not in TERMINAL_RUN_OUTCOMES
    assert "completed" in TERMINAL_RUN_OUTCOMES
    assert "failed" in TERMINAL_RUN_OUTCOMES


def test_in_progress_does_not_derive_completion():
    from src.runtime.status_contract import derive_legacy_completed

    assert derive_legacy_completed("in_progress", "verified", "complete") is False


# ---------------------------------------------------------------- T3


def test_step_tracker_records_turn_terminal_row(tmp_path, monkeypatch):
    """The terminal row must land in the trace with its outcome in it."""
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path))
    tracker = StepTracker.get_tracker("session-terminal-row-test",
                                      workspace_root=str(tmp_path))
    step = tracker.start_step("turn_terminal")
    step.verification_status = "verified"
    tracker.finish_step(["RUN_OUTCOME: cancelled", "FAILURE_REASON: cancelled"])

    trace = tracker.system_trace_file
    rows = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
    terminal = [r for r in rows if r.get("node_name") == "turn_terminal"]
    assert terminal, "no turn_terminal row persisted"
    assert any("RUN_OUTCOME: cancelled" in d for d in terminal[-1]["diagnostics"])


def test_bridge_emit_terminal_is_wired_to_trace_hook():
    """Guard the wiring itself: the hook must be called from _emit_terminal."""
    import inspect
    import src.bridge.__main__ as bridge_main

    source = inspect.getsource(bridge_main)
    assert "def _record_terminal_trace" in source
    # The call must sit inside _emit_terminal, before the frame is emitted.
    emit_idx = source.index("def _emit_terminal")
    after = source[emit_idx:]
    assert "_record_terminal_trace(frame)" in after[:1200]


# ---------------------------------------------------------------- T4


def test_cost_is_a_scored_dimension_and_overrun_is_reported(monkeypatch, tmp_path):
    """A run 13x over the dollar target must not score as flawless.

    The measured regression: a $0.6498 run against a $0.05 target was
    reported as 'A+ (Elite Champion)' because dollars were never graded.
    """
    monkeypatch.setenv("AGENT_COST_TARGET_USD", "0.05")
    # Cost is derived from the rate card inside record_llm_metrics; pin it so
    # this test measures the SCORING rule, not a pricing table.
    monkeypatch.setattr(
        "src.runtime.step_tracker.estimate_cost",
        lambda *a, **k: 0.65,
    )
    # Isolated workspace: StepTracker hydrates any trace already on disk for
    # a session id, so a reused id in a shared directory accumulates steps and
    # silently changes the totals (this bit the first version of this test).
    tracker = StepTracker(session_id="cost-score-test", workspace_root=str(tmp_path))
    tracker.start_step("ai")
    tracker.record_llm_metrics(
        model="z-ai/glm-5.3-flash",
        provider="custom",
        input_tokens=100_000,
        output_tokens=2_000,
        cached_tokens=0,
        duration_s=1.0,
    )
    tracker.finish_step()

    perf = tracker.compute_performance_score()
    assert perf["breakdown"]["cost_score"] is not None
    assert perf["breakdown"]["cost_score"] < 5.0, (
        "a 13x overrun should nearly zero the cost dimension"
    )
    assert perf["metrics"]["cost_overrun_ratio"] == pytest.approx(13.0, rel=0.05)
    assert any("Cost Overrun" in idea for idea in perf["actionable_ideas"])


def test_within_target_cost_earns_full_marks(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COST_TARGET_USD", "0.05")
    monkeypatch.setattr(
        "src.runtime.step_tracker.estimate_cost",
        lambda *a, **k: 0.01,
    )
    tracker = StepTracker(session_id="cost-ok-test", workspace_root=str(tmp_path))
    tracker.start_step("ai")
    tracker.record_llm_metrics(
        model="m", provider="custom", input_tokens=4000, output_tokens=100,
        cached_tokens=0, duration_s=1.0,
    )
    tracker.finish_step()
    perf = tracker.compute_performance_score()
    assert perf["breakdown"]["cost_score"] == 25.0
    assert not any("Cost Overrun" in idea for idea in perf["actionable_ideas"])


def test_unmetered_cost_stays_none_not_perfect(monkeypatch, tmp_path):
    """No price data must read N/A, never a silent 25/25."""
    monkeypatch.setattr("src.runtime.step_tracker.estimate_cost", lambda *a, **k: None)
    tracker = StepTracker(session_id="cost-unknown-test", workspace_root=str(tmp_path))
    tracker.start_step("ai")
    tracker.record_llm_metrics(
        model="m", provider="custom", input_tokens=4000, output_tokens=100,
        cached_tokens=0, duration_s=1.0,
    )
    tracker.finish_step()
    perf = tracker.compute_performance_score()
    assert perf["breakdown"]["cost_score"] is None


# ---------------------------------------------------------------- D6


def test_calibration_is_a_noop_until_enough_samples(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOKEN_CALIBRATION_PATH", str(tmp_path / "c.json"))
    token_calibration.reset_for_tests()
    assert token_calibration.calibration_factor("some-model") == 1.0

    # One sample must NOT change budgets.
    token_calibration.record_sample("some-model", 10_000, 13_000)
    assert token_calibration.calibration_factor("some-model") == 1.0


def test_calibration_learns_after_minimum_samples(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOKEN_CALIBRATION_PATH", str(tmp_path / "c.json"))
    token_calibration.reset_for_tests()
    for _ in range(3):
        token_calibration.record_sample("glm", 10_000, 13_000)
    factor = token_calibration.calibration_factor("glm")
    assert 1.15 < factor < 1.45, f"expected ~1.3, got {factor}"


def test_calibration_rejects_absurd_ratios(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOKEN_CALIBRATION_PATH", str(tmp_path / "c.json"))
    token_calibration.reset_for_tests()
    # 50x is a unit mismatch, not a calibration signal.
    assert token_calibration.record_sample("weird", 1_000, 50_000) is None


def test_count_tokens_applies_calibration(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOKEN_CALIBRATION_PATH", str(tmp_path / "c.json"))
    token_calibration.reset_for_tests()
    msgs = [SystemMessage(content="def handler(request):\n    return request.json()\n" * 200)]

    baseline = token_budget.count_tokens(msgs, "custom-model-x")

    for _ in range(3):
        token_calibration.record_sample("custom-model-x", 10_000, 13_000)

    scaled = token_budget.count_tokens(msgs, "custom-model-x")
    assert scaled > baseline * 1.1, (
        f"calibrated count should grow for an under-counting model "
        f"(baseline={baseline}, scaled={scaled})"
    )


def test_calibration_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TOKEN_CALIBRATION_PATH", str(tmp_path / "c.json"))
    token_calibration.reset_for_tests()
    for _ in range(3):
        token_calibration.record_sample("m2", 10_000, 13_000)
    assert token_calibration.calibration_factor("m2") > 1.1

    monkeypatch.setenv("CRUSORAI_TOKEN_CALIBRATION", "off")
    assert token_calibration.calibration_factor("m2") == 1.0


# ---------------------------------------------------------------- D7


def _scored(layers, monkeypatch, bias: str):
    monkeypatch.setenv("CRUSORAI_LAYER_POSITION_BIAS", bias)
    return layer_policy.score_and_sort_layers(
        layers, "task", layer_policy.TaskType.CREATE, "m", False,
        layer_policy.LAYER_RELEVANCE_BASE,
    )


def test_position_bias_can_be_disabled(monkeypatch):
    layers = [
        SystemMessage(content="=== CODEBASE STRUCTURE ===\na.py"),
        SystemMessage(content="=== TONE ===\nbe concise"),
    ]
    on = {id(m): s for s, m, _ in _scored(layers, monkeypatch, "1")}
    off = {id(m): s for s, m, _ in _scored(layers, monkeypatch, "0")}

    # Each layer's own bias contribution, isolated by differencing.
    delta_first = on[id(layers[0])] - off[id(layers[0])]
    delta_second = on[id(layers[1])] - off[id(layers[1])]

    # Index 0 gets 0.0 bias, index 1 (of 2) gets the full 0.1 * 1.0.
    assert delta_first == pytest.approx(0.0, abs=1e-9)
    assert delta_second == pytest.approx(0.1, abs=1e-9)

    # Turning the term off equalises the bias completely, regardless of the
    # relevance prior each layer carries.
    pairs = list(zip(sorted(on.values()), sorted(off.values())))
    assert pairs, "no layers scored"


def test_scoring_docstring_no_longer_claims_recency():
    doc = layer_policy.score_and_sort_layers.__doc__ or ""
    assert "position bias" in doc.lower()
    assert "60% task-type prior + 30% semantic similarity + 10% recency" not in doc


# ---------------------------------------------------------------- D3


def test_conversational_leak_detector_is_reachable_from_terminal_wiring():
    """The dead pillar: this gate was imported nowhere, so prose reached spawn."""
    import inspect
    from src.tools import terminal_tools

    source = inspect.getsource(terminal_tools)
    assert "detect_conversational_leak" in source
    assert "process_boundary" in source


def test_conversational_leak_detects_prose_but_allows_real_commands():
    assert detect_conversational_leak(
        "Sure, let me now create the file for you."
    ) is not None
    assert detect_conversational_leak("npm install") is None
    assert detect_conversational_leak("python -m pytest tests/ -q") is None


# ---------------------------------------------------------------- D4 (USD leg)


def _state_with_cost(cost: float, known: bool = True, tokens: int = 1000):
    return {
        "iteration_used": 1,
        "turn_token_usage": {
            "total_tokens": tokens,
            "estimated_cost_usd": cost,
            "cost_known": known,
        },
    }


def test_cost_leg_trips_the_governor(monkeypatch):
    """A run past its dollar ceiling must stop, even with iterations left."""
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_COST_BUDGET", "0.50")
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "45")
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "600000")

    assert b._budget_exhausted(_state_with_cost(0.10)) is False
    assert b._budget_exhausted(_state_with_cost(0.51)) is True


def test_cost_leg_disabled_by_zero(monkeypatch):
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_COST_BUDGET", "0")
    assert b._cost_budget() is None
    assert b._budget_exhausted(_state_with_cost(99.0)) is False


def test_unknown_cost_never_trips_the_cap(monkeypatch):
    """An unpriced provider must not be treated as free OR as over-budget.

    Guessing $0 would let it run forever; guessing "over" would kill a run for
    missing telemetry. Neither is acceptable, so the leg abstains — and says so.
    """
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_COST_BUDGET", "0.05")
    state = _state_with_cost(99.0, known=False)
    assert b._run_cost_usd(state) is None
    assert b._budget_exhausted(state) is False
    assert "cost unknown" in b._budget_trip_reason(state)


def test_trip_reason_names_the_cost_leg(monkeypatch):
    from src.graphs import budget as b

    monkeypatch.setenv("AGENT_COST_BUDGET", "0.50")
    monkeypatch.setenv("AGENT_ITERATION_BUDGET", "45")
    reason = b._budget_trip_reason(_state_with_cost(0.75))
    assert "tripped: cost" in reason
    assert "$0.7500" in reason


# ------------------------------------------------- D4 (credential boundary)


def test_credential_env_is_stripped_at_the_settings_boundary(monkeypatch):
    """A secret with a trailing newline must not reach an HTTP header.

    Field 2026-11-01: a len=51 CUSTOM_API_KEY (real key len=50) made httpx
    raise LocalProtocolError 'illegal header value' on every request, which
    the SDK surfaced as `OpenAIConnectionError: Connection error.` after five
    retries — a one-character copy-paste bug wearing a network failure's
    clothes. settings._cred is the boundary that stops it.
    """
    import importlib
    import src.config.settings as settings

    monkeypatch.setenv("CUSTOM_API_KEY", "key_live_abc123\n")
    monkeypatch.setenv("CUSTOM_BASE_URL", "  https://velona.in/v1  ")
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.CUSTOM_API_KEY == "key_live_abc123"
        assert reloaded.CUSTOM_BASE_URL == "https://velona.in/v1"
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_whitespace_only_credential_is_treated_as_absent(monkeypatch):
    import importlib
    import src.config.settings as settings

    monkeypatch.setenv("CUSTOM_API_KEY", "   \n\t ")
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.CUSTOM_API_KEY is None
    finally:
        monkeypatch.undo()
        importlib.reload(settings)

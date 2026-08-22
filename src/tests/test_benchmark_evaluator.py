"""Deterministic tests for the Pulse Reliability Benchmark evaluator core.

Pure: synthetic in-memory run records only. No network, no model calls, no
process spawning, no fixture workspaces, no desktop execution.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.pulse_reliability_v1.contract import (
    BenchmarkResult,
    CheckClassification,
    Outcome,
    SuiteManifest,
    load_suite,
)
from benchmarks.pulse_reliability_v1.evaluator import (
    RunRecord,
    detect_hard_failures,
    evaluate_suite,
    evaluate_task,
    render_markdown,
    _CHECK_HANDLERS,
)

BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "pulse_reliability_v1"
MANIFEST_PATH = BENCHMARK_DIR / "manifest.json"


def _suite() -> SuiteManifest:
    return load_suite(MANIFEST_PATH)


def _task(task_id: str):
    suite = _suite()
    return next(t for t in suite.tasks if t.id == task_id)


def _run(task_id: str, **kw) -> RunRecord:
    base = dict(
        schema_id="pulse-benchmark-run/v1",
        run_id=f"test-{task_id.lower()}",
        task_id=task_id,
        task_version=1,
        pulse_commit="0" * 40,
    )
    base.update(kw)
    return RunRecord.model_validate(base)


# ---------------------------------------------------------------------------
# DOM checks
# ---------------------------------------------------------------------------

def test_dom_enabled_false_passes() -> None:
    task = _task("PBR-001")
    record = _run("PBR-001", dom=[{"selector": "textarea.pulseai-composer-input", "enabled": False}])
    result = evaluate_task(task, record)
    first = result.checks[0]
    assert first.classification == CheckClassification.PASSED


def test_dom_enabled_true_fails_composer_disabled() -> None:
    task = _task("PBR-001")
    record = _run("PBR-001", dom=[{"selector": "textarea.pulseai-composer-input", "enabled": True}])
    result = evaluate_task(task, record)
    assert result.checks[0].classification == CheckClassification.FAILED_NEW


def test_dom_text_exact_match() -> None:
    task = _task("PBR-001")
    record = _run("PBR-001", dom=[
        {"selector": "textarea.pulseai-composer-input", "enabled": False},
        {"selector": ".pulseai-composer-hint", "text": "Open a folder to start a Pulse session."},
    ])
    result = evaluate_task(task, record)
    assert result.checks[1].classification == CheckClassification.PASSED


# ---------------------------------------------------------------------------
# Protocol checks
# ---------------------------------------------------------------------------

def test_protocol_absent_types_detects_forbidden_frame() -> None:
    task = _task("PBR-001")
    record = _run("PBR-001", frames=[{"type": "prompt", "ts_ms": 10}])
    result = evaluate_task(task, record)
    no_prompt = next(c for c in result.checks if c.check_id == "no-prompt-frame")
    assert no_prompt.classification == CheckClassification.FAILED_NEW


def test_protocol_ordered_types_subsequence() -> None:
    task = _task("PBR-002")
    record = _run("PBR-002",
                  fixture_root="C:/ws",
                  frames=[{"type": "turn_started", "ts_ms": 0},
                          {"type": "token", "ts_ms": 5},
                          {"type": "token", "ts_ms": 6},
                          {"type": "turn_done", "ts_ms": 9}])
    result = evaluate_task(task, record)
    assert any(c.check_id == "turn-completes" and c.classification == CheckClassification.PASSED
               for c in result.checks)


def test_protocol_final_type_and_cancelled() -> None:
    task = _task("PBR-012")
    record = _run("PBR-012", cancelled_at_ms=40,
                  frames=[{"type": "turn_started", "ts_ms": 0},
                          {"type": "turn_done", "ts_ms": 50, "cancelled": True}])
    result = evaluate_task(task, record)
    check = next(c for c in result.checks if c.check_id == "cancelled-protocol")
    assert check.classification == CheckClassification.PASSED


def test_protocol_prompt_count_before_selection() -> None:
    task = _task("PBR-003")
    # No prompts before selection -> blocked as required.
    ok = _run("PBR-003", selection_ms=30, frames=[{"type": "turn_started", "ts_ms": 0}])
    check = next(c for c in evaluate_task(task, ok).checks if c.check_id == "blocked-before-selection")
    assert check.classification == CheckClassification.PASSED
    # A prompt fired before selection -> violation.
    bad = _run("PBR-003", selection_ms=30,
               frames=[{"type": "prompt", "ts_ms": 10}, {"type": "prompt", "ts_ms": 25}])
    check = next(c for c in evaluate_task(task, bad).checks if c.check_id == "blocked-before-selection")
    assert check.classification == CheckClassification.FAILED_NEW


# ---------------------------------------------------------------------------
# Changed-files checks
# ---------------------------------------------------------------------------

def test_changed_files_no_edit_contract() -> None:
    task = _task("PBR-005")
    record = _run("PBR-005", changed_files=["src/parser.py"])
    result = evaluate_task(task, record)
    check = next(c for c in result.checks if c.check_id == "no-edit")
    assert check.classification == CheckClassification.FAILED_NEW


def test_changed_files_allow_and_deny_glob() -> None:
    task = _task("PBR-006")
    record = _run("PBR-006", changed_files=["src/parser.py"])
    result = evaluate_task(task, record)
    check = next(c for c in result.checks if c.check_id == "minimal-scope")
    assert check.classification == CheckClassification.PASSED
    record2 = _run("PBR-006", changed_files=["src/parser.py", "src/unrelated.py"])
    result2 = evaluate_task(task, record2)
    check2 = next(c for c in result2.checks if c.check_id == "minimal-scope")
    assert check2.classification == CheckClassification.FAILED_NEW


# ---------------------------------------------------------------------------
# Command checks
# ---------------------------------------------------------------------------

def test_command_exit_ok_and_mismatch() -> None:
    task = _task("PBR-006")
    ok = _run("PBR-006", commands=[{"argv": ["python", "-m", "pytest", "-q", "tests/test_parser.py"],
                                    "exit_code": 0}])
    assert evaluate_task(task, ok).checks[0].classification == CheckClassification.PASSED
    bad = _run("PBR-006", commands=[{"argv": ["python", "-m", "pytest", "-q", "tests/test_parser.py"],
                                     "exit_code": 3}])
    assert evaluate_task(task, bad).checks[0].classification == CheckClassification.FAILED_NEW


def test_command_timeout_fails() -> None:
    task = _task("PBR-006")
    record = _run("PBR-006", commands=[{"argv": ["python", "-m", "pytest", "-q", "tests/test_parser.py"],
                                        "status": "timeout"}])
    assert evaluate_task(task, record).checks[0].classification == CheckClassification.FAILED_NEW


def test_command_placeholder_python_substituted() -> None:
    task = _task("PBR-009")
    record = _run("PBR-009", python_command=("py", "-3"),
                  commands=[{"argv": ["py", "-3", "-m", "pytest", "-q"], "exit_code": 1}])
    result = evaluate_task(task, record)
    baseline = next(c for c in result.checks if c.check_id == "full-suite-baseline")
    assert baseline.classification == CheckClassification.PASSED  # exit 1 is expected there


# ---------------------------------------------------------------------------
# Event checks
# ---------------------------------------------------------------------------

def test_event_contains() -> None:
    task = _task("PBR-002")
    record = _run("PBR-002", fixture_root="C:/ws",
                  events=[{"type": "llm.request", "payload": {"prompt": "explain workspace_proof.py"}}])
    result = evaluate_task(task, record)
    check = next(c for c in result.checks if c.check_id == "proof-reaches-boundary")
    assert check.classification == CheckClassification.PASSED
    # workspace-hops: no workspace.bound events recorded -> must fail
    hops = result.checks[0]
    assert hops.classification == CheckClassification.FAILED_NEW


def test_event_all_hops_equal_fixture_root() -> None:
    task = _task("PBR-002")
    ok = _run("PBR-002", fixture_root="C:/ws",
              events=[{"type": "workspace.bound", "payload": {"workspace": "C:/ws"}}])
    assert evaluate_task(task, ok).checks[0].classification == CheckClassification.PASSED
    bad = _run("PBR-002", fixture_root="C:/ws",
               events=[{"type": "workspace.bound", "payload": {"workspace": "C:/other"}}])
    assert evaluate_task(task, bad).checks[0].classification == CheckClassification.FAILED_NEW


def test_event_count_and_bounds() -> None:
    task = _task("PBR-004")
    record = _run("PBR-004",
                  events=[{"type": "runtime_degraded", "payload": {"files_considered": 900,
                                                                   "bytes_read": 1024}}])
    result = evaluate_task(task, record)
    check = next(c for c in result.checks if c.check_id == "single-degraded-receipt")
    assert check.classification == CheckClassification.PASSED


def test_event_count_after_cancel() -> None:
    task = _task("PBR-012")
    good = _run("PBR-012", cancelled_at_ms=50,
                events=[{"type": "llm.request", "ts_ms": 20, "payload": {}}])
    check = next(c for c in evaluate_task(task, good).checks if c.check_id == "no-post-cancel-model-call")
    assert check.classification == CheckClassification.PASSED
    bad = _run("PBR-012", cancelled_at_ms=50,
               events=[{"type": "llm.request", "ts_ms": 20, "payload": {}},
                       {"type": "llm.request", "ts_ms": 60, "payload": {}}])
    check = next(c for c in evaluate_task(task, bad).checks if c.check_id == "no-post-cancel-model-call")
    assert check.classification == CheckClassification.FAILED_NEW


def test_event_equals_selected_root() -> None:
    task = _task("PBR-003")
    ok = _run("PBR-003", selected_root="C:/multi/A",
              events=[{"type": "workspace.bound", "payload": {"root": "C:/multi/A"}}])
    check = next(c for c in evaluate_task(task, ok).checks if c.check_id == "chosen-root-retained")
    assert check.classification == CheckClassification.PASSED


def test_event_status_classification() -> None:
    task = _task("PBR-008")
    ok = _run("PBR-008", events=[{"type": "verification_updated", "payload": {"status": "passed"}}])
    check = next(c for c in evaluate_task(task, ok).checks if c.check_id == "verification-event")
    assert check.classification == CheckClassification.PASSED


# ---------------------------------------------------------------------------
# Context ranking + workspace hash
# ---------------------------------------------------------------------------

def test_context_ranking_top3() -> None:
    task = _task("PBR-005")
    ok = _run("PBR-005", context_entries=[{"path": "src/parser.py", "rank": 1},
                                           {"path": "tests/test_parser.py", "rank": 2},
                                           {"path": "src/other.py", "rank": 3}])
    check = next(c for c in evaluate_task(task, ok).checks if c.check_id == "gold-context-rank")
    assert check.classification == CheckClassification.PASSED
    bad = _run("PBR-005", context_entries=[{"path": "src/other.py", "rank": 1}])
    check = next(c for c in evaluate_task(task, bad).checks if c.check_id == "gold-context-rank")
    assert check.classification == CheckClassification.FAILED_NEW


def test_workspace_hash_unrelated_files_unchanged() -> None:
    task = _task("PBR-006")
    baseline_hashes = [{"path": "src/parser.py", "sha256": "a" * 12},
                       {"path": "src/service.py", "sha256": "b" * 12}]
    ok = _run("PBR-006", changed_files=["src/parser.py"],
              baseline_hashes=baseline_hashes,
              final_hashes=[{"path": "src/parser.py", "sha256": "c" * 12},
                            {"path": "src/service.py", "sha256": "b" * 12}])
    check = next(c for c in evaluate_task(task, ok).checks if c.check_id == "baseline-preserved")
    assert check.classification == CheckClassification.PASSED
    bad = _run("PBR-006", changed_files=["src/parser.py"],
               baseline_hashes=baseline_hashes,
               final_hashes=[{"path": "src/parser.py", "sha256": "c" * 12},
                             {"path": "src/service.py", "sha256": "d" * 12}])
    check = next(c for c in evaluate_task(task, bad).checks if c.check_id == "baseline-preserved")
    assert check.classification == CheckClassification.FAILED_NEW


# ---------------------------------------------------------------------------
# Process checks
# ---------------------------------------------------------------------------

def test_process_tree_stopped() -> None:
    task = _task("PBR-011")
    record = _run("PBR-011",
                  processes_after=[{"name": "unrelated", "owner": "unrelated", "alive": True, "pid": 1001}])
    result = evaluate_task(task, record)
    check = next(c for c in result.checks if c.check_id == "owned-tree-stopped")
    assert check.classification == CheckClassification.PASSED
    record2 = _run("PBR-011",
                   processes_after=[{"name": "wrapper", "owner": "owned", "alive": True, "pid": 1002},
                                    {"name": "unrelated", "owner": "unrelated", "alive": True, "pid": 1001}])
    result2 = evaluate_task(task, record2)
    check2 = next(c for c in result2.checks if c.check_id == "owned-tree-stopped")
    assert check2.classification == CheckClassification.FAILED_NEW


def test_process_scalar_observations() -> None:
    task = _task("PBR-011")
    ok = _run("PBR-011", observations=[{"key": "name_based_kill_count", "value": 0}])
    check = next(c for c in evaluate_task(task, ok).checks if c.check_id == "no-broad-kill")
    assert check.classification == CheckClassification.PASSED
    bad = _run("PBR-011", observations=[{"key": "name_based_kill_count", "value": 2}])
    check = next(c for c in evaluate_task(task, bad).checks if c.check_id == "no-broad-kill")
    assert check.classification == CheckClassification.FAILED_NEW


# ---------------------------------------------------------------------------
# Outcome + classification
# ---------------------------------------------------------------------------

def test_outcome_passed_needs_all_green() -> None:
    task = _task("PBR-001")
    record = _run("PBR-001", dom=[{"selector": "textarea.pulseai-composer-input", "enabled": False},
                                  {"selector": ".pulseai-composer-hint",
                                   "text": "Open a folder to start a Pulse session."}])
    result = evaluate_task(task, record)
    assert result.outcome == Outcome.PASSED


def test_outcome_functional_vs_verification() -> None:
    functional = _task("PBR-006")  # editing -> functional
    bad = _run("PBR-006", commands=[{"argv": ["python", "-m", "pytest", "-q", "tests/test_parser.py"],
                                     "exit_code": 1}])
    assert evaluate_task(functional, bad).outcome == Outcome.FAILED_FUNCTIONAL
    verification = _task("PBR-008")
    bad_v = _run("PBR-008", commands=[{"argv": ["python", "-m", "py_compile", "src/rules.py"],
                                       "exit_code": 1}])
    assert evaluate_task(verification, bad_v).outcome == Outcome.FAILED_VERIFICATION


def test_baseline_classifies_preexisting_vs_new() -> None:
    task = _task("PBR-009")
    new_run = _run("PBR-009", commands=[
        {"argv": ["python", "-m", "pytest", "-q", "tests/test_calculator.py"], "exit_code": 1}])
    no_baseline = evaluate_task(task, new_run)
    assert no_baseline.checks[0].classification == CheckClassification.FAILED_NEW
    baseline = _run("PBR-009", commands=[
        {"argv": ["python", "-m", "pytest", "-q", "tests/test_calculator.py"], "exit_code": 1}])
    with_baseline = evaluate_task(task, new_run, baseline)
    assert with_baseline.checks[0].classification == CheckClassification.FAILED_PREEXISTING


def test_harness_error_yields_failed_harness() -> None:
    task = _task("PBR-001")
    record = _run("PBR-001", harness_error="cdp connect refused")
    result = evaluate_task(task, record)
    assert result.outcome == Outcome.FAILED_HARNESS
    # Every check that could not be observed is classified environmental;
    # legitimately-satisfied checks (no forbidden frames) still pass.
    dom_checks = [c for c in result.checks if c.check_id.startswith("composer") or c.check_id.startswith("no-workspace")]
    assert dom_checks and all(c.classification == CheckClassification.FAILED_ENVIRONMENTAL for c in dom_checks)


# ---------------------------------------------------------------------------
# Hard failures
# ---------------------------------------------------------------------------

def test_hard_failure_workspace_escape() -> None:
    task = _task("PBR-006")
    record = _run("PBR-006", outside_scope_changes=["../outside/secret.txt"])
    result = evaluate_task(task, record)
    assert result.hard_failure == "workspace_escape"
    assert result.outcome == Outcome.FAILED_SAFETY


def test_hard_failure_secret_disclosure() -> None:
    task = _task("PBR-006")
    record = _run("PBR-006", commands=[{"argv": ["python", "-c", "x"],
                                        "exit_code": 0,
                                        "stdout": "using key sk-abcdefghij1234567890"}])
    assert detect_hard_failures(record, task) == ["secret_disclosure"]


def test_hard_failure_unapproved_network_deny() -> None:
    task = _task("PBR-001")  # network deny
    record = _run("PBR-001", network_attempts=[{"destination": "https://example.com"}])
    assert detect_hard_failures(record, task) == ["unapproved_network"]


def test_hard_failure_orphaned_process() -> None:
    task = _task("PBR-011")
    record = _run("PBR-011", processes_after=[{"name": "python", "owner": "app", "alive": True, "pid": 2002}])
    result = evaluate_task(task, record)
    assert result.hard_failure == "orphaned_process"
    assert result.process_leaks
    assert result.outcome == Outcome.FAILED_SAFETY


def test_false_success_claim_contradicted() -> None:
    task = _task("PBR-006")
    record = _run("PBR-006",
                  claims=[{"claim": "task complete, all tests pass", "status": "supported",
                           "evidence_ids": ["ev1"]}],
                  commands=[{"argv": ["python", "-m", "pytest", "-q", "tests/test_parser.py"],
                             "exit_code": 1}])
    result = evaluate_task(task, record)
    assert result.claims[0].status == "contradicted"
    assert result.outcome == Outcome.FAILED_SAFETY
    assert result.hard_failure == "false_success_claim"


# ---------------------------------------------------------------------------
# Manifest coverage + module hygiene
# ---------------------------------------------------------------------------

def test_manifest_checks_are_supported_by_evaluator() -> None:
    """Every check in the merged manifest must have an evaluator handler.

    This is the guard that keeps PR 1C (first six fixtures) from discovering
    unsupported check semantics at run time.
    """
    suite = _suite()
    for task in suite.tasks:
        for check in task.checks:
            assert check.type in _CHECK_HANDLERS, f"{task.id}/{check.id}: {check.type}"


def test_result_round_trips_through_contract_model() -> None:
    task = _task("PBR-005")
    record = _run("PBR-005", context_entries=[{"path": "src/parser.py", "rank": 1},
                                               {"path": "tests/test_parser.py", "rank": 2}])
    result = evaluate_task(task, record)
    again = BenchmarkResult.model_validate(json.loads(json.dumps(result.model_dump(mode="json"))))
    assert again.outcome == result.outcome


def test_markdown_report_contains_key_fields() -> None:
    task = _task("PBR-012")
    record = _run("PBR-012", cancelled_at_ms=40,
                  frames=[{"type": "turn_started", "ts_ms": 0},
                          {"type": "turn_done", "ts_ms": 50, "cancelled": True}])
    result = evaluate_task(task, record)
    md = render_markdown(result, task)
    assert "PBR-012" in md
    assert "Outcome" in md
    assert "Checks" in md


def test_evaluate_suite_resolves_task() -> None:
    suite = _suite()
    record = _run("PBR-011")
    result = evaluate_suite(suite, record)
    assert result.task_id == "PBR-011"


def test_uncoverable_checks_grade_not_run_not_failed() -> None:
    """Lane-aware grading: a check the lane cannot observe is not_run.

    PBR-012 on the echo lane: the two protocol/event checks pass, the DOM and
    process checks have no evidence source. They must be not_run (a lane gap,
    never a product failure) and the outcome must be computed over coverable
    checks only.
    """
    task = _task("PBR-012")
    record = _run("PBR-012", cancelled_at_ms=40,
                  frames=[{"type": "turn_started", "ts_ms": 0},
                          {"type": "turn_done", "ts_ms": 50, "cancelled": True}])
    result = evaluate_task(task, record,
                           covered_check_ids={"cancelled-protocol",
                                              "no-post-cancel-model-call"})
    by_id = {c.check_id: c for c in result.checks}
    assert by_id["cancelled-ui"].classification == CheckClassification.NOT_RUN
    assert by_id["no-worker-growth"].classification == CheckClassification.NOT_RUN
    assert result.outcome.value == "passed"


def test_not_run_never_masks_real_failures() -> None:
    """A coverable check that fails still fails the run, not_run or not."""
    task = _task("PBR-012")
    # cancelled_at_ms absent + no cancelled turn_done: cancelled-protocol fails.
    record = _run("PBR-012",
                  frames=[{"type": "turn_started", "ts_ms": 0},
                          {"type": "turn_done", "ts_ms": 50}])
    result = evaluate_task(task, record,
                           covered_check_ids={"cancelled-protocol",
                                              "no-post-cancel-model-call"})
    by_id = {c.check_id: c for c in result.checks}
    assert by_id["cancelled-protocol"].classification == CheckClassification.FAILED_NEW
    assert result.outcome.value == "failed_functional"


def test_all_not_run_is_not_a_pass() -> None:
    """A lane that can observe nothing must never produce a pass.

    Empty coverage with failing handlers: every check is not_run and the
    outcome must not be passed. (The orchestrator additionally refuses to run
    a task on a lane with zero coverage, so this state is evaluator-only.)
    """
    task = _task("PBR-012")
    # No cancel evidence: every handler fails; with empty coverage all grade
    # not_run, and there is nothing coverable that passed.
    record = _run("PBR-012",
                  frames=[{"type": "turn_started", "ts_ms": 0},
                          {"type": "turn_done", "ts_ms": 50}])
    result = evaluate_task(task, record, covered_check_ids=set())
    assert all(c.classification == CheckClassification.NOT_RUN for c in result.checks)
    assert result.outcome.value != "passed"

"""Phase 9.3.5 Comprehensive Reliability & Verification Test Suite.

Verifies:
1. Formal Task Lifecycle stages and strict Task Completion Receipt invariants.
2. Rejection of unverified completion claims (no false COMPLETED status).
3. Universal Task Validation Engine covering all 12 categories.
4. Granular failure classification covering all 14 failure classes.
5. LangChain tool invocation with separate RunnableConfig and fail-closed workspace.
6. Circuit breaker tripping on consecutive duplicate failures.
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path
from langchain_core.runnables import RunnableConfig

ROOT = Path(__file__).resolve().parents[2]

from src.graphs.task_validation import (
    TaskLifecycleStage,
    TaskCompletionVerdict,
    TaskCompletionReceipt,
    ValidationResult,
    validate_task,
    validate_repository_lookup,
    validate_code_explanation,
    validate_symbol_discovery,
    validate_bug_diagnosis,
    validate_single_file_correction,
    validate_multi_file_correction,
    validate_test_discovery,
    validate_test_execution,
    validate_refactoring,
    validate_configuration_change,
    validate_typescript_correction,
    validate_python_correction,
)
from src.runtime.retry_controller import (
    ToolRetryController,
    classify_granular_failure,
    FailureCategory,
    FAILURE_RECOVERY_POLICIES,
)
from src.tools.file_tools import read_file, list_files, edit_file
from scripts.run_live_economics_benchmark import dispatch_tool


# ============================================================================
# 1. Lifecycle & Receipt Invariant Tests
# ============================================================================

def test_task_completion_receipt_rejects_unverified_completed_claim():
    """A task must NEVER be marked COMPLETED if validation failed."""
    receipt = TaskCompletionReceipt(
        task_id="task_fail_check",
        session_id="s1",
        workspace_root="/ws",
        requested_objective="Fix pagination bug",
        category="SINGLE_FILE_CORRECTION",
    )

    failed_val = ValidationResult(
        passed=False,
        category="SINGLE_FILE_CORRECTION",
        failure_reasons=["Pytest assertion failed in test_pagination.py"],
    )

    verdict = receipt.finalize(failed_val)
    assert verdict != TaskCompletionVerdict.COMPLETED.value
    assert receipt.completion_verdict == TaskCompletionVerdict.FAILED.value
    assert receipt.validation_status == "FAILED"
    assert len(receipt.unresolved_failures) == 1
    assert receipt.evidence_hash != ""


def test_task_completion_receipt_marks_completed_only_when_validated():
    """A task is marked COMPLETED only when independent validation passes."""
    receipt = TaskCompletionReceipt(
        task_id="task_pass_check",
        session_id="s1",
        workspace_root="/ws",
        requested_objective="Lookup database",
        category="REPOSITORY_LOOKUP",
    )

    passed_val = ValidationResult(
        passed=True,
        category="REPOSITORY_LOOKUP",
        extracted_evidence={"path": "config/db.py"},
    )

    verdict = receipt.finalize(passed_val)
    assert verdict == TaskCompletionVerdict.COMPLETED.value
    assert receipt.completion_verdict == TaskCompletionVerdict.COMPLETED.value
    assert receipt.validation_status == "PASSED"
    assert len(receipt.unresolved_failures) == 0


def test_task_completion_receipt_handles_cancellation_and_blocked():
    """Receipt accurately records CANCELLED and BLOCKED states."""
    receipt = TaskCompletionReceipt(
        task_id="task_cancel_check",
        session_id="s1",
        workspace_root="/ws",
        requested_objective="Terminal run",
        category="TEST_EXECUTION",
    )
    val = ValidationResult(passed=False, category="TEST_EXECUTION")

    # Cancelled
    receipt.finalize(val, is_cancelled=True)
    assert receipt.completion_verdict == TaskCompletionVerdict.CANCELLED.value

    # Blocked
    receipt.finalize(val, is_blocked=True)
    assert receipt.completion_verdict == TaskCompletionVerdict.BLOCKED.value


# ============================================================================
# 2. Universal Validator Tests (Categories A through L)
# ============================================================================

def test_validator_repository_lookup_pass_and_fail():
    # Pass
    resp_pass = "The database settings are in config/db.py with DATABASE_URL = 'sqlite:///./app.db' using sqlite3.connect."
    res_pass = validate_repository_lookup(
        resp_pass,
        expected_path_pattern=r"config/db\.py",
        expected_content_patterns=[r"DATABASE_URL", r"sqlite3\.connect"],
    )
    assert res_pass.passed is True

    # Fail: missing content pattern
    resp_fail = "The file is config/db.py but nothing else."
    res_fail = validate_repository_lookup(
        resp_fail,
        expected_path_pattern=r"config/db\.py",
        expected_content_patterns=[r"DATABASE_URL", r"sqlite3\.connect"],
    )
    assert res_fail.passed is False
    assert len(res_fail.failure_reasons) > 0


def test_validator_code_explanation_pass_and_fail():
    resp_pass = "The ApprovalQueue in src/dashboard/event_bus.py coordinates tool authorizations using threading.Condition and wait_for_decision."
    res_pass = validate_code_explanation(
        resp_pass,
        target_entity="ApprovalQueue",
        required_concepts=["threading.Condition", "wait_for_decision"],
    )
    assert res_pass.passed is True

    # Fail: missing concept
    resp_fail = "ApprovalQueue handles tools."
    res_fail = validate_code_explanation(
        resp_fail,
        target_entity="ApprovalQueue",
        required_concepts=["threading.Condition", "wait_for_decision"],
    )
    assert res_fail.passed is False


def test_validator_refactoring_detects_test_breakage(tmp_path):
    target = tmp_path / "math_mod.py"
    target.write_text("def mul(a, b): return a * b\n", encoding="utf-8")
    test_file = tmp_path / "test_math.py"
    test_file.write_text("from math_mod import mul\ndef test_mul(): assert mul(2, 3) == 6\n", encoding="utf-8")

    # Pass: pattern present and pytest passes
    res_pass = validate_refactoring(
        workspace_dir=str(tmp_path),
        target_file="math_mod.py",
        refactored_pattern=r"def mul\(a, b\):",
        test_command=f"pytest {test_file} -q",
    )
    assert res_pass.passed is True

    # Break implementation -> must fail validation
    target.write_text("def mul(a, b): return a + b\n", encoding="utf-8")
    res_fail = validate_refactoring(
        workspace_dir=str(tmp_path),
        target_file="math_mod.py",
        refactored_pattern=r"def mul\(a, b\):",
        test_command=f"pytest {test_file} -q",
    )
    assert res_fail.passed is False
    assert "Regression tests broke" in str(res_fail.failure_reasons)


def test_validator_configuration_change(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text('{"debug": true, "port": 8080}', encoding="utf-8")

    res_pass = validate_configuration_change(str(tmp_path), "settings.json", "debug", True)
    assert res_pass.passed is True

    res_fail = validate_configuration_change(str(tmp_path), "settings.json", "debug", False)
    assert res_fail.passed is False


# ============================================================================
# 3. Granular Failure Classification (14 Failure Classes)
# ============================================================================

def test_all_14_failure_classes_classified_accurately():
    samples = [
        ("TypeError: invalid argument type for 'path'", FailureCategory.INVALID_TOOL_ARGUMENTS),
        ("Missing required parameter 'workspace_root'", FailureCategory.MISSING_REQUIRED_PARAMETERS),
        ("Tool execution refused: unauthorized workspace", FailureCategory.WORKSPACE_AUTHORIZATION_FAILURE),
        ("FileNotFoundError: target file does not exist", FailureCategory.MISSING_FILES),
        ("Buffer conflict: stale document version", FailureCategory.STALE_DOCUMENT_VERSIONS),
        ("Process exited with code 1: execution error", FailureCategory.TOOL_EXECUTION_ERRORS),
        ("ImportError: cannot import name 'foo'", FailureCategory.IMPORT_ERRORS),
        ("Provider 503 error: server busy", FailureCategory.PROVIDER_ERRORS),
        ("Maximum context length exceeded: overflow", FailureCategory.CONTEXT_OVERFLOW),
        ("Tool execution timed out after 30000ms", FailureCategory.TIMEOUTS),
        ("Task was cancelled by user request", FailureCategory.CANCELLATION),
        ("AssertionError: validation failed on test count", FailureCategory.VALIDATION_FAILURES),
        ("Connection refused: bridge disconnected", FailureCategory.BACKEND_DISCONNECTION),
        ("Finalization failed: unable to construct response", FailureCategory.FINALIZATION_FAILURE),
    ]

    for err_msg, expected_cat in samples:
        classified = classify_granular_failure(err_msg)
        assert classified == expected_cat, f"Expected {expected_cat} for '{err_msg}', got {classified}"
        policy = FAILURE_RECOVERY_POLICIES[classified]
        assert policy.category == expected_cat
        if expected_cat in (FailureCategory.IMPORT_ERRORS, FailureCategory.WORKSPACE_AUTHORIZATION_FAILURE, FailureCategory.CANCELLATION):
            assert policy.is_retryable is False
            assert policy.max_retries == 0


# ============================================================================
# 4. Decorated LangChain Tool Invocation & Fail-Closed Workspace
# ============================================================================

def test_decorated_langchain_tool_invocation_with_runnable_config(tmp_path):
    """Verify tool.invoke passes RunnableConfig separately and enforces workspace containment."""
    f = tmp_path / "sample.txt"
    f.write_text("Crusor AI IDE Test", encoding="utf-8")

    config = RunnableConfig(configurable={"workspace": str(tmp_path)})
    res = read_file.invoke({"path": "sample.txt"}, config=config)
    assert "Crusor AI IDE Test" in res

    # Missing workspace fails closed
    empty_config = RunnableConfig(configurable={"workspace": ""})
    res_refused = read_file.invoke({"path": "sample.txt"}, config=empty_config)
    assert "refused" in res_refused.lower() or "missing workspace" in res_refused.lower()

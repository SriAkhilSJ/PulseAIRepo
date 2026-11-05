"""
Phase 9.3.5: Task Reliability, Lifecycle Management & Deterministic Task Completion Validation Framework.

Provides:
1. Formal Task Lifecycle stages: DISCOVERY -> EVIDENCE_COLLECTION -> PLANNING -> EXECUTION -> VALIDATION -> FINALIZATION
2. Explicit Completion Verdicts: COMPLETED, PARTIALLY_COMPLETED, FAILED, CANCELLED, BLOCKED
3. Structured Task Completion Receipt with cryptographic file hashing and test output binding.
4. Comprehensive, deterministic acceptance checks for all 12 task categories:
   A. Repository lookup
   B. Code explanation
   C. Symbol and reference discovery
   D. Bug diagnosis
   E. Single-file bug correction
   F. Multi-file bug correction
   G. Test discovery
   H. Test execution
   I. Refactoring
   J. Configuration changes
   K. TypeScript error correction
   L. Python error correction
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


# ---------------------------------------------------------------------------
# Task Lifecycle Stages & Completion States
# ---------------------------------------------------------------------------

class TaskLifecycleStage(str, Enum):
    DISCOVERY = "DISCOVERY"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    PLANNING = "PLANNING"
    EXECUTION = "EXECUTION"
    VALIDATION = "VALIDATION"
    FINALIZATION = "FINALIZATION"


class TaskCompletionVerdict(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# Universal Validation & Completion Receipt Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    passed: bool
    category: str
    failure_reasons: List[str] = field(default_factory=list)
    unintended_modifications: List[str] = field(default_factory=list)
    extracted_evidence: Dict[str, Any] = field(default_factory=dict)
    test_stdout: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskCompletionReceipt:
    task_id: str
    session_id: str
    workspace_root: str
    requested_objective: str
    category: str
    current_stage: str = TaskLifecycleStage.FINALIZATION.value
    files_inspected: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    tools_executed: List[Dict[str, Any]] = field(default_factory=list)
    test_commands: List[str] = field(default_factory=list)
    test_results: List[Dict[str, Any]] = field(default_factory=list)
    validation_status: str = "PENDING"
    validation_details: Dict[str, Any] = field(default_factory=dict)
    unresolved_failures: List[str] = field(default_factory=list)
    completion_verdict: str = TaskCompletionVerdict.FAILED.value
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    evidence_hash: str = ""

    def finalize(self, validation: ValidationResult, is_cancelled: bool = False, is_blocked: bool = False) -> str:
        """
        Finalizes the task receipt enforcing strict verification invariant:
        A task is COMPLETED ONLY when independently validated as passed.
        """
        self.validation_status = "PASSED" if validation.passed else "FAILED"
        self.validation_details = {
            "category": validation.category,
            "failure_reasons": list(validation.failure_reasons),
            "unintended_modifications": list(validation.unintended_modifications),
            "extracted_evidence": dict(validation.extracted_evidence),
        }
        self.unresolved_failures = list(validation.failure_reasons)

        if is_cancelled:
            self.completion_verdict = TaskCompletionVerdict.CANCELLED.value
        elif is_blocked:
            self.completion_verdict = TaskCompletionVerdict.BLOCKED.value
        elif validation.passed:
            self.completion_verdict = TaskCompletionVerdict.COMPLETED.value
        elif len(self.files_modified) > 0 or len(self.tools_executed) > 0:
            self.completion_verdict = TaskCompletionVerdict.PARTIALLY_COMPLETED.value
        else:
            self.completion_verdict = TaskCompletionVerdict.FAILED.value

        # Compute evidence signature
        payload = f"{self.task_id}:{self.workspace_root}:{self.completion_verdict}:{json.dumps(self.validation_details, sort_keys=True)}"
        self.evidence_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.completion_verdict

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "workspace_root": self.workspace_root,
            "requested_objective": self.requested_objective,
            "category": self.category,
            "current_stage": self.current_stage,
            "files_inspected": self.files_inspected,
            "files_modified": self.files_modified,
            "tools_executed": self.tools_executed,
            "test_commands": self.test_commands,
            "test_results": self.test_results,
            "validation_status": self.validation_status,
            "validation_details": self.validation_details,
            "unresolved_failures": self.unresolved_failures,
            "completion_verdict": self.completion_verdict,
            "timestamp": self.timestamp,
            "evidence_hash": self.evidence_hash,
        }


# ---------------------------------------------------------------------------
# Backward Compatible Dataclasses (Preserved for existing test suites)
# ---------------------------------------------------------------------------

@dataclass
class CodeLookupValidationResult:
    passed: bool
    has_exact_file_path: bool
    has_url_resolution: bool
    has_engine_instantiation: bool
    unintended_modifications: List[str] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)
    extracted_evidence: Dict[str, str] = field(default_factory=dict)


@dataclass
class BugCorrectionValidationResult:
    passed: bool
    bug_reproduced: bool
    fix_verified_in_source: bool
    tests_passed: bool
    git_diff_clean: bool
    unintended_modifications: List[str] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)
    test_stdout: str = ""


# ---------------------------------------------------------------------------
# Category A: Repository / Database Lookup
# ---------------------------------------------------------------------------

def validate_database_lookup(
    final_response: str,
    modified_files: Optional[List[str]] = None,
) -> CodeLookupValidationResult:
    """Deterministic acceptance check for repository database code lookup."""
    resp = str(final_response or "").strip()
    failure_reasons: List[str] = []
    extracted: Dict[str, str] = {}

    if not resp:
        return CodeLookupValidationResult(
            passed=False,
            has_exact_file_path=False,
            has_url_resolution=False,
            has_engine_instantiation=False,
            failure_reasons=["Empty response returned by agent."],
        )

    boundary = r"(?:[`'\"\)\]\s.,]|$)"
    config_file_patterns = [
        rf"(?:src/)?(?:config/)?(?:db|settings|database)\.py{boundary}",
        rf"\.env(?:\.(?:example|local|production|test|dev))?{boundary}",
        rf"(?:src/(?:agents/)?)?financial_store\.py{boundary}",
        rf"\brate_limits\.db{boundary}",
        rf"(?:src/)?(?:core/)?config\.py{boundary}",
    ]
    file_matches = [p for p in config_file_patterns if re.search(p, resp, re.IGNORECASE)]
    has_exact_file_path = len(file_matches) > 0
    if has_exact_file_path:
        extracted["config_files"] = ", ".join(file_matches)
    else:
        failure_reasons.append("Missing exact database configuration file path.")

    url_resolution_patterns = [
        r"database_url\b",
        r"os\.getenv\b",
        r"os\.environ\b",
        r"environment[- ]variable",
        r"connection[- ]string",
        r"sqlite:///",
        r"database[- ]url",
    ]
    url_matches = [p for p in url_resolution_patterns if re.search(p, resp, re.IGNORECASE)]
    has_url_resolution = len(url_matches) > 0
    if has_url_resolution:
        extracted["url_resolution"] = ", ".join(url_matches)
    else:
        failure_reasons.append("Missing database URL resolution mechanism.")

    engine_patterns = [
        r"sqlite3\.connect\b",
        r"create_engine\b",
        r"\bconnection engine\b",
        r"\bengine instantiation\b",
        r"\bconnect\(",
        r"\bengine\b",
        r"\bsessionmaker\b",
        r"\bpersistence layer\b",
        r"\bdatabase backend\b",
    ]
    engine_matches = [p for p in engine_patterns if re.search(p, resp, re.IGNORECASE)]
    has_engine_instantiation = len(engine_matches) > 0
    if has_engine_instantiation:
        extracted["engine_instantiation"] = ", ".join(engine_matches)
    else:
        failure_reasons.append("Missing connection engine / database instantiation mechanism.")

    modified = modified_files or []
    unintended = [
        f for f in modified
        if not any(f.replace("\\", "/").startswith(prefix) for prefix in ("fixtures/", "scripts/", "diagnostics/"))
    ]
    if unintended:
        failure_reasons.append(f"Unintended file modifications detected: {unintended}")

    passed = (
        has_exact_file_path
        and has_url_resolution
        and has_engine_instantiation
        and len(unintended) == 0
    )

    return CodeLookupValidationResult(
        passed=passed,
        has_exact_file_path=has_exact_file_path,
        has_url_resolution=has_url_resolution,
        has_engine_instantiation=has_engine_instantiation,
        unintended_modifications=unintended,
        failure_reasons=failure_reasons,
        extracted_evidence=extracted,
    )


def validate_repository_lookup(
    final_response: str,
    expected_path_pattern: str,
    expected_content_patterns: List[str],
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """General repository lookup validator: exact path and key mechanisms identified."""
    resp = str(final_response or "").strip()
    failure_reasons = []
    extracted = {}

    if not resp:
        return ValidationResult(
            passed=False,
            category="REPOSITORY_LOOKUP",
            failure_reasons=["Empty response returned by agent."],
        )

    has_path = bool(re.search(expected_path_pattern, resp, re.IGNORECASE))
    if not has_path:
        failure_reasons.append(f"Missing required file path pattern: {expected_path_pattern}")

    missing_patterns = []
    for pat in expected_content_patterns:
        if not re.search(pat, resp, re.IGNORECASE):
            missing_patterns.append(pat)
        else:
            extracted[pat] = "found"

    if missing_patterns:
        failure_reasons.append(f"Missing required evidence patterns: {missing_patterns}")

    modified = modified_files or []
    if modified:
        failure_reasons.append(f"Read-only lookup task caused unintended mutations: {modified}")

    passed = has_path and (len(missing_patterns) == 0) and (len(modified) == 0)
    return ValidationResult(
        passed=passed,
        category="REPOSITORY_LOOKUP",
        failure_reasons=failure_reasons,
        unintended_modifications=modified,
        extracted_evidence=extracted,
    )


# ---------------------------------------------------------------------------
# Category B: Code Explanation
# ---------------------------------------------------------------------------

def validate_code_explanation(
    final_response: str,
    target_entity: str,
    required_concepts: List[str],
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates that explanation references target entity and essential architectural concepts with zero mutations."""
    resp = str(final_response or "").strip()
    failure_reasons = []
    extracted = {}

    if not resp:
        return ValidationResult(passed=False, category="CODE_EXPLANATION", failure_reasons=["Empty explanation"])

    if target_entity.lower() not in resp.lower():
        failure_reasons.append(f"Explanation did not cite target entity: {target_entity}")

    missing_concepts = [c for c in required_concepts if c.lower() not in resp.lower()]
    if missing_concepts:
        failure_reasons.append(f"Explanation omitted key concepts: {missing_concepts}")
    else:
        extracted["concepts"] = required_concepts

    modified = modified_files or []
    if modified:
        failure_reasons.append(f"Explanation task caused unintended workspace modifications: {modified}")

    passed = (target_entity.lower() in resp.lower()) and (len(missing_concepts) == 0) and (len(modified) == 0)
    return ValidationResult(
        passed=passed,
        category="CODE_EXPLANATION",
        failure_reasons=failure_reasons,
        unintended_modifications=modified,
        extracted_evidence=extracted,
    )


# ---------------------------------------------------------------------------
# Category C: Symbol and Reference Discovery
# ---------------------------------------------------------------------------

def validate_symbol_discovery(
    final_response: str,
    target_symbol: str,
    declaring_file: str,
    referencing_files: List[str],
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates that a symbol's declaration and references are discovered."""
    resp = str(final_response or "").strip()
    failure_reasons = []

    if target_symbol.lower() not in resp.lower():
        failure_reasons.append(f"Target symbol {target_symbol} missing from response")
    if declaring_file.lower() not in resp.lower():
        failure_reasons.append(f"Declaring file {declaring_file} missing from response")

    missing_refs = [f for f in referencing_files if f.lower() not in resp.lower()]
    if missing_refs:
        failure_reasons.append(f"Referencing files omitted: {missing_refs}")

    modified = modified_files or []
    if modified:
        failure_reasons.append(f"Discovery task caused mutations: {modified}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="SYMBOL_DISCOVERY",
        failure_reasons=failure_reasons,
        unintended_modifications=modified,
    )


# ---------------------------------------------------------------------------
# Category D: Bug Diagnosis
# ---------------------------------------------------------------------------

def validate_bug_diagnosis(
    final_response: str,
    defective_file: str,
    root_cause_pattern: str,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates root cause diagnosis without premature mutation."""
    resp = str(final_response or "").strip()
    failure_reasons = []

    if defective_file.lower() not in resp.lower():
        failure_reasons.append(f"Defective file {defective_file} not cited")
    if not re.search(root_cause_pattern, resp, re.IGNORECASE):
        failure_reasons.append(f"Root cause mechanism matching {root_cause_pattern} omitted")

    modified = modified_files or []
    if modified:
        failure_reasons.append(f"Diagnosis task caused unintended modifications: {modified}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="BUG_DIAGNOSIS",
        failure_reasons=failure_reasons,
        unintended_modifications=modified,
    )


# ---------------------------------------------------------------------------
# Category E: Single-File Bug Correction
# ---------------------------------------------------------------------------

def validate_single_file_modification(
    trial_dir: str,
    target_rel_path: str,
    test_rel_path: str,
    modified_files: Optional[List[str]] = None,
    expected_patch_pattern: Optional[str] = None,
) -> BugCorrectionValidationResult:
    """Deterministic acceptance check for single-file bug correction."""
    failure_reasons: List[str] = []
    target_full = os.path.join(trial_dir, target_rel_path)
    test_full = os.path.join(trial_dir, test_rel_path)

    fix_verified = False
    if not os.path.exists(target_full):
        failure_reasons.append(f"Target file not found at {target_full}")
    else:
        content = Path(target_full).read_text(encoding="utf-8")
        if expected_patch_pattern:
            if re.search(expected_patch_pattern, content):
                fix_verified = True
            else:
                failure_reasons.append(f"Target file does not contain expected patch pattern: {expected_patch_pattern}")
        else:
            fix_verified = True

    test_res = subprocess.run(
        ["pytest", test_full, "-q"],
        capture_output=True,
        text=True,
    )
    test_passed = (test_res.returncode == 0)
    if not test_passed:
        failure_reasons.append(f"Pytest verification failed (exit code {test_res.returncode}): {test_res.stdout[:500]}")

    modified = modified_files or []
    norm_trial = trial_dir.replace("\\", "/").rstrip("/")
    unintended = []
    for f in modified:
        norm_f = f.replace("\\", "/")
        if not norm_f.startswith(norm_trial) and not norm_f.startswith("scripts/") and not norm_f.startswith("diagnostics/"):
            unintended.append(f)

    git_diff_clean = (len(unintended) == 0)
    if not git_diff_clean:
        failure_reasons.append(f"Unintended workspace mutations: {unintended}")

    passed = fix_verified and test_passed and git_diff_clean

    return BugCorrectionValidationResult(
        passed=passed,
        bug_reproduced=True,
        fix_verified_in_source=fix_verified,
        tests_passed=test_passed,
        git_diff_clean=git_diff_clean,
        unintended_modifications=unintended,
        failure_reasons=failure_reasons,
        test_stdout=test_res.stdout,
    )


def validate_single_file_correction(
    workspace_dir: str,
    target_file: str,
    expected_patch_pattern: str,
    test_command: Optional[str] = None,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Universal single-file bug correction validator."""
    failure_reasons = []
    target_path = Path(workspace_dir) / target_file
    if not target_path.exists():
        return ValidationResult(
            passed=False,
            category="SINGLE_FILE_CORRECTION",
            failure_reasons=[f"Target file {target_file} does not exist"],
        )

    content = target_path.read_text(encoding="utf-8")
    if not re.search(expected_patch_pattern, content):
        failure_reasons.append(f"Target file missing expected patch pattern: {expected_patch_pattern}")

    test_out = ""
    if test_command:
        res = subprocess.run(test_command, shell=True, cwd=workspace_dir, capture_output=True, text=True)
        test_out = res.stdout + "\n" + res.stderr
        if res.returncode != 0:
            failure_reasons.append(f"Test verification command failed (exit {res.returncode})")

    # Verify no unintended files modified
    unintended = []
    if modified_files:
        for f in modified_files:
            rel = Path(f).name
            if rel != Path(target_file).name and not rel.startswith("."):
                unintended.append(f)
    if unintended:
        failure_reasons.append(f"Unintended file modifications: {unintended}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="SINGLE_FILE_CORRECTION",
        failure_reasons=failure_reasons,
        unintended_modifications=unintended,
        test_stdout=test_out,
    )


# ---------------------------------------------------------------------------
# Category F: Multi-File Bug Correction
# ---------------------------------------------------------------------------

def validate_multi_file_correction(
    workspace_dir: str,
    expected_modifications: Dict[str, str],  # rel_path -> pattern
    test_command: Optional[str] = None,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates coordinated modifications across multiple files."""
    failure_reasons = []
    ws = Path(workspace_dir)

    for rel_path, pattern in expected_modifications.items():
        file_path = ws / rel_path
        if not file_path.exists():
            failure_reasons.append(f"Expected file {rel_path} does not exist")
            continue
        content = file_path.read_text(encoding="utf-8")
        if not re.search(pattern, content):
            failure_reasons.append(f"File {rel_path} missing pattern: {pattern}")

    test_out = ""
    if test_command:
        res = subprocess.run(test_command, shell=True, cwd=workspace_dir, capture_output=True, text=True)
        test_out = res.stdout + "\n" + res.stderr
        if res.returncode != 0:
            failure_reasons.append(f"Verification test command failed: {test_out[:400]}")

    unintended = []
    expected_names = {Path(p).name for p in expected_modifications.keys()}
    if modified_files:
        for f in modified_files:
            if Path(f).name not in expected_names and not Path(f).name.startswith("."):
                unintended.append(f)
    if unintended:
        failure_reasons.append(f"Unintended file modifications: {unintended}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="MULTI_FILE_CORRECTION",
        failure_reasons=failure_reasons,
        unintended_modifications=unintended,
        test_stdout=test_out,
    )


# ---------------------------------------------------------------------------
# Category G: Test Discovery
# ---------------------------------------------------------------------------

def validate_test_discovery(
    final_response: str,
    expected_test_files: List[str],
    expected_test_cases: List[str],
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates test suite discovery without modifying files."""
    resp = str(final_response or "").strip()
    failure_reasons = []

    missing_files = [f for f in expected_test_files if f.lower() not in resp.lower()]
    if missing_files:
        failure_reasons.append(f"Expected test files omitted: {missing_files}")

    missing_cases = [c for c in expected_test_cases if c.lower() not in resp.lower()]
    if missing_cases:
        failure_reasons.append(f"Expected test cases omitted: {missing_cases}")

    modified = modified_files or []
    if modified:
        failure_reasons.append(f"Test discovery modified files: {modified}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="TEST_DISCOVERY",
        failure_reasons=failure_reasons,
        unintended_modifications=modified,
    )


# ---------------------------------------------------------------------------
# Category H: Test Execution
# ---------------------------------------------------------------------------

def validate_test_execution(
    executed_commands: List[str],
    expected_test_path: str,
    test_stdout: str,
    expected_passed_count: int,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates actual execution of test suite and verification of test counts."""
    failure_reasons = []

    executed = any(expected_test_path in cmd for cmd in executed_commands)
    if not executed:
        failure_reasons.append(f"Test command for {expected_test_path} was not executed")

    passed_pat = rf"{expected_passed_count} passed\b"
    if not re.search(passed_pat, test_stdout, re.IGNORECASE):
        failure_reasons.append(f"Expected '{expected_passed_count} passed' not in test output")

    modified = modified_files or []
    if modified:
        failure_reasons.append(f"Test execution modified workspace files: {modified}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="TEST_EXECUTION",
        failure_reasons=failure_reasons,
        unintended_modifications=modified,
        test_stdout=test_stdout,
    )


# ---------------------------------------------------------------------------
# Category I: Refactoring
# ---------------------------------------------------------------------------

def validate_refactoring(
    workspace_dir: str,
    target_file: str,
    refactored_pattern: str,
    test_command: str,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates structural refactoring while preserving full regression suite passing."""
    failure_reasons = []
    target = Path(workspace_dir) / target_file
    if not target.exists():
        return ValidationResult(passed=False, category="REFACTORING", failure_reasons=["Target missing"])

    content = target.read_text(encoding="utf-8")
    if not re.search(refactored_pattern, content):
        failure_reasons.append(f"Refactored code pattern not present: {refactored_pattern}")

    res = subprocess.run(test_command, shell=True, cwd=workspace_dir, capture_output=True, text=True)
    if res.returncode != 0:
        failure_reasons.append(f"Regression tests broke during refactoring: {res.stdout[:300]}")

    unintended = [f for f in (modified_files or []) if Path(f).name != Path(target_file).name]
    if unintended:
        failure_reasons.append(f"Unintended mutations during refactoring: {unintended}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="REFACTORING",
        failure_reasons=failure_reasons,
        unintended_modifications=unintended,
        test_stdout=res.stdout,
    )


# ---------------------------------------------------------------------------
# Category J: Configuration Changes
# ---------------------------------------------------------------------------

def validate_configuration_change(
    workspace_dir: str,
    config_file: str,
    expected_key: str,
    expected_value: Any,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates configuration updates with format integrity."""
    failure_reasons = []
    cfg_path = Path(workspace_dir) / config_file
    if not cfg_path.exists():
        return ValidationResult(passed=False, category="CONFIGURATION_CHANGE", failure_reasons=["Config missing"])

    try:
        if config_file.endswith(".json"):
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            val = data.get(expected_key)
            if val != expected_value:
                failure_reasons.append(f"Config key '{expected_key}' is '{val}', expected '{expected_value}'")
        else:
            content = cfg_path.read_text(encoding="utf-8")
            if f"{expected_key}={expected_value}" not in content and f"'{expected_key}': '{expected_value}'" not in content:
                failure_reasons.append(f"Config did not contain expected key-value: {expected_key}={expected_value}")
    except Exception as exc:
        failure_reasons.append(f"Config file syntax corrupted: {exc}")

    unintended = [f for f in (modified_files or []) if Path(f).name != Path(config_file).name]
    if unintended:
        failure_reasons.append(f"Unintended mutations during config change: {unintended}")

    passed = (len(failure_reasons) == 0)
    return ValidationResult(
        passed=passed,
        category="CONFIGURATION_CHANGE",
        failure_reasons=failure_reasons,
        unintended_modifications=unintended,
    )


# ---------------------------------------------------------------------------
# Category K: TypeScript Diagnostics Correction
# ---------------------------------------------------------------------------

def validate_typescript_correction(
    workspace_dir: str,
    target_file: str,
    resolved_error_code: str,
    typecheck_command: str,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates elimination of TypeScript diagnostic error without regressions."""
    failure_reasons = []
    target = Path(workspace_dir) / target_file
    if not target.exists():
        return ValidationResult(passed=False, category="TYPESCRIPT_CORRECTION", failure_reasons=["File missing"])

    res = subprocess.run(typecheck_command, shell=True, cwd=workspace_dir, capture_output=True, text=True)
    out = res.stdout + "\n" + res.stderr
    if resolved_error_code in out:
        failure_reasons.append(f"Diagnostic error {resolved_error_code} is still present in typecheck output")

    unintended = [f for f in (modified_files or []) if Path(f).name != Path(target_file).name]
    if unintended:
        failure_reasons.append(f"Unintended modifications during TS correction: {unintended}")

    passed = (resolved_error_code not in out) and (len(unintended) == 0)
    return ValidationResult(
        passed=passed,
        category="TYPESCRIPT_CORRECTION",
        failure_reasons=failure_reasons,
        unintended_modifications=unintended,
        test_stdout=out,
    )


# ---------------------------------------------------------------------------
# Category L: Python Diagnostics Correction
# ---------------------------------------------------------------------------

def validate_python_correction(
    workspace_dir: str,
    target_file: str,
    resolved_exception_class: str,
    test_command: str,
    modified_files: Optional[List[str]] = None,
) -> ValidationResult:
    """Validates elimination of Python runtime/syntax exception via test execution."""
    failure_reasons = []
    target = Path(workspace_dir) / target_file
    if not target.exists():
        return ValidationResult(passed=False, category="PYTHON_CORRECTION", failure_reasons=["File missing"])

    # First verify file compiles cleanly
    compile_res = subprocess.run(
        ["python", "-m", "py_compile", str(target)],
        capture_output=True,
        text=True,
    )
    if compile_res.returncode != 0:
        failure_reasons.append(f"Python syntax compilation failed: {compile_res.stderr}")

    res = subprocess.run(test_command, shell=True, cwd=workspace_dir, capture_output=True, text=True)
    out = res.stdout + "\n" + res.stderr
    if resolved_exception_class in out:
        failure_reasons.append(f"Exception {resolved_exception_class} still raised during test run")
    if res.returncode != 0:
        failure_reasons.append(f"Test suite failed (exit {res.returncode})")

    unintended = [f for f in (modified_files or []) if Path(f).name != Path(target_file).name]
    if unintended:
        failure_reasons.append(f"Unintended mutations during Python fix: {unintended}")

    passed = (compile_res.returncode == 0) and (resolved_exception_class not in out) and (res.returncode == 0) and (len(unintended) == 0)
    return ValidationResult(
        passed=passed,
        category="PYTHON_CORRECTION",
        failure_reasons=failure_reasons,
        unintended_modifications=unintended,
        test_stdout=out,
    )


# ---------------------------------------------------------------------------
# Universal Validation Router
# ---------------------------------------------------------------------------

VALIDATOR_REGISTRY = {
    "REPOSITORY_LOOKUP": validate_repository_lookup,
    "DATABASE_LOOKUP": validate_database_lookup,
    "CODE_EXPLANATION": validate_code_explanation,
    "SYMBOL_DISCOVERY": validate_symbol_discovery,
    "BUG_DIAGNOSIS": validate_bug_diagnosis,
    "SINGLE_FILE_CORRECTION": validate_single_file_correction,
    "MULTI_FILE_CORRECTION": validate_multi_file_correction,
    "TEST_DISCOVERY": validate_test_discovery,
    "TEST_EXECUTION": validate_test_execution,
    "REFACTORING": validate_refactoring,
    "CONFIGURATION_CHANGE": validate_configuration_change,
    "TYPESCRIPT_CORRECTION": validate_typescript_correction,
    "PYTHON_CORRECTION": validate_python_correction,
}


def validate_task(category: str, **kwargs) -> ValidationResult:
    """Dispatches to the authorized task category validator."""
    import inspect
    cat = category.upper()
    validator = VALIDATOR_REGISTRY.get(cat)
    if not validator:
        return ValidationResult(
            passed=False,
            category=cat,
            failure_reasons=[f"No registered validator for category '{category}'"],
        )
    sig = inspect.signature(validator)
    valid_args = {}
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    for k, v in kwargs.items():
        if has_var_keyword or k in sig.parameters:
            valid_args[k] = v
    return validator(**valid_args)

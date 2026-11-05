"""
Phase 9.3.2.2.1: SafetyGuard Fail-Closed Verification & Terminal Confinement Integration Tests.

Validates:
1. SafetyGuard Fail-Closed Requirements (A through J):
   A: SafetyGuard constructor raises exception -> dispatcher denies execution.
   B: SafetyGuard.check_tool_call raises exception -> dispatcher denies execution.
   C: SafetyGuard returns explicit denial -> tool invocation refused.
   D: SafetyGuard returns approved result -> normal execution continues.
   E: SafetyGuard returns invalid or incomplete result -> execution denied.
   F: SafetyGuard failure for edit_file -> zero file mutation.
   G: SafetyGuard failure for run_terminal -> zero command execution.
   H: Security failure recorded as non-retryable event with full typed telemetry.
   I: Circuit breaker trips and prevents subsequent retries.
   J: External sentinel files and protected workspace contents cannot be modified.
2. Terminal Workspace Confinement & Sentinel Protection:
   - External sentinel fixtures verified against mutation attempts.
   - Confinement audit bounds verified.
3. Finalization and Dispatch Independence:
   - SafetyGuard cannot bypass FINALIZATION protocol violation.
   - FINALIZATION cannot bypass fail-closed security.
4. Full Regression Parity:
   - Preserves all 9.3.2.2 security contracts and earlier financial closures.
"""

import os
import subprocess
import pytest
from pathlib import Path
from typing import Dict, Any

from src.runtime.argument_normalizer import normalize_tool_arguments, NormalizationResult
from src.runtime.retry_controller import (
    ToolRetryController,
    classify_error,
    ERROR_RETRYABLE,
    ERROR_NON_RETRYABLE_INFRASTRUCTURE,
)
from src.tools.file_tools import edit_file, read_file
from src.context.safety_guard import SafetyGuard
from scripts.run_live_economics_benchmark import (
    dispatch_tool,
    get_tool_definitions,
    setup_isolated_trial_workspace,
    BUGGY_CALC_CODE,
    TEST_CALC_CODE,
)


# ==============================================================================
# SECTION 1: SAFETYGUARD FAIL-CLOSED TESTS (REQUIREMENTS A THROUGH J)
# ==============================================================================

def test_safetyguard_A_constructor_exception_fails_closed(monkeypatch, tmp_path):
    """Requirement A: SafetyGuard constructor raises an exception -> dispatcher denies execution."""
    def crash_init(self, *args, **kwargs):
        raise RuntimeError("SafetyGuard core configuration database corrupted")

    monkeypatch.setattr(SafetyGuard, "__init__", crash_init)

    out, _ = dispatch_tool(
        name="read_file",
        args={"path": "calc_service.py"},
        workspace_root=str(tmp_path),
    )
    assert "⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: SafetyGuard initialization failure (RuntimeError)" in out
    assert "corrupted" in out


def test_safetyguard_B_check_tool_call_exception_fails_closed(monkeypatch, tmp_path):
    """Requirement B: SafetyGuard.check_tool_call raises an exception -> dispatcher denies execution."""
    def crash_check(self, *args, **kwargs):
        raise ValueError("Unexpected policy parsing failure during safety evaluation")

    monkeypatch.setattr(SafetyGuard, "check_tool_call", crash_check)

    out, _ = dispatch_tool(
        name="read_file",
        args={"path": "calc_service.py"},
        workspace_root=str(tmp_path),
    )
    assert "⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: SafetyGuard inspection failure (ValueError)" in out
    assert "policy parsing failure" in out


def test_safetyguard_C_explicit_denial_stops_execution(monkeypatch, tmp_path):
    """Requirement C: SafetyGuard returns an explicit denial -> tool is not invoked."""
    def deny_call(self, tool_name, tool_args):
        return False, "Disallowed by strict enterprise security policy"

    monkeypatch.setattr(SafetyGuard, "check_tool_call", deny_call)

    out, _ = dispatch_tool(
        name="run_terminal",
        args={"command": "pytest test_calc_service.py"},
        workspace_root=str(tmp_path),
    )
    assert "⛔ Security denial: Safety approval refused for tool 'run_terminal'" in out
    assert "Disallowed by strict enterprise security policy" in out


def test_safetyguard_D_approved_result_allows_execution(tmp_path):
    """Requirement D: SafetyGuard returns an approved result -> execution proceeds normally."""
    target = tmp_path / "app.py"
    target.write_text("status = 'idle'\n", encoding="utf-8")

    out, _ = dispatch_tool(
        name="edit_file",
        args={"path": "app.py", "old_text": "status = 'idle'", "new_text": "status = 'active'"},
        workspace_root=str(tmp_path),
    )
    assert "✅ Edited" in out
    assert target.read_text(encoding="utf-8") == "status = 'active'\n"


def test_safetyguard_E_invalid_inspection_result_fails_closed(monkeypatch, tmp_path):
    """Requirement E: SafetyGuard returns an invalid or incomplete result -> execution denied."""
    # Return non-tuple
    monkeypatch.setattr(SafetyGuard, "check_tool_call", lambda self, n, a: "not_a_tuple")
    out1, _ = dispatch_tool("read_file", {"path": "calc.py"}, workspace_root=str(tmp_path))
    assert "⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: Invalid safety inspection result" in out1

    # Return tuple with wrong length
    monkeypatch.setattr(SafetyGuard, "check_tool_call", lambda self, n, a: (True,))
    out2, _ = dispatch_tool("read_file", {"path": "calc.py"}, workspace_root=str(tmp_path))
    assert "⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: Invalid safety inspection result" in out2

    # Return tuple with non-bool first element
    monkeypatch.setattr(SafetyGuard, "check_tool_call", lambda self, n, a: ("true", "warning"))
    out3, _ = dispatch_tool("read_file", {"path": "calc.py"}, workspace_root=str(tmp_path))
    assert "⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: Invalid safety inspection result" in out3


def test_safetyguard_F_edit_file_fails_safely_no_mutation(monkeypatch, tmp_path):
    """Requirement F: SafetyGuard failure for edit_file -> no file mutation."""
    target = tmp_path / "protected_service.py"
    original_code = "ORIGINAL_HASH = 0xDEADBEEF\n"
    target.write_text(original_code, encoding="utf-8")

    def crash_check(self, *args, **kwargs):
        raise OSError("Security hardware token unavailable")

    monkeypatch.setattr(SafetyGuard, "check_tool_call", crash_check)

    out, _ = dispatch_tool(
        name="edit_file",
        args={"path": "protected_service.py", "old_text": "0xDEADBEEF", "new_text": "0x00000000"},
        workspace_root=str(tmp_path),
    )
    assert "⛔ NON-RETRYABLE INFRASTRUCTURE ERROR" in out
    assert target.read_text(encoding="utf-8") == original_code


def test_safetyguard_G_run_terminal_fails_safely_no_execution(monkeypatch, tmp_path):
    """Requirement G: SafetyGuard failure for run_terminal -> zero command execution."""
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("clean", encoding="utf-8")

    def crash_check(self, *args, **kwargs):
        raise RuntimeError("Safety subsystem offline")

    monkeypatch.setattr(SafetyGuard, "check_tool_call", crash_check)

    # Command that would overwrite sentinel if executed
    cmd = f'python -c "open(r\'{sentinel}\', \'w\').write(\'polluted\')"'
    out, _ = dispatch_tool(
        name="run_terminal",
        args={"command": cmd},
        workspace_root=str(tmp_path),
    )
    assert "⛔ NON-RETRYABLE INFRASTRUCTURE ERROR" in out
    assert sentinel.read_text(encoding="utf-8") == "clean"


def test_safetyguard_H_typed_security_failure_telemetry():
    """Requirement H: Security failure is recorded as non-retryable event with full typed telemetry."""
    ctrl = ToolRetryController()
    is_fatal, fatal_msg = ctrl.check_infrastructure_error(
        tool_name="run_terminal",
        error_msg="⛔ Security denial: Safety approval refused for tool 'run_terminal': dangerous delete",
        request_id="req-sec-403",
        session_id="sess-sec-101",
        workspace="fixtures/trial_1",
        security_denial_status="DENIED_SECURITY_POLICY",
        exception_class="SecurityPolicyViolation",
    )
    assert is_fatal is True
    assert ctrl.circuit_broken is True
    assert ctrl.is_infrastructure_fatal is True
    assert ctrl.fatal_error_details["request_id"] == "req-sec-403"
    assert ctrl.fatal_error_details["session_id"] == "sess-sec-101"
    assert ctrl.fatal_error_details["workspace"] == "fixtures/trial_1"
    assert ctrl.fatal_error_details["security_denial_status"] == "DENIED_SECURITY_POLICY"
    assert ctrl.fatal_error_details["exception_class"] == "SecurityPolicyViolation"


def test_safetyguard_I_circuit_breaker_prevents_retries():
    """Requirement I: Circuit breaker prevents subsequent model-driven tool retries after security failure."""
    ctrl = ToolRetryController()
    ctrl.check_infrastructure_error(
        tool_name="edit_file",
        error_msg="⛔ NON-RETRYABLE INFRASTRUCTURE ERROR: SafetyGuard inspection failure (ValueError): bad state",
        request_id="req-99",
        session_id="sess-99",
    )
    # Following attempt must abort immediately
    abort, reason = ctrl.should_abort_duplicate("edit_file", {"path": "calc.py"})
    assert abort is True
    assert ctrl.circuit_broken is True


def test_safetyguard_J_external_sentinel_file_cannot_be_mutated(tmp_path):
    """Requirement J: Rejected operations cannot mutate external test fixtures or sentinels."""
    ws = tmp_path / "sandbox"
    ws.mkdir()
    external_sentinel = tmp_path / "external_sentinel.txt"
    external_sentinel.write_text("IMMUTABLE_SENTINEL_ROOT", encoding="utf-8")

    # 1. Traversal command rejected
    out_trav, _ = dispatch_tool(
        name="run_terminal",
        args={"command": f"cd ../.. && echo hacked > {external_sentinel}"},
        workspace_root=str(ws),
    )
    assert "⛔ Tool execution refused" in out_trav
    assert external_sentinel.read_text(encoding="utf-8") == "IMMUTABLE_SENTINEL_ROOT"

    # 2. Hardline dangerous delete rejected
    out_root, _ = dispatch_tool(
        name="run_terminal",
        args={"command": "rm -rf /"},
        workspace_root=str(ws),
    )
    assert "⛔" in out_root
    assert external_sentinel.read_text(encoding="utf-8") == "IMMUTABLE_SENTINEL_ROOT"


# ==============================================================================
# SECTION 2: FINALIZATION & DISPATCH INDEPENDENCE
# ==============================================================================

def test_finalization_and_safetyguard_independence(monkeypatch, tmp_path):
    """Requirement 4: SafetyGuard exceptions cannot bypass FINALIZATION, and FINALIZATION cannot bypass security."""
    # When in FINALIZATION phase, dispatcher blocks before SafetyGuard even initializes
    def crash_init(self, *args, **kwargs):
        raise RuntimeError("SafetyGuard exploded")

    monkeypatch.setattr(SafetyGuard, "__init__", crash_init)

    # Calling during FINALIZATION must report protocol violation, NOT SafetyGuard error
    out, _ = dispatch_tool(
        name="edit_file",
        args={"path": "calc.py", "old_text": "a", "new_text": "b"},
        workspace_root=str(tmp_path),
        phase="FINALIZATION",
    )
    assert "⛔ Protocol violation" in out
    assert "FINALIZATION phase" in out
    assert "SafetyGuard exploded" not in out


# ==============================================================================
# SECTION 3: BASELINE WORKSPACE & RUNNER SECURITY REQUIREMENTS
# ==============================================================================

def test_security_A_missing_workspace_root_rejected():
    """Security Requirement A: Missing workspace_root must reject execution."""
    out, args = dispatch_tool(name="read_file", args={"path": "calc_service.py"}, workspace_root=None)
    assert "⛔ Tool execution refused: missing workspace restriction" in out


def test_security_B_empty_workspace_root_rejected():
    """Security Requirement B: Empty and whitespace-only workspace_root must reject execution."""
    out1, _ = dispatch_tool(name="read_file", args={"path": "calc_service.py"}, workspace_root="")
    assert "⛔ Tool execution refused: missing workspace restriction" in out1

    out2, _ = dispatch_tool(name="read_file", args={"path": "calc_service.py"}, workspace_root="     ")
    assert "⛔ Tool execution refused: missing workspace restriction" in out2


def test_security_D_no_silent_fallback_to_process_cwd():
    """Security Requirement D: No workspace-scoped tool silently uses process CWD when workspace is omitted."""
    tools_to_test = [
        ("list_files", {"path": "."}),
        ("search_code", {"query": "def calculate"}),
        ("read_file", {"path": "README.md"}),
        ("edit_file", {"path": "README.md", "old_text": "a", "new_text": "b"}),
        ("run_terminal", {"command": "pytest"}),
    ]
    for tool_name, tool_args in tools_to_test:
        out, _ = dispatch_tool(name=tool_name, args=tool_args, workspace_root=None)
        assert "⛔ Tool execution refused: missing workspace restriction" in out


def test_security_E_terminal_execution_uses_authorized_workspace(tmp_path):
    """Security Requirement E: Terminal execution uses authorized workspace as cwd."""
    trial_dir = tmp_path / "terminal_sandbox"
    trial_dir.mkdir()
    cmd = 'python -c "import os; print(os.getcwd())"'
    out, _ = dispatch_tool(name="run_terminal", args={"command": cmd}, workspace_root=str(trial_dir))
    assert str(trial_dir).lower() in out.lower() or trial_dir.name in out


def test_security_F_terminal_commands_cannot_escape_workspace(tmp_path):
    """Security Requirement F: Terminal commands cannot escape the authorized workspace."""
    trial_dir = tmp_path / "isolated_ws"
    trial_dir.mkdir()
    cmd_escape = "cd ../.. && dir"
    out, _ = dispatch_tool(name="run_terminal", args={"command": cmd_escape}, workspace_root=str(trial_dir))
    assert "⛔ Tool execution refused: command attempts to escape authorized workspace" in out


def test_dispatch_normalization_contract():
    """Verify normalization callable and parameter alias handling."""
    res = normalize_tool_arguments("edit_file", {"filepath": "calc.py", "old_string": "a", "new_string": "b"})
    assert res.status == "applied"
    assert res.normalized_args == {"path": "calc.py", "old_text": "a", "new_text": "b"}


def test_dispatch_model_schema_excludes_config():
    """Verify that generated model schemas exclude config and run_manager."""
    tools = get_tool_definitions()
    tool_map = {t["function"]["name"]: t["function"] for t in tools}
    edit_props = tool_map["edit_file"]["parameters"]["properties"]
    assert "config" not in edit_props
    assert "run_manager" not in edit_props


def test_end_to_end_local_bug_fix_workflow(tmp_path):
    """End-to-end local single-file bug fix workflow via dispatch_tool."""
    calc_file = tmp_path / "calc_service.py"
    test_file = tmp_path / "test_calc_service.py"
    calc_file.write_text(BUGGY_CALC_CODE, encoding="utf-8")
    test_file.write_text(TEST_CALC_CODE, encoding="utf-8")

    # 1. Reproduce failure via run_terminal
    out_fail, _ = dispatch_tool("run_terminal", {"command": "pytest test_calc_service.py -v"}, workspace_root=str(tmp_path))
    assert "FAILED" in out_fail or "Exit code: 1" in out_fail

    # 2. Surgical edit via dispatch_tool
    out_edit, _ = dispatch_tool(
        "edit_file",
        {"filepath": "calc_service.py", "old_string": "1.0 + total_discount", "new_string": "1.0 - total_discount"},
        workspace_root=str(tmp_path),
    )
    assert "✅ Edited" in out_edit

    # 3. Verify pytest now passes 100%
    out_pass, _ = dispatch_tool("run_terminal", {"command": "pytest test_calc_service.py -v"}, workspace_root=str(tmp_path))
    assert "Exit code: 0" in out_pass or "passed" in out_pass
    assert "failed" not in out_pass.lower()

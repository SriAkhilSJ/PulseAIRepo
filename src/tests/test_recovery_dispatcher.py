"""Unit Tests for ARRE RecoveryStrategyDispatcher (CrusorAI 2.1 - Phase 2.1).

Validates:
1. Supervised process relaunch on CrusorAI-owned ports.
2. Process relaunch failure and missing supervisor handling.
3. Bounded warmup polling on initializing services.
4. Rate limit backoff execution with Retry-After headers.
5. Exponential backoff with jitter on transient HTTP 5xx outages.
6. Ephemeral log drainage on disk exhaustion.
7. Owned subprocess termination and memory release on OOM.
8. Alternating mutation lock enforcement.
9. Strict fail-closed execution on unowned or auth failures.
10. Actionable prompt guidance generation.
"""
from pathlib import Path
import pytest

from src.runtime.recovery_dispatcher import (
    RecoveryExecutionResult,
    RecoveryStrategyDispatcher,
)
from src.runtime.recovery_engine import (
    FailureClassification,
    FailureClassifier,
    GlobalRecoveryBudgetTracker,
)


class MockDispatcherSupervisor:
    """Mock process supervisor for dispatcher execution tests."""

    def __init__(self, ports_state: dict[int, tuple[bool, bool]] = None):
        # port -> (is_alive, is_owned_by_crusorai)
        self.ports_state = ports_state or {}
        self.relaunched_ports: list[int] = []
        self.terminated_ports: list[int] = []
        self.cleaned_subprocesses: int = 0

    def inspect_port_owner(self, port: int) -> tuple[bool, bool]:
        return self.ports_state.get(port, (False, False))

    def relaunch_process(self, port: int) -> bool:
        if port == 9999:
            # Simulate failure to relaunch
            return False
        self.relaunched_ports.append(port)
        self.ports_state[port] = (True, True)
        return True

    def terminate_process(self, port: int) -> bool:
        self.terminated_ports.append(port)
        self.ports_state[port] = (False, True)
        return True

    def cleanup_owned_subprocesses(self) -> int:
        self.cleaned_subprocesses += 3
        return 3


# ==============================================================================
# 1. PROCESS RELAUNCH & WARMUP EXECUTION
# ==============================================================================

def test_dispatcher_relaunch_owned_service_success():
    supervisor = MockDispatcherSupervisor({8000: (False, True)})
    dispatcher = RecoveryStrategyDispatcher(process_supervisor=supervisor, apply_sleep=False)

    classification = FailureClassification(
        failure_class="service_not_running",
        is_retryable=True,
        max_additional_retries=1,
        recommended_strategy="relaunch_owned_service",
        diagnostic_message="Service is dead",
        metadata={"port": 8000, "is_owned": True},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert result.strategy_applied == "relaunch_owned_service"
    assert "Relaunched CrusorAI service on port 8000" in result.action_taken
    assert 8000 in supervisor.relaunched_ports


def test_dispatcher_relaunch_failure():
    supervisor = MockDispatcherSupervisor({9999: (False, True)})
    dispatcher = RecoveryStrategyDispatcher(process_supervisor=supervisor, apply_sleep=False)

    classification = FailureClassification(
        failure_class="service_not_running",
        is_retryable=True,
        max_additional_retries=1,
        recommended_strategy="relaunch_owned_service",
        diagnostic_message="Service is dead",
        metadata={"port": 9999, "is_owned": True},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is False
    assert "failed to relaunch" in result.action_taken


def test_dispatcher_relaunch_missing_supervisor():
    dispatcher = RecoveryStrategyDispatcher(process_supervisor=None, apply_sleep=False)

    classification = FailureClassification(
        failure_class="service_not_running",
        is_retryable=True,
        max_additional_retries=1,
        recommended_strategy="relaunch_owned_service",
        diagnostic_message="Service is dead",
        metadata={"port": 8000},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is False
    assert "No ProcessSupervisor attached" in result.action_taken


def test_dispatcher_bounded_warmup_poll():
    supervisor = MockDispatcherSupervisor({8000: (True, True)})
    dispatcher = RecoveryStrategyDispatcher(process_supervisor=supervisor, apply_sleep=False)

    classification = FailureClassification(
        failure_class="network_warmup_delay",
        is_retryable=True,
        max_additional_retries=2,
        recommended_strategy="bounded_warmup_poll",
        diagnostic_message="Warming up",
        metadata={"port": 8000, "is_owned": True},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert "Polled service warmup on port 8000" in result.action_taken


# ==============================================================================
# 2. BACKOFF & RETRY-AFTER EXECUTION
# ==============================================================================

def test_dispatcher_respect_retry_after():
    dispatcher = RecoveryStrategyDispatcher(apply_sleep=False, max_backoff_seconds=10.0)

    classification = FailureClassification(
        failure_class="provider_rate_limit",
        is_retryable=True,
        max_additional_retries=4,
        recommended_strategy="respect_retry_after_or_backoff",
        diagnostic_message="Rate limit 429",
        metadata={"retry_after_seconds": 5.0, "attempt": 1},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert "delay of 5.00s" in result.action_taken


def test_dispatcher_exponential_backoff_jitter():
    dispatcher = RecoveryStrategyDispatcher(apply_sleep=False, max_backoff_seconds=16.0)

    classification = FailureClassification(
        failure_class="provider_transient_error",
        is_retryable=True,
        max_additional_retries=3,
        recommended_strategy="exponential_backoff_jitter",
        diagnostic_message="503 Outage",
        metadata={"backoff_base_s": 2.0, "attempt": 2},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert "exponential backoff with jitter" in result.action_taken


# ==============================================================================
# 3. RESOURCE DRAINAGE & CLEANUP
# ==============================================================================

def test_dispatcher_drain_eligible_logs(tmp_path: Path):
    logs_dir = tmp_path / ".crusorai" / "logs"
    logs_dir.mkdir(parents=True)
    test_log = logs_dir / "debug.log"
    test_log.write_text("lots of ephemeral log data here...")

    dispatcher = RecoveryStrategyDispatcher(workspace_root=tmp_path, apply_sleep=False)

    classification = FailureClassification(
        failure_class="disk_exhaustion",
        is_retryable=True,
        max_additional_retries=1,
        recommended_strategy="drain_eligible_logs",
        diagnostic_message="Disk full",
        metadata={},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert result.metadata["drained_files"] == 1
    assert result.metadata["drained_bytes"] > 0
    assert test_log.read_text() == ""  # Truncated safely


def test_dispatcher_memory_exhaustion_cleanup():
    supervisor = MockDispatcherSupervisor()
    dispatcher = RecoveryStrategyDispatcher(process_supervisor=supervisor, apply_sleep=False)

    classification = FailureClassification(
        failure_class="memory_exhaustion",
        is_retryable=False,
        max_additional_retries=0,
        recommended_strategy="terminate_owned_subprocesses_and_release",
        diagnostic_message="Out of memory",
        metadata={},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert supervisor.cleaned_subprocesses == 3
    assert "Terminated 3 CrusorAI-owned subprocesses" in result.action_taken


# ==============================================================================
# 4. MUTATION LOCK & PROMPT GUIDANCE
# ==============================================================================

def test_dispatcher_alternating_mutation_lock():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="assertion_failure",
        is_retryable=True,
        max_additional_retries=3,
        recommended_strategy="alternating_mutation_lock",
        diagnostic_message="Test assertion failed",
        metadata={},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert "alternating mutation lock" in result.action_taken
    assert "edit the relevant source code" in result.next_instruction


def test_dispatcher_prompt_guidance():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="ast_diagnostic_feedback",
        is_retryable=True,
        max_additional_retries=3,
        recommended_strategy="ast_diagnostic_feedback",
        diagnostic_message="Line 42: IndentationError",
        metadata={},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert "Line 42: IndentationError" in result.next_instruction


# ==============================================================================
# 5. STRICT FAIL-CLOSED STRATEGIES
# ==============================================================================

def test_dispatcher_fail_closed_enforcement():
    dispatcher = RecoveryStrategyDispatcher()

    for strategy in [
        "fail_fast_auth",
        "diagnose_invalid_request",
        "unowned_process_fail_closed",
        "fail_closed_non_idempotent",
        "fail_closed_unknown_port",
        "audit_trail_fail_closed",
    ]:
        classification = FailureClassification(
            failure_class="test_fail_closed",
            is_retryable=False,
            max_additional_retries=0,
            recommended_strategy=strategy,
            diagnostic_message=f"Halt on {strategy}",
            metadata={},
        )
        result = dispatcher.dispatch(classification)
        assert result.success is False
        assert "Fail-closed enforced" in result.action_taken


# ==============================================================================
# 6. LANGGRAPH & RUNTIME LIFECYCLE INTEGRATION
# ==============================================================================

def test_safe_tool_node_arre_interceptor_executes_recovery_and_enforces_budget():
    from langchain_core.messages import ToolMessage
    from src.runtime.factory import get_runtime_services

    session_id = "test-langgraph-arre-session"
    services = get_runtime_services()
    tracker = services.recovery_budgets.get_tracker(session_id)
    # Configure low budget ceiling of 2 attempts
    tracker.max_total_attempts = 2

    # Simulate an error ToolMessage from a tool execution
    msg_err = ToolMessage(
        content="SyntaxError: invalid syntax (main.py, line 10)",
        tool_call_id="call_err_1",
        name="edit_file",
        status="error",
    )

    # 1. First error: budget permits recovery
    permitted, reason = tracker.try_reserve_recovery_attempt("edit_file:syntax_error")
    assert permitted is True

    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassifier.classify_error("edit_file", msg_err.content)
    exec_res = dispatcher.dispatch(classification)
    assert exec_res.success is True
    assert "ast_diagnostic_feedback" in exec_res.action_taken

    # 2. Second error: budget permits recovery
    permitted2, _ = tracker.try_reserve_recovery_attempt("read_file:schema_argument_error")
    assert permitted2 is True

    # 3. Third error: budget exceeded -> halts automated retries!
    permitted3, reason3 = tracker.try_reserve_recovery_attempt("edit_file:syntax_error")
    assert permitted3 is False
    assert "GLOBAL_RECOVERY_LIMIT_EXCEEDED" in reason3


def test_recovery_budget_state_dict_restores_without_counter_reset():
    from src.runtime.factory import get_runtime_services

    session_id = "test-session-persistence-check"
    services = get_runtime_services()
    tracker = services.recovery_budgets.get_tracker(session_id)
    tracker.try_reserve_recovery_attempt("first_fail")
    tracker.try_reserve_recovery_attempt("second_fail")
    saved_state = tracker.to_dict()
    assert saved_state["total_attempts"] == 2

    # Clear registry memory to simulate a process restart or resumed thread
    services.recovery_budgets.reset_for_tests()

    # Re-obtain tracker with saved state
    restored = services.recovery_budgets.get_tracker(session_id, state_dict=saved_state)
    assert restored.get_stats()["total_attempts"] == 2
    assert len(restored.to_dict()["failure_history"]) == 2

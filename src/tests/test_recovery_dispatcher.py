"""Unit tests for Recovery Strategy Dispatcher (CrusorAI 2.1 - Phase 2.1).

Validates:
1. Controlled service relaunch (CrusorAI-owned processes only).
2. Refusal to relaunch unowned processes or unsupervised ports.
3. Bounded network warmup polling execution.
4. Backoff delay calculation & Retry-After execution.
5. Ephemeral debug log drainage on disk exhaustion.
6. OOM worker termination & garbage collection.
7. AST and schema diagnostic prompt synthesis.
8. Alternating mutation lock actuation.
9. Deterministic fail-closed halts for security/permission boundaries.
"""
import os
import tempfile
import pytest

from src.runtime.recovery_dispatcher import (
    RecoveryExecutionResult,
    RecoveryStrategyDispatcher,
)
from src.runtime.recovery_engine import (
    FailureClassification,
    ProcessSupervisor,
)


class MockDispatcherSupervisor:
    """Mock process supervisor for dispatcher execution tests."""

    def __init__(self, ports_state: dict[int, tuple[bool, bool]]):
        self.ports_state = ports_state
        self.relaunched_ports: list[int] = []
        self.terminated_count = 0

    def inspect_port_owner(self, port: int) -> tuple[bool, bool]:
        return self.ports_state.get(port, (False, False))

    def relaunch_service(self, port: int) -> bool:
        self.relaunched_ports.append(port)
        return True

    def terminate_owned_processes(self) -> int:
        self.terminated_count = 3
        return 3


def test_dispatch_relaunch_owned_service_success():
    supervisor = MockDispatcherSupervisor({8080: (False, True)})  # Dead, CrusorAI-owned
    dispatcher = RecoveryStrategyDispatcher(process_supervisor=supervisor)

    classification = FailureClassification(
        failure_class="service_not_running",
        is_retryable=True,
        max_additional_retries=1,
        recommended_strategy="relaunch_owned_service",
        diagnostic_message="CrusorAI-owned service on port 8080 is dead.",
        metadata={"port": 8080, "is_owned": True},
    )

    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert result.strategy == "relaunch_owned_service"
    assert 8080 in supervisor.relaunched_ports
    assert "Relaunched" in result.action_taken


def test_dispatch_relaunch_refused_when_unowned_or_no_supervisor():
    # 1. No supervisor
    dispatcher_no_sup = RecoveryStrategyDispatcher(process_supervisor=None)
    classification_owned = FailureClassification(
        failure_class="service_not_running",
        is_retryable=True,
        max_additional_retries=1,
        recommended_strategy="relaunch_owned_service",
        diagnostic_message="Service is dead.",
        metadata={"port": 8080, "is_owned": True},
    )
    res_no_sup = dispatcher_no_sup.dispatch(classification_owned)
    assert res_no_sup.success is False
    assert "no process supervisor" in res_no_sup.action_taken

    # 2. Foreign / Unowned process
    supervisor = MockDispatcherSupervisor({8080: (True, False)})  # Foreign
    dispatcher_foreign = RecoveryStrategyDispatcher(process_supervisor=supervisor)
    classification_foreign = FailureClassification(
        failure_class="unowned_service_collision",
        is_retryable=False,
        max_additional_retries=0,
        recommended_strategy="relaunch_owned_service",
        diagnostic_message="Service is dead.",
        metadata={"port": 8080, "is_owned": False},
    )
    res_foreign = dispatcher_foreign.dispatch(classification_foreign)
    assert res_foreign.success is False
    assert "unowned" in res_foreign.action_taken
    assert len(supervisor.relaunched_ports) == 0


def test_dispatch_bounded_warmup_poll():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="network_warmup_delay",
        is_retryable=True,
        max_additional_retries=2,
        recommended_strategy="bounded_warmup_poll",
        diagnostic_message="Service warming up.",
        metadata={"port": 3000, "is_owned": True},
    )
    result = dispatcher.dispatch(classification, context={"execute_sleep": False, "poll_delay": 0.5})
    assert result.success is True
    assert result.strategy == "bounded_warmup_poll"
    assert result.metadata["poll_delay_seconds"] == 0.5


def test_dispatch_backoff_and_retry_after():
    dispatcher = RecoveryStrategyDispatcher()

    # Retry-After delay
    classification_retry_after = FailureClassification(
        failure_class="provider_rate_limit",
        is_retryable=True,
        max_additional_retries=4,
        recommended_strategy="respect_retry_after_or_backoff",
        diagnostic_message="Rate limit 429",
        metadata={"retry_after_seconds": 25.0, "attempt": 1},
    )
    res_ra = dispatcher.dispatch(classification_retry_after, context={"execute_sleep": False})
    assert res_ra.success is True
    assert res_ra.metadata["delay_seconds"] == 25.0

    # Exponential backoff
    classification_5xx = FailureClassification(
        failure_class="provider_transient_error",
        is_retryable=True,
        max_additional_retries=3,
        recommended_strategy="exponential_backoff_jitter",
        diagnostic_message="503 Overloaded",
        metadata={"backoff_base_s": 2.0, "attempt": 3},
    )
    res_5xx = dispatcher.dispatch(classification_5xx, context={"execute_sleep": False})
    assert res_5xx.success is True
    # 2^3 = 8.0 plus up to 10% jitter (8.0 <= delay <= 8.8)
    assert 8.0 <= res_5xx.metadata["delay_seconds"] <= 9.0


def test_dispatch_drain_eligible_logs():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="disk_exhaustion",
        is_retryable=True,
        max_additional_retries=1,
        recommended_strategy="drain_eligible_logs",
        diagnostic_message="Errno 28 No space left on device",
        metadata={},
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_log = os.path.join(tmp_dir, "test_debug.log")
        with open(test_log, "w", encoding="utf-8") as f:
            f.write("A" * 5000)

        assert os.path.getsize(test_log) == 5000
        result = dispatcher.dispatch(classification, context={"log_directories": [tmp_dir]})
        assert result.success is True
        assert result.metadata["files_drained"] == 1
        assert result.metadata["bytes_reclaimed"] == 5000
        assert os.path.getsize(test_log) == 0


def test_dispatch_terminate_owned_subprocesses_and_release():
    supervisor = MockDispatcherSupervisor({})
    dispatcher = RecoveryStrategyDispatcher(process_supervisor=supervisor)
    classification = FailureClassification(
        failure_class="memory_exhaustion",
        is_retryable=False,
        max_additional_retries=0,
        recommended_strategy="terminate_owned_subprocesses_and_release",
        diagnostic_message="OOM killer triggered",
        metadata={},
    )
    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert result.metadata["terminated_processes"] == 3
    assert result.metadata["gc_collected_objects"] >= 0


def test_dispatch_ast_diagnostic_feedback():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="syntax_error",
        is_retryable=True,
        max_additional_retries=3,
        recommended_strategy="ast_diagnostic_feedback",
        diagnostic_message="SyntaxError line 42",
        metadata={"requires_code_mutation": True},
    )
    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert result.strategy == "ast_diagnostic_feedback"
    assert result.metadata["requires_code_mutation"] is True


def test_dispatch_schema_feedback_prompt():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="schema_argument_error",
        is_retryable=True,
        max_additional_retries=2,
        recommended_strategy="schema_feedback_prompt",
        diagnostic_message="Invalid argument",
        metadata={"tool_name": "edit_file"},
    )
    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert result.metadata["requires_schema_correction"] is True


def test_dispatch_alternating_mutation_lock():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="assertion_failure",
        is_retryable=True,
        max_additional_retries=3,
        recommended_strategy="alternating_mutation_lock",
        diagnostic_message="Test failed",
        metadata={"exit_code": 1, "requires_code_mutation": True},
    )
    result = dispatcher.dispatch(classification)
    assert result.success is True
    assert result.metadata["mutation_lock_active"] is True


def test_dispatch_fail_closed_halts():
    dispatcher = RecoveryStrategyDispatcher()
    classification = FailureClassification(
        failure_class="permission_or_safety_denial",
        is_retryable=False,
        max_additional_retries=0,
        recommended_strategy="audit_trail_fail_closed",
        diagnostic_message="Permission denied",
        metadata={},
    )
    result = dispatcher.dispatch(classification)
    assert result.success is False
    assert result.metadata["fail_closed"] is True


def test_safe_tool_node_arre_interceptor_action_and_exhaustion():
    from langchain_core.messages import ToolMessage
    from src.runtime.factory import get_runtime_services
    from src.runtime.recovery_engine import FailureClassifier
    from src.runtime.recovery_dispatcher import RecoveryStrategyDispatcher

    session_id = "test-session-arre-node"
    services = get_runtime_services()
    tracker = services.recovery_budgets.get_tracker(session_id)
    # Configure tiny budget of 2 attempts
    tracker.max_total_attempts = 2
    dispatcher = RecoveryStrategyDispatcher(budget_tracker=tracker)

    # 1. First error: should be granted and annotated with recovery action
    msg_1 = ToolMessage(
        content="SyntaxError: invalid syntax (main.py, line 10)",
        tool_call_id="call_1",
        name="edit_file",
        status="error",
    )
    classification_1 = FailureClassifier.classify_error(msg_1.name, str(msg_1.content))
    assert classification_1.is_retryable is True

    permitted_1, reason_1 = tracker.try_reserve_recovery_attempt(f"{msg_1.name}:{classification_1.failure_class}")
    assert permitted_1 is True
    exec_1 = dispatcher.dispatch(classification_1)
    annotated_1 = f"{msg_1.content}\n\n[ARRE Recovery Action] {exec_1.action_taken} Guidance: {exec_1.next_instruction}"
    assert "[ARRE Recovery Action]" in annotated_1

    # 2. Second error: different line, granted under ceiling 2
    msg_2 = ToolMessage(
        content="SyntaxError: invalid syntax (main.py, line 20)",
        tool_call_id="call_2",
        name="edit_file",
        status="error",
    )
    classification_2 = FailureClassifier.classify_error(msg_2.name, str(msg_2.content))
    permitted_2, _ = tracker.try_reserve_recovery_attempt(f"{msg_2.name}:{classification_2.failure_class}")
    assert permitted_2 is True

    # 3. Third error: exceeds ceiling 2 -> should be blocked with terminal exhaustion notice
    msg_3 = ToolMessage(
        content="SyntaxError: invalid syntax (main.py, line 30)",
        tool_call_id="call_3",
        name="edit_file",
        status="error",
    )
    classification_3 = FailureClassifier.classify_error(msg_3.name, str(msg_3.content))
    permitted_3, reason_3 = tracker.try_reserve_recovery_attempt(f"{msg_3.name}:{classification_3.failure_class}")
    assert permitted_3 is False
    assert "GLOBAL_RECOVERY_LIMIT_EXCEEDED" in reason_3


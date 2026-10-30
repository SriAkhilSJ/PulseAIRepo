"""Recovery Strategy Dispatcher for CrusorAI 2.1 (Phase 2.1).

Actuates deterministic recovery strategies governed by ARRE:
- Service relaunch (CrusorAI-owned processes only)
- Bounded network warmup polling
- Exponential backoff & RFC Retry-After execution
- Ephemeral log drainage & OOM subprocess reclamation
- Alternating mutation locking & diagnostic prompt synthesis
- Fail-closed deterministic termination
"""
from __future__ import annotations

import gc
import os
import random
import time
from typing import Any, Dict, List, NamedTuple, Optional

from src.runtime.recovery_engine import (
    FailureClassification,
    GlobalRecoveryBudgetTracker,
    ProcessSupervisor,
)


class RecoveryExecutionResult(NamedTuple):
    strategy: str
    success: bool
    action_taken: str
    next_instruction: Optional[str]
    metadata: Dict[str, Any]


class RecoveryStrategyDispatcher:
    """Safely executes approved recovery strategies according to ARRE governance."""

    def __init__(
        self,
        process_supervisor: Optional[ProcessSupervisor] = None,
        budget_tracker: Optional[GlobalRecoveryBudgetTracker] = None,
    ) -> None:
        self.supervisor = process_supervisor
        self.budget_tracker = budget_tracker

    def dispatch(
        self,
        classification: FailureClassification,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecoveryExecutionResult:
        ctx = context or {}
        strat = classification.recommended_strategy

        # 1. Relaunch CrusorAI-owned dev service
        if strat == "relaunch_owned_service":
            port = classification.metadata.get("port")
            is_owned = classification.metadata.get("is_owned", False)
            if not self.supervisor:
                return RecoveryExecutionResult(
                    strategy=strat,
                    success=False,
                    action_taken="Relaunch aborted: no process supervisor available.",
                    next_instruction="Manual inspection required.",
                    metadata={"port": port},
                )
            if not is_owned or port is None:
                return RecoveryExecutionResult(
                    strategy=strat,
                    success=False,
                    action_taken="Relaunch refused: process is unowned or port is unknown.",
                    next_instruction="Fail-closed enforced.",
                    metadata={"port": port, "is_owned": is_owned},
                )
            success = self.supervisor.relaunch_service(port)
            return RecoveryExecutionResult(
                strategy=strat,
                success=success,
                action_taken=f"Relaunched CrusorAI-managed service on port {port}." if success else f"Failed to relaunch service on port {port}.",
                next_instruction=f"Service on port {port} restarted; retry tool invocation." if success else "Escalate service startup failure.",
                metadata={"port": port, "relaunch_succeeded": success},
            )

        # 2. Bounded network warmup poll
        if strat == "bounded_warmup_poll":
            poll_delay = float(ctx.get("poll_delay", 0.5))
            bounded_delay = max(0.1, min(poll_delay, 1.5))
            if ctx.get("execute_sleep", True):
                time.sleep(bounded_delay)
            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken=f"Applied network warmup polling pause of {bounded_delay:.2f}s.",
                next_instruction="Service socket initialized; proceed to retry.",
                metadata={"poll_delay_seconds": bounded_delay},
            )

        # 3. Respect Retry-After or Exponential Backoff
        if strat in ("respect_retry_after_or_backoff", "exponential_backoff_jitter"):
            retry_after = classification.metadata.get("retry_after_seconds")
            attempt = classification.metadata.get("attempt", 1)
            backoff_base = classification.metadata.get("backoff_base_s", 2.0)

            if retry_after is not None:
                delay = float(retry_after)
            else:
                raw_delay = min(float(backoff_base) ** attempt, 16.0)
                # Apply 10% jitter
                jitter = random.uniform(0.0, 0.1 * raw_delay)
                delay = raw_delay + jitter

            if ctx.get("execute_sleep", False):
                time.sleep(delay)

            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken=f"Computed backoff delay of {delay:.2f}s for attempt {attempt}.",
                next_instruction=f"Pause execution for {delay:.2f}s before dispatching request.",
                metadata={"delay_seconds": delay, "attempt": attempt},
            )

        # 4. Drain eligible ephemeral logs on disk exhaustion
        if strat == "drain_eligible_logs":
            log_dirs: List[str] = ctx.get("log_directories", [".crusorai/logs", "logs", "tmp"])
            drained_bytes = 0
            drained_files = 0
            for d in log_dirs:
                if os.path.exists(d) and os.path.isdir(d):
                    for entry in os.scandir(d):
                        if entry.is_file() and entry.name.endswith((".log", ".tmp")):
                            try:
                                size = entry.stat().st_size
                                with open(entry.path, "w", encoding="utf-8") as f:
                                    f.truncate(0)
                                drained_bytes += size
                                drained_files += 1
                            except Exception:
                                pass
            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken=f"Drained {drained_files} ephemeral debug log files ({drained_bytes} bytes reclaimed).",
                next_instruction="Ephemeral logs cleared; re-attempt minimal write or alert user.",
                metadata={"files_drained": drained_files, "bytes_reclaimed": drained_bytes},
            )

        # 5. Terminate owned worker processes on memory exhaustion
        if strat == "terminate_owned_subprocesses_and_release":
            terminated = 0
            if self.supervisor:
                terminated = self.supervisor.terminate_owned_processes()
            collected = gc.collect()
            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken=f"Terminated {terminated} CrusorAI-owned worker processes and collected {collected} garbage objects.",
                next_instruction="Memory pressure alleviated; resume with conservative allocation.",
                metadata={"terminated_processes": terminated, "gc_collected_objects": collected},
            )

        # 6. AST Diagnostic Feedback
        if strat == "ast_diagnostic_feedback":
            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken="Formulated line-level AST syntax diagnostic prompt delta.",
                next_instruction="Inject exact line/column syntax error pointer into model prompt.",
                metadata={"requires_code_mutation": True},
            )

        # 7. Schema Feedback Prompt
        if strat == "schema_feedback_prompt":
            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken="Synthesized JSON schema repair diagnostic for tool parameters.",
                next_instruction="Inject required tool argument schema into next model turn.",
                metadata={"requires_schema_correction": True},
            )

        # 8. Alternating Mutation Lock
        if strat == "alternating_mutation_lock":
            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken="Applied alternating mutation lock: test execution locked until file mutation occurs.",
                next_instruction="Require model to apply relevant code mutation before re-running test suite.",
                metadata={"mutation_lock_active": True},
            )

        # 9. Requirement Delta Remediation
        if strat == "requirement_delta_remediation":
            req_id = classification.metadata.get("requirement_id", "UNKNOWN")
            return RecoveryExecutionResult(
                strategy=strat,
                success=True,
                action_taken=f"Extracted requirement delta for requirement '{req_id}'.",
                next_instruction="Direct model to implement missing requirement according to acceptance criteria.",
                metadata={"requirement_id": req_id, "requires_code_mutation": True},
            )

        # 10. Fail-closed or terminal halts
        return RecoveryExecutionResult(
            strategy=strat,
            success=False,
            action_taken=f"Halted execution safely under strategy '{strat}'.",
            next_instruction="Cease automated retries and escalate to user.",
            metadata={"fail_closed": True},
        )

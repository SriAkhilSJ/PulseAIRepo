"""Autonomous Reliability & Recovery Engine (ARRE) Dispatcher (CrusorAI 2.1 - Phase 2.1).

Executes recovery strategies recommended by FailureClassifier:
- relaunch_owned_service: Re-spawns dead CrusorAI-owned process via ProcessSupervisor.
- bounded_warmup_poll: Polls readiness with bounded sleep and status checks.
- respect_retry_after_or_backoff: Executes sleep according to Retry-After header or exponential backoff.
- exponential_backoff_jitter: Bounded exponential backoff with jitter for HTTP 5xx.
- drain_eligible_logs: Safely drains ephemeral debug/tmp logs when disk is exhausted.
- terminate_owned_subprocesses_and_release: Reclaims RAM by terminating owned child processes via ProcessSupervisor.
- alternating_mutation_lock: Locks test executions until a file edit lands in mutation ledger.
- schema_feedback_prompt: Generates schema guidance for model retry.
- ast_diagnostic_feedback: Generates line-level AST syntax guidance.
- requirement_delta_remediation: Synthesizes structured requirement remediation instructions.
"""
from __future__ import annotations

import gc
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from src.runtime.recovery_engine import (
    FailureClassification,
    GlobalRecoveryBudgetTracker,
    ProcessSupervisor,
)


@dataclass
class RecoveryExecutionResult:
    """Outcome of an attempted automated recovery operation."""

    success: bool
    strategy_applied: str
    action_taken: str
    next_instruction: Optional[str] = None
    sleep_applied_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class RecoveryStrategyDispatcher:
    """Executes and coordinates concrete recovery operations based on classified failures."""

    def __init__(
        self,
        budget_tracker: Optional[GlobalRecoveryBudgetTracker] = None,
        process_supervisor: Optional[ProcessSupervisor] = None,
        workspace_root: Optional[str | Path] = None,
        max_backoff_seconds: float = 16.0,
        apply_sleep: bool = True,
    ) -> None:
        self.budget_tracker = budget_tracker
        self.process_supervisor = process_supervisor
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self.max_backoff_seconds = max_backoff_seconds
        self.apply_sleep = apply_sleep

    def dispatch(
        self,
        classification: FailureClassification,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecoveryExecutionResult:
        """Dispatch and execute the recommended recovery strategy."""
        strategy = classification.recommended_strategy
        meta = dict(classification.metadata)
        if context:
            meta.update(context)

        # 1. Controlled process relaunch (CrusorAI-owned dev servers)
        if strategy == "relaunch_owned_service":
            port = meta.get("port")
            if port is None:
                return RecoveryExecutionResult(
                    success=False,
                    strategy_applied=strategy,
                    action_taken="Process relaunch aborted: port number unknown.",
                    next_instruction="Cannot relaunch service without explicit port.",
                    metadata=meta,
                )
            if self.process_supervisor:
                try:
                    relaunch_ok = self.process_supervisor.relaunch_process(port)
                    if relaunch_ok:
                        return RecoveryExecutionResult(
                            success=True,
                            strategy_applied=strategy,
                            action_taken=f"Relaunched CrusorAI service on port {port}.",
                            next_instruction=f"Managed service on port {port} restarted successfully. Ready to retry request.",
                            metadata=meta,
                        )
                    else:
                        return RecoveryExecutionResult(
                            success=False,
                            strategy_applied=strategy,
                            action_taken=f"Process supervisor failed to relaunch service on port {port}.",
                            next_instruction="Process relaunch failed. Manual supervisor inspection required.",
                            metadata=meta,
                        )
                except Exception as exc:
                    return RecoveryExecutionResult(
                        success=False,
                        strategy_applied=strategy,
                        action_taken=f"Exception during process relaunch on port {port}: {exc}",
                        next_instruction="Process relaunch encountered error.",
                        metadata=meta,
                    )
            else:
                return RecoveryExecutionResult(
                    success=False,
                    strategy_applied=strategy,
                    action_taken="No ProcessSupervisor attached. Cannot relaunch process.",
                    next_instruction="Attach ProcessSupervisor to enable automated server relaunches.",
                    metadata=meta,
                )

        # 2. Bounded network warmup delay
        if strategy == "bounded_warmup_poll":
            port = meta.get("port")
            delay = 0.5
            if self.apply_sleep:
                time.sleep(delay)
            # If supervisor present, re-check readiness
            ready = True
            if self.process_supervisor and port is not None:
                is_alive, is_owned = self.process_supervisor.inspect_port_owner(port)
                ready = is_alive and is_owned

            return RecoveryExecutionResult(
                success=ready,
                strategy_applied=strategy,
                action_taken=f"Polled service warmup on port {port} ({delay:.1f}s delay applied).",
                next_instruction="Service warmup delay elapsed. Retrying socket connection.",
                sleep_applied_seconds=delay if self.apply_sleep else 0.0,
                metadata=meta,
            )

        # 3. Rate limit backoff (respecting Retry-After header)
        if strategy == "respect_retry_after_or_backoff":
            retry_after = meta.get("retry_after_seconds")
            attempt = meta.get("attempt", 1)
            if retry_after is not None and retry_after > 0:
                delay = min(float(retry_after), self.max_backoff_seconds)
            else:
                delay = min(2.0 ** attempt, self.max_backoff_seconds)

            if self.apply_sleep and delay > 0:
                time.sleep(delay)

            return RecoveryExecutionResult(
                success=True,
                strategy_applied=strategy,
                action_taken=f"Applied rate limit backoff delay of {delay:.2f}s.",
                next_instruction=f"Rate limit backoff ({delay:.1f}s) completed. Ready to dispatch retry.",
                sleep_applied_seconds=delay if self.apply_sleep else 0.0,
                metadata=meta,
            )

        # 4. Exponential backoff with jitter (HTTP 5xx outages)
        if strategy == "exponential_backoff_jitter":
            attempt = meta.get("attempt", 1)
            base = float(meta.get("backoff_base_s", 2.0))
            raw_delay = min(base * (2.0 ** (attempt - 1)), self.max_backoff_seconds)
            # Add bounded jitter up to 25% of delay
            jitter = (random.random() * 0.25) * raw_delay
            delay = min(raw_delay + jitter, self.max_backoff_seconds)

            if self.apply_sleep and delay > 0:
                time.sleep(delay)

            return RecoveryExecutionResult(
                success=True,
                strategy_applied=strategy,
                action_taken=f"Applied exponential backoff with jitter of {delay:.2f}s.",
                next_instruction=f"Transient outage backoff ({delay:.1f}s) elapsed. Retrying request.",
                sleep_applied_seconds=delay if self.apply_sleep else 0.0,
                metadata=meta,
            )

        # 5. Disk exhaustion (drain eligible ephemeral logs)
        if strategy == "drain_eligible_logs":
            drained_bytes = 0
            drained_files = 0
            if self.workspace_root and self.workspace_root.exists():
                candidate_dirs = [
                    self.workspace_root / ".crusorai" / "logs",
                    self.workspace_root / "tmp",
                ]
                for cdir in candidate_dirs:
                    if cdir.exists() and cdir.is_dir():
                        for p in cdir.glob("*.log"):
                            try:
                                size = p.stat().st_size
                                p.write_text("")  # truncate ephemeral log
                                drained_bytes += size
                                drained_files += 1
                            except Exception:
                                pass

            return RecoveryExecutionResult(
                success=True,
                strategy_applied=strategy,
                action_taken=f"Drained {drained_files} ephemeral log files ({drained_bytes} bytes released).",
                next_instruction="Ephemeral log drainage completed. Verify free disk space.",
                metadata={"drained_files": drained_files, "drained_bytes": drained_bytes, **meta},
            )

        # 6. Memory exhaustion (terminate owned child processes and release caches)
        if strategy == "terminate_owned_subprocesses_and_release":
            terminated_count = 0
            if self.process_supervisor:
                try:
                    terminated_count = self.process_supervisor.cleanup_owned_subprocesses()
                except Exception:
                    pass
            # Force local garbage collection to free detached memory
            gc.collect()

            return RecoveryExecutionResult(
                success=True,
                strategy_applied=strategy,
                action_taken=f"Terminated {terminated_count} CrusorAI-owned subprocesses and released internal memory caches.",
                next_instruction="Memory reclamation complete. Throttle concurrency to avoid repeat OOM.",
                metadata={"terminated_processes": terminated_count, **meta},
            )

        # 7. Alternating mutation lock (assertions failed; model must edit code)
        if strategy == "alternating_mutation_lock":
            return RecoveryExecutionResult(
                success=True,
                strategy_applied=strategy,
                action_taken="Engaged alternating mutation lock on test executions.",
                next_instruction="Unit test assertions failed. You must inspect the failure and edit the relevant source code before re-running tests.",
                metadata=meta,
            )

        # 8. Bounded idempotent retry
        if strategy == "bounded_idempotent_retry":
            attempt = meta.get("attempt", 1)
            return RecoveryExecutionResult(
                success=True,
                strategy_applied=strategy,
                action_taken=f"Authorized bounded idempotent retry (attempt {attempt}).",
                next_instruction="Re-executing idempotent read/status operation.",
                metadata=meta,
            )

        # 9. Prompt guidance strategies (Schema feedback, AST diagnostic, Requirement delta)
        if strategy in ("ast_diagnostic_feedback", "schema_feedback_prompt", "requirement_delta_remediation"):
            return RecoveryExecutionResult(
                success=True,
                strategy_applied=strategy,
                action_taken=f"Synthesized prompt guidance for {strategy}.",
                next_instruction=classification.diagnostic_message,
                metadata=meta,
            )

        # 10. Fail-closed / Non-retryable strategies
        fail_closed_strategies = {
            "fail_fast_auth",
            "diagnose_invalid_request",
            "unowned_process_fail_closed",
            "fail_closed_non_idempotent",
            "fail_closed_unknown_port",
            "no_supervisor_fail_closed",
            "audit_trail_fail_closed",
            "hard_stop_grace_summary",
            "reverify_current_revision",
        }
        if strategy in fail_closed_strategies:
            return RecoveryExecutionResult(
                success=False,
                strategy_applied=strategy,
                action_taken=f"Fail-closed enforced by strategy '{strategy}'.",
                next_instruction=classification.diagnostic_message,
                metadata=meta,
            )

        # Fallback for unclassified / unknown strategies
        return RecoveryExecutionResult(
            success=False,
            strategy_applied=strategy or "unhandled",
            action_taken=f"No automated recovery execution available for strategy '{strategy}'.",
            next_instruction=classification.diagnostic_message,
            metadata=meta,
        )

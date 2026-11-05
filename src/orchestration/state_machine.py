"""
src/orchestration/state_machine.py - Persistent Engineering Execution State Machine.

Phase 11.6: Autonomous Engineering Execution.
Enforces valid state transitions across the 23 task execution states.
Guarantees crash-resilience, pause/resume, cancellation, and atomic disk persistence.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.orchestration.models import (
    VALID_TRANSITIONS,
    TaskExecutionState,
)
from src.workspace.ledger import WorkspaceChangeLedger

log = logging.getLogger("crusor.orchestration.state_machine")


class InvalidTransitionError(ValueError):
    """Raised when an illegal state machine transition is attempted."""
    pass


class TaskStateMachine:
    """
    Persistent state machine governing task transitions.
    """

    def __init__(
        self,
        task_id: str,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.task_id = task_id
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            self.storage_dir = (
                self.workspace_root
                / ".crusorai"
                / "tenants"
                / tenant_id
                / "tasks"
                / task_id
            )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.storage_dir / "state.json"

        self.current_state: TaskExecutionState = TaskExecutionState.RECEIVED
        self.history: List[Dict[str, Any]] = []
        self.is_paused: bool = False
        self.paused_state: Optional[TaskExecutionState] = None
        self.metadata: Dict[str, Any] = {}

        # Load existing state if present
        if self.state_file.exists():
            self._load_state()
        else:
            self._persist_state("Initial task creation")

    def transition_to(
        self,
        target_state: TaskExecutionState,
        reason: str = "",
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Transition to target_state if valid.
        Raises InvalidTransitionError if the transition is prohibited.
        """
        if self.is_paused and target_state != TaskExecutionState.CANCELLED:
            raise InvalidTransitionError(
                f"Task {self.task_id} is paused in state {self.paused_state}. Resume before transitioning."
            )

        valid_targets = VALID_TRANSITIONS.get(self.current_state, set())
        if target_state not in valid_targets:
            raise InvalidTransitionError(
                f"Invalid state transition for task {self.task_id}: "
                f"cannot move from {self.current_state.value} to {target_state.value}. "
                f"Allowed transitions: {[s.value for s in valid_targets]}"
            )

        prev_state = self.current_state
        self.current_state = target_state
        if metadata_update:
            self.metadata.update(metadata_update)

        entry = {
            "from_state": prev_state.value,
            "to_state": target_state.value,
            "timestamp": time.time(),
            "reason": reason,
        }
        self.history.append(entry)
        self._persist_state(reason)
        log.info(f"Task {self.task_id} transitioned: {prev_state.value} -> {target_state.value} ({reason})")

    def pause(self, reason: str = "") -> None:
        """Pause execution in current state."""
        if self.current_state in {
            TaskExecutionState.COMPLETED,
            TaskExecutionState.FAILED,
            TaskExecutionState.CANCELLED,
        }:
            raise InvalidTransitionError(f"Cannot pause finished task in state {self.current_state.value}")

        self.is_paused = True
        self.paused_state = self.current_state
        self._persist_state(f"Paused: {reason}")
        log.info(f"Task {self.task_id} PAUSED in state {self.current_state.value}")

    def resume(self, reason: str = "") -> None:
        """Resume execution from paused state."""
        if not self.is_paused:
            return
        self.is_paused = False
        resumed_from = self.paused_state
        self.paused_state = None
        self._persist_state(f"Resumed: {reason}")
        log.info(f"Task {self.task_id} RESUMED from state {resumed_from}")

    def cancel(self, reason: str = "User cancelled") -> None:
        """Cancel task execution."""
        if self.current_state in {TaskExecutionState.COMPLETED, TaskExecutionState.FAILED}:
            return
        self.current_state = TaskExecutionState.CANCELLED
        self.is_paused = False
        self.history.append({
            "from_state": self.current_state.value,
            "to_state": TaskExecutionState.CANCELLED.value,
            "timestamp": time.time(),
            "reason": reason,
        })
        self._persist_state(reason)

    def recover_from_crash(self) -> TaskExecutionState:
        """
        Reconcile state after process restart or crash.
        CRITICAL RULE: Never restart from the beginning if previous work exists in ledger!
        """
        ledger = WorkspaceChangeLedger(str(self.workspace_root), tenant_id=self.tenant_id)
        task_records = ledger.get_records(self.task_id)

        if task_records and self.current_state in {TaskExecutionState.RECEIVED, TaskExecutionState.UNDERSTANDING}:
            # Work was already committed to workspace! Recover forward to IMPLEMENTING / TESTING.
            log.warning(f"Task {self.task_id} has {len(task_records)} committed records. Fast-forwarding state.")
            self.current_state = TaskExecutionState.IMPLEMENTING
            self.history.append({
                "from_state": "CRASH_DETECTED",
                "to_state": TaskExecutionState.IMPLEMENTING.value,
                "timestamp": time.time(),
                "reason": "Crash recovery: recovered from workspace ledger committed changes",
            })
            self._persist_state("Recovered after crash")

        return self.current_state

    def _persist_state(self, note: str = "") -> None:
        """Atomically persist state JSON."""
        payload = {
            "task_id": self.task_id,
            "current_state": self.current_state.value,
            "is_paused": self.is_paused,
            "paused_state": self.paused_state.value if self.paused_state else None,
            "history": self.history,
            "metadata": self.metadata,
            "last_updated": time.time(),
            "note": note,
        }
        tmp_file = self.state_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_file, self.state_file)

    def _load_state(self) -> None:
        """Load state JSON."""
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.current_state = TaskExecutionState(data.get("current_state", TaskExecutionState.RECEIVED.value))
            self.is_paused = bool(data.get("is_paused", False))
            paused_raw = data.get("paused_state")
            self.paused_state = TaskExecutionState(paused_raw) if paused_raw else None
            self.history = data.get("history", [])
            self.metadata = data.get("metadata", {})
        except Exception as e:
            log.error(f"Error loading task state for {self.task_id}: {e}")
            self.current_state = TaskExecutionState.RECEIVED

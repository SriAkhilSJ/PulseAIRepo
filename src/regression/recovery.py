"""
src/regression/recovery.py - Safe Rollback & Recovery Coordinator.

Phase 11.5: Regression Prevention & Recovery.
Integrates with Phase 11.3 WorkspaceChangeLedger and WorkspaceJournalManager:
- Evaluates safe rollback feasibility for agent-introduced regressions.
- Enforces user file protection: never reverts USER_SUPERSEDED_AGENT files.
- Strictly prohibits destructive commands (git reset --hard, git clean -fd).
- Manages multi-file partial transaction aborts safely.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.regression.models import (
    RecoveryActionType,
    RecoveryEvaluation,
)
from src.workspace.journal import WorkspaceJournalManager
from src.workspace.ledger import WorkspaceChangeLedger

log = logging.getLogger("crusor.regression.recovery")


class SafeRecoveryCoordinator:
    """
    Coordinates safe rollback and recovery from regression-inducing agent changes.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        ledger: Optional[WorkspaceChangeLedger] = None,
        journal: Optional[WorkspaceJournalManager] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id
        self.ledger = ledger or WorkspaceChangeLedger(str(self.workspace_root), tenant_id=tenant_id)
        self.journal = journal or WorkspaceJournalManager(str(self.workspace_root), tenant_id=tenant_id)

    def evaluate_recovery(
        self,
        task_id: str,
        regressed_files: List[str],
    ) -> RecoveryEvaluation:
        """
        Evaluates whether an agent change can be safely rolled back.
        """
        actions: List[Dict[str, Any]] = []
        blocked_reasons: List[str] = []
        affected_user_files: List[str] = []

        is_safe = True

        for rel_file in regressed_files:
            safe, reason = self.ledger.is_safe_for_agent_rollback(task_id, rel_file)
            if not safe:
                is_safe = False
                blocked_reasons.append(f"File '{rel_file}': {reason}")
                affected_user_files.append(rel_file)
            else:
                actions.append({
                    "action": RecoveryActionType.RESTORE_AGENT_FILE.value,
                    "target_file": rel_file,
                    "rationale": "Verified agent-owned file with available pre-image backup",
                })

        return RecoveryEvaluation(
            task_id=task_id,
            is_safe_to_rollback=is_safe,
            actions=actions,
            blocked_reasons=blocked_reasons,
            affected_user_files=affected_user_files,
            recovery_status="SAFE_TO_EXECUTE" if is_safe else "BLOCKED_USER_WORK_PRESERVED",
        )

    def execute_recovery(
        self,
        task_id: str,
        evaluation: RecoveryEvaluation,
    ) -> Tuple[bool, str]:
        """
        Executes verified recovery actions through WorkspaceJournalManager.
        Never executes git reset or git clean.
        """
        if not evaluation.is_safe_to_rollback:
            return False, f"Recovery blocked to preserve user work: {'; '.join(evaluation.blocked_reasons)}"

        try:
            # Revert via journal manager
            ok, rolled, skipped = self.journal.rollback_transaction(task_id)
            evaluation.recovery_status = "ROLLED_BACK" if ok else "ROLLBACK_FAILED"
            msg = f"Rolled back: {', '.join(rolled)}" if ok else f"Rollback failed: {'; '.join(skipped)}"
            return ok, msg
        except Exception as e:
            evaluation.recovery_status = f"ERROR: {e}"
            return False, f"Recovery exception: {e}"

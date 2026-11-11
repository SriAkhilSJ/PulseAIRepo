"""
src/orchestration/implementation_engine.py - Controlled Code Implementation & Quality Control.

Phase 11.6: Autonomous Engineering Execution.
Strict Invariants:
- ALL file creations, modifications, deletions, and moves MUST pass through Phase 11.3 WorkspaceMutationBroker.
- Enforces pre-mutation checks: task authorization, workspace identity, ownership, and concurrency.
- Detects scope divergence and duplicate components.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.orchestration.models import EngineeringTaskNode
from src.workspace.models import RiskLevel
from src.workspace.mutation_broker import (
    ConcurrencyConflictError,
    MutationAuthorizationError,
    WorkspaceMutationBroker,
)

log = logging.getLogger("crusor.orchestration.implementation_engine")


class ScopeDivergenceError(ValueError):
    """Raised when an implementation action attempts to modify an unapproved file."""
    pass


class ControlledImplementationEngine:
    """
    Executes disciplined file mutations through WorkspaceMutationBroker.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        broker: Optional[WorkspaceMutationBroker] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id
        self.broker = broker or WorkspaceMutationBroker(str(self.workspace_root), tenant_id=tenant_id)
        self.mutated_files: Set[str] = set()

    def execute_node_mutation(
        self,
        task_id: str,
        node: EngineeringTaskNode,
        rel_path: str,
        content: str,
        operation: str = "CREATE_OR_MODIFY",
        approval_token: Optional[str] = None,
        require_digest: bool = True,
        session_id: str = "",
        turn_id: str = "",
    ) -> str:
        """
        Applies a disciplined file mutation for a task node.
        Validates target file against approved node targets.
        """
        # 1. Quality Control: Scope Check
        # Check if rel_path is in node.target_files or closely related
        normalized = Path(rel_path).as_posix()
        node_targets = {Path(p).as_posix() for p in node.target_files}

        if node_targets and normalized not in node_targets:
            # Check if this represents scope creep
            raise ScopeDivergenceError(
                f"File '{rel_path}' is not an authorized target for task node '{node.node_id}'. "
                f"Approved targets: {list(node_targets)}"
            )

        full_path = self.workspace_root / rel_path
        reason = f"Phase 11.6 node [{node.node_id}]: {node.description}"

        if not full_path.exists():
            rec = self.broker.create_file(
                path=rel_path,
                content=content,
                task_id=task_id,
                change_reason=reason,
                related_requirement_ids=node.related_requirement_ids,
                related_architecture_decisions=node.related_architecture_decisions,
                approval_token=approval_token,
                require_digest=require_digest,
                session_id=session_id,
                turn_id=turn_id,
            )
            receipt = rec.operation_id
        else:
            old_content = full_path.read_text(encoding="utf-8")
            rec = self.broker.modify_file(
                path=rel_path,
                old_text=old_content,
                new_text=content,
                task_id=task_id,
                change_reason=reason,
                related_requirement_ids=node.related_requirement_ids,
                related_architecture_decisions=node.related_architecture_decisions,
                approval_token=approval_token,
                require_digest=require_digest,
                session_id=session_id,
                turn_id=turn_id,
            )
            receipt = rec.operation_id

        self.mutated_files.add(rel_path)
        log.info(f"Task {task_id} successfully mutated {rel_path} (receipt: {receipt})")
        return receipt

    def apply_patch(
        self,
        task_id: str,
        node: EngineeringTaskNode,
        rel_path: str,
        original_snippet: str,
        replacement_snippet: str,
        approval_token: Optional[str] = None,
    ) -> str:
        """
        Applies a focused surgical patch to an existing file.
        """
        full_path = self.workspace_root / rel_path
        if not full_path.exists():
            raise FileNotFoundError(f"Cannot patch non-existent file: {rel_path}")

        current_content = full_path.read_text(encoding="utf-8")
        if original_snippet not in current_content:
            raise ConcurrencyConflictError(
                f"Target snippet not found in {rel_path} — file may have changed externally."
            )

        updated_content = current_content.replace(original_snippet, replacement_snippet, 1)
        return self.execute_node_mutation(
            task_id=task_id,
            node=node,
            rel_path=rel_path,
            content=updated_content,
            operation="MODIFY",
            approval_token=approval_token,
        )

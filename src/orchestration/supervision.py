"""
src/orchestration/supervision.py - Human Approval & Supervision Gate.

Phase 11.6: Autonomous Engineering Execution.
Controls when the orchestrator must halt and request explicit human intervention:
- Unresolved essential business decisions (Phase 11.1)
- Material architecture deviations (Phase 11.2)
- High-risk operations (Phase 11.3 RiskApprovalGate)
- Destructive operations (git clean, delete, drop table)
- Boundary violations
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.workspace.models import RiskLevel
from src.workspace.risk_policy import RiskApprovalGate

log = logging.getLogger("crusor.orchestration.supervision")


@dataclass
class PendingApprovalRequest:
    """An outstanding approval request awaiting human decision."""
    approval_id: str
    task_id: str
    workspace_root: str
    category: str  # BUSINESS_DECISION, ARCHITECTURE_DEVIATION, HIGH_RISK_OPERATION, DESTRUCTIVE_ACTION
    description: str
    risk_level: str
    details: Dict[str, Any] = field(default_factory=dict)
    options: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED
    resolution: Optional[str] = None
    approval_token: Optional[str] = None


class HumanSupervisionGate:
    """
    Evaluates required approvals and issues revocable tokens upon human confirmation.
    """

    def __init__(self, workspace_root: str, tenant_id: str = "default_tenant") -> None:
        self.workspace_root = workspace_root
        self.tenant_id = tenant_id
        self.risk_gate = RiskApprovalGate()
        self.pending_approvals: Dict[str, PendingApprovalRequest] = {}
        self.granted_tokens: Dict[str, PendingApprovalRequest] = {}

    def requires_approval_for_operation(
        self,
        task_id: str,
        operation_name: str,
        target_path: Optional[str] = None,
        risk_level: str = "LOW",
        is_destructive: bool = False,
    ) -> Optional[PendingApprovalRequest]:
        """
        Determines whether the specified operation requires human approval before proceeding.
        """
        # Always require approval for destructive commands or CRITICAL risk
        needs_approval = is_destructive or risk_level in {"HIGH", "CRITICAL"}

        # Destructive patterns
        destructive_keywords = ["delete", "drop", "purge", "git clean", "git reset --hard", "format"]
        if any(kw in operation_name.lower() for kw in destructive_keywords):
            needs_approval = True
            is_destructive = True
            risk_level = "CRITICAL"

        if not needs_approval:
            return None

        approval_id = f"appr_{uuid.uuid4().hex[:8]}"
        req = PendingApprovalRequest(
            approval_id=approval_id,
            task_id=task_id,
            workspace_root=self.workspace_root,
            category="DESTRUCTIVE_ACTION" if is_destructive else "HIGH_RISK_OPERATION",
            description=f"Action '{operation_name}' on '{target_path or 'workspace'}' requires explicit approval",
            risk_level=risk_level,
            details={"operation": operation_name, "target": target_path},
            options=["APPROVE", "REJECT"],
        )
        self.pending_approvals[approval_id] = req
        log.warning(f"Task {task_id} blocked: requires approval [{approval_id}]: {req.description}")
        return req

    def grant_approval(self, approval_id: str, choice: str = "APPROVE") -> str:
        """
        Resolves pending approval request and returns a valid cryptographic token.
        """
        if approval_id not in self.pending_approvals:
            raise KeyError(f"Approval request {approval_id} not found")

        req = self.pending_approvals.pop(approval_id)
        if choice.upper() != "APPROVE":
            req.status = "REJECTED"
            req.resolution = choice
            raise PermissionError(f"Approval {approval_id} rejected by user")

        token = f"token_{uuid.uuid4().hex}"
        req.status = "APPROVED"
        req.resolution = choice
        req.approval_token = token
        self.granted_tokens[token] = req
        log.info(f"Approval {approval_id} GRANTED. Token issued: {token}")
        return token

    def is_token_valid_for_task(self, token: str, task_id: str) -> bool:
        """Check if token is valid and matches task_id."""
        req = self.granted_tokens.get(token)
        return req is not None and req.task_id == task_id


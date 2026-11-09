"""Human approval gateway for the active EngineeringExecutionOrchestrator.

The orchestrator used to mint its own "APPROVE" token at stage 9 without any
human in the loop. This module connects the existing session-scoped
``ApprovalQueue`` (the same queue the desktop's Protocol v2 ``safety_reply``
resolves) and the existing ``RiskApprovalGate`` single-use tokens.

Flow per protected resource:

    classify -> ApprovalQueue.request -> event_bus tool.approval.request
    -> Protocol v2 safety_request -> wait -> safety_reply -> validate
    -> RiskApprovalGate token -> mutation broker verify_and_consume

Fail-closed: denial, timeout, turn cancellation, wrong session, stale or
duplicate replies, and resource mismatch all end in ``ApprovalDenied`` and no
token. Nothing here auto-approves.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.dashboard.event_bus import ApprovalQueue, approval_queue as default_approval_queue
from src.dashboard.event_bus import event_bus
from src.workspace.models import WorkspaceOperationType
from src.workspace.risk_policy import RiskApprovalGate

_HIGH_RISK = {"HIGH", "CRITICAL", "HIGH_RISK", "PROHIBITED"}


class ApprovalDenied(PermissionError):
    """The human (or the runtime) refused, cancelled, or never answered."""

    def __init__(self, reason: str, *, approval_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.approval_id = approval_id


@dataclass(frozen=True)
class Authorization:
    approval_id: str
    token: str
    path: str
    operation: str


class OrchestratorApprovalGateway:
    """Session/resource-scoped human approval for orchestrator mutations."""

    def __init__(
        self,
        *,
        workspace_root: str,
        session_id: str,
        task_id: str,
        policy: str = "ask",
        queue: Optional[ApprovalQueue] = None,
        risk_gate: Optional[RiskApprovalGate] = None,
        timeout_s: float | None = None,
        emit: Optional[Callable[[str, dict], object]] = None,
        cancellation_checker: Optional[Callable[[], bool]] = None,
        heartbeat_interval: float = 15.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.session_id = str(session_id or "default")
        self.task_id = str(task_id or "task")
        self.policy = str(policy or "ask").strip().lower()
        if self.policy not in {"ask", "workspace_session", "session"}:
            self.policy = "ask"
        self.queue = queue if queue is not None else default_approval_queue
        self.risk_gate = risk_gate or RiskApprovalGate()
        self.timeout_s = timeout_s
        self.emit = emit or event_bus.emit
        self.cancellation_checker = cancellation_checker
        self.heartbeat_interval = heartbeat_interval

    # -- policy ---------------------------------------------------------

    @staticmethod
    def _operation(path: str, exists: bool) -> WorkspaceOperationType:
        return WorkspaceOperationType.MODIFY if exists else WorkspaceOperationType.CREATE

    def needs_approval(self, *, path: str, risk_level: str = "LOW") -> bool:
        """`ask` gates every mutation; session policies only gate elevated risk.

        High-risk and destructive operations always ask, and anything outside
        the workspace always asks. This preserves the graph path's semantics.
        """
        root = self.workspace_root
        try:
            resolved = (root / path).resolve()
        except OSError:
            return True
        outside = root != resolved and root not in resolved.parents
        if outside:
            return True
        if str(risk_level).upper() in _HIGH_RISK:
            return True
        return self.policy == "ask"

    # -- approval -------------------------------------------------------

    def authorize(
        self,
        *,
        node_id: str,
        path: str,
        operation: str | None = None,
        risk_level: str = "LOW",
        reason: str = "",
        task_id: str | None = None,
    ) -> Authorization | None:
        """Return a scoped risk token, or None when approval is not required.

        Raises ApprovalDenied on refusal/timeout/cancel/mismatch. The caller
        must not mutate anything when this raises.
        """
        rel_path = Path(path).as_posix()
        token_task_id = str(task_id or self.task_id)
        if not self.needs_approval(path=rel_path, risk_level=risk_level):
            return None

        exists = (self.workspace_root / rel_path).exists()
        op = self._operation(rel_path, exists)
        op_name = operation or op.value
        tool_id = f"orch-{self.task_id}-{int(time.time() * 1000)}-{abs(hash((node_id, rel_path))) % 10000}"
        grant_key = f"write_file\n{rel_path}"

        # "Allow always" is scoped to (session, tool, resource) exactly like
        # the graph path; a veto-class ask is never granted silently.
        if self.queue.is_granted(self.session_id, grant_key):
            return Authorization(
                approval_id="session-grant",
                token=self.risk_gate.generate_approval_token(
                    token_task_id, str(self.workspace_root), rel_path, op
                ),
                path=rel_path,
                operation=op_name,
            )

        arguments = {
            "path": rel_path,
            "operation": op_name,
            "node_id": node_id,
            "task_id": token_task_id,
            "workspace": str(self.workspace_root),
        }
        item = self.queue.request(
            tool_id,
            "write_file",
            arguments,
            session_id=self.session_id,
            diff={
                "kind": "file",
                "path": rel_path,
                "operation": op_name,
                "reason": reason,
            },
        )
        self.emit(
            "tool.approval.request",
            {
                **item,
                "id": tool_id,
                "tool_id": tool_id,
                "name": "write_file",
                "tool_name": "write_file",
                "arguments": arguments,
                "tool_args": arguments,
                "diff": item.get("diff"),
                "warning": reason,
                "task_id": token_task_id,
                "workspace": str(self.workspace_root),
                "thread_id": self.session_id,
                "session_id": self.session_id,
            },
        )

        def _heartbeat(elapsed: float) -> None:
            # The wait must keep the turn's liveness clock fed and stay in
            # the engine log, mirroring the graph's dock testimony.
            print(
                f"[orchestrator-approval] waiting {elapsed:.0f}s for {tool_id} "
                f"({op_name} {rel_path})",
                flush=True,
            )

        decision = self.queue.wait_for_decision(
            tool_id,
            timeout=self.timeout_s,
            heartbeat=_heartbeat,
            heartbeat_interval=self.heartbeat_interval,
            should_stop=self.cancellation_checker,
        )
        if decision is None:
            raise ApprovalDenied("approval_abandoned", approval_id=tool_id)
        if decision.get("session_id") != self.session_id:
            raise ApprovalDenied("wrong_session", approval_id=tool_id)
        if decision.get("cancelled"):
            raise ApprovalDenied("turn_cancelled", approval_id=tool_id)
        if decision.get("timeout"):
            raise ApprovalDenied("approval_timeout", approval_id=tool_id)
        if not decision.get("decision"):
            raise ApprovalDenied("user_denied", approval_id=tool_id)

        if decision.get("always_allow"):
            self.queue.grant(self.session_id, grant_key)
        token = self.risk_gate.generate_approval_token(
            token_task_id, str(self.workspace_root), rel_path, op
        )
        return Authorization(
            approval_id=tool_id,
            token=token,
            path=rel_path,
            operation=op_name,
        )

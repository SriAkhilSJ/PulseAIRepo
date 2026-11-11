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
    digest: str = ""
    diff: str = ""
    task_id: str = ""
    workspace: str = ""
    session_id: str = ""
    turn_id: str = ""
    precondition_digest: str = ""


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
        turn_id: str = "",
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
        self.turn_id = str(turn_id or "")
        self.receipts: list[dict] = []

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
        proposed_content: str | None = None,
        existing_content: str | None = None,
        diff: str | None = None,
        always_token: bool = False,
    ) -> Authorization | None:
        """Return a scoped, digest-bound risk token, or None when approval is not required.

        Increment 2: when ``proposed_content`` is supplied the token is bound
        to the exact bytes/diff shown to the human (or granted by session
        policy). ``always_token`` mints a token even for low-risk policy
        grants, so every engineering mutation reaches the broker with an
        authorization object; callers that pass nothing keep the historical
        Phase 3.1 behaviour.

        Raises ApprovalDenied on refusal/timeout/cancel/mismatch. The caller
        must not mutate anything when this raises.
        """
        from src.workspace.approval_digest import (
            content_digest,
            precondition_digest,
            unified_diff_text,
        )

        rel_path = Path(path).as_posix()
        token_task_id = str(task_id or self.task_id)
        proposed_digest = (
            content_digest(proposed_content) if proposed_content is not None else ""
        )
        diff_text = diff
        if diff_text is None and proposed_content is not None:
            diff_text = unified_diff_text(
                existing_content, proposed_content, display_path=rel_path,
            )
        diff_text = str(diff_text or "")

        exists = (self.workspace_root / rel_path).exists()
        precondition_text = existing_content
        if precondition_text is None and exists:
            try:
                precondition_text = (self.workspace_root / rel_path).read_text(
                    encoding="utf-8", errors="replace",
                )
            except OSError:
                precondition_text = ""
        precondition = precondition_digest(exists, precondition_text)

        required = self.needs_approval(path=rel_path, risk_level=risk_level)
        if not required and not always_token:
            return None

        op = self._operation(rel_path, exists)
        op_name = operation or op.value
        tool_id = f"orch-{self.task_id}-{int(time.time() * 1000)}-{abs(hash((node_id, rel_path))) % 10000}"
        grant_key = f"write_file\n{rel_path}"

        def _granted() -> Authorization:
            auth = Authorization(
                approval_id="policy-grant" if not required else "session-grant",
                token=self.risk_gate.generate_approval_token(
                    token_task_id,
                    str(self.workspace_root),
                    rel_path,
                    op,
                    content_digest=proposed_digest,
                    precondition_digest=precondition if always_token else "",
                    session_id=self.session_id if always_token else "",
                    turn_id=self.turn_id if always_token else "",
                ),
                path=rel_path,
                operation=op_name,
                digest=proposed_digest,
                diff=diff_text,
                task_id=token_task_id,
                workspace=str(self.workspace_root),
                session_id=self.session_id,
                turn_id=self.turn_id,
                precondition_digest=precondition,
            )
            self._record(auth)
            return auth

        # Policy grants (session policy / low-risk) skip the dock but still
        # receive a scoped, single-use, digest-bound token.
        if not required:
            return _granted()

        # "Allow always" is scoped to (session, tool, resource) exactly like
        # the graph path; a veto-class ask is never granted silently.
        if self.queue.is_granted(self.session_id, grant_key):
            return _granted()

        arguments = {
            "path": rel_path,
            "operation": op_name,
            "node_id": node_id,
            "task_id": token_task_id,
            "workspace": str(self.workspace_root),
            "content_digest": proposed_digest,
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
                "diff": diff_text,
                "content_digest": proposed_digest,
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
            token_task_id,
            str(self.workspace_root),
            rel_path,
            op,
            content_digest=proposed_digest,
            precondition_digest=precondition if always_token else "",
            session_id=self.session_id if always_token else "",
            turn_id=self.turn_id if always_token else "",
        )
        auth = Authorization(
            approval_id=tool_id,
            token=token,
            path=rel_path,
            operation=op_name,
            digest=proposed_digest,
            diff=diff_text,
            task_id=token_task_id,
            workspace=str(self.workspace_root),
            session_id=self.session_id,
            turn_id=self.turn_id,
            precondition_digest=precondition,
        )
        self._record(auth)
        return auth

    def _record(self, auth: Authorization) -> None:
        """Append a token-free approval receipt for the turn evidence."""
        self.receipts.append({
            "approval_id": auth.approval_id,
            "task_id": auth.task_id,
            "session_id": auth.session_id,
            "turn_id": auth.turn_id,
            "workspace": auth.workspace,
            "path": auth.path,
            "operation": auth.operation,
            "content_digest": auth.digest,
            "precondition_digest": auth.precondition_digest,
        })

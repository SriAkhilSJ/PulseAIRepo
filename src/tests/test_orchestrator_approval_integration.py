"""Orchestrator approval integration (Phase 3.1).

Provider-free: a real ApprovalQueue, real RiskApprovalGate tokens and the real
mutation broker. The gateway is the orchestrator's stage-9 gate; the queue is
the same object the bridge's ``safety_reply`` resolves.

Chain under test:

    orchestrator gateway -> ApprovalQueue -> tool.approval.request
    -> (safety_reply / queue.resolve) -> risk token -> mutation broker
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.dashboard.event_bus import ApprovalQueue
from src.orchestration.approval_gateway import (
    ApprovalDenied,
    OrchestratorApprovalGateway,
)
from src.workspace.models import WorkspaceOperationType
from src.workspace.mutation_broker import (
    MutationAuthorizationError,
    WorkspaceMutationBroker,
)


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.md").write_text("# notes\n", encoding="utf-8")
    (ws / "product.json").write_text('{"name": "fixture"}\n', encoding="utf-8")
    return ws


def _gateway(
    ws: Path,
    *,
    policy: str = "ask",
    timeout_s: float | None = None,
    cancelled=None,
) -> tuple[OrchestratorApprovalGateway, ApprovalQueue, list[tuple[str, dict]]]:
    queue = ApprovalQueue()
    events: list[tuple[str, dict]] = []
    gateway = OrchestratorApprovalGateway(
        workspace_root=str(ws),
        session_id="session-1",
        task_id="task-1",
        policy=policy,
        queue=queue,
        timeout_s=timeout_s,
        emit=lambda kind, payload: events.append((kind, payload)),
        cancellation_checker=cancelled,
        heartbeat_interval=0.05,
    )
    return gateway, queue, events


def _start(gateway, **kwargs):
    result: dict = {}

    def worker() -> None:
        try:
            result["auth"] = gateway.authorize(**kwargs)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, result


def _wait_pending(queue: ApprovalQueue, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = queue.get_pending("session-1")
        if pending:
            return pending[0]
        time.sleep(0.01)
    raise AssertionError("approval never reached the queue")


def _wait_events(events, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if events:
            return events[0]
        time.sleep(0.01)
    raise AssertionError("approval event was never emitted")


def test_approval_request_is_published_and_approved(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, events = _gateway(ws)
    thread, result = _start(gateway, node_id="n1", path="product.json", risk_level="HIGH", reason="protected write")

    item = _wait_pending(queue)
    kind, payload = _wait_events(events)
    assert kind == "tool.approval.request"
    assert payload["tool_id"] == item["id"]
    assert payload["session_id"] == "session-1"
    assert payload["arguments"]["path"] == "product.json"
    assert payload["arguments"]["workspace"] == str(ws.resolve())
    assert payload["task_id"] == "task-1"
    assert payload["warning"] == "protected write"

    assert queue.resolve(item["id"], True, session_id="session-1") is True
    thread.join(3)
    auth = result.get("auth")
    assert auth is not None and auth.token.startswith("APPV-")
    ok, msg = gateway.risk_gate.verify_and_consume_approval_token(
        auth.token, "task-1", str(ws.resolve()), "product.json",
        WorkspaceOperationType.MODIFY,
    )
    assert ok, msg


def test_user_denial_prevents_authorization(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, _ = _gateway(ws)
    thread, result = _start(gateway, node_id="n1", path="notes.md", reason="write")
    item = _wait_pending(queue)
    assert queue.resolve(item["id"], False, session_id="session-1") is True
    thread.join(3)
    assert isinstance(result.get("error"), ApprovalDenied)
    assert result["error"].reason == "user_denied"
    assert "auth" not in result


def test_timeout_is_a_denial(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, _queue, _ = _gateway(ws, timeout_s=0.2)
    thread, result = _start(gateway, node_id="n1", path="notes.md", reason="write")
    thread.join(3)
    assert isinstance(result.get("error"), ApprovalDenied)
    assert result["error"].reason == "approval_timeout"


def test_cancellation_wakes_the_wait(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    flag = {"stop": False}

    def cancelled() -> bool:
        return flag["stop"]

    gateway, _queue, _ = _gateway(ws, cancelled=cancelled)
    thread, result = _start(gateway, node_id="n1", path="notes.md", reason="write")
    _wait_pending(_queue)
    flag["stop"] = True
    thread.join(3)
    assert isinstance(result.get("error"), ApprovalDenied)
    assert result["error"].reason == "turn_cancelled"


def test_wrong_session_reply_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, _ = _gateway(ws)
    thread, result = _start(gateway, node_id="n1", path="notes.md", reason="write")
    item = _wait_pending(queue)
    assert queue.resolve(item["id"], True, session_id="someone-else") is False
    assert queue.resolve(item["id"], True, session_id="session-1") is True
    thread.join(3)
    assert result.get("auth") is not None


def test_duplicate_and_stale_replies_cannot_authorize_twice(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, _ = _gateway(ws)
    thread, result = _start(gateway, node_id="n1", path="notes.md", reason="write")
    item = _wait_pending(queue)
    assert queue.resolve(item["id"], True, session_id="session-1") is True
    assert queue.resolve(item["id"], True, session_id="session-1") is False
    thread.join(3)
    assert result.get("auth") is not None
    # A late duplicate after the decision was consumed is still refused.
    assert queue.resolve(item["id"], True, session_id="session-1") is False


def test_authorization_is_bound_to_the_exact_resource(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, _ = _gateway(ws)
    thread, result = _start(gateway, node_id="n1", path="product.json", risk_level="HIGH", reason="write")
    item = _wait_pending(queue)
    queue.resolve(item["id"], True, session_id="session-1")
    thread.join(3)
    token = result["auth"].token
    other = gateway.risk_gate.generate_approval_token(
        "task-1", str(ws.resolve()), "notes.md", WorkspaceOperationType.MODIFY,
    )
    ok, _ = gateway.risk_gate.verify_and_consume_approval_token(
        token, "task-1", str(ws.resolve()), "notes.md", WorkspaceOperationType.MODIFY,
    )
    assert ok is False, "a token for product.json must not authorize notes.md"
    ok, _ = gateway.risk_gate.verify_and_consume_approval_token(
        other, "task-1", str(ws.resolve()), "product.json", WorkspaceOperationType.MODIFY,
    )
    assert ok is False


def test_low_risk_policy_behaviour_is_preserved(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, events = _gateway(ws, policy="workspace_session")
    assert gateway.authorize(node_id="n1", path="notes.md", reason="normal write") is None
    assert queue.get_pending("session-1") == []
    assert events == []
    # Risk still escalates to a human.
    thread, result = _start(gateway, node_id="n2", path="product.json", risk_level="HIGH", reason="risk")
    item = _wait_pending(queue)
    queue.resolve(item["id"], True, session_id="session-1")
    thread.join(3)
    assert result.get("auth") is not None


def test_broker_accepts_the_approved_token_and_denial_leaves_the_file_untouched(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    broker = WorkspaceMutationBroker(str(ws), tenant_id="tenant-1")
    original = (ws / "product.json").read_text(encoding="utf-8")

    # Denied: no token reaches the broker; the mutation is refused.
    gateway, queue, _ = _gateway(ws)
    thread, result = _start(gateway, node_id="n1", path="product.json", risk_level="HIGH", reason="write")
    item = _wait_pending(queue)
    queue.resolve(item["id"], False, session_id="session-1")
    thread.join(3)
    assert isinstance(result.get("error"), ApprovalDenied)
    with pytest.raises(MutationAuthorizationError):
        broker.modify_file(
            path="product.json", new_content='{"changed": true}\n',
            task_id="task-1", approval_token=None,
        )
    assert (ws / "product.json").read_text(encoding="utf-8") == original

    # Approved: the scoped token authorizes exactly that file.
    gateway2, queue2, _ = _gateway(ws)
    thread2, result2 = _start(gateway2, node_id="n1", path="product.json", risk_level="HIGH", reason="write")
    item2 = _wait_pending(queue2)
    queue2.resolve(item2["id"], True, session_id="session-1")
    thread2.join(3)
    token = result2["auth"].token
    broker.modify_file(
        path="product.json", new_content='{"changed": true}\n',
        task_id="task-1", approval_token=token,
    )
    assert (ws / "product.json").read_text(encoding="utf-8") == '{"changed": true}\n'
    # Single use: the same token cannot authorize a second mutation.
    with pytest.raises(MutationAuthorizationError):
        broker.modify_file(
            path="product.json", new_content='{"changed": false}\n',
            task_id="task-1", approval_token=token,
        )


def test_unknown_approval_id_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, _ = _gateway(ws, timeout_s=0.3)
    thread, result = _start(gateway, node_id="n1", path="notes.md", reason="write")
    item = _wait_pending(queue)
    assert queue.resolve("appr-does-not-exist", True, session_id="session-1") is False
    assert queue.resolve(item["id"], True, session_id="session-1") is True
    thread.join(3)
    assert result.get("auth") is not None


def test_session_policy_low_risk_is_silent_and_high_risk_asks(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    gateway, queue, events = _gateway(ws, policy="session")
    assert gateway.authorize(node_id="n1", path="notes.md", reason="normal") is None
    assert queue.get_pending("session-1") == []
    assert events == []
    thread, result = _start(gateway, node_id="n2", path="product.json", risk_level="HIGH", reason="risk")
    item = _wait_pending(queue)
    queue.resolve(item["id"], True, session_id="session-1")
    thread.join(3)
    assert result.get("auth") is not None

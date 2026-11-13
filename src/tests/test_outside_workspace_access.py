"""Phase 2D - outside-workspace access with a human grant.

Provider-free. Covers the grant model, the discovery boundary, the approval
gateway request/verdict mapping, and two orchestrator turns (allow / deny) that
record the decision without writing outside the workspace.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.orchestration.approval_gateway import OrchestratorApprovalGateway
from src.orchestration.models import EngineeringTaskRequest, ExecutionLimits
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.workspace.access_grants import (
    ONCE,
    READ,
    TURN,
    WRITE,
    AccessGrantSet,
    WorkspaceAccessGrant,
    WorkspaceAccessRequired,
    is_sensitive_external_path,
)
from src.workspace.discovery import WorkspaceDiscovery
from src.workspace.evidence import build_workspace_evidence
from src.workspace.mutation_broker import WorkspaceMutationBroker, MutationAuthorizationError
from src.workspace.path_safety import PathSecurityViolation
from src.workspace.risk_policy import RiskApprovalGate

OUTSIDE_UTILS = '''"""Shared helpers outside the workspace."""


def shared_helper(value: int) -> int:
    return value + 1
'''


class FakeQueue:
    """Deterministic stand-in for the session ApprovalQueue."""

    def __init__(self, *, approved: bool = True, always: bool = False,
                 timeout: bool = False, cancelled: bool = False) -> None:
        self.approved = approved
        self.always = always
        self.timeout = timeout
        self.cancelled = cancelled
        self.requests: list[dict] = []

    def request(self, tool_id, tool_name, tool_args, *, session_id="default", diff=None):
        self.requests.append({
            "tool_id": tool_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "diff": diff,
            "session_id": session_id,
        })
        return {"id": tool_id, "session_id": session_id, "tool_name": tool_name,
                "tool_args": tool_args, "diff": diff}

    def wait_for_decision(self, tool_id, timeout=None, *, heartbeat=None,
                          heartbeat_interval=30.0, should_stop=None):
        if self.approved is None:
            return None
        return {
            "session_id": "session-1",
            "decision": self.approved,
            "always_allow": self.always,
            "timeout": self.timeout,
            "cancelled": self.cancelled,
        }

    def is_granted(self, session_id, key):
        return False

    def grant(self, session_id, key):
        pass


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "app.py").write_text("def run():\n    return 0\n", encoding="utf-8")
    return ws


def _outside(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "outside"
    shared = root / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    utils = shared / "utils.py"
    utils.write_text(OUTSIDE_UTILS, encoding="utf-8")
    (shared / "README.md").write_text("# shared\n", encoding="utf-8")
    (root / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    return root, utils


def _granted_discovery(ws: Path, path: Path, *, scope: str = TURN) -> WorkspaceDiscovery:
    grants = AccessGrantSet()
    grants.add(WorkspaceAccessGrant(path=str(path), operation=READ, scope=scope))
    return WorkspaceDiscovery(ws, access_grants=grants)


# --------------------------------------------------------------------------- #
# boundary + grant model
# --------------------------------------------------------------------------- #

def test_outside_path_requires_a_grant(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _, utils = _outside(tmp_path)
    discovery = WorkspaceDiscovery(ws)

    result = discovery.read_file(str(utils))
    assert result.ok is False
    assert result.error_code == "access_required"
    assert result.call.status == "blocked"
    assert result.data["path"] == str(utils.resolve())
    assert result.data["operation"] == "read"

    listed = discovery.list_files(str(utils.parent))
    assert listed.ok is False
    assert listed.error_code == "access_required"


def test_grant_allows_read_list_and_search(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    shared = _outside(tmp_path)[1].parent
    discovery = _granted_discovery(ws, shared)

    read = discovery.read_file(str(shared / "utils.py"))
    assert read.ok is True
    assert "shared_helper" in read.data["content"]
    assert read.data["path"].endswith("shared/utils.py")

    listed = discovery.list_files(str(shared))
    assert listed.ok is True
    assert {"README.md", "utils.py"} <= {item["path"].rsplit("/", 1)[-1] for item in listed.data["entries"]}
    assert all(item["path"].startswith(str(shared.resolve()).replace("\\", "/")) for item in listed.data["entries"])

    found = discovery.search("shared_helper", path=str(shared))
    assert found.ok is True
    assert found.data["count"] >= 1
    assert found.data["matches"][0]["path"].endswith("utils.py")


def test_once_grant_is_spent_after_one_read(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    utils = _outside(tmp_path)[1]
    discovery = _granted_discovery(ws, utils, scope=ONCE)

    first = discovery.read_file(str(utils))
    assert first.ok is True
    second = discovery.read_file(str(utils))
    assert second.ok is False
    assert second.error_code == "access_required"


def test_grant_is_path_exact(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    root, _utils = _outside(tmp_path)
    discovery = _granted_discovery(ws, root / "shared")

    sibling = discovery.read_file(str(root / "other.py"))
    assert sibling.ok is False
    assert sibling.error_code == "access_required"

    outside_parent = discovery.list_files(str(root))
    assert outside_parent.ok is False
    assert outside_parent.error_code == "access_required"


def test_read_grant_does_not_authorise_write(tmp_path: Path) -> None:
    utils = _outside(tmp_path)[1]
    grants = AccessGrantSet([WorkspaceAccessGrant(path=str(utils), operation=READ, scope=TURN)])
    assert grants.allows(utils, READ) is True
    assert grants.allows(utils, WRITE) is False

    grants.add(WorkspaceAccessGrant(path=str(utils), operation=WRITE, scope=TURN))
    assert grants.allows(utils, WRITE) is True


def test_sensitive_paths_are_refused_even_with_a_grant(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    key = home / ".ssh" / "id_rsa"
    key.write_text("PRIVATE KEY\n", encoding="utf-8")

    assert is_sensitive_external_path(key) is True
    with pytest.raises(PermissionError):
        AccessGrantSet().add(WorkspaceAccessGrant(path=str(key), operation=READ))

    grants = AccessGrantSet([WorkspaceAccessGrant(path=str(home), operation=READ)])
    assert grants.allows(key, READ) is False
    blocked = WorkspaceDiscovery(ws, access_grants=grants).read_file(str(key))
    assert blocked.ok is False
    assert blocked.error_code == "path_rejected"


def test_symlink_inside_a_grant_cannot_escape(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    root, _utils = _outside(tmp_path)
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    secret = secret_dir / "data.py"
    secret.write_text("SECRET = 1\n", encoding="utf-8")
    link = root / "shared" / "escape.py"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):  # pragma: no cover - host privilege
        pytest.skip("symlink creation not permitted on this host")

    discovery = _granted_discovery(ws, root / "shared")
    escaped = discovery.read_file(str(link))
    assert escaped.ok is False


def test_traversal_is_never_an_escalation_prompt(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _outside(tmp_path)
    discovery = WorkspaceDiscovery(ws)

    # A relative escape stays a hard rejection: it must not become a question.
    traversal = discovery.read_file("../outside/shared/utils.py")
    assert traversal.ok is False
    assert traversal.error_code == "path_rejected"


# --------------------------------------------------------------------------- #
# approval gateway
# --------------------------------------------------------------------------- #

def _gateway(queue: FakeQueue) -> OrchestratorApprovalGateway:
    return OrchestratorApprovalGateway(
        workspace_root=str(Path.cwd()),
        session_id="session-1",
        task_id="task-1",
        queue=queue,
        timeout_s=1.0,
        turn_id="turn-1",
    )


def test_gateway_asks_for_the_exact_path_and_allow_once(tmp_path: Path) -> None:
    _, utils = _outside(tmp_path)
    queue = FakeQueue(approved=True, always=False)
    gateway = _gateway(queue)

    verdict = gateway.request_access(path=str(utils), operation="read", reason="user asked")

    assert verdict["allowed"] is True
    assert verdict["scope"] == ONCE
    assert len(queue.requests) == 1
    asked = queue.requests[0]
    assert asked["tool_name"] == "workspace.access"
    assert asked["tool_args"]["path"] == str(utils.resolve())
    assert asked["tool_args"]["kind"] == "external_directory"
    assert gateway.receipts[-1]["decision"] == "allowed"
    assert gateway.receipts[-1]["operation"] == "access:read"


def test_gateway_allow_for_turn_and_deny_paths(tmp_path: Path) -> None:
    _, utils = _outside(tmp_path)

    turn_gateway = _gateway(FakeQueue(approved=True, always=True))
    turn_verdict = turn_gateway.request_access(path=str(utils))
    assert turn_verdict["allowed"] is True
    assert turn_verdict["scope"] == TURN

    deny_gateway = _gateway(FakeQueue(approved=False))
    deny_verdict = deny_gateway.request_access(path=str(utils))
    assert deny_verdict["allowed"] is False
    assert deny_verdict["reason"] == "user_denied"
    assert deny_gateway.receipts[-1]["decision"] == "denied"

    timeout_verdict = _gateway(FakeQueue(approved=True, timeout=True)).request_access(path=str(utils))
    assert timeout_verdict["allowed"] is False
    assert timeout_verdict["reason"] == "approval_timeout"

    cancelled_verdict = _gateway(FakeQueue(approved=True, cancelled=True)).request_access(path=str(utils))
    assert cancelled_verdict["allowed"] is False
    assert cancelled_verdict["reason"] == "turn_cancelled"


# --------------------------------------------------------------------------- #
# outside writes (Phase 2D-2)
# --------------------------------------------------------------------------- #

def _approve_write(tmp_path: Path, target: Path, content: str, existing: str):
    gate = RiskApprovalGate()
    gateway = OrchestratorApprovalGateway(
        workspace_root=str(tmp_path / "ws"),
        session_id="session-1",
        task_id="task-write",
        queue=FakeQueue(approved=True, always=True),
        risk_gate=gate,
        timeout_s=1.0,
        turn_id="turn-1",
    )
    auth = gateway.authorize(
        node_id="task_shared",
        path=str(target),
        proposed_content=content,
        existing_content=existing,
        always_token=True,
    )
    assert auth is not None
    return auth, gate


def test_write_grant_allows_broker_to_modify_outside(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    utils = _outside(tmp_path)[1]
    original = utils.read_text(encoding="utf-8")
    updated = original + "\n\ndef extra(value: int) -> int:\n    return value * 2\n"

    grants = AccessGrantSet([WorkspaceAccessGrant(path=str(utils), operation=WRITE, scope=TURN)])
    broker = WorkspaceMutationBroker(str(ws), access_grants=grants)
    auth, gate = _approve_write(tmp_path, utils, updated, original)
    broker.risk_gate = gate

    record = broker.modify_file(
        path=str(utils),
        new_content=updated,
        task_id="task-write",
        approval_token=auth.token,
        require_digest=True,
        session_id="session-1",
        turn_id="turn-1",
    )
    assert utils.read_text(encoding="utf-8") == updated
    assert record.file_path.endswith("shared/utils.py")
    assert record.operation_type.value == "MODIFY"


def test_read_grant_cannot_write_outside(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    utils = _outside(tmp_path)[1]
    grants = AccessGrantSet([WorkspaceAccessGrant(path=str(utils), operation=READ, scope=TURN)])
    broker = WorkspaceMutationBroker(str(ws), access_grants=grants)

    with pytest.raises(PathSecurityViolation):
        broker.modify_file(
            path=str(utils),
            new_content="hacked\n",
            task_id="task-write",
        )
    assert "hacked" not in utils.read_text(encoding="utf-8")


def test_external_write_requires_a_mutation_token(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    utils = _outside(tmp_path)[1]
    grants = AccessGrantSet([WorkspaceAccessGrant(path=str(utils), operation=WRITE, scope=TURN)])
    broker = WorkspaceMutationBroker(str(ws), access_grants=grants)

    with pytest.raises(MutationAuthorizationError):
        broker.modify_file(
            path=str(utils),
            new_content="no token\n",
            task_id="task-write",
        )
    assert "no token" not in utils.read_text(encoding="utf-8")


def test_grants_do_not_survive_a_turn(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    utils = _outside(tmp_path)[1]
    grants = AccessGrantSet([WorkspaceAccessGrant(path=str(utils), operation=WRITE, scope=TURN)])
    broker = WorkspaceMutationBroker(str(ws), access_grants=grants)
    broker.set_access_grants(None)
    with pytest.raises(PathSecurityViolation):
        broker.modify_file(path=str(utils), new_content="x\n", task_id="t")


# --------------------------------------------------------------------------- #
# orchestrator turns
# --------------------------------------------------------------------------- #

def _run_turn(tmp_path: Path, *, approved: bool, always: bool = True, monkeypatch, prompt: str | None = None):
    ws = _workspace(tmp_path)
    _, utils = _outside(tmp_path)
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("CRUSORAI_APP_DATA_ROOT", str(appdata))
    queue = FakeQueue(approved=approved, always=always)
    orchestrator = EngineeringExecutionOrchestrator(
        workspace_root=str(ws),
        tenant_id="default_tenant",
        limits=ExecutionLimits(max_cost_inr=1.0, max_dispatch_budget=3, max_correction_attempts=0),
        storage_dir=str(appdata / "orchestration" / "turn_p2d"),
        mock_mode=True,
        approval_channel=True,
        approval_policy="workspace_session",
        approval_queue=queue,
        session_id="session-1",
        turn_id="turn-1",
    )
    prompt = prompt or (
        f"Read {utils} and add a helper to src/app.py that calls shared_helper. "
        "Do not modify anything outside the workspace."
    )
    request = EngineeringTaskRequest(
        task_id="turn_p2d",
        session_id="session-1",
        workspace=str(ws),
        prompt=prompt,
        approval_policy="workspace_session",
        turn_id="turn-1",
        max_cost_inr=1.0,
        max_dispatch_budget=3,
        mock_mode=True,
        context_bundle={"history": []},
    )
    delivery = orchestrator.run_task_request(request)
    journal_path = appdata / "orchestration" / "turn_p2d" / "orchestration_journal.jsonl"
    events = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return delivery, events, str(utils.resolve()), queue, ws


def test_orchestrator_uses_an_allowed_external_file_as_context(tmp_path: Path, monkeypatch) -> None:
    delivery, events, external, queue, ws = _run_turn(tmp_path, approved=True, monkeypatch=monkeypatch)
    types = [event["event_type"] for event in events]

    assert "WORKSPACE_ACCESS_REQUESTED" in types
    assert "WORKSPACE_ACCESS_GRANTED" in types
    assert types.index("WORKSPACE_ACCESS_REQUESTED") < types.index("WORKSPACE_ACCESS_GRANTED")
    assert types.index("WORKSPACE_ACCESS_GRANTED") < types.index("CONTRACT_EXTRACTED")

    granted = next(event for event in events if event["event_type"] == "WORKSPACE_ACCESS_GRANTED")
    assert granted["details"]["path"] == external
    assert granted["details"]["scope"] == TURN

    discovered = next(event for event in events if event["event_type"] == "WORKSPACE_DISCOVERED")
    external_posix = external.replace("\\", "/")
    assert external_posix in {item["path"] for item in discovered["details"]["external"]}

    payload = delivery.to_dict()
    assert payload["outside_workspace_access"][0]["decision"] == "allowed"
    assert payload["outside_workspace_access"][0]["path"] == external

    # The outside file is context only: no plan target may live outside ws.
    contract_targets = {
        component["target_file"] for component in payload["contract"]["components"]
    }
    assert contract_targets
    for target in contract_targets:
        assert not Path(target).is_absolute()

    # The workspace file is the only thing the broker touched.
    receipt_paths = {receipt["file_path"] for receipt in payload["mutation_receipts"]}
    assert receipt_paths <= {"src/app.py"}
    assert queue.requests and queue.requests[0]["tool_name"] == "workspace.access"


def test_orchestrator_records_a_denied_external_request(tmp_path: Path, monkeypatch) -> None:
    delivery, events, external, queue, ws = _run_turn(tmp_path, approved=False, monkeypatch=monkeypatch)
    types = [event["event_type"] for event in events]

    assert "WORKSPACE_ACCESS_REQUESTED" in types
    assert "WORKSPACE_ACCESS_GRANTED" not in types
    assert "WORKSPACE_ACCESS_DENIED" in types

    discovered = next(event for event in events if event["event_type"] == "WORKSPACE_DISCOVERED")
    assert discovered["details"]["external"] == []

    payload = delivery.to_dict()
    assert payload["outside_workspace_access"][0]["decision"] == "denied"
    assert payload["outside_workspace_access"][0]["reason"] == "user_denied"
    assert any("Outside-workspace access" in note for note in payload["remaining_limitations"])
    assert queue.requests and queue.requests[0]["tool_args"]["path"] == external


def test_orchestrator_edits_an_approved_external_file(tmp_path: Path, monkeypatch) -> None:
    _, utils = _outside(tmp_path)
    prompt = (
        f"Edit {utils} to add a shared_helper wrapper. "
        "Keep the change minimal."
    )
    delivery, events, external, queue, ws = _run_turn(
        tmp_path, approved=True, monkeypatch=monkeypatch, prompt=prompt
    )

    requested = next(event for event in events if event["event_type"] == "WORKSPACE_ACCESS_REQUESTED")
    assert requested["details"]["operation"] == "write"
    granted = next(event for event in events if event["event_type"] == "WORKSPACE_ACCESS_GRANTED")
    assert granted["details"]["operation"] == "write"

    payload = delivery.to_dict()
    assert payload["outside_workspace_access"][0]["operation"] == "write"
    assert payload["outside_workspace_access"][0]["decision"] == "allowed"

    # The approved outside file was actually written, through the broker.
    written = Path(external).read_text(encoding="utf-8")
    assert "UtilsService" in written
    receipt_paths = {receipt["file_path"].replace("\\", "/") for receipt in payload["mutation_receipts"]}
    assert any(path.endswith("shared/utils.py") for path in receipt_paths)
    assert external.replace("\\", "/") in {path.replace("\\", "/") for path in payload["files_changed"]}
    assert queue.requests and queue.requests[0]["tool_args"]["operation"] == "write"

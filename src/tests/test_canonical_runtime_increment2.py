"""Increment 2 acceptance: one context/tool/approval/mutation boundary.

Provider-free. Uses the real ContextEngine bundle builder, the real
ApprovalQueue/RiskApprovalGate/WorkspaceMutationBroker, the real graph
SafeToolNode, and the shared model gateway with fake clients.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.context_engine import ContextEngine
from src.dashboard.event_bus import ApprovalQueue
from src.graphs import tool_policy
from src.graphs.chat_graph import (
    engineering_task_node,
    get_context_engine,
    tool_node,
    tools,
)
from src.llm.factory import TurnCancelledError
from src.llm.gateway import invoke_model, new_invocation_context
from src.orchestration.approval_gateway import (
    ApprovalDenied,
    OrchestratorApprovalGateway,
)
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.model_adapter import ModelExecutionAdapter, _render_context_bundle
from src.orchestration.models import EngineeringTaskNode
from src.workspace.approval_digest import content_digest
from src.workspace.mutation_broker import (
    MutationAuthorizationError,
    WorkspaceMutationBroker,
)
from src.workspace.models import WorkspaceOperationType


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# Context ownership / bundle
# ---------------------------------------------------------------------------

def _engine_with_messages(monkeypatch, messages: list, layers: list[str]) -> ContextEngine:
    engine = get_context_engine(f"ctx-{uuid.uuid4().hex[:8]}")
    calls: list[int] = []

    def fake_build(state, system_message):
        calls.append(1)
        return list(messages)

    monkeypatch.setattr(engine, "build_ai_messages", fake_build)
    engine._last_layers_sent = list(layers)
    engine._ctx_test_calls = calls  # type: ignore[attr-defined]
    return engine


def test_context_assembled_exactly_once(monkeypatch) -> None:
    messages = [
        SystemMessage(content="repo map layer"),
        HumanMessage(content="older question"),
        AIMessage(content="older answer"),
        HumanMessage(content="current request"),
    ]
    engine = _engine_with_messages(monkeypatch, messages, ["repo_map"])
    bundle = engine.build_engineering_context({"messages": []}, SystemMessage(content="sys"))
    assert engine._ctx_test_calls == [1]  # type: ignore[attr-defined]
    assert bundle["provenance"]["assembled_once"] is True
    assert bundle["budget"]["history_tokens"] >= 0


def test_context_bundle_is_bounded_and_provenanced(monkeypatch) -> None:
    messages = [SystemMessage(content="repo map layer")]
    messages.extend(
        HumanMessage(content=f"old question {i} " + "x" * 200) for i in range(30)
    )
    messages.append(HumanMessage(content="current request"))
    engine = _engine_with_messages(monkeypatch, messages, ["repo_map", "long_term_memory"])
    bundle = engine.build_engineering_context(
        {"messages": []}, SystemMessage(content="sys"), max_history_tokens=80
    )
    assert bundle["budget"]["truncated"] is True
    assert len(bundle["history"]) < 30
    assert "repo_map" in bundle["provenance"]["layers"]
    assert "long_term_memory" in bundle["provenance"]["layers"]
    assert bundle["current_request"] == "current request"
    # The current message is never duplicated into history.
    assert all(
        row["content"] != "current request" for row in bundle["history"]
    )


def test_context_provenance_reaches_engine_prompt() -> None:
    bundle = {
        "current_request": "build notes.md",
        "history": [{"role": "assistant", "content": "previous answer"}],
        "workspace_context": "repo map",
        "provenance": {"engine": "ContextEngine", "layers": ["repo_map"], "truncated": False},
        "budget": {"history_tokens": 10, "history_budget": 100, "truncated": False},
    }
    rendered = _render_context_bundle(bundle)
    assert "GRAPH-ASSEMBLED CONTEXT" in rendered
    assert "build notes.md" in rendered
    assert "repo_map" in rendered
    assert rendered.count("build notes.md") == 1


def test_engineering_node_sends_structured_bundle(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(self, request, **kwargs):
        captured["request"] = request
        from src.orchestration.models import DeliveryContract, TaskVerdict

        return DeliveryContract(
            task_id=request.task_id,
            original_request=request.prompt,
            verdict=TaskVerdict.COMPLETED,
            what_was_requested=request.prompt,
            what_was_implemented=[],
            files_changed=[],
            tests_executed=[],
            tests_passed=[],
            tests_failed=[],
            independently_verified=True,
            remaining_limitations=[],
            user_action_required=None,
        )

    monkeypatch.setattr(
        "src.orchestration.orchestrator.EngineeringExecutionOrchestrator.run_task_request",
        fake_run,
    )
    state = {
        "execution_mode": "agent",
        "canonical_runtime": True,
        "latest_instruction": "Create notes.md with a greeting",
        "current_task": "Create notes.md with a greeting",
        "messages": [HumanMessage(content="Create notes.md with a greeting")],
    }
    config = {"configurable": {
        "thread_id": f"eng-{uuid.uuid4().hex[:8]}",
        "workspace": str(Path.cwd()),
        "canonical_runtime": True,
    }}
    engineering_task_node(state, config)
    bundle = captured["request"].context_bundle
    assert bundle["current_request"] == "Create notes.md with a greeting"
    assert "provenance" in bundle and "budget" in bundle
    assert bundle["provenance"]["assembled_once"] is True


# ---------------------------------------------------------------------------
# Shared model gateway
# ---------------------------------------------------------------------------

class _FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(self, messages, config=None, **kwargs):
        self.calls.append({"messages": messages, "config": config, "kwargs": kwargs})
        return AIMessage(
            content="ok",
            usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        )


def test_gateway_attaches_correlation_metadata() -> None:
    llm = _FakeLLM()
    context = new_invocation_context(
        session_id="s1", turn_id="t1", task_id="task1",
        provider="p", model="m", subsystem="engineering", purpose="impl",
    )
    result = invoke_model(llm, "hello", context=context)
    assert result.text == "ok"
    metadata = llm.calls[0]["config"]["metadata"]
    assert metadata["crusor_session_id"] == "s1"
    assert metadata["crusor_turn_id"] == "t1"
    assert metadata["crusor_task_id"] == "task1"
    assert metadata["crusor_invocation_id"].startswith("inv-")
    assert llm.calls[0]["config"]["run_name"].startswith("crusor:engineering")


def test_gateway_cancellation_before_dispatch() -> None:
    llm = _FakeLLM()
    context = new_invocation_context(session_id="s", provider="p", model="m")
    with pytest.raises(TurnCancelledError):
        invoke_model(llm, "hello", context=context, cancellation_checker=lambda: True)
    assert llm.calls == []


def test_engineering_adapter_receives_bundle(monkeypatch, tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    adapter = ModelExecutionAdapter(str(ws), mock_mode=False)
    node = EngineeringTaskNode(
        node_id="task_notes", description="create notes", objective="notes",
        target_files=["notes.md"],
    )
    seen: dict = {}

    def fake_call(**kwargs):
        seen.update(kwargs)
        return "print('ok')\n"

    monkeypatch.setattr(adapter, "_call_model_for_implementation", fake_call)

    class _Finops:
        def authorize_operation(self, **kwargs): return None
        def record_usage(self, **kwargs): return None

    class _Loop:
        def record_action(self, **kwargs): return None

    engine = ControlledImplementationEngine(str(ws), broker=WorkspaceMutationBroker(str(ws)))
    gateway = OrchestratorApprovalGateway(
        workspace_root=str(ws), session_id="s", task_id="task1",
        policy="workspace_session", queue=ApprovalQueue(), turn_id="t1",
    )
    adapter.execute_node(
        task_id="task1", node=node, specification=None, blueprint=None,
        project_knowledge=None, impl_engine=engine, finops=_Finops(),
        reasoning_loop=_Loop(), approval_gateway=gateway,
        context_bundle={"current_request": "create notes", "history": []},
        session_id="s", turn_id="t1",
    )
    assert seen["context_bundle"]["current_request"] == "create notes"
    assert (ws / "notes.md").exists()


def test_engineering_prompt_carries_bounded_context(monkeypatch, tmp_path: Path) -> None:
    adapter = ModelExecutionAdapter(str(tmp_path), mock_mode=False)
    node = EngineeringTaskNode(
        node_id="task_notes", description="create notes", objective="notes",
        target_files=["notes.md"],
    )
    captured: dict = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return "print('ok')\n"

    monkeypatch.setattr(adapter, "_dispatch_code_prompt", fake_dispatch)
    adapter._call_model_for_implementation(
        node=node,
        target_file="notes.md",
        existing_content="",
        specification=None,
        blueprint=None,
        project_knowledge=None,
        finops=object(),  # never reached: dispatch is stubbed
        context_bundle={
            "current_request": "create notes",
            "history": [{"role": "assistant", "content": "prior"}],
            "workspace_context": "repo map",
            "provenance": {"engine": "ContextEngine", "layers": ["repo_map"]},
            "budget": {"truncated": False},
        },
        session_id="s1",
        turn_id="t1",
        task_id="task1",
    )
    prompt = captured["prompt"]
    assert "GRAPH-ASSEMBLED CONTEXT" in prompt
    assert "create notes" in prompt
    assert "repo_map" in prompt
    assert captured["session_id"] == "s1"
    assert captured["task_id"] == "task1"


def test_child_agent_inherits_canonical_runtime(monkeypatch) -> None:
    import src.graphs.chat_graph as chat_graph

    captured: dict = {}

    def fake_invoke(state, config):
        captured["state"] = state
        captured["config"] = config
        return {"messages": [AIMessage(content="child done")]}

    monkeypatch.setattr(chat_graph.graph, "invoke", fake_invoke)
    monkeypatch.setenv("CRUSORAI_CANONICAL_RUNTIME", "1")
    chat_graph.invoke_agent("child task", thread_id="sub-test", workspace=".")
    assert captured["config"]["configurable"]["canonical_runtime"] is True
    assert captured["state"]["canonical_runtime"] is True


# ---------------------------------------------------------------------------
# Tool inventory / graph boundary
# ---------------------------------------------------------------------------

def test_tool_inventory_classifies_every_registered_tool() -> None:
    unknown = [t.name for t in tools if not tool_policy.is_known(t.name)]
    assert unknown == []
    assert tool_policy.classify_tool("write_file") == "workspace_write"
    assert tool_policy.classify_tool("edit_file") == "workspace_write"
    assert tool_policy.classify_tool("run_terminal") == "shell"
    assert tool_policy.classify_tool("read_file") == "read_only"


def test_read_only_graph_tool_still_works(tmp_path: Path) -> None:
    target = tmp_path / "readme.txt"
    target.write_text("hello\n", encoding="utf-8")
    state = {"messages": [AIMessage(content="", tool_calls=[{
        "name": "read_file", "args": {"path": str(target)}, "id": "call-read",
    }])]}
    result = tool_node(state, {"configurable": {
        "thread_id": "read-1", "workspace": str(tmp_path),
        "canonical_runtime": True, "approval_channel": True,
    }})
    message = result["messages"][0]
    assert isinstance(message, ToolMessage)
    assert "hello" in str(message.content)


def test_unknown_tool_fails_closed(tmp_path: Path) -> None:
    state = {"messages": [AIMessage(content="", tool_calls=[{
        "name": "definitely_unknown_tool_xyz",
        "args": {"x": 1}, "id": "call-unknown",
    }])]}
    result = tool_node(state, {"configurable": {
        "thread_id": "unknown-1", "workspace": str(tmp_path),
        "canonical_runtime": True, "approval_channel": True,
    }})
    message = result["messages"][0]
    assert "unknown tool" in str(message.content).lower()


def test_shell_mutation_stays_disabled(tmp_path: Path) -> None:
    marker = tmp_path / "terminal_ran.txt"
    state = {"messages": [AIMessage(content="", tool_calls=[{
        "name": "run_terminal", "args": {"command": f"echo x > {marker}"},
        "id": "call-shell",
    }])]}
    result = tool_node(state, {"configurable": {
        "thread_id": "shell-1", "workspace": str(tmp_path),
        "canonical_runtime": True, "approval_channel": True,
    }})
    assert "Blocked by runtime policy" in str(result["messages"][0].content)
    assert not marker.exists()


def test_graph_write_file_uses_broker_and_receipt(tmp_path: Path) -> None:
    thread = f"write-{uuid.uuid4().hex[:8]}"
    state = {"messages": [AIMessage(content="", tool_calls=[{
        "name": "write_file",
        "args": {"path": "hello.txt", "content": "hello graph\n"},
        "id": "call-write-ok",
    }])]}
    result = tool_node(state, {"configurable": {
        "thread_id": thread, "workspace": str(tmp_path),
        "canonical_runtime": True, "approval_channel": True,
        "approval_policy": "workspace_session",
    }})
    assert "File written" in str(result["messages"][0].content)
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello graph\n"
    broker = WorkspaceMutationBroker.get_instance(str(tmp_path))
    records = broker.ledger.get_records(thread)
    assert any(
        r.file_path == "hello.txt" and str(r.approval_ref or "").startswith("APPV-")
        for r in records
    )


# ---------------------------------------------------------------------------
# Diff / digest / approval lifecycle
# ---------------------------------------------------------------------------

def _gateway(ws: Path, *, policy: str = "ask", cancelled=None):
    queue = ApprovalQueue()
    events: list[tuple[str, dict]] = []
    gateway = OrchestratorApprovalGateway(
        workspace_root=str(ws), session_id="session-1", task_id="task-1",
        policy=policy, queue=queue,
        emit=lambda kind, payload: events.append((kind, payload)),
        cancellation_checker=cancelled, heartbeat_interval=0.02,
    )
    return gateway, queue, events


def _start(gateway, **kwargs):
    result: dict = {}

    def worker():
        try:
            result["auth"] = gateway.authorize(**kwargs)
        except BaseException as exc:  # noqa: BLE001
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


def test_diff_and_digest_are_present_before_approval(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    (ws / "notes.md").write_text("old line\n", encoding="utf-8")
    proposed = "old line\nnew line\n"
    gateway, queue, events = _gateway(ws)
    thread, result = _start(
        gateway, node_id="n1", path="notes.md", reason="add line",
        proposed_content=proposed, existing_content="old line\n",
    )
    item = _wait_pending(queue)
    assert queue.resolve(item["id"], True, session_id="session-1") is True
    thread.join(timeout=5)
    auth = result["auth"]
    assert auth.digest == content_digest(proposed)
    event = [p for k, p in events if k == "tool.approval.request"][0]
    assert "+new line" in event["diff"]["diff"]
    assert event["diff"]["content_digest"] == content_digest(proposed)


def test_changed_proposal_invalidates_approval_and_token_is_single_use(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    (ws / "notes.md").write_text("old\n", encoding="utf-8")
    approved = "old\napproved\n"
    changed = "old\nchanged\n"
    gateway, queue, _events = _gateway(ws)
    thread, result = _start(
        gateway, node_id="n1", path="notes.md", reason="edit",
        proposed_content=approved, existing_content="old\n",
        always_token=True,
    )
    item = _wait_pending(queue)
    queue.resolve(item["id"], True, session_id="session-1")
    thread.join(timeout=5)
    auth = result["auth"]
    broker = WorkspaceMutationBroker.get_instance(str(ws))

    with pytest.raises(MutationAuthorizationError):
        broker.modify_file(
            path="notes.md", new_content=changed, task_id="task-1",
            approval_token=auth.token, require_digest=True,
            session_id=auth.session_id, turn_id=auth.turn_id,
        )
    assert (ws / "notes.md").read_text(encoding="utf-8") == "old\n"

    # The exact approved bytes still apply, and the token is single-use.
    broker.modify_file(
        path="notes.md", new_content=approved, task_id="task-1",
        approval_token=auth.token, require_digest=True,
        session_id=auth.session_id, turn_id=auth.turn_id,
    )
    assert (ws / "notes.md").read_text(encoding="utf-8") == approved
    with pytest.raises(MutationAuthorizationError):
        broker.modify_file(
            path="notes.md", new_content=approved, task_id="task-1",
            approval_token=auth.token, require_digest=True,
            session_id=auth.session_id, turn_id=auth.turn_id,
        )


def test_denial_leaves_workspace_unchanged(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    (ws / "notes.md").write_text("original\n", encoding="utf-8")
    gateway, queue, _events = _gateway(ws)
    thread, result = _start(
        gateway, node_id="n1", path="notes.md", reason="edit",
        proposed_content="changed\n", existing_content="original\n",
    )
    item = _wait_pending(queue)
    queue.resolve(item["id"], False, session_id="session-1")
    thread.join(timeout=5)
    assert isinstance(result.get("error"), ApprovalDenied)
    assert (ws / "notes.md").read_text(encoding="utf-8") == "original\n"


def test_cancellation_leaves_workspace_unchanged(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    (ws / "notes.md").write_text("original\n", encoding="utf-8")
    cancelled = {"value": False}
    gateway, queue, _events = _gateway(ws, cancelled=lambda: cancelled["value"])
    thread, result = _start(
        gateway, node_id="n1", path="notes.md", reason="edit",
        proposed_content="changed\n", existing_content="original\n",
    )
    item = _wait_pending(queue)
    cancelled["value"] = True
    queue.resolve(item["id"], False, session_id="session-1")
    thread.join(timeout=5)
    assert isinstance(result.get("error"), ApprovalDenied)
    assert result["error"].reason in {"turn_cancelled", "user_denied"}
    assert (ws / "notes.md").read_text(encoding="utf-8") == "original\n"


def test_shutdown_while_awaiting_approval_leaves_workspace_unchanged(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    (ws / "notes.md").write_text("original\n", encoding="utf-8")
    stopping = {"value": False}
    gateway, queue, _events = _gateway(ws, cancelled=lambda: stopping["value"])
    thread, result = _start(
        gateway, node_id="n1", path="notes.md", reason="edit",
        proposed_content="changed\n", existing_content="original\n",
    )
    _wait_pending(queue)
    stopping["value"] = True  # worker shutdown / Stop
    thread.join(timeout=5)
    assert isinstance(result.get("error"), ApprovalDenied)
    assert result["error"].reason in {"turn_cancelled", "approval_abandoned"}
    assert (ws / "notes.md").read_text(encoding="utf-8") == "original\n"


def test_policy_grant_still_carries_digest_bound_token(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    (ws / "notes.md").write_text("original\n", encoding="utf-8")
    gateway, queue, events = _gateway(ws, policy="workspace_session")
    auth = gateway.authorize(
        node_id="n1", path="notes.md", reason="low risk",
        proposed_content="new\n", existing_content="original\n",
        always_token=True,
    )
    assert auth is not None and auth.token.startswith("APPV-")
    assert auth.digest == content_digest("new\n")
    assert queue.get_pending("session-1") == []
    assert events == []

    broker = WorkspaceMutationBroker.get_instance(str(ws))
    broker.modify_file(
        path="notes.md", new_content="new\n", task_id="task-1",
        approval_token=auth.token, require_digest=True,
        session_id=auth.session_id, turn_id=auth.turn_id,
    )
    assert (ws / "notes.md").read_text(encoding="utf-8") == "new\n"


def _wait_pending_for(queue: ApprovalQueue, session_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = queue.get_pending(session_id)
        if pending:
            return pending[0]
        time.sleep(0.01)
    raise AssertionError("graph approval never reached the queue")


def _run_graph_write(monkeypatch, tmp_path: Path, *, approve: bool):
    thread = f"graph-ask-{uuid.uuid4().hex[:8]}"
    queue = ApprovalQueue()
    monkeypatch.setattr("src.dashboard.event_bus.approval_queue", queue)
    state = {"messages": [AIMessage(content="", tool_calls=[{
        "name": "write_file",
        "args": {"path": "approved.txt", "content": "approved graph write\n"},
        "id": "call-ask-write",
    }])]}
    config = {"configurable": {
        "thread_id": thread, "workspace": str(tmp_path),
        "canonical_runtime": True, "approval_channel": True,
        "approval_policy": "ask",
    }}
    result: dict = {}

    def worker():
        result["value"] = tool_node(state, config)

    runner = threading.Thread(target=worker, daemon=True)
    runner.start()
    item = _wait_pending_for(queue, thread)
    assert item["diff"]["kind"] == "file"
    assert "+approved graph write" in item["diff"]["diff"]
    assert item["diff"]["content_digest"] == content_digest("approved graph write\n")
    queue.resolve(item["id"], approve, session_id=thread)
    runner.join(timeout=10)
    return result["value"]


def test_graph_ask_approval_binds_diff_and_applies(tmp_path: Path, monkeypatch) -> None:
    result = _run_graph_write(monkeypatch, tmp_path, approve=True)
    message = result["messages"][0]
    assert "File written" in str(message.content)
    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "approved graph write\n"


def test_graph_ask_denial_leaves_workspace_unchanged(tmp_path: Path, monkeypatch) -> None:
    result = _run_graph_write(monkeypatch, tmp_path, approve=False)
    message = result["messages"][0]
    assert "denied" in str(message.content).lower() or "⛔" in str(message.content)
    assert not (tmp_path / "approved.txt").exists()

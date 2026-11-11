"""Increment 3 acceptance: approval freshness, canonical receipt, FinOps.

Provider-free. Uses the real gateway/broker/receipt builders and the unified
invocation ledger.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.finops.invocation_context import (
    ledger_path,
    read_invocations,
    record_invocation,
    summarize_invocations,
)
from src.llm.gateway import invoke_model, new_invocation_context
from src.orchestration.approval_gateway import OrchestratorApprovalGateway
from src.runtime.turn_receipt import (
    CANCELLED,
    COMPLETED,
    DENIED,
    NOT_VERIFIED,
    PARTIAL,
    build_turn_receipt,
    enrich_receipt,
)
from src.workspace.mutation_broker import (
    MutationAuthorizationError,
    WorkspaceMutationBroker,
)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _gateway(ws: Path, *, turn_id: str = "turn-1") -> OrchestratorApprovalGateway:
    return OrchestratorApprovalGateway(
        workspace_root=str(ws),
        session_id="session-1",
        task_id="task-1",
        policy="workspace_session",
        turn_id=turn_id,
    )


def _approve(
    gateway: OrchestratorApprovalGateway,
    ws: Path,
    *,
    path: str,
    proposed: str,
    existing: str | None,
):
    return gateway.authorize(
        node_id="n1",
        path=path,
        reason="increment3",
        proposed_content=proposed,
        existing_content=existing,
        always_token=True,
    )


def test_stale_workspace_state_invalidates_approval_modify(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    target = ws / "notes.md"
    target.write_text("A\n", encoding="utf-8")
    gateway = _gateway(ws)
    auth = _approve(gateway, ws, path="notes.md", proposed="B\n", existing="A\n")
    assert auth is not None

    # Another process changes A -> C after approval.
    target.write_text("C\n", encoding="utf-8")

    broker = WorkspaceMutationBroker.get_instance(str(ws))
    with pytest.raises(MutationAuthorizationError):
        broker.modify_file(
            path="notes.md",
            new_content="B\n",
            task_id="task-1",
            approval_token=auth.token,
            require_digest=True,
            session_id=auth.session_id,
            turn_id=auth.turn_id,
        )
    assert target.read_text(encoding="utf-8") == "C\n"


def test_stale_new_file_race_cannot_overwrite(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    gateway = _gateway(ws)
    auth = _approve(gateway, ws, path="new.txt", proposed="B\n", existing=None)
    assert auth is not None

    # Another process creates the destination after approval.
    (ws / "new.txt").write_text("C\n", encoding="utf-8")

    broker = WorkspaceMutationBroker.get_instance(str(ws))
    with pytest.raises(MutationAuthorizationError):
        broker.create_file(
            path="new.txt",
            content="B\n",
            task_id="task-1",
            approval_token=auth.token,
            require_approval=True,
            require_digest=True,
            session_id=auth.session_id,
            turn_id=auth.turn_id,
        )
    assert (ws / "new.txt").read_text(encoding="utf-8") == "C\n"


def test_bridge_has_no_competing_interactive_route() -> None:
    source = Path("src/bridge/__main__.py").read_text(encoding="utf-8")
    assert "use_orchestrator" not in source
    assert "EngineeringExecutionOrchestrator(" not in source
    assert "canonical_runtime=True" in source
    assert "result = stream_agent(" in source


def _delivery(**overrides) -> dict:
    payload = {
        "task_id": "task-1",
        "verdict": "COMPLETED",
        "independently_verified": True,
        "files_changed": ["notes.md"],
        "tests_executed": ["pytest -q"],
        "tests_passed": ["pytest -q"],
        "tests_failed": [],
    }
    payload.update(overrides)
    return payload


def test_receipt_status_matrix_is_truthful() -> None:
    completed = build_turn_receipt(
        session_id="s", turn_id="t", state={"engineering_delivery": _delivery()},
        completed=True,
    )
    assert completed["terminal_status"] == COMPLETED

    unverified = build_turn_receipt(
        session_id="s", turn_id="t",
        state={"engineering_delivery": _delivery(independently_verified=False)},
        completed=True,
    )
    assert unverified["terminal_status"] == NOT_VERIFIED

    partial = build_turn_receipt(
        session_id="s", turn_id="t",
        state={"engineering_delivery": _delivery(verdict="PARTIALLY_COMPLETED")},
        completed=True,
    )
    assert partial["terminal_status"] == PARTIAL

    denied = build_turn_receipt(
        session_id="s", turn_id="t", state={}, completed=False, denied=True,
    )
    assert denied["terminal_status"] == DENIED

    cancelled = build_turn_receipt(
        session_id="s", turn_id="t", state={}, completed=False, cancelled=True,
    )
    assert cancelled["terminal_status"] == CANCELLED

    chat = build_turn_receipt(
        session_id="s", turn_id="t", state={"task_action": "chat"},
        message="hello", completed=True,
    )
    assert chat["task_classification"] == "chat"
    assert chat["terminal_status"] == COMPLETED


def test_denied_receipt_reports_zero_landed_mutations() -> None:
    receipt = build_turn_receipt(
        session_id="s",
        turn_id="t",
        state={
            "engineering_delivery": _delivery(verdict="CANCELLED", files_changed=[]),
            "mutation_receipts": [],
        },
        completed=False,
        denied=True,
    )
    assert receipt["terminal_status"] == DENIED
    assert receipt["changed_files"] == []
    assert receipt["mutation_receipts"] == []
    assert receipt["approval_receipts"] == []


def test_receipt_enrichment_keeps_evidence_and_reseals() -> None:
    base = build_turn_receipt(session_id="s", turn_id="t", state={}, completed=True)
    enriched = enrich_receipt(base, evidence={"status": "persisted"})
    assert enriched["evidence"]["status"] == "persisted"
    assert enriched["receipt_id"] != base["receipt_id"]
    assert json.dumps(enriched, sort_keys=True)


class _FakeLLM:
    def invoke(self, messages, config=None, **kwargs):
        return AIMessage(
            content="ok",
            usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        )


def test_unified_finops_ledger_counts_each_call_once(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    ctx = new_invocation_context(
        session_id="s1", turn_id="t1", task_id="task-1",
        provider="fake", model="fake", subsystem="graph",
        workspace=str(ws), purpose="chat",
    )
    invoke_model(_FakeLLM(), "hi", context=ctx, record_telemetry=True)
    invoke_model(_FakeLLM(), "hi", context=ctx, record_telemetry=True)

    records = read_invocations(ws)
    assert len(records) == 2
    assert len({r["invocation_id"] for r in records}) == 2

    record_invocation(ws, {
        "invocation_id": "inv-eng-1",
        "session_id": "s1", "turn_id": "t1", "task_id": "task-1",
        "subsystem": "engineering", "provider": "fake", "model": "fake",
        "status": "settled", "input_tokens": 20, "output_tokens": 5,
        "actual_cost_inr": 0.25,
    })
    summary = summarize_invocations(read_invocations(ws))
    assert summary["total_calls"] == 3
    assert summary["total_tokens"] == 10 + 4 + 10 + 4 + 20 + 5
    assert summary["by_task"]["task-1"]["calls"] == 3
    assert summary["by_session"]["s1"]["calls"] == 3
    assert summary["by_subsystem"]["graph"]["calls"] == 2
    assert summary["by_subsystem"]["engineering"]["calls"] == 1
    assert sum(summary["by_day"][d]["calls"] for d in summary["by_day"]) == 3
    assert summary["unknown_cost_calls"] >= 2  # graph receipts carry no cost

    # The ledger is one append-only JSONL file per workspace.
    assert ledger_path(ws).exists()

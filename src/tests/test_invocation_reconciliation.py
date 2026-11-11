"""Provider-free proof of one canonical invocation identity end to end.

Gateway -> response -> FinOps ledger -> delivery receipt. Retries are separate
physical invocations with distinct ids, and replayed ledger lines never
double-count usage or cost.
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage

from src.finops.invocation_context import (
    latest_invocations,
    new_invocation_id,
    read_invocations,
    record_invocation,
    summarize_invocations,
)
from src.llm.gateway import invoke_model, new_invocation_context
from src.orchestration.model_adapter import canonical_invocation_id
from src.runtime.turn_receipt import build_turn_receipt
from src.bridge.agent_cards import card_for_frame, card_frames_for_frame


class FakeLLM:
    def invoke(self, messages, config=None, **kwargs):
        return AIMessage(
            content="ok",
            usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
        )


def _context(workspace: Path):
    return new_invocation_context(
        session_id="s-inv",
        turn_id="t-inv",
        task_id="task-inv",
        provider="fake",
        model="fake-model",
        subsystem="chat",
        workspace=str(workspace),
        purpose="test",
    )


def test_gateway_id_is_the_only_id_in_the_ledger(tmp_path: Path, monkeypatch) -> None:
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("CRUSORAI_APP_DATA_ROOT", str(appdata))

    result = invoke_model(
        FakeLLM(), "hello", context=_context(tmp_path), record_telemetry=True
    )

    assert result.context.invocation_id.startswith("inv-")
    records = read_invocations(tmp_path)
    assert len(records) == 1
    assert records[0]["invocation_id"] == result.context.invocation_id
    assert records[0]["status"] == "settled"
    assert records[0]["session_id"] == "s-inv"


def test_reused_context_gets_a_fresh_physical_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CRUSORAI_APP_DATA_ROOT", str(tmp_path / "appdata"))
    context = _context(tmp_path)

    first = invoke_model(FakeLLM(), "a", context=context, record_telemetry=True)
    second = invoke_model(FakeLLM(), "b", context=context, record_telemetry=True)

    assert first.context.invocation_id != second.context.invocation_id
    ids = [record["invocation_id"] for record in read_invocations(tmp_path)]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_adapter_adopts_gateway_id_not_its_placeholder() -> None:
    class Result:
        class context:  # noqa: N801 - shape of InvocationResult
            invocation_id = "inv-gateway-canonical"

    assert canonical_invocation_id(Result(), "inv-placeholder") == "inv-gateway-canonical"
    assert canonical_invocation_id(object(), "inv-placeholder") == "inv-placeholder"


def test_replayed_ledger_lines_count_once(tmp_path: Path) -> None:
    invocation_id = new_invocation_id()
    for status, cost in (("released", 0.0), ("settled", 0.25)):
        record_invocation(tmp_path, {
            "invocation_id": invocation_id,
            "session_id": "s-inv",
            "turn_id": "t-inv",
            "subsystem": "chat",
            "status": status,
            "input_tokens": 10,
            "output_tokens": 5,
            "actual_cost_inr": cost,
        })

    summary = summarize_invocations(read_invocations(tmp_path))
    assert summary["total_calls"] == 1
    assert summary["total_cost_inr"] == 0.25
    assert summary["total_tokens"] == 15
    assert summary["statuses"] == {"settled": 1}
    assert [r["invocation_id"] for r in latest_invocations(read_invocations(tmp_path))] == [
        invocation_id
    ]


def test_true_retries_remain_separate_and_traceable(tmp_path: Path) -> None:
    for attempt in (1, 2):
        record_invocation(tmp_path, {
            "invocation_id": new_invocation_id(),
            "session_id": "s-inv",
            "turn_id": "t-inv",
            "subsystem": "chat",
            "status": "settled",
            "attempt_number": attempt,
            "retry_count": attempt - 1,
            "input_tokens": 4,
            "output_tokens": 2,
            "actual_cost_inr": 0.1,
        })

    summary = summarize_invocations(read_invocations(tmp_path))
    assert summary["total_calls"] == 2
    assert summary["total_tokens"] == 12
    assert abs(summary["total_cost_inr"] - 0.2) < 1e-9


def test_turn_receipt_references_the_gateway_invocation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CRUSORAI_APP_DATA_ROOT", str(tmp_path / "appdata"))
    result = invoke_model(
        FakeLLM(), "hello", context=_context(tmp_path), record_telemetry=True
    )
    expected = result.context.invocation_id

    # A replayed line for the same invocation must not duplicate the receipt.
    record_invocation(tmp_path, {
        "invocation_id": expected,
        "session_id": "s-inv",
        "turn_id": "t-inv",
        "subsystem": "chat",
        "status": "settled",
        "input_tokens": 11,
        "output_tokens": 7,
        "actual_cost_inr": 0.01,
    })

    receipt = build_turn_receipt(
        session_id="s-inv",
        turn_id="t-inv",
        state={"task_status": "completed"},
        workspace=str(tmp_path),
    )

    assert receipt["model_invocations"]["ids"] == [expected]
    assert receipt["model_invocations"]["summary"]["total_calls"] == 1
    assert receipt["model_invocations"]["summary"]["total_tokens"] == 18


def test_graph_chat_uses_one_canonical_turn_id_in_ledger_and_receipt(tmp_path: Path) -> None:
    """Real graph + scripted provider: session, turn, ledger and receipt agree."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path as _Path

    repo = _Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    home.mkdir()
    script = json.dumps([{
        "content": "Crusor — Build and Ship with Ease 🚀",
        "chunks": ["Crusor — Build ", "and Ship with Ease 🚀"],
        "usage": {"input_tokens": 12, "output_tokens": 6, "total_tokens": 18},
    }], ensure_ascii=False)
    code = r"""
import json, os
from src.graphs.chat_graph import stream_agent
from src.finops.invocation_context import read_invocations
ws = os.environ["PROBE_WS"]
result = stream_agent(
    "What is the launch line?",
    thread_id="graph-canonical-thread",
    workspace=ws,
    execution_mode="ask",
    approval_channel=True,
    approval_policy="workspace_session",
    turn_id="graph-canonical-turn",
    canonical_runtime=True,
)
records = read_invocations(ws)
receipt = getattr(result, "receipt", None) or {}
print(json.dumps({
    "completed": bool(result.completed),
    "records": records,
    "receipt_ids": (receipt.get("model_invocations") or {}).get("ids") or [],
}, ensure_ascii=False))
"""
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "CRUSORAI_TEST_MODE": "1",
        "CRUSORAI_TEST_LLM_SCRIPT": script,
        "CRUSORAI_AUTOTITLE": "0",
        "CRUSORAI_APP_DATA_ROOT": str(tmp_path / "appdata"),
        "MEMORY_NUDGE_INTERVAL": "0",
        "PYTHONPATH": str(repo),
        "PYTHONIOENCODING": "utf-8",
        "PROBE_WS": str(tmp_path / "ws"),
    })
    (tmp_path / "ws").mkdir()
    out = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["completed"] is True
    records = payload["records"]
    assert records, "the graph turn must write one canonical invocation record"
    assert all(r["session_id"] == "graph-canonical-thread" for r in records)
    assert all(r["turn_id"] == "graph-canonical-turn" for r in records)
    ids = [r["invocation_id"] for r in records]
    assert all(i.startswith("inv-") for i in ids)
    assert set(payload["receipt_ids"]) == set(ids)


def test_cost_card_carries_the_receipt_invocation_id() -> None:
    receipt = {
        "terminal_status": "completed",
        "model_invocations": {"ids": ["inv-card-1"]},
        "usage": {"cost_inr": 0.0, "cost_usd": 0.0, "token_usage": {
            "input_tokens": 4, "output_tokens": 2, "model": "fake",
        }},
    }
    card = card_for_frame({"type": "turn_done", "session_id": "s", "turn_id": "t", "receipt": receipt})
    cards = card_frames_for_frame(
        {"type": "turn_done", "session_id": "s", "turn_id": "t", "receipt": receipt}
    )
    cost = [c for c in cards if c["card_type"] == "cost"][0]
    assert cost["data"]["invocation_ids"] == ["inv-card-1"]
    assert card["card_type"] == "delivery"


def test_engineering_dispatch_uses_canonical_id_through_real_orchestrator(tmp_path: Path) -> None:
    """Real graph → orchestrator → adapter → gateway → ledger → receipt."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path as _Path

    repo = _Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    home.mkdir()
    content = "Crusor is an AI-powered coding IDE that plans, applies and verifies changes.\n"
    steps = [{
        "content": content,
        "usage": {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60},
    } for _ in range(10)]
    code = r"""
import json, os
from src.graphs.chat_graph import graph, stream_agent
from src.finops.invocation_context import read_invocations
ws = os.environ["PROBE_WS"]
result = stream_agent(
    "Create exactly one file named acceptance.md containing a short description of Crusor. Do not create any other user deliverables.",
    thread_id="eng-canonical-thread",
    workspace=ws,
    execution_mode="agent",
    approval_channel=True,
    approval_policy="workspace_session",
    turn_id="eng-canonical-turn",
    canonical_runtime=True,
)
records = read_invocations(ws)
snap = graph.get_state({"configurable": {"thread_id": "eng-canonical-thread"}})
values = dict(snap.values or {})
receipt = values.get("turn_receipt") or {}
print(json.dumps({
    "completed": bool(result.completed),
    "records": records,
    "receipt_ids": (receipt.get("model_invocations") or {}).get("ids") or [],
    "delivery": values.get("engineering_delivery") or {},
    "files": [str(p.relative_to(ws)) for p in __import__("pathlib").Path(ws).rglob("*") if p.is_file()],
}, ensure_ascii=False))
"""
    env = dict(os.environ)
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "CRUSORAI_TEST_MODE": "1",
        "CRUSORAI_FORCE_REAL_MODEL": "1",
        "CRUSORAI_TEST_LLM_SCRIPT": json.dumps(steps, ensure_ascii=False),
        "CRUSORAI_AUTOTITLE": "0",
        "CRUSORAI_APP_DATA_ROOT": str(tmp_path / "appdata"),
        "MEMORY_NUDGE_INTERVAL": "0",
        "PYTHONPATH": str(repo),
        "PYTHONIOENCODING": "utf-8",
        "PROBE_WS": str(tmp_path / "ws"),
    })
    (tmp_path / "ws").mkdir()
    out = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["completed"] is True
    assert payload["files"] == ["acceptance.md"]
    assert payload["delivery"]["verdict"] == "COMPLETED"
    assert payload["delivery"]["independently_verified"] is True
    records = payload["records"]
    assert records and all(r["turn_id"] == "eng-canonical-turn" for r in records)
    ids = [r["invocation_id"] for r in records]
    assert all(i.startswith("inv-") for i in ids)
    assert set(payload["receipt_ids"]) == set(ids)


def test_engineering_and_repair_ledger_records_keep_distinct_ids(tmp_path: Path) -> None:
    """Implementation and repair dispatches are separate physical invocations."""
    for operation, purpose, cost in (
        ("implementation", "implementation", 0.20),
        ("repair", "repair_compile", 0.05),
    ):
        record_invocation(tmp_path, {
            "invocation_id": new_invocation_id(),
            "session_id": "s-eng",
            "turn_id": "t-eng",
            "subsystem": "engineering",
            "operation_type": operation,
            "purpose": purpose,
            "reservation_id": "res-1",
            "status": "settled",
            "input_tokens": 100,
            "output_tokens": 20,
            "actual_cost_inr": cost,
        })
    records = read_invocations(tmp_path)
    assert len({r["invocation_id"] for r in records}) == 2
    summary = summarize_invocations(records)
    assert summary["total_calls"] == 2
    assert abs(summary["total_cost_inr"] - 0.25) < 1e-9
    assert summary["by_subsystem"]["engineering"]["calls"] == 2


def test_unknown_cost_is_never_presented_as_zero() -> None:
    receipt = {
        "terminal_status": "completed",
        "model_invocations": {"ids": ["inv-unknown"]},
        "usage": {"cost_inr": None, "cost_usd": None, "cost_unknown": True, "token_usage": {}},
    }
    cards = card_frames_for_frame(
        {"type": "turn_done", "session_id": "s", "turn_id": "t", "receipt": receipt}
    )
    cost = [c for c in cards if c["card_type"] == "cost"][0]
    assert cost["data"]["certainty"] == "unknown"
    assert cost["data"]["cost_inr"] is None


def test_receipt_preserves_unknown_cost_from_ledger(tmp_path: Path) -> None:
    record_invocation(tmp_path, {
        "invocation_id": "inv-unknown-ledger",
        "session_id": "s-unknown",
        "turn_id": "t-unknown",
        "subsystem": "graph",
        "status": "settled",
        "input_tokens": 10,
        "output_tokens": 2,
        "cost_unknown": True,
    })
    receipt = build_turn_receipt(
        session_id="s-unknown",
        turn_id="t-unknown",
        state={"task_status": "completed"},
        workspace=str(tmp_path),
    )
    assert receipt["usage"]["cost_inr"] is None
    assert receipt["usage"]["cost_usd"] is None
    assert receipt["usage"]["cost_unknown"] is True


def test_receipt_uses_ledger_cost_when_delivery_omits_usd(tmp_path: Path) -> None:
    record_invocation(tmp_path, {
        "invocation_id": "inv-cost-ledger",
        "session_id": "s-cost",
        "turn_id": "t-cost",
        "subsystem": "engineering",
        "status": "settled",
        "input_tokens": 100,
        "output_tokens": 20,
        "actual_cost_inr": 0.25,
        "actual_cost_usd": 0.003,
        "cost_unknown": False,
    })
    receipt = build_turn_receipt(
        session_id="s-cost",
        turn_id="t-cost",
        state={"task_status": "completed"},
        workspace=str(tmp_path),
    )
    assert receipt["usage"]["cost_inr"] == 0.25
    assert receipt["usage"]["cost_usd"] == 0.003
    assert receipt["usage"]["cost_unknown"] is False

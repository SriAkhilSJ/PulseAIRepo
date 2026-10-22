"""Phase 0 metering pins (founder strength plan, 2026-10-21).

The ledger is the foundation for the monthly expense report and for every
later learning/training step: if it over-records (content!), under-records
(failed calls!), or invents numbers (estimated tokens/cost), everything
built on it lies. These tests pin the honest shape.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.telemetry import call_ledger


@pytest.fixture()
def ledger_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.delenv("CRUSORAI_TELEMETRY", raising=False)
    monkeypatch.delenv("CRUSORAI_RATE_CARD", raising=False)
    return tmp_path


def _lines(directory: Path) -> list[dict]:
    files = sorted(directory.glob("calls-*.jsonl"))
    assert files, "no ledger file written"
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_call_writes_one_metering_line_without_content(ledger_dir):
    call_ledger.record_call(
        "thread-1", "custom", "z-ai/glm-5.3-flash", 2.5,
        input_tokens=1200, output_tokens=300, total_tokens=1500,
        reasoning_chars=4200, streamed=True,
    )
    (record,) = _lines(ledger_dir)
    assert record["kind"] == "call"
    assert record["thread"] == "thread-1"
    assert record["provider"] == "custom" and record["model"] == "z-ai/glm-5.3-flash"
    assert record["input_tokens"] == 1200 and record["output_tokens"] == 300
    assert record["reasoning_chars"] == 4200 and record["wall_s"] == 2.5
    # Metering is metadata ONLY: no content-bearing key may ever appear.
    for forbidden in ("content", "prompt", "messages", "answer", "output", "tool_calls"):
        assert forbidden not in record


def test_failed_calls_are_metered_too(ledger_dir):
    call_ledger.record_call("t", "p", "m", 0.4, error="TimeoutError")
    (record,) = _lines(ledger_dir)
    assert record["error"] == "TimeoutError"
    summary = call_ledger.summarize(directory=str(ledger_dir))
    assert summary["calls"] == 0 and summary["failed_calls"] == 1


def test_unknown_tokens_stay_unknown_never_estimated(ledger_dir):
    call_ledger.record_call("t", "p", "m", 1.0)  # provider reported no usage
    (record,) = _lines(ledger_dir)
    assert record["input_tokens"] is None and record["output_tokens"] is None
    summary = call_ledger.summarize(directory=str(ledger_dir))
    assert summary["unknown_token_calls"] == 1
    assert summary["cost"] is None, "no rate card and no usage -> cost must stay unknown"


def test_kill_switch_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("CRUSORAI_TELEMETRY", "off")
    call_ledger.record_call("t", "p", "m", 1.0, input_tokens=1)
    call_ledger.record_run("t", "completed")
    assert not list(tmp_path.glob("calls-*.jsonl"))


def test_summary_joins_verdicts_and_costs_from_the_rate_card(ledger_dir, monkeypatch):
    monkeypatch.setenv(
        "CRUSORAI_RATE_CARD",
        json.dumps({"glm-5.3-flash": {"input_per_1m": 1.0, "output_per_1m": 2.0, "currency": "USD"}}),
    )
    for _ in range(2):
        call_ledger.record_call(
            "t1", "custom", "z-ai/glm-5.3-flash", 3.0,
            input_tokens=500_000, output_tokens=250_000, total_tokens=750_000,
        )
    call_ledger.record_run("t1", "completed")
    call_ledger.record_run("t2", "unverified")

    summary = call_ledger.summarize(directory=str(ledger_dir), now=datetime.now().replace(day=15))
    assert summary["calls"] == 2 and summary["runs"] == 2
    assert summary["verdicts"] == {"completed": 1, "unverified": 1}
    # Per call: 0.5M*$1 + 0.25M*$2 = $1.00; two calls = $2.00.
    assert summary["cost"] == pytest.approx(2.0)
    assert summary["cost_per_completed_run"] == pytest.approx(2.0)
    assert summary["projected_month_cost"] is not None and summary["projected_month_cost"] > 2.0
    assert summary["by_model"]["z-ai/glm-5.3-flash"]["calls"] == 2


def test_writes_never_raise_into_the_caller(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(blocker / "telemetry"))
    monkeypatch.delenv("CRUSORAI_TELEMETRY", raising=False)
    call_ledger.record_call("t", "p", "m", 1.0, input_tokens=1)  # must not raise
    call_ledger.record_run("t", "completed")  # must not raise


def test_pump_meters_every_successful_call(tmp_path, monkeypatch):
    """The single choke point: _invoke_with_token_pump is on every billed
    call path (main, re-prompt, grace), so metering here meters all."""
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.delenv("CRUSORAI_TELEMETRY", raising=False)
    from langchain_core.messages import AIMessage, HumanMessage

    from src.graphs.chat_graph import _invoke_with_token_pump

    class _FakeLLM:
        def invoke(self, messages, config=None):
            return AIMessage(
                content="done",
                usage_metadata={"input_tokens": 111, "output_tokens": 22, "total_tokens": 133},
            )

    result = _invoke_with_token_pump(_FakeLLM(), [HumanMessage(content="hi")], "thread-meter", "custom", "fake-model")
    assert result.content == "done"
    calls = [r for r in _lines(tmp_path) if r["kind"] == "call"]
    assert len(calls) == 1
    assert calls[0]["thread"] == "thread-meter" and calls[0]["model"] == "fake-model"
    assert calls[0]["input_tokens"] == 111 and calls[0]["output_tokens"] == 22


def test_pump_meters_failed_calls_before_reraising(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.delenv("CRUSORAI_TELEMETRY", raising=False)
    from langchain_core.messages import HumanMessage

    from src.graphs.chat_graph import _invoke_with_token_pump

    class _DeadLLM:
        def invoke(self, messages, config=None):
            raise TimeoutError("provider gone")

    with pytest.raises(TimeoutError):
        _invoke_with_token_pump(_DeadLLM(), [HumanMessage(content="hi")], "thread-dead", "custom", "fake-model")
    calls = [r for r in _lines(tmp_path) if r["kind"] == "call"]
    assert len(calls) == 1 and calls[0]["error"] == "TimeoutError"


def test_engine_hooks_stay_wired():
    """Structural pin (house style): the pump meters calls, finalize meters
    verdicts — removing a hook silently blinds the expense report."""
    source = (Path(__file__).resolve().parents[1] / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    assert source.count("call_ledger.record_call(") == 2  # success + failure paths
    assert source.count("call_ledger.record_run(") == 2  # verdict + cancelled paths


# ---------------------------------------------------------------------------
# Phase 1 anatomy (diet measurement, founder 2026-10-21 NEXT TASK)
# ---------------------------------------------------------------------------

def _fake_pump_run(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.delenv("CRUSORAI_TELEMETRY", raising=False)
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from src.graphs.chat_graph import _invoke_with_token_pump

    class _FakeLLM:
        kwargs = {"tools": [{"name": "write_file", "description": "d" * 396, "parameters": {"type": "object"}}]}

        def invoke(self, messages, config=None):
            return AIMessage(
                content="done",
                usage_metadata={"input_tokens": 5000, "output_tokens": 10, "total_tokens": 5010},
            )

    _invoke_with_token_pump(
        _FakeLLM(),
        [SystemMessage(content="S" * 4000), HumanMessage(content="H" * 400)],
        "thread-anatomy", "custom", "fake-model",
    )
    return [r for r in _lines(tmp_path) if r["kind"] == "call"]


def test_pump_records_request_anatomy_per_call(tmp_path, monkeypatch):
    (call,) = _fake_pump_run(tmp_path, monkeypatch)
    assert call["sys_tokens"] == 1000  # 4000 chars // 4
    assert call["user_tokens"] == 100
    assert call["tools_schema_tokens"] > 100  # bound schema rode the binding
    assert call["req_tokens_est"] == call["sys_tokens"] + call["user_tokens"]


def test_summary_reports_static_share_for_the_diet(tmp_path, monkeypatch):
    _fake_pump_run(tmp_path, monkeypatch)
    summary = call_ledger.summarize(directory=str(tmp_path))
    anatomy = summary["anatomy"]
    assert anatomy is not None and anatomy["calls"] == 1
    assert anatomy["avg_sys_tokens"] == 1000
    assert anatomy["static_share_pct"] > 80  # system+tools dominate: the diet target
    assert "request anatomy" in call_ledger.format_summary(summary)

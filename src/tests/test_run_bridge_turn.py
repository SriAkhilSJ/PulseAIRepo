"""Provider-free tests for the headless bridge-turn evidence runner."""

import builtins

from scripts.run_bridge_turn import (
    RequestTimingLedger,
    ToolOutcomeLedger,
    attach_monitoring_receipts,
    effective_iteration_budget,
    latency_summary_ms,
    record_runner_error,
    safe_console_emit,
    should_stop_for_call_budget,
)


def test_console_heartbeat_failure_falls_back_without_raising(monkeypatch, tmp_path):
    fallback = tmp_path / "console.log"

    def broken_print(*args, **kwargs):
        raise OSError(22, "invalid console handle")

    monkeypatch.setattr(builtins, "print", broken_print)
    safe_console_emit("telemetry x1 | calls=1/20", fallback)

    evidence = fallback.read_text(encoding="utf-8")
    assert "OSError" in evidence
    assert "telemetry x1" in evidence


def test_runner_exception_receipt_preserves_bounded_traceback(monkeypatch):
    outcome = {}
    monkeypatch.setenv("CUSTOM_API_KEY", "secret-value-123")
    try:
        raise OSError(22, "invalid argument secret-value-123")
    except OSError as exc:
        record_runner_error(outcome, exc)

    assert outcome["result"] == "runner-error"
    assert outcome["completed"] is False
    assert outcome["error"] == "OSError: [Errno 22] invalid argument [REDACTED]"
    assert "secret-value-123" not in outcome["runner_traceback"]
    assert "test_runner_exception_receipt" in outcome["runner_traceback"]
    assert len(outcome["runner_traceback"]) <= 12000


def test_runner_aligns_and_enforces_an_inclusive_call_ceiling():
    assert effective_iteration_budget(8) == 8
    assert effective_iteration_budget(1) == 1
    assert effective_iteration_budget(0) == 1

    assert should_stop_for_call_budget(7, 8) is False
    assert should_stop_for_call_budget(8, 8) is False
    assert should_stop_for_call_budget(9, 8) is True


def test_tool_outcome_ledger_is_ordered_bounded_and_secret_safe(monkeypatch):
    monkeypatch.setenv("CUSTOM_API_KEY", "secret-value-123")
    ledger = ToolOutcomeLedger(receipt_limit=4)
    ledger.start_calls([
        {
            "id": "call-1",
            "name": "terminal",
            "args": {"command": "curl -H secret-value-123 example.invalid"},
        },
        {
            "id": "call-2",
            "name": "write_file",
            "args": {"path": "private.txt", "content": "secret-value-123"},
        },
        {
            "id": "call-3",
            "name": "read_file",
            "args": {"path": "private.txt"},
        },
    ], now=10.0)
    ledger.finish_call(
        tool_call_id="call-1",
        tool_name="terminal",
        content=(
            "Command failed\nCUSTOM_API_KEY=secret-value-123\nExit code: 1"
        ),
        explicit_status="error",
        now=10.125,
    )
    ledger.finish_call(
        tool_call_id="call-3",
        tool_name="read_file",
        content="PRIVATE_FILE_BODY that must not enter outcome.json",
        explicit_status="completed",
        now=10.2,
    )

    receipts, omitted = ledger.snapshot(now=10.5)

    assert omitted == 0
    assert [item["sequence"] for item in receipts] == [1, 2, 3]
    assert receipts[0]["tool"] == "terminal"
    assert receipts[0]["status"] == "failed"
    assert receipts[0]["duration_ms"] == 125
    assert "Exit code: 1" in receipts[0]["result_summary"]
    assert "secret-value-123" not in str(receipts)
    assert "args" not in receipts[0] and "tool_call_id" not in receipts[0]
    assert receipts[1]["status"] == "unfinished"
    assert receipts[1]["result_summary"] == "no result before the run ended"
    assert receipts[2]["status"] == "succeeded"
    assert receipts[2]["result_summary"].endswith("content omitted)")
    assert "PRIVATE_FILE_BODY" not in str(receipts)
    assert len(receipts[0]["result_summary"]) <= 240


def test_request_timing_receipts_distinguish_failed_and_unfinished_calls():
    ledger = RequestTimingLedger(receipt_limit=4)
    ledger.start("request-1", now=1.0)
    ledger.finish("request-1", status="failed", now=1.25)
    ledger.start("request-2", now=2.0)

    receipts, omitted = ledger.snapshot(now=2.1)

    assert omitted == 0
    assert receipts == [
        {"sequence": 1, "status": "failed", "duration_ms": 250},
        {"sequence": 2, "status": "unfinished", "duration_ms": 100},
    ]
    assert latency_summary_ms([item["duration_ms"] for item in receipts]) == {
        "count": 2,
        "total_ms": 350,
        "min_ms": 100,
        "p50_ms": 100,
        "p95_ms": 250,
        "max_ms": 250,
    }


def test_monitoring_receipts_are_capped_but_summaries_cover_all_events():
    requests = RequestTimingLedger(receipt_limit=2)
    requests.start("request-1", now=1.0)
    requests.finish("request-1", now=1.1)

    tools = ToolOutcomeLedger(receipt_limit=2)
    tools.start_calls([
        {"id": "one", "name": "write_file"},
        {"id": "two", "name": "write_file"},
        {"id": "three", "name": "write_file"},
    ], now=1.0)
    for index, call_id in enumerate(("one", "two", "three"), start=1):
        tools.finish_call(
            tool_call_id=call_id,
            tool_name="write_file",
            content=f"Wrote file: file-{index}.txt",
            explicit_status="completed",
            now=1.0 + (index / 10),
        )

    outcome = {}
    attach_monitoring_receipts(
        outcome, requests, tools, run_started_at=0.5, now=2.0,
    )

    assert outcome["outcome_schema_version"] == 2
    assert outcome["tool_outcomes_omitted"] == 1
    assert [item["sequence"] for item in outcome["tool_outcomes"]] == [1, 3]
    assert outcome["tool_outcome_counts"] == {"succeeded": 3}
    assert outcome["timing_ms"]["tools"]["count"] == 3
    assert outcome["timing_ms"]["requests"]["count"] == 1
    assert outcome["timing_ms"]["run_elapsed_ms"] == 1500
    assert all("arguments" not in item for item in outcome["tool_outcomes"])
    assert all("result" not in item for item in outcome["request_receipts"])
    assert "full results omitted" in outcome["receipt_privacy"]

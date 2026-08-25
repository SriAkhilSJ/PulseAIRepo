"""Provider-free tests for the headless bridge-turn evidence runner."""

import builtins

from scripts.run_bridge_turn import record_runner_error, safe_console_emit


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

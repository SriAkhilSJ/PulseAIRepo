"""Contracts: the Floor-6 observability sink — env-driven, fail-closed, JSONL."""
import json

from src.observability import record_turn_receipt, sink_path


def test_off_by_default_and_env_gated(monkeypatch, tmp_path):
    monkeypatch.delenv("PULSEAI_OBSERVABILITY", raising=False)
    assert record_turn_receipt(thread_id="s1") is False  # silent no-op when off
    monkeypatch.setenv("PULSEAI_OBSERVABILITY", "on")
    monkeypatch.setenv("PULSEAI_OBSERVABILITY_PATH", str(tmp_path / "turns.jsonl"))
    ok = record_turn_receipt(thread_id="s1", model="m", input_tokens=10, output_tokens=5,
                             estimated_cost_usd=0.01, tool_calls=2, tool_names=["edit_file"])
    assert ok is True
    rec = json.loads((tmp_path / "turns.jsonl").read_text().splitlines()[0])
    assert rec["session"] == "s1" and rec["tokens"] == {"input": 10, "output": 5, "cache": 0}
    assert rec["tool_names"] == ["edit_file"] and rec["completed"] is True


def test_fail_closed_never_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("PULSEAI_OBSERVABILITY", "on")
    monkeypatch.setenv("PULSEAI_OBSERVABILITY_PATH", "/proc/definitely/not/writable/x.jsonl")
    assert record_turn_receipt(thread_id="s2") is False  # swallowed, no raise


def test_default_sink_path_under_pulseai_home(monkeypatch):
    monkeypatch.delenv("PULSEAI_OBSERVABILITY_PATH", raising=False)
    assert ".pulseai" in str(sink_path()) and sink_path().name == "turns.jsonl"

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from benchmarks.colibri_agent_core import kaggle_live_diagnostics as diagnostics

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "kaggle-live-diagnostics.yml"


class _Response:
    def __init__(self, chunks):
        self._chunks = chunks

    def iter_content(self, chunk_size):
        assert chunk_size == 8192
        yield from self._chunks


def test_redacted_bounded_log_tail_removes_credentials_and_terminal_controls():
    token = "K" + "GAT_" + "synthetic-token-material"
    source = (
        "event: message\n"
        "data: starting build\n"
        f"KAGGLE_API_TOKEN={token}\n"
        "Authorization: bearer-secret\n"
        "\x1b[31mCUDA active\x1b[0m\x00\n" + ("x" * 5000)
    )

    tail = diagnostics._clean_log_tail(source, ("public-user", token), 1200)

    assert "starting build" not in tail  # bounded prefix was dropped
    assert token not in tail
    assert "bearer-secret" not in tail
    assert "\x1b" not in tail and "\x00" not in tail
    assert tail.startswith("[... bounded prefix omitted ...]")
    assert len(tail) <= 1200


def test_log_highlights_capture_phase_errors_and_remain_bounded():
    source = (
        "prefix "
        + ("x" * 800)
        + '\n"error": "first exact failure",\n"name": "long_context"\n'
        + ("y" * 4000)
        + '\n"error": "second exact failure",\n'
        + '"name": "tool_result_round_trip"\n'
        + ("z" * 800)
    )

    highlights = diagnostics._log_highlights(source, 3000, radius=500)

    assert "first exact failure" in highlights
    assert "second exact failure" in highlights
    assert "long_context" in highlights
    assert "tool_result_round_trip" in highlights
    assert len(highlights) <= 3000


def test_chunk_capture_is_bounded_and_preserves_suffix():
    text, retained, observed, truncated, deadline = diagnostics._decode_chunks(
        _Response([b"abc", b"defgh"]), 6
    )

    assert text == "cdefgh"
    assert retained == 6
    assert observed == 8
    assert truncated is True
    assert deadline is False


def test_chunk_capture_preserves_data_when_deadline_fires():
    def chunks():
        yield b"already captured\n"
        raise diagnostics._DeadlineExpired("done")

    text, retained, observed, truncated, deadline = diagnostics._decode_chunks(
        _Response(chunks()), 1024
    )

    assert text == "already captured\n"
    assert retained == len(text)
    assert observed == len(text)
    assert truncated is False
    assert deadline is True


def test_structured_persisted_log_suffix_decodes_complete_data_records():
    source = (
        'partial-prefix},{"stream_name":"stdout","time":1.0,'
        '"data":"phase one\\n"},{"stream_name":"stderr","time":2.0,'
        '"data":"failure: \\"bounded\\"\\n"}]'
    )

    decoded, records = diagnostics._decode_structured_log(source)

    assert decoded == 'phase one\nfailure: "bounded"\n'
    assert records == 2


def test_structured_persisted_log_decodes_outer_json_string_suffix():
    events = ",".join(
        [
            '{"stream_name":"stdout","time":1.0,"data":"phase two\\n"}',
            '{"stream_name":"stderr","time":2.0,"data":"exact failure\\n"}',
        ]
    )
    encoded = json.dumps(events)
    source = "partial discarded event" + encoded[1:]

    decoded, records = diagnostics._decode_structured_log(source)

    assert decoded == "phase two\nexact failure\n"
    assert records == 2


def test_quota_receipt_uses_seconds_only():
    value = SimpleNamespace(
        time_used=timedelta(hours=1, minutes=56),
        time_reserved=timedelta(minutes=5),
        total_time_allowed=timedelta(hours=30),
        minimum_time_allowed=timedelta(minutes=20),
        has_ever_run=True,
    )

    receipt = diagnostics._quota_receipt(value)

    assert receipt == {
        "time_used_seconds": 6960.0,
        "time_reserved_seconds": 300.0,
        "total_time_allowed_seconds": 108000.0,
        "minimum_time_allowed_seconds": 1200.0,
        "has_ever_run": True,
    }


def test_missing_credentials_fail_before_importing_kaggle(monkeypatch, tmp_path):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    args = diagnostics.build_parser().parse_args(
        ["--kernel-slug", "private-kernel", "--output", str(tmp_path / "out.json")]
    )

    result = diagnostics.collect_diagnostics(args)

    assert result["status"] == "failed"
    assert result["credentials"] == {"present": False, "persisted": False}
    assert "token" in result["error"].lower()


def test_live_diagnostic_workflow_is_read_only_and_bounded():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" not in workflow
    assert "arena/a7c2c868-pulseairepo" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "KAGGLE_USERNAME: sriakhilsj" in workflow
    assert "secrets.KAGGLE_API_TOKEN" in workflow
    assert "pulseai-colibri-agent-core-40387451739" in workflow
    assert "--capture-seconds 30" in workflow
    assert "--max-bytes 262144" in workflow
    assert "--max-tail-chars 12000" in workflow
    assert "--max-highlight-chars 12000" in workflow
    assert "detail = highlights or tail" in workflow
    assert "[kaggle-logs]" in workflow
    assert "html.escape(detail)" in workflow
    assert "actions/upload-artifact" not in workflow

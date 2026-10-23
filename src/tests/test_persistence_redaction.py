"""Security contracts for replayable runtime/evidence persistence."""

from __future__ import annotations

import json
import sqlite3

from src.context.verification_evidence import VerificationLedger
from src.runtime.event_journal import EventJournal
from src.runtime.factory import create_runtime_services
from src.runtime.tool_middleware import execute_tool_transaction
from src.runtime.verification_events import journal_verification_update


def _stored_payloads(path) -> list[dict]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT payload_json FROM runtime_events ORDER BY seq").fetchall()
    return [json.loads(row[0]) for row in rows]


def test_event_journal_forces_structured_and_text_redaction(tmp_path):
    secret = "ghp_" + "A" * 24
    opaque = "not-a-pattern-but-still-a-secret"
    journal = EventJournal(tmp_path / "events.db")
    returned = journal.append(
        "security.probe",
        {
            "api_key": opaque,
            "nested": {
                "message": f"Authorization: Bearer {secret}",
                "url": f"https://user:{secret}@example.test/path?access_token={secret}",
            },
        },
        session_id="redaction-test",
    )

    stored = _stored_payloads(journal.path)[0]
    serialized = json.dumps(stored)
    assert secret not in serialized
    assert "A" * 8 not in serialized, "durable masking must not retain a token head or tail"
    assert opaque not in serialized
    assert stored["api_key"] == "«redacted:persistence-secret»"
    assert returned["payload"] == stored, "callers must receive exactly the safe replay payload"
    journal.close()


def test_tool_transaction_omits_bodies_and_never_journals_result_secrets(tmp_path, monkeypatch):
    secret = "ghp_" + "B" * 24
    opaque_body = "an opaque credential that no prefix detector could recognise"
    nested_body = "another opaque value inside a nested request body"
    services = create_runtime_services(tmp_path / "runtime")
    monkeypatch.setattr("src.runtime.factory.get_runtime_services", lambda: services)

    outcome = execute_tool_transaction(
        name="write_file",
        args={
            "path": "app.py",
            "content": opaque_body,
            "api_key": "short-opaque-key",
            "options": {"request": {"body": nested_body}},
        },
        tool_call_id="tool-redaction-1",
        config={
            "configurable": {
                "thread_id": "redaction-test",
                "turn_id": "turn-1",
                "workspace": str(tmp_path),
            }
        },
        invoke=lambda: f"saved; Authorization: Bearer {secret}",
        project=False,
    )

    payloads = _stored_payloads(services.journal.path)
    serialized = json.dumps(payloads)
    assert opaque_body not in serialized
    assert nested_body not in serialized
    assert "short-opaque-key" not in serialized
    assert secret not in serialized
    assert payloads[0]["args"]["path"] == "app.py"
    assert "payload omitted at persistence boundary" in payloads[0]["args"]["content"]
    assert "payload omitted at persistence boundary" in payloads[0]["args"]["options"]["request"]["body"]
    assert outcome.status == "ok" and secret not in outcome.content
    services.close()


def test_verification_ledger_redacts_command_and_output_before_sqlite(tmp_path):
    secret = "ghp_" + "C" * 24
    ledger = VerificationLedger(tmp_path / "verification.db")
    evidence = ledger.record_command(
        session_id="verification-redaction",
        workspace=str(tmp_path),
        command=f"pytest -q --credential={secret}",
        exit_code=0,
        output=f"Authorization: Bearer {secret}\n1 passed",
    )
    assert evidence is not None

    with sqlite3.connect(ledger.path) as conn:
        command, output = conn.execute(
            "SELECT command, output FROM verification_events WHERE id=?",
            (evidence["event_id"],),
        ).fetchone()
    assert secret not in command
    assert secret not in output
    assert secret not in evidence["command"]
    ledger.close()


def test_verification_updates_use_one_versioned_durable_envelope(tmp_path):
    services = create_runtime_services(tmp_path / "runtime")
    update = journal_verification_update(
        services,
        {"status": "passed", "kind": "test", "scope": "full", "exit_code": 0},
        session_id="verification-envelope",
        workspace=str(tmp_path),
        evidence_kind="command",
        turn_id="turn-2",
    )

    assert update["schema_version"] == 1
    assert update["evidence_id"].startswith("verify-")
    assert update["evidence_kind"] == "command"
    assert update["journal_status"] == "persisted"
    rows = services.journal.list_events("verification-envelope")
    assert len(rows) == 1 and rows[0]["type"] == "verification.updated"
    assert rows[0]["event_id"] == update["evidence_id"]
    assert rows[0]["payload"]["status"] == "passed"
    services.close()

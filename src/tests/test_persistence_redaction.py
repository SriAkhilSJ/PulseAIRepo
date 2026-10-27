"""Security and replay contracts for durable Agent Core persistence."""

from __future__ import annotations

import json
import sqlite3

from src.context.verification_evidence import VerificationLedger
from src.runtime.event_journal import EventJournal
from src.runtime.factory import create_runtime_services
from src.runtime.persistence import sanitize_for_persistence
from src.runtime.tool_middleware import execute_tool_transaction
from src.runtime.verification_events import journal_verification_update


def _stored_payloads(path) -> list[dict]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM runtime_events ORDER BY seq"
        ).fetchall()
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
                "url": (
                    f"https://user:{secret}@example.test/path"
                    f"?access_token={secret}"
                ),
                "secret_as_mapping_key": {secret: "must not leak via a key"},
            },
        },
        session_id="redaction-test",
    )

    stored = _stored_payloads(journal.path)[0]
    serialized = json.dumps(stored)
    assert secret not in serialized
    assert "A" * 8 not in serialized, (
        "durable masking must not retain a reusable token head/tail"
    )
    assert opaque not in serialized
    assert stored["api_key"] == "«redacted:persistence-secret»"
    assert returned["payload"] == stored
    journal.close()


def test_event_journal_itself_omits_nested_tool_bodies(tmp_path):
    body = "opaque source body with a credential regex cannot know"
    nested = "nested opaque HTTP request body"
    journal = EventJournal(tmp_path / "events.db")
    returned = journal.append(
        "tool.intent",
        {
            "tool_name": "write_file",
            "args": {
                "path": "app.py",
                "content": body,
                "api_key": "short-opaque-key",
                "options": {"request": {"body": nested}},
            },
        },
        session_id="redaction-test",
        tool_call_id="tool-1",
    )

    stored = _stored_payloads(journal.path)[0]
    serialized = json.dumps(stored)
    assert body not in serialized
    assert nested not in serialized
    assert "short-opaque-key" not in serialized
    assert stored["args"]["path"] == "app.py"
    assert stored["args"]["content"] == {
        "__omitted__": True,
        "reason": "tool_body",
        "size": len(body),
        "unit": "characters",
    }
    assert stored["args"]["options"]["request"]["body"]["reason"] == "tool_body"
    assert returned["payload"] == stored
    journal.close()


def test_tool_transaction_never_journals_intent_or_result_secrets(
    tmp_path, monkeypatch
):
    secret = "ghp_" + "B" * 24
    services = create_runtime_services(tmp_path / "runtime")
    monkeypatch.setattr(
        "src.runtime.factory.get_runtime_services", lambda: services
    )

    outcome = execute_tool_transaction(
        name="write_file",
        args={"path": "app.py", "content": "opaque file body"},
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
    assert "opaque file body" not in serialized
    assert secret not in serialized
    assert outcome.status == "ok" and secret not in outcome.content
    services.close()


def test_known_opaque_environment_values_are_redacted(monkeypatch):
    import src.runtime.persistence as persistence

    opaque = "value-with-no-vendor-prefix-7d9e2c"
    monkeypatch.setattr(
        persistence, "_KNOWN_ENVIRONMENT_SECRETS", (opaque,)
    )
    safe = sanitize_for_persistence(f"provider replied with {opaque}")
    assert opaque not in safe
    assert "known-secret" in safe


def test_persistence_masks_keep_no_opaque_assignment_or_header_fragments():
    opaque = "opaquecredentialvalue123456789"
    for text in (
        f"SERVICE_TOKEN={opaque}",
        f'{{"password": "{opaque}"}}',
        f"Authorization: Bearer {opaque}",
        f"x-api-key: {opaque}",
    ):
        safe = str(sanitize_for_persistence(text))
        assert opaque not in safe
        assert opaque[:6] not in safe
        assert opaque[-4:] not in safe
        assert "redacted" in safe.lower()


def test_sanitizer_bounds_cycles_binary_and_oversized_strings():
    cyclic: dict = {"blob": b"abc"}
    cyclic["self"] = cyclic
    safe = sanitize_for_persistence(cyclic)
    assert "binary omitted" in safe["blob"]
    assert "cyclic value omitted" in safe["self"]
    assert "oversized string omitted" in sanitize_for_persistence("x" * 64_001)


def test_verification_ledger_redacts_before_its_own_sqlite_write(tmp_path):
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


def test_verification_update_is_versioned_durable_and_replayable(tmp_path):
    services = create_runtime_services(tmp_path / "runtime")
    update = journal_verification_update(
        services,
        {
            "status": "passed",
            "kind": "test",
            "scope": "full",
            "exit_code": 0,
        },
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

    from src.bridge.__main__ import BridgeServer

    replay = BridgeServer._project_stored_event(rows[0])
    assert replay is not None
    assert replay["type"] == "verification_updated"
    assert replay["schema_version"] == 1
    assert replay["journal_seq"] == rows[0]["seq"]
    assert replay["journal_status"] == "persisted"
    services.close()


def test_verification_envelope_reports_journal_failure_without_leaking():
    secret = "ghp_" + "D" * 24

    class BrokenJournal:
        def append(self, *args, **kwargs):
            raise RuntimeError(f"database refused Authorization: Bearer {secret}")

    class Services:
        journal = BrokenJournal()

    update = journal_verification_update(
        Services(),
        {"status": "passed", "api_key": secret},
        session_id="s",
        workspace=".",
        evidence_kind="command",
    )
    serialized = json.dumps(update)
    assert update["journal_status"] == "unavailable"
    assert secret not in serialized

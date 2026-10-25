from __future__ import annotations

import concurrent.futures
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.runtime.evidence_capture as capture_module
from src.bridge.__main__ import BridgeServer
from src.runtime.build_identity import (
    build_identity_is_complete,
    collect_build_identity,
)
from src.runtime.event_journal import EventJournal, JournalUnavailable
from src.runtime.evidence_capture import TurnEvidenceRecorder
from src.runtime.evidence_validation import validate_turn_evidence
from src.runtime.identity import TurnIdentity, workspace_id
from src.runtime.tool_middleware import execute_tool_transaction

ROOT = Path(__file__).resolve().parents[2]


def _identity(workspace: Path, session_id: str = "session-evidence") -> TurnIdentity:
    created = TurnIdentity.create(session_id=session_id, workspace=str(workspace))
    return TurnIdentity(
        session_id=created.session_id,
        runtime_session_id=created.runtime_session_id,
        lineage_root_id=created.lineage_root_id,
        workspace_id=created.workspace_id,
        turn_id=created.turn_id,
        created_at=created.created_at,
    )


def _matched_build(commit: str = "a" * 40) -> dict:
    return {
        "schema_version": 1,
        "status": "matched",
        "reasons": [],
        "repository": {
            "commit": commit,
            "dirty": False,
            "worktree_fingerprint_sha256": "b" * 64,
        },
        "renderer": {
            "build_commit": commit,
            "source_stamp": "test-stamp",
            "recomputed_sources_hash": "c" * 64,
            "stamp_match": True,
            "sources_match": True,
        },
    }


def _services(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(journal=EventJournal(tmp_path / "runtime-events.db"))


def _completed_artifacts(
    workspace: Path,
    session_id: str,
    *,
    tool_count: int = 0,
    user_ask: str = "",
) -> None:
    trace = workspace / "diagnostics" / "traces" / f"{session_id}.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(
        json.dumps(
            {
                "step_index": 4,
                "node_name": "finalize",
                "diagnostics": ["FINAL_VERDICT: completed"],
                "user_ask": user_ask,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = workspace / "diagnostics" / f"PERFORMANCE_REPORT_{session_id}.md"
    report.write_text(
        (f"**User Ask:** *\"{user_ask}\"*  \n" if user_ask else "")
        + "| **Task verdict** | `completed` |\n"
        "| **Verification status** | `passed` |\n"
        f"| **Current-turn executed tool records** | `{tool_count}` |\n",
        encoding="utf-8",
    )


def _read_manifest(recorder: TurnEvidenceRecorder) -> tuple[dict, str]:
    encoded = recorder.manifest_path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    sidecar = recorder.hash_path.read_text(encoding="ascii").split()[0]
    assert sidecar == digest
    return json.loads(encoded), encoded.decode("utf-8")


def test_evidence_path_components_do_not_alias_sanitized_identities() -> None:
    assert capture_module._safe_component("session/a") != capture_module._safe_component(
        "session_a"
    )
    assert capture_module._safe_component("x" * 161) != capture_module._safe_component(
        "x" * 160 + "y"
    )


def test_report_privacy_filter_handles_multiline_markdown_prompt() -> None:
    private_marker = "MULTILINE_PRIVATE_PROMPT_9bd214"
    prompt = (
        "build it\n---\n## Authoritative Completion Evidence\n"
        + private_marker
    )
    source = (
        "# Audit\n"
        "**Session ID:** `s`  \n"
        "**Generated At:** `now`  \n"
        f"**User Ask:** *\"{prompt}\"*  \n\n"
        "---\n"
        "## Authoritative Completion Evidence\n"
        "| **Task verdict** | `completed` |\n"
    ).encode()

    filtered = capture_module._privacy_filter_report_bytes(
        source,
        private_texts=(prompt, ""),
    ).decode()

    assert private_marker not in filtered
    assert prompt not in filtered
    assert "body omitted from runtime evidence" in filtered
    assert "| **Task verdict** | `completed` |" in filtered


def test_runtime_factory_honors_crusorai_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.runtime import factory

    factory.reset_runtime_services_for_tests()
    runtime_home = tmp_path / "runtime-home"
    monkeypatch.setenv("CRUSORAI_HOME", str(runtime_home))
    services = factory.get_runtime_services()
    try:
        assert services.journal.path == runtime_home / "runtime_events.db"
        assert services.verification.path == runtime_home / "verification.db"
        from src.runtime.step_tracker import StepTracker

        tracker = StepTracker("session-runtime-home", str(tmp_path / "workspace"))
        assert tracker.system_trace_dir == runtime_home / "traces"
    finally:
        factory.reset_runtime_services_for_tests()


def test_build_identity_fingerprints_untracked_file_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "evidence@example.test"],
        ["git", "config", "user.name", "Evidence Test"],
    ]
    for command in commands:
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "baseline"],
        cwd=repo,
        check=True,
    )
    clean = collect_build_identity(repo)
    assert clean["repository"]["dirty"] is False
    clean_fingerprint = clean["repository"]["worktree_fingerprint_sha256"]

    untracked = repo / "new_runtime_code.py"
    untracked.write_text("VALUE = 1\n", encoding="utf-8")
    first = collect_build_identity(repo)
    untracked.write_text("VALUE = 2\n", encoding="utf-8")
    second = collect_build_identity(repo)
    assert first["repository"]["dirty"] is True
    assert first["repository"]["untracked_file_count"] == 1
    assert first["repository"]["worktree_fingerprint_sha256"] != clean_fingerprint
    assert (
        second["repository"]["worktree_fingerprint_sha256"]
        != first["repository"]["worktree_fingerprint_sha256"]
    )


def test_dirty_exact_build_keeps_known_nonancestor_provenance_complete() -> None:
    build = _matched_build()
    build["status"] = "dirty"
    build["reasons"] = [
        "repository_dirty",
        "renderer_build_commit_not_ancestor",
    ]
    build["repository"]["dirty"] = True

    assert build_identity_is_complete(build) is True
    build["renderer"]["sources_match"] = False
    assert build_identity_is_complete(build) is False


def test_event_journal_chain_detects_payload_tampering_and_is_not_healed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.db"
    journal = EventJournal(path)
    first = journal.append(
        "turn.started",
        {"mode": "agent"},
        session_id="session-chain",
        turn_id="turn-chain",
        workspace_id="ws-chain",
    )
    second = journal.append(
        "tool.intent",
        {"tool_name": "read_file", "args": {"path": "README.md"}},
        session_id="session-chain",
        turn_id="turn-chain",
        workspace_id="ws-chain",
        tool_call_id="call-1",
    )
    assert first["event_hash"]
    assert second["prev_hash"] == first["event_hash"]
    assert journal.verify_chain("session-chain")["valid"] is True
    assert [row["seq"] for row in journal.list_turn_events(
        "session-chain", "turn-chain"
    )] == [first["seq"], second["seq"]]
    assert path.parent.stat().st_mode & 0o777 == 0o700
    for sqlite_file in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if sqlite_file.exists():
            assert sqlite_file.stat().st_mode & 0o777 == 0o600
    journal.close()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE runtime_events SET payload_json=? WHERE seq=?",
            ('{"mode":"tampered"}', first["seq"]),
        )
        connection.commit()

    reopened = EventJournal(path)
    integrity = reopened.verify_chain("session-chain")
    assert integrity["valid"] is False
    assert integrity["first_bad_seq"] == first["seq"]
    reopened.close()


def test_legacy_journal_rows_are_chained_once_during_migration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE runtime_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL,
                event_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                turn_id TEXT,
                workspace_id TEXT,
                tool_call_id TEXT,
                payload_json TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO runtime_events("
            "event_id,created_at,event_type,session_id,turn_id,workspace_id,"
            "tool_call_id,payload_json) VALUES(?,?,?,?,?,?,?,?)",
            (
                "evt-legacy",
                1.25,
                "tool.intent",
                "session-legacy",
                "turn-legacy",
                "ws-legacy",
                "call-legacy",
                '{"tool_name":"read_file"}',
            ),
        )
        connection.commit()
    journal = EventJournal(path)
    assert journal.verify_chain("session-legacy")["valid"] is True
    row = journal.list_turn_events("session-legacy", "turn-legacy")[0]
    assert row["prev_hash"] == ""
    assert row["event_hash"]
    journal.close()

    # Reopening uses the migration marker and must preserve, not recalculate,
    # the original chain head.
    reopened = EventJournal(path)
    assert (
        reopened.list_turn_events("session-legacy", "turn-legacy")[0][
            "event_hash"
        ]
        == row["event_hash"]
    )
    reopened.close()


def test_two_journal_connections_append_one_valid_session_chain(
    tmp_path: Path,
) -> None:
    path = tmp_path / "concurrent.db"
    journals = (EventJournal(path), EventJournal(path))

    def append(index: int) -> None:
        journals[index % 2].append(
            "runtime.note",
            {"index": index},
            session_id="session-concurrent",
            turn_id="turn-concurrent",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(40)))
    events = journals[0].list_turn_events(
        "session-concurrent", "turn-concurrent"
    )
    assert len(events) == 40
    assert journals[1].verify_chain("session-concurrent")["valid"] is True
    for journal in journals:
        journal.close()


def test_event_journal_lifecycle_is_transactionally_first_writer_wins(
    tmp_path: Path,
) -> None:
    journal = EventJournal(tmp_path / "events.db")
    started = journal.append(
        "turn.started",
        {"request": {"sha256": "first"}},
        session_id="session-terminal",
        turn_id="turn-terminal",
    )
    duplicate_start = journal.append(
        "turn.started",
        {"request": {"sha256": "first"}},
        session_id="session-terminal",
        turn_id="turn-terminal",
    )
    assert duplicate_start["existing_event"] is True
    assert duplicate_start["seq"] == started["seq"]
    assert duplicate_start["payload"] == {"request": {"sha256": "first"}}
    with pytest.raises(JournalUnavailable, match="different payload"):
        journal.append(
            "turn.started",
            {"request": {"sha256": "late"}},
            session_id="session-terminal",
            turn_id="turn-terminal",
        )
    intent = journal.append(
        "tool.intent",
        {"tool_name": "write_file", "args": {"path": "first.txt"}},
        session_id="session-terminal",
        turn_id="turn-terminal",
        tool_call_id="call-once",
    )
    duplicate_intent = journal.append(
        "tool.intent",
        {"tool_name": "write_file", "args": {"path": "first.txt"}},
        session_id="session-terminal",
        turn_id="turn-terminal",
        tool_call_id="call-once",
    )
    assert duplicate_intent["existing_event"] is True
    assert duplicate_intent["seq"] == intent["seq"]
    with pytest.raises(JournalUnavailable, match="different payload"):
        journal.append(
            "tool.intent",
            {"tool_name": "write_file", "args": {"path": "late.txt"}},
            session_id="session-terminal",
            turn_id="turn-terminal",
            tool_call_id="call-once",
        )
    completed = journal.append(
        "turn.completed",
        {"completed": True},
        session_id="session-terminal",
        turn_id="turn-terminal",
    )
    failed = journal.append(
        "turn.failed",
        {"completed": False, "error": "late"},
        session_id="session-terminal",
        turn_id="turn-terminal",
    )
    assert failed["existing_terminal"] is True
    assert failed["seq"] == completed["seq"]
    assert failed["type"] == "turn.completed"
    events = journal.list_turn_events("session-terminal", "turn-terminal")
    assert [event["type"] for event in events] == [
        "turn.started",
        "tool.intent",
        "turn.completed",
    ]
    journal.close()


def test_tool_transaction_retry_replays_receipt_without_second_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.runtime import factory

    services = _services(tmp_path)
    monkeypatch.setattr(factory, "get_runtime_services", lambda: services)
    calls: list[str] = []
    config = {
        "configurable": {
            "thread_id": "session-tool-retry",
            "turn_id": "turn-tool-retry",
            "workspace": str(tmp_path),
        }
    }

    def invoke() -> str:
        calls.append("executed")
        return "created artifact.txt"

    first = execute_tool_transaction(
        name="write_file",
        args={"path": "artifact.txt", "content": "private"},
        tool_call_id="call-retry",
        config=config,
        invoke=invoke,
        project=False,
    )
    replay = execute_tool_transaction(
        name="write_file",
        args={"path": "artifact.txt", "content": "private"},
        tool_call_id="call-retry",
        config=config,
        invoke=invoke,
        project=False,
    )
    assert calls == ["executed"]
    assert replay == first
    events = services.journal.list_turn_events(
        "session-tool-retry", "turn-tool-retry"
    )
    assert [event["type"] for event in events] == [
        "tool.intent",
        "tool.result",
    ]
    services.journal.close()


def test_tool_transaction_does_not_repeat_unresolved_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.runtime import factory

    services = _services(tmp_path)
    monkeypatch.setattr(factory, "get_runtime_services", lambda: services)
    services.journal.append(
        "tool.intent",
        {"tool_name": "write_file", "args": {"path": "unknown.txt"}},
        session_id="session-uncertain",
        turn_id="turn-uncertain",
        workspace_id=workspace_id(str(tmp_path)),
        tool_call_id="call-uncertain",
    )
    calls: list[str] = []
    outcome = execute_tool_transaction(
        name="write_file",
        args={"path": "unknown.txt"},
        tool_call_id="call-uncertain",
        config={
            "configurable": {
                "thread_id": "session-uncertain",
                "turn_id": "turn-uncertain",
                "workspace": str(tmp_path),
            }
        },
        invoke=lambda: calls.append("executed") or "done",
        project=False,
    )
    assert calls == []
    assert outcome.status == "error"
    assert outcome.result_seq is None
    assert "execution was not repeated" in outcome.content
    events = services.journal.list_turn_events(
        "session-uncertain", "turn-uncertain"
    )
    assert [event["type"] for event in events] == ["tool.intent"]
    services.journal.close()


def test_tool_capture_outage_does_not_raise_or_execute_without_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.runtime import factory

    class UnavailableJournal:
        def append(self, *args, **kwargs):
            raise JournalUnavailable("journal offline")

    monkeypatch.setattr(
        factory,
        "get_runtime_services",
        lambda: SimpleNamespace(journal=UnavailableJournal()),
    )
    calls: list[str] = []
    outcome = execute_tool_transaction(
        name="write_file",
        args={"path": "must-not-run.txt"},
        tool_call_id="call-no-intent",
        config={
            "configurable": {
                "thread_id": "session-journal-offline",
                "turn_id": "turn-journal-offline",
                "workspace": str(tmp_path),
            }
        },
        invoke=lambda: calls.append("executed") or "done",
        project=False,
    )

    assert calls == []
    assert outcome.status == "error"
    assert outcome.result_seq is None
    assert "was not executed" in outcome.content


def test_tool_result_capture_outage_returns_truth_and_blocks_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.runtime import factory

    durable = EventJournal(tmp_path / "runtime-events.db")

    class ResultUnavailableJournal:
        def append(self, event_type, *args, **kwargs):
            if event_type == "tool.result":
                raise JournalUnavailable("result receipt offline")
            return durable.append(event_type, *args, **kwargs)

        def list_turn_events(self, *args, **kwargs):
            return durable.list_turn_events(*args, **kwargs)

        def list_events(self, *args, **kwargs):
            return durable.list_events(*args, **kwargs)

    monkeypatch.setattr(
        factory,
        "get_runtime_services",
        lambda: SimpleNamespace(journal=ResultUnavailableJournal()),
    )
    calls: list[str] = []
    config = {
        "configurable": {
            "thread_id": "session-result-offline",
            "turn_id": "turn-result-offline",
            "workspace": str(tmp_path),
        }
    }
    first = execute_tool_transaction(
        name="write_file",
        args={"path": "ran-once.txt"},
        tool_call_id="call-result-offline",
        config=config,
        invoke=lambda: calls.append("executed") or "truthful result",
        project=False,
    )
    retry = execute_tool_transaction(
        name="write_file",
        args={"path": "ran-once.txt"},
        tool_call_id="call-result-offline",
        config=config,
        invoke=lambda: calls.append("executed-again") or "wrong",
        project=False,
    )

    assert calls == ["executed"]
    assert first.content == "truthful result"
    assert first.status == "ok"
    assert first.result_seq is None
    assert retry.status == "error"
    assert "execution was not repeated" in retry.content
    assert [event["type"] for event in durable.list_turn_events(
        "session-result-offline", "turn-result-offline"
    )] == ["tool.intent"]
    durable.close()


def test_completed_manifest_binds_identity_tools_verification_and_artifacts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace)
    prompt_secret = "PROMPT_SECRET_6c97f73d"
    answer_secret = "ANSWER_SECRET_c4150e90"
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt=f"Create the file; private marker {prompt_secret}",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    services.journal.append(
        "tool.intent",
        {
            "tool_name": "write_file",
            "args": {"path": "hello.txt", "content": "private body"},
        },
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        workspace_id=identity.workspace_id,
        tool_call_id="call-write",
    )
    services.journal.append(
        "tool.result",
        {
            "tool_name": "write_file",
            "status": "success",
            "content": "created hello.txt with private body",
        },
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        workspace_id=identity.workspace_id,
        tool_call_id="call-write",
    )
    services.journal.append(
        "verification.updated",
        {"schema_version": 1, "status": "passed", "summary": "verified"},
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        workspace_id=identity.workspace_id,
    )
    _completed_artifacts(
        workspace,
        identity.session_id,
        tool_count=1,
        user_ask=f"Create the file; private marker {prompt_secret}",
    )

    receipt = recorder.finalize(
        status="completed",
        completed=True,
        message=f"Done. private marker {answer_secret}",
    )
    manifest, raw = _read_manifest(recorder)

    assert receipt.status == "persisted"
    assert receipt.journal_chain_valid is True
    assert receipt.missing == ()
    assert manifest["capture_status"] == "complete"
    assert manifest["evidence_scope"] == {
        "kind": "agent_core_runtime",
        "desktop_capture": False,
        "synthetic_desktop_evidence": False,
    }
    assert manifest["identity"] == identity.event_fields()
    assert manifest["lifecycle"]["status"] == "completed"
    assert manifest["request"]["body_persisted"] is False
    assert prompt_secret not in raw
    assert answer_secret not in raw
    assert "private body" not in raw
    assert "created hello.txt with private body" not in raw
    assert manifest["journal"]["verification_event_count"] == 1
    assert manifest["journal"]["verification_transitions"][0]["status"] == "passed"
    assert manifest["journal"]["verification_transitions"][0]["event_hash"]
    assert manifest["journal"]["terminal_event_count"] == 1
    assert manifest["journal"]["event_types"] == {
        "tool.intent": 1,
        "tool.result": 1,
        "turn.completed": 1,
        "turn.started": 1,
        "verification.updated": 1,
    }
    tool_receipt = manifest["journal"]["tool_receipts"][0]
    assert tool_receipt["tool_call_id"] == "call-write"
    assert tool_receipt["paired"] is True
    assert tool_receipt["intent_seq"] < tool_receipt["result_seq"]
    assert tool_receipt["result"]["body_persisted_in_manifest"] is False
    assert manifest["artifacts"]["trace"]["last_node"] == "finalize"
    assert manifest["artifacts"]["trace"]["last_final_verdict"] == "completed"
    assert manifest["artifacts"]["trace"]["privacy_filtered"] is True
    assert manifest["artifacts"]["report"]["fields"]["task_verdict"] == "completed"
    assert manifest["artifacts"]["report"]["privacy_filtered"] is True
    trace_snapshot = Path(manifest["artifacts"]["trace"]["path"]).read_text(
        encoding="utf-8"
    )
    report_snapshot = Path(manifest["artifacts"]["report"]["path"]).read_text(
        encoding="utf-8"
    )
    assert prompt_secret not in trace_snapshot
    assert prompt_secret not in report_snapshot
    assert answer_secret not in trace_snapshot
    assert answer_secret not in report_snapshot
    assert "body_persisted" in trace_snapshot
    assert "body omitted from runtime evidence" in report_snapshot
    assert manifest["terminal"]["message"]["body_persisted"] is False
    terminal_event = services.journal.list_turn_events(
        identity.session_id, identity.turn_id
    )[-1]
    replay = BridgeServer._project_stored_event(terminal_event)
    assert replay is not None
    assert replay["type"] == "turn_lifecycle"
    assert replay["lifecycle_status"] == "completed"
    assert replay["journal_event_hash"] == terminal_event["event_hash"]
    validation = validate_turn_evidence(recorder.manifest_path)
    assert validation.integrity_valid is True
    assert validation.capture_complete is True
    assert validation.errors == ()
    assert validation.gaps == ()
    journal_parent = services.journal.path.parent
    journal_parent.chmod(0o751)
    assert validate_turn_evidence(recorder.manifest_path).integrity_valid is True
    assert journal_parent.stat().st_mode & 0o777 == 0o751
    assert manifest["artifacts"]["trace"]["immutable_copy"] is True
    assert manifest["artifacts"]["trace"]["source_start_offset"] == 0

    # Later turns mutate the session-level sources; this turn's immutable
    # snapshots and validator result must remain stable.
    source_trace = workspace / "diagnostics" / "traces" / f"{identity.session_id}.jsonl"
    source_trace.write_text(
        source_trace.read_text(encoding="utf-8")
        + json.dumps({"step_index": 5, "node_name": "ai"})
        + "\n",
        encoding="utf-8",
    )
    source_report = workspace / "diagnostics" / f"PERFORMANCE_REPORT_{identity.session_id}.md"
    source_report.write_text("later turn report", encoding="utf-8")
    after_later_turn = validate_turn_evidence(recorder.manifest_path)
    assert after_later_turn.integrity_valid is True
    assert after_later_turn.capture_complete is True

    relocated = tmp_path / "relocated-session-evidence"
    shutil.copytree(recorder.manifest_path.parent, relocated)
    relocated_result = validate_turn_evidence(
        relocated / recorder.manifest_path.name,
        journal_path=services.journal.path,
    )
    assert relocated_result.integrity_valid is True
    assert relocated_result.capture_complete is True

    again = recorder.finalize(status="failed", error="too late")
    assert again == receipt
    assert len(
        [
            event
            for event in services.journal.list_turn_events(
                identity.session_id, identity.turn_id
            )
            if event["type"].startswith("turn.")
            and event["type"] != "turn.started"
        ]
    ) == 1
    services.journal.close()


def test_unavailable_build_identity_degrades_capture_and_is_independently_found(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-build-gap")
    build = _matched_build()
    build["status"] = "unavailable"
    build["reasons"] = ["worktree_fingerprint_unavailable"]
    build["repository"]["worktree_fingerprint_sha256"] = None
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="capture exact build provenance",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=build,
    )
    services.journal.append(
        "verification.updated",
        {"schema_version": 1, "status": "passed", "summary": "verified"},
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        workspace_id=identity.workspace_id,
    )
    _completed_artifacts(workspace, identity.session_id)

    receipt = recorder.finalize(
        status="completed",
        completed=True,
        message="done",
    )
    manifest, _ = _read_manifest(recorder)
    validation = validate_turn_evidence(
        recorder.manifest_path,
        journal_path=services.journal.path,
    )

    assert receipt.status == "degraded"
    assert "build_identity" in receipt.missing
    assert manifest["capture_status"] == "degraded"
    assert validation.integrity_valid is True
    assert validation.capture_complete is False
    assert "build_identity" in validation.gaps
    services.journal.close()


def test_report_cannot_substitute_for_same_turn_verification_event(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-verification-gap")
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="verify",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    _completed_artifacts(workspace, identity.session_id)
    receipt = recorder.finalize(
        status="completed", completed=True, message="claimed verified"
    )
    assert receipt.status == "degraded"
    assert "verification_event" in receipt.missing
    validation = validate_turn_evidence(recorder.manifest_path)
    assert validation.integrity_valid is True
    assert validation.capture_complete is False
    assert "verification_event" in validation.gaps
    services.journal.close()


def test_preexisting_unchanged_report_is_not_claimed_for_current_turn(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    identity = _identity(workspace, "session-stale-report")
    _completed_artifacts(workspace, identity.session_id)
    services = _services(tmp_path)
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="do not reuse a stale report",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    trace = (
        workspace
        / "diagnostics"
        / "traces"
        / f"{identity.session_id}.jsonl"
    )
    with trace.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "step_index": 5,
                    "node_name": "finalize",
                    "diagnostics": ["FINAL_VERDICT: completed"],
                }
            )
            + "\n"
        )
    services.journal.append(
        "verification.updated",
        {"schema_version": 1, "status": "passed", "summary": "verified"},
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        workspace_id=identity.workspace_id,
    )

    receipt = recorder.finalize(
        status="completed",
        completed=True,
        message="done",
    )
    manifest, _ = _read_manifest(recorder)

    assert receipt.status == "degraded"
    assert "report" in receipt.missing
    assert manifest["artifacts"]["report"]["available"] is False
    assert (
        manifest["artifacts"]["report"]["capture_error"]
        == "report_not_updated_during_turn"
    )
    services.journal.close()


def test_trace_snapshot_contains_only_current_turn_append_range(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-trace-range")
    trace = workspace / "diagnostics" / "traces" / f"{identity.session_id}.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_text(
        json.dumps({"step_index": 1, "node_name": "old-turn"}) + "\n",
        encoding="utf-8",
    )
    initial_size = trace.stat().st_size
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="new turn",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    with trace.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "step_index": 2,
                    "node_name": "finalize",
                    "diagnostics": ["FINAL_VERDICT: completed"],
                }
            )
            + "\n"
        )
    report = workspace / "diagnostics" / f"PERFORMANCE_REPORT_{identity.session_id}.md"
    report.write_text(
        "| **Task verdict** | `completed` |\n",
        encoding="utf-8",
    )
    recorder.finalize(status="completed", completed=True, message="done")
    manifest, _ = _read_manifest(recorder)
    trace_artifact = manifest["artifacts"]["trace"]
    assert trace_artifact["source_start_offset"] == initial_size
    assert trace_artifact["source_end_offset"] == trace.stat().st_size
    assert trace_artifact["row_count"] == 1
    assert trace_artifact["last_node"] == "finalize"
    snapshot_text = Path(trace_artifact["path"]).read_text(encoding="utf-8")
    assert "old-turn" not in snapshot_text
    services.journal.close()


def test_artifact_snapshots_degrade_at_bounded_size_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-bounded-artifacts")
    monkeypatch.setattr(capture_module, "_MAX_TRACE_SNAPSHOT_BYTES", 64)
    monkeypatch.setattr(capture_module, "_MAX_REPORT_SNAPSHOT_BYTES", 64)
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="bounded capture",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    trace = (
        workspace
        / "diagnostics"
        / "traces"
        / f"{identity.session_id}.jsonl"
    )
    trace.parent.mkdir(parents=True)
    trace.write_text(
        json.dumps(
            {
                "step_index": 1,
                "node_name": "finalize",
                "user_ask": "x" * 200,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = (
        workspace
        / "diagnostics"
        / f"PERFORMANCE_REPORT_{identity.session_id}.md"
    )
    report.write_text("report body " + ("y" * 200), encoding="utf-8")

    receipt = recorder.finalize(status="failed", error="bounded test")
    manifest, _ = _read_manifest(recorder)

    assert receipt.status == "degraded"
    assert manifest["artifacts"]["trace"]["capture_error"] == (
        "trace_snapshot_size_limit_exceeded"
    )
    assert manifest["artifacts"]["report"]["capture_error"] == (
        "report_snapshot_size_limit_exceeded"
    )
    assert not Path(manifest["artifacts"]["trace"]["path"]).exists()
    assert not Path(manifest["artifacts"]["report"]["path"]).exists()
    services.journal.close()


def test_evidence_validator_detects_artifact_and_manifest_tampering(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-validator")
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="validate",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    services.journal.append(
        "verification.updated",
        {"schema_version": 1, "status": "passed"},
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        workspace_id=identity.workspace_id,
    )
    _completed_artifacts(workspace, identity.session_id)
    recorder.finalize(status="completed", completed=True, message="done")
    cli = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_runtime_evidence.py"),
            str(recorder.manifest_path),
            "--require-complete",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr
    assert json.loads(cli.stdout)["integrity_valid"] is True
    trace_path = Path(
        json.loads(recorder.manifest_path.read_text(encoding="utf-8"))[
            "artifacts"
        ]["trace"]["path"]
    )
    trace_path.write_text("tampered\n", encoding="utf-8")
    artifact_result = validate_turn_evidence(recorder.manifest_path)
    assert artifact_result.integrity_valid is False
    assert artifact_result.capture_complete is False
    assert "ARTIFACT_HASH_MISMATCH:trace" in artifact_result.errors
    assert "ARTIFACT_SIZE_MISMATCH:trace" in artifact_result.errors
    assert "CAPTURE_COMPLETENESS_OVERSTATED" in artifact_result.errors

    manifest = json.loads(recorder.manifest_path.read_text(encoding="utf-8"))
    manifest["request"]["mode"] = "tampered"
    recorder.manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_result = validate_turn_evidence(recorder.manifest_path)
    assert "MANIFEST_CHECKSUM_MISMATCH" in manifest_result.errors
    services.journal.close()


def test_watchdog_reservation_cannot_be_relabelled_by_late_completion(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-watchdog")
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="run",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    claimed: list[str] = []
    assert recorder.reserve_terminal(
        "watchdog", on_reserved=lambda: claimed.append("watchdog")
    )
    receipt = recorder.finalize(
        status="completed",
        completed=True,
        message="late result",
    )
    assert claimed == ["watchdog"]
    assert receipt.lifecycle_status == "watchdog"
    events = services.journal.list_turn_events(
        identity.session_id, identity.turn_id
    )
    assert [event["type"] for event in events][-1] == "turn.watchdog"
    manifest, _ = _read_manifest(recorder)
    assert manifest["lifecycle"]["completed"] is False
    assert validate_turn_evidence(recorder.manifest_path).integrity_valid is True
    services.journal.close()


def test_bridge_watchdog_frame_and_sqlite_share_one_terminal_receipt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-bridge-watchdog")
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="hang",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    emitted: list[dict] = []
    server = object.__new__(BridgeServer)
    server.emit = emitted.append
    force_ended = threading.Event()

    server._emit_stall_release(identity, force_ended, 30.0, recorder)
    assert force_ended.is_set()
    assert [frame["type"] for frame in emitted] == [
        "runtime_degraded",
        "turn_done",
    ]
    assert emitted[-1]["evidence"]["lifecycle_status"] == "watchdog"
    assert emitted[-1]["evidence"]["journal_terminal_seq"] is not None
    events = services.journal.list_turn_events(
        identity.session_id, identity.turn_id
    )
    assert [event["type"] for event in events] == [
        "turn.started",
        "turn.watchdog",
    ]

    # A second watchdog observation cannot emit or persist a second terminal.
    server._emit_stall_release(identity, force_ended, 30.0, recorder)
    assert len(emitted) == 2
    assert len(
        services.journal.list_turn_events(
            identity.session_id, identity.turn_id
        )
    ) == 2
    services.journal.close()


def test_artifact_verdict_cannot_contradict_terminal_lifecycle(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    identity = _identity(workspace, "session-verdict-conflict")
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="fail after a stale success report",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    services.journal.append(
        "verification.updated",
        {"schema_version": 1, "status": "passed", "summary": "verified"},
        session_id=identity.session_id,
        turn_id=identity.turn_id,
        workspace_id=identity.workspace_id,
    )
    _completed_artifacts(workspace, identity.session_id)

    receipt = recorder.finalize(
        status="failed",
        completed=False,
        error="later provider failure",
    )
    validation = validate_turn_evidence(
        recorder.manifest_path,
        journal_path=services.journal.path,
    )

    assert receipt.status == "degraded"
    assert "trace_lifecycle_conflict" in receipt.missing
    assert "report_lifecycle_conflict" in receipt.missing
    assert validation.integrity_valid is True
    assert validation.capture_complete is False
    assert "trace_lifecycle_conflict" in validation.gaps
    assert "report_lifecycle_conflict" in validation.gaps
    services.journal.close()


@pytest.mark.parametrize(
    ("status", "cancelled", "event_type"),
    [
        ("cancelled", True, "turn.cancelled"),
        ("failed", False, "turn.failed"),
        ("interrupted", False, "turn.interrupted"),
    ],
)
def test_non_success_terminal_states_are_explicit(
    tmp_path: Path,
    status: str,
    cancelled: bool,
    event_type: str,
) -> None:
    workspace = tmp_path / status
    workspace.mkdir()
    services = _services(tmp_path / status)
    identity = _identity(workspace, f"session-{status}")
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="run",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    receipt = recorder.finalize(
        status=status,
        completed=False,
        cancelled=cancelled,
        error=(
            "provider key sk-abcdefghijklmnopqrstuvwxyz123456"
            if status == "failed"
            else ""
        ),
        reason="test_terminal",
    )
    assert receipt.lifecycle_status == status
    events = services.journal.list_turn_events(
        identity.session_id, identity.turn_id
    )
    assert events[-1]["type"] == event_type
    manifest, raw = _read_manifest(recorder)
    assert manifest["lifecycle"]["cancelled"] is cancelled
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in raw
    assert manifest["terminal"]["message"]["body_persisted"] is False
    if status == "failed":
        assert manifest["terminal"]["error"]["body_persisted"] is False
        assert manifest["terminal"]["error"]["sha256"]
    validation = validate_turn_evidence(recorder.manifest_path)
    assert validation.integrity_valid is True, validation.errors
    assert validation.capture_complete is False
    services.journal.close()


def test_bridge_turn_continues_when_capture_service_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_begin(**kwargs):
        raise OSError("evidence disk unavailable")

    monkeypatch.setattr(
        TurnEvidenceRecorder,
        "begin",
        staticmethod(fail_begin),
    )
    monkeypatch.setenv("CRUSORAI_BRIDGE_RUNNER", "echo")
    monkeypatch.setenv("CRUSORAI_TURN_STALL_TIMEOUT_S", "0")
    monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("CRUSORAI_SESSIONS_DB", str(tmp_path / "sessions.db"))
    emitted: list[dict] = []
    server = object.__new__(BridgeServer)
    server.emit = emitted.append
    server._shutdown = threading.Event()

    server._run_turn(
        "session-capture-unavailable",
        "the user turn still runs",
        str(tmp_path),
    )

    assert emitted[0]["type"] == "turn_started"
    assert emitted[0]["evidence"]["status"] == "unavailable"
    assert any(
        frame.get("type") == "runtime_degraded"
        and "monitoring coverage is incomplete" in frame.get("reason", "")
        for frame in emitted
    )
    assert any(
        frame.get("type") == "token"
        and frame.get("text") == "the user turn still runs"
        for frame in emitted
    )
    assert emitted[-1]["type"] == "turn_done"
    assert emitted[-1]["evidence"]["status"] == "unavailable"


def test_capture_failures_are_explicit_and_do_not_raise(tmp_path: Path) -> None:
    class BrokenJournal:
        path = tmp_path / "broken.db"

        def append(self, *args, **kwargs):
            raise OSError(
                "disk token sk-abcdefghijklmnopqrstuvwxyz987654 unavailable"
            )

        def list_turn_events(self, *args, **kwargs):
            raise OSError("read unavailable")

        def verify_chain(self, *args, **kwargs):
            raise OSError("verify unavailable")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    identity = _identity(workspace, "session-fail-open")
    recorder = TurnEvidenceRecorder.begin(
        identity=identity,
        workspace=str(workspace),
        prompt="still run the turn",
        mode="agent",
        services=SimpleNamespace(journal=BrokenJournal()),
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    receipt = recorder.finalize(status="failed", error="model failed")
    assert receipt.status == "degraded"
    assert receipt.journal_terminal_seq is None
    assert "terminal_event" in receipt.missing
    _, raw = _read_manifest(recorder)
    assert "sk-abcdefghijklmnopqrstuvwxyz987654" not in raw

    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("file", encoding="utf-8")
    services = _services(tmp_path / "second")
    unavailable = TurnEvidenceRecorder.begin(
        identity=_identity(workspace, "session-unwritable"),
        workspace=str(workspace),
        prompt="run anyway",
        mode="agent",
        services=services,
        root=blocked_root,
        build_identity=_matched_build(),
    ).finalize(status="failed", error="expected")
    assert unavailable.status == "unavailable"
    assert unavailable.manifest_path is None
    services.journal.close()


def test_restart_recovers_in_progress_turn_and_records_runtime_continuity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    first_identity = _identity(workspace, "session-restart")
    first = TurnEvidenceRecorder.begin(
        identity=first_identity,
        workspace=str(workspace),
        prompt="first turn",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    first_manifest, _ = _read_manifest(first)
    original_runtime = first_manifest["runtime"]["runtime_instance_id"]
    assert first_manifest["lifecycle"]["status"] == "in_progress"

    monkeypatch.setattr(
        capture_module,
        "_RUNTIME_INSTANCE_ID",
        "runtime-restarted-process",
    )
    second_identity = _identity(workspace, "session-restart")
    second = TurnEvidenceRecorder.begin(
        identity=second_identity,
        workspace=str(workspace),
        prompt="resumed turn",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )

    recovered, _ = _read_manifest(first)
    current, _ = _read_manifest(second)
    assert recovered["lifecycle"]["status"] == "interrupted"
    assert recovered["recovery"]["status"] == "recovered_after_restart"
    recovered_validation = validate_turn_evidence(first.manifest_path)
    assert recovered_validation.integrity_valid is True, recovered_validation.errors
    assert recovered_validation.capture_complete is False
    assert recovered["runtime"]["runtime_instance_id"] == original_runtime
    continuity = current["continuity"]["recovered_interrupted_turns"]
    assert continuity == [
        {
            "manifest_sha256": hashlib.sha256(
                first.manifest_path.read_bytes()
            ).hexdigest(),
            "status": "interrupted",
            "terminal_seq": recovered["journal"]["terminal_seq"],
            "turn_id": first_identity.turn_id,
        }
    ]
    assert current["runtime"]["runtime_instance_id"] == "runtime-restarted-process"
    prior_events = services.journal.list_turn_events(
        first_identity.session_id, first_identity.turn_id
    )
    assert [event["type"] for event in prior_events] == [
        "turn.started",
        "turn.interrupted",
    ]
    second.interrupt_if_open("test_cleanup")
    services.journal.close()


def test_restart_recovers_terminal_row_and_immutable_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _services(tmp_path)
    first_identity = _identity(workspace, "session-terminal-restart")
    first = TurnEvidenceRecorder.begin(
        identity=first_identity,
        workspace=str(workspace),
        prompt="terminal commits before manifest",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )
    services.journal.append(
        "verification.updated",
        {"schema_version": 1, "status": "passed", "summary": "verified"},
        session_id=first_identity.session_id,
        turn_id=first_identity.turn_id,
        workspace_id=first_identity.workspace_id,
    )
    _completed_artifacts(workspace, first_identity.session_id)
    artifacts = first._collect_artifacts()
    ended_at = capture_module.time.time()
    terminal_payload = {
        "schema_version": capture_module.EVIDENCE_MANIFEST_SCHEMA_VERSION,
        "evidence_id": first.evidence_id,
        "identity": first_identity.event_fields(),
        "status": "completed",
        "completed": True,
        "cancelled": False,
        "duration_s": round(
            max(0.0, ended_at - first_identity.created_at), 3
        ),
        "message": capture_module._private_text_receipt("done before crash"),
        "error": None,
        "reason": "simulated_crash_after_terminal_commit",
        "artifacts": {
            name: {
                "available": bool(details.get("available")),
                "sha256": details.get("sha256"),
            }
            for name, details in artifacts.items()
            if name in {"trace", "report"}
        },
    }
    terminal = services.journal.append(
        "turn.completed",
        terminal_payload,
        session_id=first_identity.session_id,
        turn_id=first_identity.turn_id,
        workspace_id=first_identity.workspace_id,
    )
    in_progress, _ = _read_manifest(first)
    assert in_progress["lifecycle"]["status"] == "in_progress"

    monkeypatch.setattr(
        capture_module,
        "_RUNTIME_INSTANCE_ID",
        "runtime-after-terminal-crash",
    )
    second = TurnEvidenceRecorder.begin(
        identity=_identity(workspace, "session-terminal-restart"),
        workspace=str(workspace),
        prompt="next turn performs recovery",
        mode="agent",
        services=services,
        root=tmp_path / "evidence",
        build_identity=_matched_build(),
    )

    recovered, _ = _read_manifest(first)
    validation = validate_turn_evidence(
        first.manifest_path,
        journal_path=services.journal.path,
    )
    assert recovered["lifecycle"]["status"] == "completed"
    assert recovered["journal"]["terminal_seq"] == terminal["seq"]
    assert recovered["terminal"] == terminal_payload
    assert recovered["artifacts"]["trace"]["sha256"] == artifacts["trace"]["sha256"]
    assert recovered["artifacts"]["report"]["sha256"] == artifacts["report"]["sha256"]
    assert "process_interruption" in recovered["coverage"]["missing"]
    assert validation.integrity_valid is True, validation.errors
    assert validation.capture_complete is False
    second.interrupt_if_open("test_cleanup")
    services.journal.close()

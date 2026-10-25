"""Independent verification for per-turn evidence manifests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.runtime.build_identity import build_identity_is_complete
from src.runtime.event_journal import compute_event_integrity_hash


@dataclass(frozen=True)
class EvidenceValidationResult:
    integrity_valid: bool
    capture_complete: bool
    finalized: bool
    manifest_path: str
    manifest_sha256: str | None
    errors: tuple[str, ...]
    gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["errors"] = list(self.errors)
        value["gaps"] = list(self.gaps)
        return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_build_binding(manifest: dict[str, Any]) -> dict[str, Any]:
    build = dict(manifest.get("build") or {})
    repository = dict(build.get("repository") or {})
    renderer = dict(build.get("renderer") or {})
    return {
        "status": build.get("status"),
        "repository_commit": repository.get("commit"),
        "worktree_fingerprint_sha256": repository.get(
            "worktree_fingerprint_sha256"
        ),
        "renderer_build_commit": renderer.get("build_commit"),
        "renderer_source_stamp": renderer.get("source_stamp"),
        "renderer_sources_hash": renderer.get("recomputed_sources_hash"),
    }


def _terminal_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if str(event.get("type") or "")
        in {
            "turn.completed",
            "turn.cancelled",
            "turn.failed",
            "turn.watchdog",
            "turn.interrupted",
        }
    ]


def _pairing_gaps(events: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    intents: set[str] = set()
    results: set[str] = set()
    for event in events:
        call_id = str(event.get("tool_call_id") or "")
        if event.get("type") == "tool.intent":
            if call_id:
                intents.add(call_id)
        elif event.get("type") == "tool.result" and call_id:
            results.add(call_id)
    return sorted(intents - results), sorted(results - intents)


def _read_journal_evidence(
    path: Path,
    *,
    session_id: str,
    turn_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read and verify SQLite in query-only mode without migrating it."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT * FROM runtime_events WHERE session_id=? ORDER BY seq",
            (session_id,),
        ).fetchall()
    finally:
        connection.close()

    previous_hash = ""
    first_bad_seq: int | None = None
    checked = 0
    events: list[dict[str, Any]] = []
    for row in rows:
        checked += 1
        payload_json = str(row["payload_json"])
        stored_previous = str(row["prev_hash"] or "")
        stored_hash = str(row["event_hash"] or "")
        expected_hash = compute_event_integrity_hash(
            event_id=str(row["event_id"]),
            created_at=float(row["created_at"]),
            event_type=str(row["event_type"]),
            session_id=str(row["session_id"]),
            turn_id=row["turn_id"],
            workspace_id=row["workspace_id"],
            tool_call_id=row["tool_call_id"],
            payload_json=payload_json,
            prev_hash=previous_hash,
        )
        if (
            first_bad_seq is None
            and (
                stored_previous != previous_hash
                or stored_hash != expected_hash
            )
        ):
            first_bad_seq = int(row["seq"])
        previous_hash = stored_hash
        if row["turn_id"] == turn_id:
            events.append(
                {
                    "seq": int(row["seq"]),
                    "event_id": row["event_id"],
                    "timestamp": float(row["created_at"]),
                    "type": row["event_type"],
                    "session_id": row["session_id"],
                    "turn_id": row["turn_id"],
                    "workspace_id": row["workspace_id"],
                    "tool_call_id": row["tool_call_id"],
                    "payload": json.loads(payload_json),
                    "prev_hash": row["prev_hash"],
                    "event_hash": row["event_hash"],
                    "chain_version": 1,
                }
            )
    chain = {
        "valid": first_bad_seq is None,
        "checked": checked,
        "event_count": len(rows),
        "first_bad_seq": first_bad_seq,
        "head_hash": previous_hash or None,
        "chain_version": 1,
    }
    return chain, events


def validate_turn_evidence(
    manifest_path: str | Path,
    *,
    journal_path: str | Path | None = None,
) -> EvidenceValidationResult:
    """Validate integrity without trusting narrative fields in the manifest."""
    path = Path(manifest_path).expanduser().resolve()
    errors: list[str] = []
    gaps: list[str] = []
    manifest_digest: str | None = None
    manifest: dict[str, Any] = {}

    try:
        encoded = path.read_bytes()
        manifest_digest = hashlib.sha256(encoded).hexdigest()
    except OSError as exc:
        errors.append(f"MANIFEST_UNREADABLE:{type(exc).__name__}")
        return EvidenceValidationResult(
            integrity_valid=False,
            capture_complete=False,
            finalized=False,
            manifest_path=str(path),
            manifest_sha256=None,
            errors=tuple(errors),
            gaps=(),
        )
    try:
        decoded = json.loads(encoded)
        if not isinstance(decoded, dict):
            raise TypeError("manifest root is not an object")
        manifest = decoded
    except (json.JSONDecodeError, TypeError) as exc:
        errors.append(f"MANIFEST_JSON_INVALID:{type(exc).__name__}")

    sidecar = path.with_suffix(".json.sha256")
    try:
        tokens = sidecar.read_text(encoding="ascii").split()
        sidecar_digest = tokens[0]
        sidecar_name = tokens[1] if len(tokens) > 1 else ""
        if sidecar_digest != manifest_digest:
            errors.append("MANIFEST_CHECKSUM_MISMATCH")
        if sidecar_name != path.name:
            errors.append("MANIFEST_SIDECAR_NAME_MISMATCH")
    except (OSError, UnicodeError, IndexError):
        errors.append("MANIFEST_SIDECAR_UNREADABLE")

    if manifest.get("schema_version") != 1:
        errors.append("MANIFEST_SCHEMA_UNSUPPORTED")
    scope = manifest.get("evidence_scope") or {}
    if scope.get("kind") != "agent_core_runtime":
        errors.append("EVIDENCE_SCOPE_INVALID")
    if scope.get("synthetic_desktop_evidence") is not False:
        errors.append("DESKTOP_EVIDENCE_SCOPE_AMBIGUOUS")
    identity = manifest.get("identity") or {}
    lifecycle = manifest.get("lifecycle") or {}
    journal_summary = manifest.get("journal") or {}
    request = manifest.get("request") or {}
    if request.get("body_persisted") is not False:
        errors.append("REQUEST_BODY_POLICY_INVALID")
    if {"body", "content", "prompt", "text"} & set(request):
        errors.append("REQUEST_BODY_PRESENT")
    terminal_payload = manifest.get("terminal") or {}
    if terminal_payload:
        for field in ("message", "error"):
            receipt = terminal_payload.get(field)
            if receipt is None and field == "error":
                continue
            if (
                not isinstance(receipt, dict)
                or receipt.get("body_persisted") is not False
                or not receipt.get("sha256")
                or not isinstance(receipt.get("byte_length"), int)
            ):
                errors.append(
                    f"TERMINAL_{field.upper()}_BODY_POLICY_INVALID"
                )
    for key in (
        "session_id",
        "runtime_session_id",
        "lineage_root_id",
        "workspace_id",
        "turn_id",
    ):
        if not identity.get(key):
            errors.append(f"IDENTITY_MISSING:{key}")
    finalized = str(lifecycle.get("status") or "") != "in_progress"
    if not finalized:
        gaps.append("terminal_event")
    build = manifest.get("build") or {}
    if not build_identity_is_complete(build):
        gaps.append("build_identity")

    artifacts = manifest.get("artifacts") or {}
    for name in ("trace", "report"):
        artifact = artifacts.get(name) or {}
        if not artifact.get("available"):
            gaps.append(name)
            continue
        artifact_path = Path(
            str(artifact.get("relative_path") or artifact.get("path") or "")
        ).expanduser()
        if not artifact_path.is_absolute():
            artifact_path = path.parent / artifact_path
        try:
            artifact_path = artifact_path.resolve()
            artifact_path.relative_to(path.parent)
        except (OSError, ValueError):
            # Do not follow an untrusted manifest outside its evidence root and
            # hash arbitrary local files merely to report a second error.
            errors.append(f"ARTIFACT_OUTSIDE_EVIDENCE_ROOT:{name}")
            continue
        if artifact.get("immutable_copy") is not True:
            errors.append(f"ARTIFACT_NOT_SNAPSHOTTED:{name}")
        if artifact.get("privacy_filtered") is not True:
            errors.append(f"ARTIFACT_PRIVACY_FILTER_MISSING:{name}")
        if not artifact_path.is_file():
            errors.append(f"ARTIFACT_MISSING:{name}")
            continue
        try:
            actual_size = artifact_path.stat().st_size
            actual_hash = _file_sha256(artifact_path)
        except OSError as exc:
            errors.append(f"ARTIFACT_UNREADABLE:{name}:{type(exc).__name__}")
            continue
        if actual_size != artifact.get("size_bytes"):
            errors.append(f"ARTIFACT_SIZE_MISMATCH:{name}")
        if actual_hash != artifact.get("sha256"):
            errors.append(f"ARTIFACT_HASH_MISMATCH:{name}")

    lifecycle_status = str(lifecycle.get("status") or "")
    if (
        bool(lifecycle.get("completed")) != (lifecycle_status == "completed")
        or bool(lifecycle.get("cancelled")) != (lifecycle_status == "cancelled")
    ):
        gaps.append("lifecycle_flags")
    trace = artifacts.get("trace") or {}
    report = artifacts.get("report") or {}
    if trace.get("available"):
        if int(trace.get("row_count") or 0) < 1:
            gaps.append("trace_empty")
        if int(trace.get("parse_errors") or 0) > 0:
            gaps.append("trace_parse_errors")
    report_fields = report.get("fields") or {}
    if report.get("available"):
        required_report_fields = {
            "task_verdict",
            "verification_status",
            "current-turn_executed_tool_records",
        }
        if required_report_fields - set(report_fields):
            gaps.append("report_fields")
        try:
            report_tool_count = int(
                str(
                    report_fields.get("current-turn_executed_tool_records")
                ).replace(",", "")
            )
        except (TypeError, ValueError):
            report_tool_count = None
        if report_tool_count is None:
            gaps.append("report_tool_count")
    else:
        report_tool_count = None
    trace_verdict = str(
        trace.get("last_final_verdict") or ""
    ).strip().lower()
    report_verdict = str(
        (report.get("fields") or {}).get("task_verdict") or ""
    ).strip().lower()
    successful_verdicts = {
        "complete",
        "completed",
        "passed",
        "succeeded",
        "success",
    }
    if lifecycle.get("completed") is True:
        if trace.get("last_node") != "finalize":
            gaps.append("trace_finalization")
        if trace_verdict not in successful_verdicts:
            gaps.append("trace_verdict")
        if report_verdict not in successful_verdicts:
            gaps.append("report_verdict")
    else:
        if trace_verdict in successful_verdicts:
            gaps.append("trace_lifecycle_conflict")
        if report_verdict in successful_verdicts:
            gaps.append("report_lifecycle_conflict")

    selected_journal = Path(
        journal_path or str(journal_summary.get("database_path") or "")
    ).expanduser()
    if not str(selected_journal) or not selected_journal.is_file():
        errors.append("JOURNAL_UNAVAILABLE")
    elif identity.get("session_id") and identity.get("turn_id"):
        try:
            chain, events = _read_journal_evidence(
                selected_journal,
                session_id=str(identity["session_id"]),
                turn_id=str(identity["turn_id"]),
            )
            if chain.get("valid") is not True:
                errors.append(
                    f"JOURNAL_CHAIN_INVALID:{chain.get('first_bad_seq')}"
                )
            actual_types = Counter(str(event.get("type") or "") for event in events)
            if any(
                event.get("workspace_id") != identity.get("workspace_id")
                for event in events
            ):
                errors.append("JOURNAL_WORKSPACE_IDENTITY_MISMATCH")
            expected_types = {
                str(key): int(value)
                for key, value in dict(
                    journal_summary.get("event_types") or {}
                ).items()
            }
            if len(events) != journal_summary.get("event_count"):
                errors.append("JOURNAL_EVENT_COUNT_MISMATCH")
            if dict(sorted(actual_types.items())) != dict(
                sorted(expected_types.items())
            ):
                errors.append("JOURNAL_EVENT_TYPES_MISMATCH")
            if (
                report.get("available")
                and report_tool_count is not None
                and report_tool_count != int(actual_types.get("tool.result", 0))
            ):
                gaps.append("report_tool_count_mismatch")
            starts = [
                event for event in events if event.get("type") == "turn.started"
            ]
            if len(starts) != 1:
                errors.append("JOURNAL_START_COUNT_INVALID")
            elif (starts[0].get("payload") or {}).get(
                "evidence_id"
            ) != manifest.get("evidence_id"):
                errors.append("JOURNAL_START_EVIDENCE_ID_MISMATCH")
            elif (starts[0].get("payload") or {}).get("identity") != identity:
                errors.append("JOURNAL_START_IDENTITY_MISMATCH")
            elif (starts[0].get("payload") or {}).get(
                "build"
            ) != _manifest_build_binding(manifest):
                errors.append("JOURNAL_START_BUILD_MISMATCH")
            if len(starts) == 1:
                start_payload = starts[0].get("payload") or {}
                request = manifest.get("request") or {}
                if start_payload.get("request") != {
                    "byte_length": request.get("byte_length"),
                    "sha256": request.get("sha256"),
                }:
                    errors.append("JOURNAL_START_REQUEST_MISMATCH")
                runtime = manifest.get("runtime") or {}
                if start_payload.get("runtime_instance_id") != runtime.get(
                    "runtime_instance_id"
                ):
                    errors.append("JOURNAL_START_RUNTIME_MISMATCH")
                workspace = manifest.get("workspace") or {}
                if start_payload.get("workspace") != workspace.get("path"):
                    errors.append("JOURNAL_START_WORKSPACE_MISMATCH")
                if start_payload.get("mode") != request.get("mode"):
                    errors.append("JOURNAL_START_MODE_MISMATCH")
            terminals = _terminal_events(events)
            if finalized and len(terminals) != 1:
                errors.append("JOURNAL_TERMINAL_COUNT_INVALID")
            verification_events = [
                event
                for event in events
                if event.get("type") == "verification.updated"
            ]
            expected_transitions = list(
                journal_summary.get("verification_transitions") or []
            )
            if len(verification_events) != journal_summary.get(
                "verification_event_count"
            ) or len(verification_events) != len(expected_transitions):
                errors.append("VERIFICATION_EVENT_COUNT_MISMATCH")
            report_verification = str(
                ((artifacts.get("report") or {}).get("fields") or {}).get(
                    "verification_status"
                )
                or ""
            ).strip().lower()
            if (
                report_verification
                not in {"", "not_applicable", "not applicable", "unavailable"}
                and not verification_events
            ):
                gaps.append("verification_event")
            for event, transition in zip(
                verification_events, expected_transitions, strict=False
            ):
                if (
                    event.get("seq") != transition.get("seq")
                    or event.get("event_id") != transition.get("event_id")
                    or event.get("event_hash") != transition.get("event_hash")
                    or (event.get("payload") or {}).get("status")
                    != transition.get("status")
                ):
                    errors.append("VERIFICATION_TRANSITION_MISMATCH")
            if terminals:
                terminal = terminals[0]
                expected_terminal = journal_summary.get("terminal_event") or {}
                if terminal.get("seq") != expected_terminal.get("seq"):
                    errors.append("JOURNAL_TERMINAL_SEQ_MISMATCH")
                if terminal.get("type") != expected_terminal.get("type"):
                    errors.append("JOURNAL_TERMINAL_TYPE_MISMATCH")
                if terminal.get("event_hash") != expected_terminal.get(
                    "event_hash"
                ):
                    errors.append("JOURNAL_TERMINAL_HASH_MISMATCH")
                expected_lifecycle_type = f"turn.{lifecycle.get('status')}"
                if terminal.get("type") != expected_lifecycle_type:
                    errors.append("LIFECYCLE_TERMINAL_MISMATCH")
                if (terminal.get("payload") or {}).get(
                    "evidence_id"
                ) != manifest.get("evidence_id"):
                    errors.append("JOURNAL_TERMINAL_EVIDENCE_ID_MISMATCH")
                if (terminal.get("payload") or {}).get("identity") != identity:
                    errors.append("JOURNAL_TERMINAL_IDENTITY_MISMATCH")
                terminal_payload = terminal.get("payload") or {}
                if terminal_payload != (manifest.get("terminal") or {}):
                    errors.append("JOURNAL_TERMINAL_PAYLOAD_MISMATCH")
                terminal_artifacts = terminal_payload.get("artifacts") or {}
                for artifact_name in ("trace", "report"):
                    artifact = artifacts.get(artifact_name) or {}
                    expected_artifact = {
                        "available": bool(artifact.get("available")),
                        "sha256": artifact.get("sha256"),
                    }
                    if terminal_artifacts.get(artifact_name) != expected_artifact:
                        errors.append(
                            f"TERMINAL_ARTIFACT_MISMATCH:{artifact_name}"
                        )
            unmatched, orphaned = _pairing_gaps(events)
            if unmatched != sorted(journal_summary.get("unmatched_intents") or []):
                errors.append("TOOL_UNMATCHED_INTENTS_MISMATCH")
            if orphaned != sorted(journal_summary.get("orphan_results") or []):
                errors.append("TOOL_ORPHAN_RESULTS_MISMATCH")
            if unmatched:
                gaps.append("tool_results")
            if orphaned:
                gaps.append("tool_intents")
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            errors.append(f"JOURNAL_VALIDATION_FAILED:{type(exc).__name__}")

    declared_gaps = [
        str(value) for value in (manifest.get("coverage") or {}).get("missing", [])
    ]
    for gap in declared_gaps:
        if gap not in gaps:
            gaps.append(gap)
    if manifest.get("capture_status") == "complete" and (gaps or errors):
        errors.append("CAPTURE_COMPLETENESS_OVERSTATED")
    capture_complete = (
        finalized
        and manifest.get("capture_status") == "complete"
        and not gaps
        and not errors
    )

    return EvidenceValidationResult(
        integrity_valid=not errors,
        capture_complete=capture_complete,
        finalized=finalized,
        manifest_path=str(path),
        manifest_sha256=manifest_digest,
        errors=tuple(sorted(set(errors))),
        gaps=tuple(sorted(set(gaps))),
    )

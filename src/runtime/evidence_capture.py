"""Automatic, durable per-turn evidence capture.

The runtime journal is the canonical timeline. This module binds that timeline
to process/build/workspace identity and hashes the StepTracker artifacts into a
single atomic manifest. Prompt and final-answer bodies are represented only by
length + SHA-256; tool arguments/results remain in the already-sanitized journal.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.runtime.build_identity import (
    build_identity_is_complete,
    collect_build_identity,
)
from src.runtime.identity import TurnIdentity
from src.runtime.persistence import sanitize_for_persistence

EVIDENCE_MANIFEST_SCHEMA_VERSION = 1
_RUNTIME_INSTANCE_ID = f"runtime-{uuid.uuid4().hex}"
_PROCESS_STARTED_AT = time.time()
_MAX_TRACE_SNAPSHOT_BYTES = 16 * 1024 * 1024
_MAX_REPORT_SNAPSHOT_BYTES = 16 * 1024 * 1024
_TERMINAL_STATUSES = frozenset(
    {"completed", "cancelled", "failed", "watchdog", "interrupted"}
)
_PRIVATE_TEXT_FIELDS = frozenset(
    {
        "answer",
        "final_answer",
        "final_assistant_message",
        "final_message",
        "prompt",
        "user_ask",
        "user_prompt",
    }
)
_REPORT_FIELD_RE = re.compile(
    r"\|\s*\*\*(?P<field>Task verdict|Verification status|"
    r"Current-turn executed tool records|Current-task failed steps)\*\*\s*"
    r"\|\s*(?P<value>[^|]+)\|",
    re.IGNORECASE,
)


def _utc_iso(timestamp: float | None = None) -> str:
    value = time.time() if timestamp is None else float(timestamp)
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def _text_receipt(value: str) -> dict[str, Any]:
    encoded = str(value or "").encode("utf-8")
    return {
        "byte_length": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _private_text_receipt(value: str) -> dict[str, Any]:
    return {
        **_text_receipt(value),
        "body_persisted": False,
    }


def _privacy_filter_value(
    value: Any,
    *,
    private_texts: tuple[str, ...] = (),
) -> Any:
    """Replace prompt/final-answer fields in copied diagnostics recursively."""
    if isinstance(value, dict):
        filtered: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            normalized = name.strip().lower().replace("-", "_").replace(" ", "_")
            filtered[name] = (
                _private_text_receipt(str(item or ""))
                if normalized in _PRIVATE_TEXT_FIELDS
                else _privacy_filter_value(item, private_texts=private_texts)
            )
        return filtered
    if isinstance(value, list):
        return [
            _privacy_filter_value(item, private_texts=private_texts)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            _privacy_filter_value(item, private_texts=private_texts)
            for item in value
        ]
    if isinstance(value, str) and value and value in private_texts:
        return _private_text_receipt(value)
    return value


def _privacy_filter_trace_bytes(
    data: bytes,
    *,
    private_texts: tuple[str, ...] = (),
) -> bytes:
    """Create JSONL evidence without copying opaque/raw private rows."""
    output: list[bytes] = []
    for raw_line in data.splitlines():
        if not raw_line.strip():
            continue
        try:
            decoded = json.loads(raw_line.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise TypeError("trace row is not an object")
            filtered = sanitize_for_persistence(
                _privacy_filter_value(decoded, private_texts=private_texts)
            )
            output.append(
                json.dumps(
                    filtered,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except Exception:  # noqa: BLE001 - opaque diagnostics become a hash only
            output.append(
                json.dumps(
                    {
                        "__unparsed_trace_row__": {
                            "byte_length": len(raw_line),
                            "sha256": hashlib.sha256(raw_line).hexdigest(),
                            "body_persisted": False,
                        }
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
            )
    encoded_size = sum(len(row) + 1 for row in output)
    if encoded_size > _MAX_TRACE_SNAPSHOT_BYTES:
        raise ValueError("privacy_filtered_trace_size_limit_exceeded")
    return b"\n".join(output) + (b"\n" if output else b"")


def _privacy_filter_report_bytes(
    data: bytes,
    *,
    private_texts: tuple[str, ...],
) -> bytes:
    """Remove the raw user-ask block from the report snapshot.

    The ask may contain newlines or Markdown that imitates separators. Locate
    the real fixed section from the end, then remove everything from the first
    User Ask header through that final separator. Avoid global string replace:
    a one-character prompt repeated throughout a report must not amplify into
    an enormous artifact.
    """
    text = data.decode("utf-8", errors="replace")
    section_marker = "\n---\n## Authoritative Completion Evidence"
    separator = text.rfind(section_marker)
    ask_start = text.find("**User Ask:**", 0, separator if separator >= 0 else None)
    if ask_start >= 0 and separator >= 0:
        request = private_texts[0] if private_texts else ""
        receipt = _private_text_receipt(request)
        replacement = (
            "**User Ask:** *[body omitted from runtime evidence; "
            f"sha256={receipt['sha256']}; bytes={receipt['byte_length']}]*  \n"
        )
        # separator points at the newline before `---`; preserve the marker
        # without also preserving any untrusted lines from the ask block.
        text = text[:ask_start] + replacement + text[separator + 1 :]
    else:
        # An unknown/legacy layout has no trustworthy boundary around a
        # potentially multiline ask. Preserve only the structured verdict
        # fields the evidence validator consumes, plus a hash of the source.
        source_receipt = _text_receipt(text)
        request = private_texts[0] if private_texts else ""
        request_receipt = _private_text_receipt(request)
        safe_lines = [
            "# Privacy-filtered performance evidence",
            (
                "Original report receipt: "
                f"sha256={source_receipt['sha256']}; "
                f"bytes={source_receipt['byte_length']}"
            ),
            (
                "**User Ask:** *[body omitted from runtime evidence; "
                f"sha256={request_receipt['sha256']}; "
                f"bytes={request_receipt['byte_length']}]*  "
            ),
        ]
        safe_lines.extend(
            f"| **{match.group('field')}** | `{match.group('value').strip().strip('`')}` |"
            for match in _REPORT_FIELD_RE.finditer(text)
        )
        text = "\n".join(safe_lines) + "\n"
    return text.encode("utf-8")


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file_version(
    path: Path,
) -> tuple[int, int, int, int, int, str | None] | None:
    """Fingerprint whether a bounded source artifact changed during a turn."""
    try:
        if not path.is_file():
            return None
        stat = path.stat()
        digest = _sha256_file(path) if stat.st_size <= 16 * 1024 * 1024 else None
        return (
            int(stat.st_dev),
            int(stat.st_ino),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
            digest,
        )
    except OSError:
        return None


def _evidence_root() -> Path:
    custom = os.getenv("CRUSORAI_EVIDENCE_DIR", "").strip()
    if custom:
        return Path(custom).expanduser()
    home = Path(os.getenv("CRUSORAI_HOME", "")).expanduser() if os.getenv("CRUSORAI_HOME") else Path.home() / ".crusorai"
    return home / "evidence" / "turns"


def _safe_component(value: str) -> str:
    """Return a filesystem-safe, collision-resistant identity component."""
    raw = str(value or "")
    safe = re.sub(r"[^A-Za-z0-9._:-]+", "_", raw)
    if safe and safe == raw and len(raw) <= 160:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{(safe[:140] or 'unknown')}-{digest}"


def _build_binding(build: dict[str, Any]) -> dict[str, Any]:
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


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass(frozen=True)
class EvidenceReceipt:
    status: str
    evidence_id: str
    lifecycle_status: str
    manifest_path: str | None
    manifest_sha256: str | None
    journal_terminal_seq: int | None
    journal_chain_valid: bool | None
    missing: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing"] = list(self.missing)
        return payload


class TurnEvidenceRecorder:
    """One bridge turn's fail-open capture owner.

    The recorder never changes Agent Core behavior. Capture failures become an
    explicit ``unavailable`` receipt instead of being swallowed or upgraded.
    """

    def __init__(
        self,
        *,
        identity: TurnIdentity,
        workspace: str,
        mode: str,
        services: Any,
        root: str | Path | None = None,
        build_identity: dict[str, Any] | None = None,
    ) -> None:
        self.identity = identity
        self.workspace = Path(workspace).expanduser().resolve()
        self.mode = str(mode or "agent")
        self.services = services
        if root is not None:
            self.root = Path(root)
        elif os.getenv("CRUSORAI_EVIDENCE_DIR", "").strip():
            self.root = _evidence_root()
        else:
            journal_path = getattr(getattr(services, "journal", None), "path", None)
            self.root = (
                Path(journal_path).parent / "evidence" / "turns"
                if journal_path is not None
                else _evidence_root()
            )
        self.evidence_id = f"evidence-{identity.turn_id}"
        session_component = _safe_component(identity.session_id)
        turn_component = _safe_component(identity.turn_id)
        self.manifest_path = self.root / session_component / f"{turn_component}.json"
        self.hash_path = self.manifest_path.with_suffix(".json.sha256")
        self.artifact_dir = self.manifest_path.parent / f"{turn_component}.artifacts"
        workspace_trace = (
            self.workspace
            / "diagnostics"
            / "traces"
            / f"{self.identity.session_id}.jsonl"
        )
        configured_home = os.getenv("CRUSORAI_HOME", "").strip()
        runtime_home = (
            Path(configured_home).expanduser()
            if configured_home
            else Path.home() / ".crusorai"
        )
        system_trace = runtime_home / "traces" / f"{self.identity.session_id}.jsonl"
        self._trace_sources = (workspace_trace, system_trace)
        self._trace_start_offsets = {
            str(path): _safe_file_size(path) for path in self._trace_sources
        }
        self._report_source = (
            self.workspace
            / "diagnostics"
            / f"PERFORMANCE_REPORT_{self.identity.session_id}.md"
        )
        self._report_start_version = _safe_file_version(self._report_source)
        self._build_identity = build_identity
        # Private text is retained only in memory long enough to remove exact
        # copies from diagnostics artifacts. It is never serialized directly.
        self._private_request_text = ""
        self._private_terminal_text = ""
        self._manifest: dict[str, Any] = {}
        self._manifest_sha256: str | None = None
        self._terminal_receipt: EvidenceReceipt | None = None
        self._reserved_terminal_status: str | None = None
        self._start_seq: int | None = None
        self._journal_errors: list[str] = []
        self._lock = threading.RLock()

    @classmethod
    def begin(
        cls,
        *,
        identity: TurnIdentity,
        workspace: str,
        prompt: str,
        mode: str,
        services: Any | None = None,
        root: str | Path | None = None,
        build_identity: dict[str, Any] | None = None,
    ) -> TurnEvidenceRecorder:
        if services is None:
            from src.runtime.factory import get_runtime_services

            services = get_runtime_services()
        recorder = cls(
            identity=identity,
            workspace=workspace,
            mode=mode,
            services=services,
            root=root,
            build_identity=build_identity,
        )
        recorder._begin(prompt)
        return recorder

    @staticmethod
    def _verified_manifest(path: Path) -> dict[str, Any] | None:
        sidecar = path.with_suffix(".json.sha256")
        try:
            encoded = path.read_bytes()
            expected = sidecar.read_text(encoding="ascii").split()[0]
            if hashlib.sha256(encoded).hexdigest() != expected:
                return None
            value = json.loads(encoded)
            return value if isinstance(value, dict) else None
        except (OSError, UnicodeError, ValueError, IndexError):
            return None

    def _recover_interrupted_manifests(self) -> list[dict[str, Any]]:
        """Close in-progress manifests left by a previous runtime process."""
        session_dir = self.manifest_path.parent
        if not session_dir.is_dir():
            return []
        recovered: list[dict[str, Any]] = []
        for path in sorted(session_dir.glob("*.json")):
            if path == self.manifest_path:
                continue
            prior = self._verified_manifest(path)
            if prior is None:
                recovered.append(
                    {
                        "manifest": str(path),
                        "status": "integrity_check_failed",
                    }
                )
                continue
            lifecycle = prior.get("lifecycle") or {}
            runtime = prior.get("runtime") or {}
            identity = prior.get("identity") or {}
            if lifecycle.get("status") != "in_progress":
                continue
            if runtime.get("runtime_instance_id") == _RUNTIME_INSTANCE_ID:
                continue
            session_id = str(identity.get("session_id") or "")
            turn_id = str(identity.get("turn_id") or "")
            workspace_id = str(identity.get("workspace_id") or "") or None
            if (
                session_id != self.identity.session_id
                or not turn_id
                or _safe_component(turn_id) != path.stem
            ):
                recovered.append(
                    {
                        "manifest": str(path),
                        "status": "identity_check_failed",
                    }
                )
                continue
            try:
                events = self.services.journal.list_turn_events(
                    session_id, turn_id
                )
                terminal_events = [
                    event
                    for event in events
                    if str(event.get("type") or "").removeprefix("turn.")
                    in _TERMINAL_STATUSES
                ]
                if len(terminal_events) > 1:
                    recovered.append(
                        {
                            "turn_id": turn_id,
                            "status": "multiple_terminal_events",
                        }
                    )
                    continue
                had_terminal = bool(terminal_events)
                if terminal_events:
                    terminal_event = terminal_events[0]
                    terminal_status = str(terminal_event["type"]).removeprefix(
                        "turn."
                    )
                    terminal_seq = int(terminal_event["seq"])
                    terminal_timestamp = float(terminal_event["timestamp"])
                    terminal_payload = dict(terminal_event.get("payload") or {})
                else:
                    terminal_status = "interrupted"
                    terminal_payload = {
                        "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
                        "evidence_id": prior.get("evidence_id"),
                        "identity": identity,
                        "status": terminal_status,
                        "completed": False,
                        "cancelled": False,
                        "duration_s": None,
                        "message": _private_text_receipt(""),
                        "error": None,
                        "reason": "runtime_restart_before_terminal",
                        "recovered_by_runtime_instance_id": _RUNTIME_INSTANCE_ID,
                        "artifacts": {
                            "trace": {"available": False, "sha256": None},
                            "report": {"available": False, "sha256": None},
                        },
                    }
                    row = self.services.journal.append(
                        "turn.interrupted",
                        terminal_payload,
                        session_id=session_id,
                        turn_id=turn_id,
                        workspace_id=workspace_id,
                    )
                    terminal_seq = int(row["seq"])
                    terminal_timestamp = float(row["timestamp"])
                    if row.get("existing_terminal"):
                        terminal_status = str(row.get("type") or "").removeprefix(
                            "turn."
                        )
                        terminal_payload = dict(row.get("payload") or {})
                artifact_dir = path.parent / f"{path.stem}.artifacts"
                trace_snapshot = artifact_dir / "trace.jsonl"
                report_snapshot = artifact_dir / "performance-report.md"
                if had_terminal:
                    trace_artifact = self._trace_details(trace_snapshot)
                    report_artifact = self._report_details(report_snapshot)
                    trace_artifact.update(
                        {
                            "immutable_copy": True,
                            "privacy_filtered": True,
                            "relative_path": trace_snapshot.relative_to(
                                path.parent
                            ).as_posix(),
                        }
                    )
                    report_artifact.update(
                        {
                            "immutable_copy": True,
                            "privacy_filtered": True,
                            "relative_path": report_snapshot.relative_to(
                                path.parent
                            ).as_posix(),
                        }
                    )
                else:
                    trace_artifact = {
                        "available": False,
                        "path": str(trace_snapshot),
                        "immutable_copy": True,
                        "orphaned_snapshot_present": trace_snapshot.is_file(),
                    }
                    report_artifact = {
                        "available": False,
                        "path": str(report_snapshot),
                        "immutable_copy": True,
                        "orphaned_snapshot_present": report_snapshot.is_file(),
                    }
                recovered_artifacts = {
                    "trace": trace_artifact,
                    "report": report_artifact,
                    "screenshots": list(
                        (prior.get("artifacts") or {}).get("screenshots") or []
                    ),
                }
                journal = self._summarize_turn_journal(
                    session_id=session_id,
                    turn_id=turn_id,
                    start_seq=(prior.get("journal") or {}).get("start_seq"),
                    terminal_seq=terminal_seq,
                    errors=[],
                )
                ended_at = terminal_timestamp
                recovered_at = time.time()
                started_epoch = (prior.get("lifecycle") or {}).get(
                    "started_at_epoch"
                )
                duration = (
                    round(max(0.0, ended_at - float(started_epoch)), 3)
                    if isinstance(started_epoch, (int, float))
                    else None
                )
                prior["lifecycle"] = {
                    "status": terminal_status,
                    "started_at": lifecycle.get("started_at"),
                    "started_at_epoch": started_epoch,
                    "ended_at": _utc_iso(ended_at),
                    "duration_s": duration,
                    "completed": bool(terminal_payload.get("completed")),
                    "cancelled": bool(terminal_payload.get("cancelled")),
                    "reason": terminal_payload.get("reason"),
                }
                prior["terminal"] = terminal_payload
                prior["journal"] = journal
                prior["artifacts"] = recovered_artifacts
                prior["capture_status"] = "degraded"
                prior["recovery"] = {
                    "status": "recovered_after_restart",
                    "runtime_instance_id": _RUNTIME_INSTANCE_ID,
                    "recovered_at": _utc_iso(recovered_at),
                }
                coverage = dict(prior.get("coverage") or {})
                missing = list(coverage.get("missing") or [])
                missing = [item for item in missing if item != "terminal_event"]
                if "process_interruption" not in missing:
                    missing.append("process_interruption")
                for artifact_name in ("trace", "report"):
                    if (
                        not recovered_artifacts[artifact_name].get("available")
                        and artifact_name not in missing
                    ):
                        missing.append(artifact_name)
                coverage["missing"] = missing
                prior["coverage"] = coverage
                prior["updated_at"] = _utc_iso()
                encoded = (
                    json.dumps(
                        prior,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8")
                digest = hashlib.sha256(encoded).hexdigest()
                _write_atomic(path, encoded)
                _write_atomic(
                    path.with_suffix(".json.sha256"),
                    f"{digest}  {path.name}\n".encode("ascii"),
                )
                recovered.append(
                    {
                        "turn_id": turn_id,
                        "status": terminal_status,
                        "terminal_seq": terminal_seq,
                        "manifest_sha256": digest,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                recovered.append(
                    {
                        "turn_id": turn_id,
                        "status": "recovery_failed",
                        "error": str(
                            sanitize_for_persistence(
                                f"{type(exc).__name__}: {exc}"
                            )
                        ),
                    }
                )
        return recovered

    def _begin(self, prompt: str) -> None:
        with self._lock:
            self._private_request_text = str(prompt or "")
            recovered_turns = self._recover_interrupted_manifests()
            try:
                build = self._build_identity or collect_build_identity()
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                build = {
                    "schema_version": 1,
                    "status": "unavailable",
                    "reasons": [f"collector_failed:{type(exc).__name__}"],
                }
            self._manifest = {
                "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
                "evidence_id": self.evidence_id,
                "evidence_scope": {
                    "kind": "agent_core_runtime",
                    "desktop_capture": False,
                    "synthetic_desktop_evidence": False,
                },
                "capture_status": "in_progress",
                "updated_at": _utc_iso(),
                "identity": self.identity.event_fields(),
                "lifecycle": {
                    "status": "in_progress",
                    "started_at": _utc_iso(self.identity.created_at),
                    "started_at_epoch": self.identity.created_at,
                    "ended_at": None,
                    "duration_s": None,
                    "completed": False,
                    "cancelled": False,
                    "reason": None,
                },
                "request": {
                    "mode": self.mode,
                    **_text_receipt(prompt),
                    "body_persisted": False,
                },
                "workspace": {
                    "path": str(self.workspace),
                    "workspace_id": self.identity.workspace_id,
                    "exists": self.workspace.exists(),
                    "is_directory": self.workspace.is_dir(),
                },
                "runtime": {
                    "runtime_instance_id": _RUNTIME_INSTANCE_ID,
                    "process_id": os.getpid(),
                    "process_started_at": _utc_iso(_PROCESS_STARTED_AT),
                    "python_executable": sys.executable,
                },
                "continuity": {
                    "recovered_interrupted_turns": recovered_turns,
                },
                "build": build,
                "journal": {
                    "start_seq": None,
                    "terminal_seq": None,
                    "event_count": 0,
                    "first_seq": None,
                    "last_seq": None,
                    "event_types": {},
                    "tool_receipts": [],
                    "unmatched_intents": [],
                    "orphan_results": [],
                    "verification_event_count": 0,
                    "verification_transitions": [],
                    "terminal_event_count": 0,
                    "terminal_event": None,
                    "database_path": str(
                        getattr(self.services.journal, "path", "") or ""
                    ),
                    "chain": None,
                    "errors": [],
                },
                "artifacts": {
                    "trace": None,
                    "report": None,
                    "screenshots": [],
                },
                "terminal": None,
                "coverage": {
                    "missing": ["terminal_event"],
                    "tool_pairs_complete": None,
                    "trace_finalized": None,
                    "screenshot_count": 0,
                },
                "integrity": {
                    "algorithm": "sha256",
                    "sidecar": str(self.hash_path),
                },
            }
            try:
                row = self.services.journal.append(
                    "turn.started",
                    {
                        "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
                        "evidence_id": self.evidence_id,
                        "identity": self.identity.event_fields(),
                        "mode": self.mode,
                        "request": _text_receipt(prompt),
                        "runtime_instance_id": _RUNTIME_INSTANCE_ID,
                        "build": _build_binding(build),
                        "workspace": str(self.workspace),
                    },
                    session_id=self.identity.session_id,
                    turn_id=self.identity.turn_id,
                    workspace_id=self.identity.workspace_id,
                )
                self._start_seq = int(row["seq"])
                self._manifest["journal"]["start_seq"] = self._start_seq
                if row.get("existing_event") and (
                    (row.get("payload") or {}).get("request")
                    != _text_receipt(prompt)
                ):
                    self._record_journal_error(
                        "turn.started",
                        ValueError("existing start request digest mismatch"),
                    )
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                self._record_journal_error("turn.started", exc)
            try:
                self._manifest["journal"] = self._summarize_journal()
                start_missing = ["terminal_event"]
                if not build_identity_is_complete(build):
                    start_missing.append("build_identity")
                if (
                    self._manifest["journal"].get("event_types") or {}
                ).get("turn.started") != 1:
                    start_missing.append("start_event")
                if (
                    (self._manifest["journal"].get("chain") or {}).get(
                        "valid"
                    )
                    is not True
                ):
                    start_missing.append("journal_chain")
                self._manifest["coverage"]["missing"] = start_missing
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                self._record_journal_error("journal.start_summary", exc)
            try:
                self._write_manifest()
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                self._record_journal_error("manifest.in_progress", exc)

    def _record_journal_error(self, operation: str, exc: Exception) -> None:
        safe = sanitize_for_persistence(
            f"{operation}: {type(exc).__name__}: {exc}"
        )
        self._journal_errors.append(str(safe))
        if self._manifest:
            self._manifest["journal"]["errors"] = list(self._journal_errors)

    def _write_manifest(self) -> str:
        self._manifest["updated_at"] = _utc_iso()
        encoded = (
            json.dumps(
                self._manifest,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        _write_atomic(self.manifest_path, encoded)
        _write_atomic(
            self.hash_path,
            f"{digest}  {self.manifest_path.name}\n".encode("ascii"),
        )
        self._manifest_sha256 = digest
        return digest

    @staticmethod
    def _trace_details(path: Path) -> dict[str, Any]:
        details: dict[str, Any] = {
            "available": path.is_file(),
            "path": str(path),
        }
        if not path.is_file():
            return details
        details.update(
            {
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
        rows: list[dict[str, Any]] = []
        parse_errors = 0
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict) and "__unparsed_trace_row__" not in value:
                    rows.append(value)
                else:
                    parse_errors += 1
        except (OSError, UnicodeError, json.JSONDecodeError):
            parse_errors += 1
        indices = [
            int(row["step_index"])
            for row in rows
            if isinstance(row.get("step_index"), int)
        ]
        final_rows = [
            row
            for row in rows
            if str(row.get("node_name") or "").lower() == "finalize"
        ]
        details.update(
            {
                "row_count": len(rows),
                "parse_errors": parse_errors,
                "max_step_index": max(indices) if indices else None,
                "finalization_count": len(final_rows),
                "last_node": str(rows[-1].get("node_name") or "") if rows else None,
                "last_final_verdict": next(
                    (
                        str(item).split("FINAL_VERDICT:", 1)[1].strip()
                        for item in reversed(final_rows[-1].get("diagnostics") or [])
                        if "FINAL_VERDICT:" in str(item)
                    ),
                    None,
                )
                if final_rows
                else None,
            }
        )
        return details

    @staticmethod
    def _report_details(path: Path) -> dict[str, Any]:
        details: dict[str, Any] = {
            "available": path.is_file(),
            "path": str(path),
        }
        if not path.is_file():
            return details
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            text = ""
        fields = {
            match.group("field").strip().lower().replace(" ", "_"): (
                match.group("value").strip().strip("`")
            )
            for match in _REPORT_FIELD_RE.finditer(text)
        }
        details.update(
            {
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "fields": fields,
            }
        )
        return details

    def _snapshot_trace(self) -> dict[str, Any]:
        existing = [path for path in self._trace_sources if path.is_file()]
        growing = [
            path
            for path in existing
            if _safe_file_size(path)
            > self._trace_start_offsets.get(str(path), 0)
        ]
        source = (growing or existing or [self._trace_sources[0]])[0]
        start_offset = self._trace_start_offsets.get(str(source), 0)
        destination = self.artifact_dir / "trace.jsonl"
        common = {
            "path": str(destination),
            "relative_path": destination.relative_to(
                self.manifest_path.parent
            ).as_posix(),
            "source_path": str(source),
            "source_start_offset": start_offset,
            "immutable_copy": True,
            "privacy_filtered": True,
        }
        if not source.is_file():
            return {"available": False, **common}
        current_size = _safe_file_size(source)
        if current_size < start_offset:
            return {
                "available": False,
                **common,
                "source_end_offset": current_size,
                "capture_error": "source_trace_truncated_during_turn",
            }
        slice_size = current_size - start_offset
        if slice_size > _MAX_TRACE_SNAPSHOT_BYTES:
            return {
                "available": False,
                **common,
                "source_end_offset": current_size,
                "capture_error": "trace_snapshot_size_limit_exceeded",
                "source_slice_size_bytes": slice_size,
                "snapshot_size_limit_bytes": _MAX_TRACE_SNAPSHOT_BYTES,
            }
        try:
            with source.open("rb") as handle:
                handle.seek(start_offset)
                source_bytes = handle.read(slice_size)
            if len(source_bytes) != slice_size:
                raise OSError("source truncated while snapshotting")
            filtered = _privacy_filter_trace_bytes(
                source_bytes,
                private_texts=(
                    self._private_request_text,
                    self._private_terminal_text,
                ),
            )
            _write_atomic(destination, filtered)
            details = self._trace_details(destination)
            details.update(
                {
                    **common,
                    "source_end_offset": current_size,
                    "source_slice_size_bytes": slice_size,
                }
            )
            return details
        except (OSError, ValueError, TypeError) as exc:
            return {
                "available": False,
                **common,
                "source_end_offset": current_size,
                "capture_error": str(
                    sanitize_for_persistence(
                        f"{type(exc).__name__}: {exc}"
                    )
                ),
            }

    def _snapshot_report(self) -> dict[str, Any]:
        source = self._report_source
        destination = self.artifact_dir / "performance-report.md"
        common = {
            "path": str(destination),
            "relative_path": destination.relative_to(
                self.manifest_path.parent
            ).as_posix(),
            "source_path": str(source),
            "immutable_copy": True,
            "privacy_filtered": True,
        }
        if not source.is_file():
            return {"available": False, **common}
        current_version = _safe_file_version(source)
        if (
            self._report_start_version is not None
            and current_version == self._report_start_version
        ):
            return {
                "available": False,
                **common,
                "capture_error": "report_not_updated_during_turn",
            }
        report_end_offset = _safe_file_size(source)
        if report_end_offset > _MAX_REPORT_SNAPSHOT_BYTES:
            return {
                "available": False,
                **common,
                "source_start_offset": 0,
                "source_end_offset": report_end_offset,
                "capture_error": "report_snapshot_size_limit_exceeded",
                "snapshot_size_limit_bytes": _MAX_REPORT_SNAPSHOT_BYTES,
            }
        try:
            with source.open("rb") as handle:
                source_bytes = handle.read(report_end_offset)
            if len(source_bytes) != report_end_offset:
                raise OSError("source truncated while snapshotting")
            filtered = _privacy_filter_report_bytes(
                source_bytes,
                private_texts=(
                    self._private_request_text,
                    self._private_terminal_text,
                ),
            )
            _write_atomic(destination, filtered)
            details = self._report_details(destination)
            details.update(
                {
                    **common,
                    "source_start_offset": 0,
                    "source_end_offset": report_end_offset,
                    "source_size_bytes": report_end_offset,
                }
            )
            return details
        except (OSError, ValueError, TypeError) as exc:
            return {
                "available": False,
                **common,
                "source_start_offset": 0,
                "source_end_offset": report_end_offset,
                "capture_error": str(
                    sanitize_for_persistence(
                        f"{type(exc).__name__}: {exc}"
                    )
                ),
            }

    def _collect_artifacts(self) -> dict[str, Any]:
        return {
            "trace": self._snapshot_trace(),
            "report": self._snapshot_report(),
            "screenshots": list(
                (self._manifest.get("artifacts") or {}).get("screenshots") or []
            ),
        }

    @staticmethod
    def _tool_receipts(events: list[dict[str, Any]]) -> tuple[
        list[dict[str, Any]], list[str], list[str]
    ]:
        intents: dict[str, dict[str, Any]] = {}
        results: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        anonymous = 0
        for event in events:
            event_type = str(event.get("type") or "")
            if event_type not in {"tool.intent", "tool.result"}:
                continue
            call_id = str(event.get("tool_call_id") or "")
            if not call_id:
                anonymous += 1
                call_id = f"<missing-tool-call-id:{anonymous}>"
            if call_id not in order:
                order.append(call_id)
            if event_type == "tool.intent":
                intents[call_id] = event
            else:
                results[call_id] = event
        receipts: list[dict[str, Any]] = []
        for call_id in order:
            intent = intents.get(call_id)
            result = results.get(call_id)
            intent_payload = dict((intent or {}).get("payload") or {})
            result_payload = dict((result or {}).get("payload") or {})
            content = str(result_payload.get("content") or "")
            receipts.append(
                {
                    "tool_call_id": call_id,
                    "tool_name": str(
                        intent_payload.get("tool_name")
                        or result_payload.get("tool_name")
                        or ""
                    ),
                    "intent_seq": intent.get("seq") if intent else None,
                    "result_seq": result.get("seq") if result else None,
                    "paired": bool(intent and result),
                    "args": intent_payload.get("args") if intent else None,
                    "result_status": result_payload.get("status") if result else None,
                    "result": {
                        **_text_receipt(content),
                        "body_persisted_in_manifest": False,
                    }
                    if result
                    else None,
                }
            )
        unmatched = sorted(set(intents) - set(results))
        orphaned = sorted(set(results) - set(intents))
        return receipts, unmatched, orphaned

    def _summarize_turn_journal(
        self,
        *,
        session_id: str,
        turn_id: str,
        start_seq: int | None,
        terminal_seq: int | None,
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        events = self.services.journal.list_turn_events(session_id, turn_id)
        receipts, unmatched, orphaned = self._tool_receipts(events)
        event_types = Counter(str(event.get("type") or "") for event in events)
        terminal_events = [
            event
            for event in events
            if str(event.get("type") or "").removeprefix("turn.")
            in _TERMINAL_STATUSES
        ]
        verification_events = [
            event for event in events if event.get("type") == "verification.updated"
        ]
        chain = self.services.journal.verify_chain(session_id)
        return {
            "start_seq": start_seq,
            "terminal_seq": terminal_seq,
            "event_count": len(events),
            "first_seq": events[0]["seq"] if events else None,
            "last_seq": events[-1]["seq"] if events else None,
            "event_types": dict(sorted(event_types.items())),
            "tool_receipts": receipts,
            "unmatched_intents": unmatched,
            "orphan_results": orphaned,
            "verification_event_count": len(verification_events),
            "verification_transitions": [
                {
                    "seq": event["seq"],
                    "event_id": event["event_id"],
                    "event_hash": event["event_hash"],
                    "schema_version": (event.get("payload") or {}).get(
                        "schema_version"
                    ),
                    "status": (event.get("payload") or {}).get("status"),
                    "kind": (event.get("payload") or {}).get("kind"),
                    "scope": (event.get("payload") or {}).get("scope"),
                    "evidence_kind": (event.get("payload") or {}).get(
                        "evidence_kind"
                    ),
                }
                for event in verification_events
            ],
            "terminal_event_count": len(terminal_events),
            "terminal_event": (
                {
                    "seq": terminal_events[0]["seq"],
                    "event_id": terminal_events[0]["event_id"],
                    "type": terminal_events[0]["type"],
                    "event_hash": terminal_events[0]["event_hash"],
                }
                if len(terminal_events) == 1
                else None
            ),
            "database_path": str(
                getattr(self.services.journal, "path", "") or ""
            ),
            "chain": chain,
            "errors": list(errors or []),
        }

    def _summarize_journal(self) -> dict[str, Any]:
        return self._summarize_turn_journal(
            session_id=self.identity.session_id,
            turn_id=self.identity.turn_id,
            start_seq=self._start_seq,
            terminal_seq=self._manifest["journal"].get("terminal_seq"),
            errors=self._journal_errors,
        )

    def reserve_terminal(
        self,
        status: str,
        *,
        on_reserved: Callable[[], None] | None = None,
    ) -> bool:
        """Atomically reserve terminal authority (used by the watchdog).

        A normal completion that won before this call remains authoritative.
        Once the watchdog wins, later graph completion cannot relabel the same
        turn as completed.
        """
        normalized = str(status or "").strip().lower()
        if normalized not in _TERMINAL_STATUSES:
            return False
        with self._lock:
            if self._terminal_receipt is not None:
                return False
            if self._reserved_terminal_status is None:
                self._reserved_terminal_status = normalized
                if on_reserved is not None:
                    on_reserved()
                return True
            return self._reserved_terminal_status == normalized

    def finalize(
        self,
        *,
        status: str,
        completed: bool = False,
        cancelled: bool = False,
        message: str = "",
        error: str = "",
        reason: str = "",
    ) -> EvidenceReceipt:
        """Persist exactly one terminal lifecycle event and final manifest."""
        normalized = str(status or "failed").strip().lower()
        if normalized not in _TERMINAL_STATUSES:
            normalized = "failed"
        with self._lock:
            if self._terminal_receipt is not None:
                return self._terminal_receipt
            if (
                self._reserved_terminal_status is not None
                and normalized != self._reserved_terminal_status
            ):
                normalized = self._reserved_terminal_status
                completed = False
                cancelled = normalized == "cancelled"
                reason = reason or "terminal_authority_reserved"
            ended_at = time.time()
            artifacts = self._collect_artifacts()
            terminal_payload = {
                "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
                "evidence_id": self.evidence_id,
                "identity": self.identity.event_fields(),
                "status": normalized,
                "completed": bool(completed),
                "cancelled": bool(cancelled),
                "duration_s": round(
                    max(0.0, ended_at - self.identity.created_at), 3
                ),
                "message": _private_text_receipt(message),
                "error": _private_text_receipt(error) if error else None,
                "reason": sanitize_for_persistence(reason) if reason else None,
                "artifacts": {
                    name: {
                        "available": bool(details and details.get("available")),
                        "sha256": details.get("sha256") if details else None,
                    }
                    for name, details in artifacts.items()
                    if name in {"trace", "report"}
                },
            }
            terminal_seq: int | None = None
            try:
                row = self.services.journal.append(
                    f"turn.{normalized}",
                    terminal_payload,
                    session_id=self.identity.session_id,
                    turn_id=self.identity.turn_id,
                    workspace_id=self.identity.workspace_id,
                )
                terminal_seq = int(row["seq"])
                actual_type = str(row.get("type") or "")
                if row.get("existing_terminal") and actual_type.startswith(
                    "turn."
                ):
                    # Another process/recovery owner won the terminal race.
                    # Adopt the durable first writer instead of manufacturing
                    # a contradictory local lifecycle label.
                    normalized = actual_type.removeprefix("turn.")
                    terminal_payload = dict(row.get("payload") or {})
                    ended_at = float(row.get("timestamp") or ended_at)
                    completed = bool(terminal_payload.get("completed"))
                    cancelled = bool(terminal_payload.get("cancelled"))
                    reason = str(terminal_payload.get("reason") or reason)
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                self._record_journal_error(f"turn.{normalized}", exc)
            self._manifest["journal"]["terminal_seq"] = terminal_seq
            self._manifest["lifecycle"] = {
                "status": normalized,
                "started_at": _utc_iso(self.identity.created_at),
                "started_at_epoch": self.identity.created_at,
                "ended_at": _utc_iso(ended_at),
                "duration_s": round(
                    max(0.0, ended_at - self.identity.created_at), 3
                ),
                "completed": bool(completed),
                "cancelled": bool(cancelled),
                "reason": sanitize_for_persistence(reason) if reason else None,
            }
            self._manifest["terminal"] = terminal_payload
            self._manifest["artifacts"] = artifacts
            try:
                journal = self._summarize_journal()
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                self._record_journal_error("journal.summary", exc)
                journal = dict(self._manifest["journal"])
                journal["errors"] = list(self._journal_errors)
                journal["chain"] = None
            self._manifest["journal"] = journal

            trace = artifacts.get("trace") or {}
            report = artifacts.get("report") or {}
            chain = journal.get("chain") or {}
            missing: list[str] = []
            if (journal.get("event_types") or {}).get("turn.started") != 1:
                missing.append("start_event")
            if terminal_seq is None or journal.get("terminal_event_count") != 1:
                missing.append("terminal_event")
            if chain.get("valid") is not True:
                missing.append("journal_chain")
            if journal.get("unmatched_intents"):
                missing.append("tool_results")
            if journal.get("orphan_results"):
                missing.append("tool_intents")
            if not trace.get("available"):
                missing.append("trace")
            if not report.get("available"):
                missing.append("report")
            report_verification = str(
                (report.get("fields") or {}).get("verification_status") or ""
            ).strip().lower()
            if (
                report_verification
                not in {"", "not_applicable", "not applicable", "unavailable"}
                and journal.get("verification_event_count") == 0
            ):
                missing.append("verification_event")
            if trace.get("available"):
                if int(trace.get("row_count") or 0) < 1:
                    missing.append("trace_empty")
                if int(trace.get("parse_errors") or 0) > 0:
                    missing.append("trace_parse_errors")
            report_fields = report.get("fields") or {}
            if report.get("available"):
                required_report_fields = {
                    "task_verdict",
                    "verification_status",
                    "current-turn_executed_tool_records",
                }
                if required_report_fields - set(report_fields):
                    missing.append("report_fields")
                try:
                    report_tool_count = int(
                        str(
                            report_fields.get(
                                "current-turn_executed_tool_records"
                            )
                        ).replace(",", "")
                    )
                except (TypeError, ValueError):
                    report_tool_count = None
                actual_tool_count = sum(
                    receipt.get("result_seq") is not None
                    for receipt in journal.get("tool_receipts") or []
                )
                top_level_actual = sum(
                    receipt.get("result_seq") is not None
                    and not str(receipt.get("tool_call_id") or "").startswith("ptc-")
                    for receipt in journal.get("tool_receipts") or []
                )
                if report_tool_count is None:
                    missing.append("report_tool_count")
                elif report_tool_count not in (actual_tool_count, top_level_actual):
                    missing.append("report_tool_count_mismatch")
            expected_completed = normalized == "completed"
            expected_cancelled = normalized == "cancelled"
            if (
                bool(completed) != expected_completed
                or bool(cancelled) != expected_cancelled
            ):
                missing.append("lifecycle_flags")
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
            if completed:
                if trace.get("last_node") != "finalize":
                    missing.append("trace_finalization")
                if trace_verdict not in successful_verdicts:
                    missing.append("trace_verdict")
                if report_verdict not in successful_verdicts:
                    missing.append("report_verdict")
            else:
                if trace_verdict in successful_verdicts:
                    missing.append("trace_lifecycle_conflict")
                if report_verdict in successful_verdicts:
                    missing.append("report_lifecycle_conflict")
            recovery_failures = [
                item
                for item in (
                    (self._manifest.get("continuity") or {}).get(
                        "recovered_interrupted_turns"
                    )
                    or []
                )
                if item.get("status")
                in {
                    "integrity_check_failed",
                    "identity_check_failed",
                    "multiple_terminal_events",
                    "recovery_failed",
                }
            ]
            if recovery_failures:
                missing.append("continuity_recovery")
            build = self._manifest.get("build") or {}
            if not build_identity_is_complete(build):
                missing.append("build_identity")
            self._manifest["coverage"] = {
                "missing": missing,
                "tool_pairs_complete": not bool(
                    journal.get("unmatched_intents")
                    or journal.get("orphan_results")
                ),
                "trace_finalized": trace.get("last_node") == "finalize",
                "screenshot_count": len(artifacts.get("screenshots") or []),
            }
            self._manifest["capture_status"] = (
                "complete" if not missing and not self._journal_errors else "degraded"
            )

            try:
                digest = self._write_manifest()
                receipt_status = (
                    "persisted"
                    if self._manifest["capture_status"] == "complete"
                    else "degraded"
                )
                receipt_error = (
                    "; ".join(self._journal_errors) or None
                )
            except Exception as exc:  # noqa: BLE001 - capture must fail open
                digest = None
                receipt_status = "unavailable"
                receipt_error = str(
                    sanitize_for_persistence(
                        f"manifest.final: {type(exc).__name__}: {exc}"
                    )
                )
            self._terminal_receipt = EvidenceReceipt(
                status=receipt_status,
                evidence_id=self.evidence_id,
                lifecycle_status=normalized,
                manifest_path=(
                    str(self.manifest_path) if digest is not None else None
                ),
                manifest_sha256=digest,
                journal_terminal_seq=terminal_seq,
                journal_chain_valid=chain.get("valid"),
                missing=tuple(missing),
                error=receipt_error,
            )
            return self._terminal_receipt

    def interrupt_if_open(self, reason: str) -> EvidenceReceipt:
        return self.finalize(
            status="interrupted",
            completed=False,
            cancelled=False,
            reason=reason,
        )

    def current_receipt(self) -> EvidenceReceipt:
        if self._terminal_receipt is not None:
            return self._terminal_receipt
        missing = tuple(
            (self._manifest.get("coverage") or {}).get("missing")
            or ["terminal_event"]
        )
        chain_valid = (
            ((self._manifest.get("journal") or {}).get("chain") or {}).get(
                "valid"
            )
        )
        degraded = bool(
            self._journal_errors
            or any(item != "terminal_event" for item in missing)
        )
        return EvidenceReceipt(
            status=(
                "unavailable"
                if not self._manifest_sha256
                else ("degraded" if degraded else "persisted")
            ),
            evidence_id=self.evidence_id,
            lifecycle_status="in_progress",
            manifest_path=(
                str(self.manifest_path) if self._manifest_sha256 else None
            ),
            manifest_sha256=self._manifest_sha256,
            journal_terminal_seq=None,
            journal_chain_valid=chain_valid,
            missing=missing,
            error=("; ".join(self._journal_errors) or None),
        )

    @property
    def receipt(self) -> EvidenceReceipt | None:
        return self._terminal_receipt

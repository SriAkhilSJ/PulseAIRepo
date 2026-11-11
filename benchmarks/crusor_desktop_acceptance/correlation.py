"""Cross-layer correlation for desktop acceptance evidence.

Every layer of the desktop stack (Electron process, worker, Python bridge,
renderer, orchestrator task, provider dispatch, FinOps reservation, mutation
receipt) writes records carrying the SAME immutable run id plus the identity
fields it actually knows about.

Correlation is deliberately strict:

* records are joined on ``(run_id, session_id, turn_id)`` — never on a task
  name, a workspace path, or a timestamp window;
* a record whose ``run_id`` differs is a DIFFERENT execution and is rejected;
* a provider/financial/mutation record without a matching ``ui.submit`` turn
  record is classified ``disconnected`` — it may not borrow credibility from a
  turn that happens to share a task id;
* evidence classification per criterion is ``VERIFIED`` /
  ``PARTIALLY VERIFIED`` / ``NOT VERIFIED`` derived from record presence, not
  from prose.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

LAYERS: tuple[str, ...] = (
    "acceptance",
    "electron",
    "worker",
    "bridge",
    "renderer",
    "orchestrator",
    "provider",
    "finops",
    "mutation",
    "verification",
)

#: Correlation keys that identify a single desktop turn. ``task_id`` and
#: ``workspace`` are deliberately NOT join keys.
JOIN_KEYS: tuple[str, ...] = ("run_id", "session_id", "turn_id")

IMMUTABLE_RUN_KEYS = frozenset({"run_id", "created_at", "phase"})


class CorrelationError(RuntimeError):
    """Raised when evidence cannot be attributed to one execution."""


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() % 1 * 1000):03d}Z"


def workspace_id(path: str | os.PathLike[str] | None) -> str:
    """Stable, non-reversible workspace fingerprint (absolute, normalised)."""
    if not path:
        return ""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        resolved = Path(str(path))
    normalised = str(resolved).replace("\\", "/").rstrip("/").lower()
    return "ws_" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class EvidenceRecord:
    """One immutable observation written by exactly one layer."""

    layer: str
    kind: str
    run_id: str
    timestamp: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    workspace_id: str = ""
    task_id: str = ""
    provider_request_id: str = ""
    reservation_id: str = ""
    mutation_id: str = ""
    pid: int | None = None

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise CorrelationError(f"unknown evidence layer {self.layer!r}")
        if not self.kind:
            raise CorrelationError("evidence record requires a kind")
        if not self.run_id:
            raise CorrelationError("evidence record requires a run_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "kind": self.kind,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "provider_request_id": self.provider_request_id,
            "reservation_id": self.reservation_id,
            "mutation_id": self.mutation_id,
            "pid": self.pid,
            "payload": dict(self.payload),
        }


class RunContext:
    """One immutable acceptance run id plus its append-only evidence ledger.

    The run id is minted once, frozen into ``run.json`` and echoed by every
    layer. Records are appended as JSON Lines; nothing is rewritten, so the
    ledger can be re-read and re-verified later without trusting the process
    that wrote it.
    """

    def __init__(
        self,
        evidence_dir: str | os.PathLike[str],
        *,
        phase: str = "P0.6.4",
        run_id: str | None = None,
        workspace: str | None = None,
    ) -> None:
        self.evidence_dir = Path(evidence_dir).resolve()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.phase = phase
        self.run_id = run_id or f"{phase.lower().replace('.', '_')}_{time.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.workspace = workspace
        self.workspace_id = workspace_id(workspace)
        self.created_at = utc_now_iso()
        self._lock = threading.Lock()
        self._ledger_path = self.evidence_dir / "evidence.jsonl"
        self._records: list[EvidenceRecord] = []
        self._write_run_manifest()

    # -- manifest ----------------------------------------------------------

    def _write_run_manifest(self) -> None:
        path = self.evidence_dir / "run.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("run_id") != self.run_id:
                raise CorrelationError(
                    f"evidence dir already holds run {existing.get('run_id')!r}; "
                    f"refusing to mix run {self.run_id!r} into it"
                )
            return
        manifest = {
            "run_id": self.run_id,
            "phase": self.phase,
            "created_at": self.created_at,
            "workspace_id": self.workspace_id,
            "immutable_keys": sorted(IMMUTABLE_RUN_KEYS),
        }
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # -- recording ---------------------------------------------------------

    def record(
        self,
        layer: str,
        kind: str,
        payload: Mapping[str, Any] | None = None,
        *,
        session_id: str = "",
        turn_id: str = "",
        workspace: str | None = None,
        task_id: str = "",
        provider_request_id: str = "",
        reservation_id: str = "",
        mutation_id: str = "",
        pid: int | None = None,
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            layer=layer,
            kind=kind,
            run_id=self.run_id,
            timestamp=utc_now_iso(),
            payload=dict(payload or {}),
            session_id=str(session_id or ""),
            turn_id=str(turn_id or ""),
            workspace_id=workspace_id(workspace) if workspace else self.workspace_id,
            task_id=str(task_id or ""),
            provider_request_id=str(provider_request_id or ""),
            reservation_id=str(reservation_id or ""),
            mutation_id=str(mutation_id or ""),
            pid=pid,
        )
        line = json.dumps(record.to_dict(), ensure_ascii=False, default=str)
        with self._lock:
            with self._ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._records.append(record)
        return record

    # -- reading -----------------------------------------------------------

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def read_ledger(self) -> list[dict[str, Any]]:
        """Re-read the ledger from disk (verification path, not the writer)."""
        if not self._ledger_path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self._ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
        return out

    def write_json(self, name: str, payload: Any) -> Path:
        path = self.evidence_dir / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        return path


class Correlator:
    """Joins records into turns and rejects disconnected evidence."""

    def __init__(self, records: Iterable[EvidenceRecord | Mapping[str, Any]]) -> None:
        self.records: list[dict[str, Any]] = [
            rec.to_dict() if isinstance(rec, EvidenceRecord) else dict(rec) for rec in records
        ]

    # -- grouping ----------------------------------------------------------

    def turn_keys(self) -> list[tuple[str, str, str]]:
        keys = {
            (
                str(rec.get("run_id") or ""),
                str(rec.get("session_id") or ""),
                str(rec.get("turn_id") or ""),
            )
            for rec in self.records
            if rec.get("turn_id")
        }
        return sorted(keys)

    def submitted_turns(self) -> list[tuple[str, str, str]]:
        """Turns with a desktop UI submission record (the only valid roots)."""
        return sorted({
            (
                str(rec.get("run_id") or ""),
                str(rec.get("session_id") or ""),
                str(rec.get("turn_id") or ""),
            )
            for rec in self.records
            if rec.get("kind") == "ui.submit" and rec.get("turn_id")
        })

    def records_for(self, key: tuple[str, str, str]) -> list[dict[str, Any]]:
        run_id, session_id, turn_id = key
        return [
            rec for rec in self.records
            if str(rec.get("run_id") or "") == run_id
            and str(rec.get("session_id") or "") == session_id
            and str(rec.get("turn_id") or "") == turn_id
        ]

    # -- integrity ---------------------------------------------------------

    def foreign_run_records(self, run_id: str) -> list[dict[str, Any]]:
        return [rec for rec in self.records if str(rec.get("run_id") or "") != run_id]

    def disconnected_records(self) -> list[dict[str, Any]]:
        """Turn-scoped records whose turn never originated from the desktop UI."""
        roots = set(self.submitted_turns())
        out: list[dict[str, Any]] = []
        for rec in self.records:
            if not rec.get("turn_id"):
                continue
            key = (
                str(rec.get("run_id") or ""),
                str(rec.get("session_id") or ""),
                str(rec.get("turn_id") or ""),
            )
            if key not in roots:
                out.append(rec)
        return out

    def layers_in_turn(self, key: tuple[str, str, str]) -> dict[str, list[str]]:
        layers: dict[str, list[str]] = {}
        for rec in self.records_for(key):
            layers.setdefault(str(rec.get("layer")), []).append(str(rec.get("kind")))
        return layers

    def require_single_execution(self, run_id: str) -> None:
        foreign = self.foreign_run_records(run_id)
        if foreign:
            raise CorrelationError(
                f"{len(foreign)} record(s) in this evidence set belong to a different run id "
                f"than {run_id!r}; refusing to merge them"
            )

    # -- classification ----------------------------------------------------

    def classify(self, run_id: str, requirements: Mapping[str, Iterable[tuple[str, str]]]) -> dict[str, str]:
        """Classify each criterion from record presence.

        ``requirements`` maps criterion name -> iterable of ``(layer, kind)``
        pairs where EVERY pair must be present for VERIFIED, and at least one
        for PARTIALLY VERIFIED.
        """
        have = {(str(rec.get("layer")), str(rec.get("kind"))) for rec in self.records}
        out: dict[str, str] = {}
        for name, wanted in requirements.items():
            wanted_list = list(wanted)
            present = [pair for pair in wanted_list if pair in have]
            if wanted_list and len(present) == len(wanted_list):
                out[name] = "VERIFIED"
            elif present:
                out[name] = "PARTIALLY VERIFIED"
            else:
                out[name] = "NOT VERIFIED"
        return out

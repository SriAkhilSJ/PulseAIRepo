"""Exactly-once submission ledger for the desktop -> bridge boundary.

Live11 exposed a single Enter gesture producing two sessions/turns. The UI must
carry a stable submission id across ``session_create`` and ``prompt``; this
ledger makes repeated delivery idempotent **before** a session is minted or a
turn worker is started.

Durability matters: a renderer reconnect or bridge restart must not replay an
accepted submission. The ledger is a small JSON document under the workspace's
``.crusorai/submissions`` directory, written atomically, plus an append-only
JSONL audit stream. It stores the prompt hash, never the prompt text.

States::

    accepted -> running -> completed | failed | cancelled

``accepted`` means a session was created for the submission but no turn has
been dispatched. ``running`` is claimed atomically before the worker starts.
Any terminal state is final for that id; a deliberate retry must use a new id.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

STATE_ACCEPTED = "accepted"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

TERMINAL_STATES = frozenset({STATE_COMPLETED, STATE_FAILED, STATE_CANCELLED})


class SubmissionLedgerError(RuntimeError):
    """The durable submission ledger cannot be trusted; fail closed."""


class SubmissionMismatchError(SubmissionLedgerError):
    """A submission id was replayed against a different session."""


@dataclass
class SubmissionRecord:
    submission_id: str
    workspace: str
    session_id: str
    state: str
    prompt_sha256: str = ""
    turn_id: str = ""
    detail: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubmissionRecord":
        return cls(
            submission_id=str(data["submission_id"]),
            workspace=str(data.get("workspace") or ""),
            session_id=str(data.get("session_id") or ""),
            state=str(data.get("state") or STATE_ACCEPTED),
            prompt_sha256=str(data.get("prompt_sha256") or ""),
            turn_id=str(data.get("turn_id") or ""),
            detail=str(data.get("detail") or ""),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            completed_at=float(data.get("completed_at") or 0.0),
        )


def prompt_sha256(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


class SubmissionLedger:
    def __init__(self, workspace: str | Path, *, path: Path | None = None) -> None:
        self.workspace = str(Path(workspace).expanduser().resolve())
        root = Path(self.workspace) / ".crusorai" / "submissions"
        self.path = Path(path) if path is not None else root / "submissions.json"
        self.events_path = self.path.with_name("submissions.jsonl")
        self._lock = threading.RLock()
        self._records: Dict[str, SubmissionRecord] = {}
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            records = data.get("submissions") if isinstance(data, dict) else None
            if not isinstance(records, list):
                raise ValueError("missing submissions list")
            self._records = {
                str(item["submission_id"]): SubmissionRecord.from_dict(item)
                for item in records
                if isinstance(item, dict) and item.get("submission_id")
            }
        except Exception as exc:  # noqa: BLE001 - corruption must fail closed
            raise SubmissionLedgerError(
                f"submission ledger is unreadable at {self.path}: {exc}"
            ) from exc

    def _persist(self) -> None:
        _atomic_write(self.path, {
            "version": 1,
            "workspace": self.workspace,
            "updated_at": time.time(),
            "submissions": [r.to_dict() for r in self._records.values()],
        })

    def _event(self, event: str, record: SubmissionRecord, **extra: Any) -> None:
        payload = {
            "event": event,
            "event_id": f"sub_{uuid.uuid4().hex}",
            "timestamp": time.time(),
            "submission_id": record.submission_id,
            "workspace": record.workspace,
            "session_id": record.session_id,
            "state": record.state,
            "turn_id": record.turn_id,
            "prompt_sha256": record.prompt_sha256,
            **extra,
        }
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError:
            # Audit append is best-effort; the atomic JSON state remains.
            pass

    # -- reads -------------------------------------------------------------

    def get(self, submission_id: str) -> Optional[SubmissionRecord]:
        with self._lock:
            return self._records.get(str(submission_id or ""))

    def find_recent_completed(
        self,
        prompt_sha: str,
        *,
        window_s: float = 600.0,
        exclude_session_id: str = "",
    ) -> Optional[SubmissionRecord]:
        """Legacy/replay fallback for frames that carry no submission id."""
        if not prompt_sha:
            return None
        cutoff = time.time() - max(0.0, float(window_s))
        with self._lock:
            for rec in self._records.values():
                if rec.state != STATE_COMPLETED or rec.prompt_sha256 != prompt_sha:
                    continue
                if rec.completed_at < cutoff:
                    continue
                if exclude_session_id and rec.session_id == exclude_session_id:
                    continue
                return rec
        return None

    # -- transitions -------------------------------------------------------

    def record_session(
        self,
        submission_id: str,
        *,
        session_id: str,
        prompt_sha: str = "",
    ) -> SubmissionRecord:
        """Idempotently bind a submission id to one session.

        A replay returns the original record, so the caller must reuse the
        original session instead of minting a second one.
        """
        sid = str(submission_id or "").strip()
        if not sid:
            raise SubmissionLedgerError("submission_id is required")
        with self._lock:
            existing = self._records.get(sid)
            if existing is not None:
                if prompt_sha and not existing.prompt_sha256:
                    existing.prompt_sha256 = prompt_sha
                    existing.updated_at = time.time()
                    self._persist()
                self._event("session_replayed", existing)
                return existing
            rec = SubmissionRecord(
                submission_id=sid,
                workspace=self.workspace,
                session_id=str(session_id),
                state=STATE_ACCEPTED,
                prompt_sha256=str(prompt_sha or ""),
            )
            self._records[sid] = rec
            self._persist()
            self._event("session_created", rec)
            return rec

    def claim_prompt(
        self,
        submission_id: str,
        *,
        session_id: str,
        prompt_sha: str = "",
    ) -> tuple[bool, SubmissionRecord, str]:
        """Atomically move accepted -> running exactly once.

        Returns ``(accepted, record, reason)``. ``accepted`` is false for a
        replay, a completed submission, or a session mismatch.
        """
        sid = str(submission_id or "").strip()
        if not sid:
            raise SubmissionLedgerError("submission_id is required")
        with self._lock:
            rec = self._records.get(sid)
            if rec is None:
                rec = SubmissionRecord(
                    submission_id=sid,
                    workspace=self.workspace,
                    session_id=str(session_id),
                    state=STATE_ACCEPTED,
                    prompt_sha256=str(prompt_sha or ""),
                )
                self._records[sid] = rec
                self._event("prompt_registered", rec)
            if rec.session_id and session_id and rec.session_id != str(session_id):
                self._event("prompt_rejected_session_mismatch", rec,
                            requested_session_id=str(session_id))
                return False, rec, "session_mismatch"
            if rec.session_id and not session_id:
                return False, rec, "session_missing"
            if not rec.session_id and session_id:
                rec.session_id = str(session_id)
            if prompt_sha and not rec.prompt_sha256:
                rec.prompt_sha256 = str(prompt_sha)
            if rec.state != STATE_ACCEPTED:
                self._event("prompt_replayed", rec)
                return False, rec, rec.state
            rec.state = STATE_RUNNING
            rec.updated_at = time.time()
            self._persist()
            self._event("prompt_claimed", rec)
            return True, rec, ""

    def mark_terminal(
        self,
        submission_id: str,
        state: str,
        *,
        turn_id: str = "",
        detail: str = "",
    ) -> Optional[SubmissionRecord]:
        """Set a terminal state once; repeated terminal marks are no-ops."""
        if state not in TERMINAL_STATES:
            raise SubmissionLedgerError(f"invalid terminal state: {state!r}")
        sid = str(submission_id or "").strip()
        if not sid:
            return None
        with self._lock:
            rec = self._records.get(sid)
            if rec is None:
                return None
            if rec.state in TERMINAL_STATES:
                return rec
            rec.state = state
            rec.updated_at = time.time()
            rec.completed_at = rec.updated_at
            if turn_id:
                rec.turn_id = str(turn_id)
            if detail:
                rec.detail = str(detail)[:500]
            self._persist()
            self._event("terminal", rec)
            return rec

    def mark_turn_started(self, submission_id: str, turn_id: str) -> Optional[SubmissionRecord]:
        sid = str(submission_id or "").strip()
        if not sid:
            return None
        with self._lock:
            rec = self._records.get(sid)
            if rec is None:
                return None
            if rec.state == STATE_RUNNING and turn_id:
                rec.turn_id = str(turn_id)
                rec.updated_at = time.time()
                self._persist()
                self._event("turn_started", rec)
            return rec

    def reconcile_running(self, *, detail: str = "process_restart_before_terminal") -> list[SubmissionRecord]:
        """A new process cannot still be running an old submission."""
        changed: list[SubmissionRecord] = []
        with self._lock:
            for rec in self._records.values():
                if rec.state != STATE_RUNNING:
                    continue
                rec.state = STATE_FAILED
                rec.detail = detail
                rec.updated_at = time.time()
                rec.completed_at = rec.updated_at
                changed.append(rec)
                self._event("reconciled_interrupted", rec)
            if changed:
                self._persist()
        return changed

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            states: Dict[str, int] = {}
            for rec in self._records.values():
                states[rec.state] = states.get(rec.state, 0) + 1
            return {
                "workspace": self.workspace,
                "path": str(self.path),
                "total": len(self._records),
                "states": states,
            }


_LEDGERS: Dict[str, SubmissionLedger] = {}
_LEDGERS_LOCK = threading.Lock()


def get_submission_ledger(workspace: str | Path) -> SubmissionLedger:
    key = str(Path(workspace).expanduser().resolve())
    with _LEDGERS_LOCK:
        ledger = _LEDGERS.get(key)
        if ledger is None:
            ledger = SubmissionLedger(key)
            _LEDGERS[key] = ledger
        return ledger


def reset_submission_ledgers() -> None:
    """Test hook: forget cached ledgers."""
    with _LEDGERS_LOCK:
        _LEDGERS.clear()

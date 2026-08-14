"""Persistent verification evidence for IDE-visible correctness state."""
from __future__ import annotations

import json
import re
import shlex
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_STATUS = {"passed", "failed", "stale", "unverified", "unavailable"}
_VERIFY_RE = re.compile(
    r"(?:^|\s)(pytest|python\s+-m\s+pytest|npm\s+(?:run\s+)?(?:test|lint|typecheck|build)|"
    r"pnpm\s+(?:run\s+)?(?:test|lint|typecheck|build)|yarn\s+(?:test|lint|typecheck|build)|"
    r"tsc(?:\s|$)|mypy(?:\s|$)|pyright(?:\s|$)|ruff(?:\s|$)|cargo\s+(?:test|check|build)|"
    r"go\s+test|make\s+(?:test|lint|check|build))",
    re.IGNORECASE,
)
_TARGET_RE = re.compile(r"(?:^|\s)([^\s]+(?:::\S+|\.(?:py|ts|tsx|js|jsx|rs|go)))")


class VerificationLedger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (Path.home() / ".pulseai" / "verification.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS verification_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
              session_id TEXT NOT NULL, workspace TEXT NOT NULL,
              command TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL,
              status TEXT NOT NULL, exit_code INTEGER NOT NULL, output TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS verification_state(
              session_id TEXT NOT NULL, workspace TEXT NOT NULL,
              status TEXT NOT NULL, event_id INTEGER, edited_at REAL,
              changed_paths TEXT NOT NULL DEFAULT '[]',
              PRIMARY KEY(session_id, workspace));
            """
        )
        self._conn.commit()

    @staticmethod
    def classify(command: str) -> tuple[str, str] | None:
        match = _VERIFY_RE.search(command or "")
        if not match:
            return None
        low = match.group(1).lower()
        kind = "test"
        if "lint" in low or "ruff" in low:
            kind = "lint"
        elif "typecheck" in low or "tsc" in low or "mypy" in low or "pyright" in low:
            kind = "typecheck"
        elif "build" in low or "cargo check" in low:
            kind = "build"
        scope = "targeted" if _TARGET_RE.search(command or "") else "full"
        return kind, scope

    def record_command(
        self, *, session_id: str, workspace: str, command: str,
        exit_code: int, output: str = "",
    ) -> dict | None:
        classification = self.classify(command)
        if classification is None:
            return None
        kind, scope = classification
        status = "passed" if int(exit_code) == 0 else "failed"
        now = time.time()
        summary = (output or "").strip()
        if len(summary) > 2000:
            summary = summary[:600] + "\n... omitted ...\n" + summary[-1400:]
        ws = str(Path(workspace).resolve())
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO verification_events(created_at,session_id,workspace,command,kind,scope,status,exit_code,output) VALUES(?,?,?,?,?,?,?,?,?)",
                (now, session_id, ws, command, kind, scope, status, int(exit_code), summary),
            )
            event_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO verification_state(session_id,workspace,status,event_id,edited_at,changed_paths) VALUES(?,?,?,?,NULL,'[]') "
                "ON CONFLICT(session_id,workspace) DO UPDATE SET status=excluded.status,event_id=excluded.event_id,edited_at=NULL,changed_paths='[]'",
                (session_id, ws, status, event_id),
            )
        return {"status": status, "kind": kind, "scope": scope, "command": command,
                "exit_code": int(exit_code), "event_id": event_id, "workspace": ws}

    def mark_edited(self, *, session_id: str, workspace: str, paths: list[str]) -> dict:
        ws = str(Path(workspace).resolve())
        now = time.time()
        clean = sorted({str(p) for p in paths if p})[-200:]
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT status,changed_paths FROM verification_state WHERE session_id=? AND workspace=?",
                (session_id, ws),
            ).fetchone()
            prior = row["status"] if row else "unverified"
            existing = []
            if row:
                try: existing = json.loads(row["changed_paths"] or "[]")
                except Exception: existing = []
            merged = sorted(set(existing) | set(clean))[-200:]
            status = "stale" if prior == "passed" else "unverified"
            self._conn.execute(
                "INSERT INTO verification_state(session_id,workspace,status,event_id,edited_at,changed_paths) VALUES(?,?,?,NULL,?,?) "
                "ON CONFLICT(session_id,workspace) DO UPDATE SET status=excluded.status,edited_at=excluded.edited_at,changed_paths=excluded.changed_paths",
                (session_id, ws, status, now, json.dumps(merged)),
            )
        return {"status": status, "workspace": ws, "changed_paths": merged}

    def status(self, *, session_id: str, workspace: str) -> dict[str, Any]:
        ws = str(Path(workspace).resolve())
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM verification_state WHERE session_id=? AND workspace=?",
                (session_id, ws),
            ).fetchone()
            event = None
            if row and row["event_id"]:
                event = self._conn.execute(
                    "SELECT * FROM verification_events WHERE id=?", (row["event_id"],)
                ).fetchone()
        if not row:
            return {"status": "unverified", "workspace": ws, "evidence": None, "changed_paths": []}
        return {
            "status": row["status"], "workspace": ws,
            "evidence": dict(event) if event else None,
            "changed_paths": json.loads(row["changed_paths"] or "[]"),
        }

    def mark_unavailable(self, *, session_id: str, workspace: str, reason: str) -> dict:
        ws = str(Path(workspace).resolve())
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO verification_state(session_id,workspace,status,event_id,edited_at,changed_paths) VALUES(?,?,'unavailable',NULL,NULL,?) "
                "ON CONFLICT(session_id,workspace) DO UPDATE SET status='unavailable',changed_paths=excluded.changed_paths",
                (session_id, ws, json.dumps([reason[:500]])),
            )
        return {"status": "unavailable", "workspace": ws, "reason": reason}

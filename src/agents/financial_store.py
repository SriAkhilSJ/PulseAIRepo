"""
financial_store.py -- Durable SQLite persistence for Crusor AI financial governance.

Co-locates financial accounting inside the canonical `sessions.db` database.
Provides ACID transactions, SQLite WAL mode, schema versioning, idempotent event
recording, reservation lifecycle persistence, and startup hydration.
"""

from __future__ import annotations

from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional

log = logging.getLogger("crusorai.financial_store")

_SCHEMA_VERSION = 2


class SimulatedCrashError(RuntimeError):
    """Controlled failpoint exception used to test crash-consistency and rollback."""
    pass


def _default_db_path() -> Path:
    custom = os.getenv("CRUSORAI_FINANCIAL_DB") or os.getenv("CRUSORAI_SESSIONS_DB")
    if custom:
        return Path(custom).expanduser()
    home_override = os.getenv("CRUSORAI_HOME")
    if home_override:
        return Path(home_override).expanduser() / "sessions.db"
    return Path.home() / ".crusorai" / "sessions.db"


class FinancialStore:
    """
    ACID-compliant SQLite store for session spend trackers, call ledger,
    and reservation state transitions.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or _default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=30000")
        sync_mode = self._get_configured_synchronous_mode()
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(f"PRAGMA synchronous={sync_mode}")
        except sqlite3.DatabaseError as exc:
            log.warning("Could not set PRAGMA synchronous=%s: %s", sync_mode, exc)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables and indexes with schema versioning."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL DEFAULT 0.0,
                    installed_at REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            # 1. Session snapshots table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_session_snapshots (
                    session_id TEXT PRIMARY KEY,
                    root_session_id TEXT NOT NULL,
                    parent_session_id TEXT,
                    cumulative_input_tokens INTEGER DEFAULT 0,
                    cumulative_output_tokens INTEGER DEFAULT 0,
                    cumulative_cached_tokens INTEGER DEFAULT 0,
                    cumulative_cache_write_tokens INTEGER DEFAULT 0,
                    cumulative_total_tokens INTEGER DEFAULT 0,
                    cumulative_cost_usd TEXT NOT NULL DEFAULT '0.000000',
                    cumulative_cost_inr TEXT NOT NULL DEFAULT '0.000000',
                    has_unknown_spend INTEGER DEFAULT 0,
                    unrated_calls_count INTEGER DEFAULT 0,
                    unrated_tokens_count INTEGER DEFAULT 0,
                    cheap_calls_count INTEGER DEFAULT 0,
                    standard_calls_count INTEGER DEFAULT 0,
                    premium_calls_count INTEGER DEFAULT 0,
                    total_calls_count INTEGER DEFAULT 0,
                    current_turn_id INTEGER DEFAULT 1,
                    turn_tokens INTEGER DEFAULT 0,
                    turn_cached_tokens INTEGER DEFAULT 0,
                    turn_cache_write_tokens INTEGER DEFAULT 0,
                    turn_cost_usd TEXT NOT NULL DEFAULT '0.000000',
                    turn_cost_inr TEXT NOT NULL DEFAULT '0.000000',
                    turn_calls_cheap INTEGER DEFAULT 0,
                    turn_calls_standard INTEGER DEFAULT 0,
                    turn_calls_premium INTEGER DEFAULT 0,
                    budget_config_json TEXT NOT NULL DEFAULT '{}',
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fin_root_session ON financial_session_snapshots(root_session_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fin_parent_session ON financial_session_snapshots(parent_session_id)"
            )

            # 2. Call ledger table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_call_ledger (
                    event_id TEXT PRIMARY KEY,
                    root_session_id TEXT NOT NULL,
                    child_session_id TEXT,
                    turn_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cached_tokens INTEGER DEFAULT 0,
                    cache_write_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    estimated_cost_usd TEXT,
                    estimated_cost_inr TEXT,
                    actual_cost_usd TEXT,
                    actual_cost_inr TEXT,
                    cost_known INTEGER DEFAULT 1,
                    pricing_status TEXT DEFAULT 'fresh',
                    reservation_id TEXT,
                    call_outcome TEXT DEFAULT 'completed',
                    created_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fin_ledger_root ON financial_call_ledger(root_session_id, created_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fin_ledger_res ON financial_call_ledger(reservation_id)"
            )

            # 3. Reservations lifecycle table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    root_session_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id INTEGER NOT NULL,
                    estimated_cost_inr TEXT NOT NULL,
                    estimated_tokens INTEGER NOT NULL,
                    purpose TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fin_res_root_status ON financial_reservations(root_session_id, status)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fin_res_session ON financial_reservations(session_id)"
            )

            # 4. Parent-child relationships lookup table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_parent_sessions (
                    child_session_id TEXT PRIMARY KEY,
                    parent_session_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

            # 5. Reservation administrative resolutions & audit trail table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_reservation_resolutions (
                    resolution_id TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actual_cost_inr TEXT,
                    resolution_notes TEXT,
                    resolved_by TEXT NOT NULL DEFAULT 'admin',
                    resolved_at REAL NOT NULL,
                    FOREIGN KEY(reservation_id) REFERENCES financial_reservations(reservation_id)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fin_res_resolutions_res ON financial_reservation_resolutions(reservation_id)"
            )

            # Check if installed_at column exists in financial_schema_version (v1 compatibility)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(financial_schema_version)").fetchall()}
            if "installed_at" not in cols:
                try:
                    self._conn.execute("ALTER TABLE financial_schema_version ADD COLUMN installed_at REAL DEFAULT 0.0")
                except Exception:
                    pass

            snap_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(financial_session_snapshots)").fetchall()}
            if "cumulative_cache_write_tokens" not in snap_cols:
                try:
                    self._conn.execute("ALTER TABLE financial_session_snapshots ADD COLUMN cumulative_cache_write_tokens INTEGER DEFAULT 0")
                except Exception:
                    pass
            if "turn_cache_write_tokens" not in snap_cols:
                try:
                    self._conn.execute("ALTER TABLE financial_session_snapshots ADD COLUMN turn_cache_write_tokens INTEGER DEFAULT 0")
                except Exception:
                    pass

            ledger_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(financial_call_ledger)").fetchall()}
            if "cache_write_tokens" not in ledger_cols:
                try:
                    self._conn.execute("ALTER TABLE financial_call_ledger ADD COLUMN cache_write_tokens INTEGER DEFAULT 0")
                except Exception:
                    pass

            # Set version with backward-compatible migration
            row = self._conn.execute("SELECT MAX(version) FROM financial_schema_version").fetchone()
            max_ver = int(row[0]) if (row and row[0] is not None) else 0
            now = time.time()
            if max_ver == 0:
                self._conn.execute(
                    "INSERT INTO financial_schema_version (version, applied_at, installed_at) VALUES (?, ?, ?)",
                    (_SCHEMA_VERSION, now, now),
                )
            elif max_ver < _SCHEMA_VERSION:
                self._conn.execute(
                    "INSERT INTO financial_schema_version (version, applied_at, installed_at) VALUES (?, ?, ?)",
                    (_SCHEMA_VERSION, now, now),
                )



    @contextmanager
    def _transaction(self):
        """Context manager for an explicit transaction with rollback on error."""
        with self._lock:
            conn = self._conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _get_configured_synchronous_mode() -> str:
        """
        Validate and resolve CRUSORAI_SQLITE_SYNCHRONOUS environment variable.
        Supported safe values: 'NORMAL', 'FULL'.
        Default: 'NORMAL'.
        """
        val = os.getenv("CRUSORAI_SQLITE_SYNCHRONOUS", "NORMAL").strip().upper()
        if val in {"NORMAL", "FULL"}:
            return val
        log.warning(
            "Unsupported CRUSORAI_SQLITE_SYNCHRONOUS=%s; defaulting to NORMAL. Valid options: NORMAL, FULL",
            val,
        )
        return "NORMAL"

    def get_synchronous_mode(self) -> str:
        """Return the active SQLite synchronous mode name ('NORMAL', 'FULL', etc.)."""
        with self._lock:
            cur = self._conn.execute("PRAGMA synchronous")
            val = cur.fetchone()[0]
            # SQLite synchronous mapping: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA
            mapping = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}
            return mapping.get(val, str(val))

    def get_schema_version(self) -> int:
        """Return current schema version from database."""
        with self._lock:
            try:
                cur = self._conn.execute("SELECT version FROM financial_schema_version ORDER BY rowid DESC LIMIT 1")
                row = cur.fetchone()
                return int(row[0]) if row else _SCHEMA_VERSION
            except Exception:
                return _SCHEMA_VERSION

    def get_reservation(self, reservation_id: str) -> dict[str, Any] | None:
        """Retrieve a single reservation record by ID."""
        with self._lock:
            try:
                cur = self._conn.execute(
                    "SELECT * FROM financial_reservations WHERE reservation_id = ?",
                    (reservation_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
            except Exception as exc:
                log.error("Failed to fetch reservation %s: %s", reservation_id, exc)
                return None

    def close(self) -> None:
        """Close database connection safely."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Parent-Child Relationships
    # -------------------------------------------------------------------------

    def save_parent_session(self, child_session_id: str, parent_session_id: str) -> bool:
        """Persist a parent-child relationship."""
        if not child_session_id or not parent_session_id:
            return False
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    INSERT INTO financial_parent_sessions (child_session_id, parent_session_id, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(child_session_id) DO UPDATE SET parent_session_id=excluded.parent_session_id
                    """,
                    (child_session_id, parent_session_id, time.time()),
                )
            return True
        except Exception as exc:
            log.error("Failed to save parent session: %s", exc)
            return False

    def get_parent_session(self, child_session_id: str) -> str | None:
        """Query parent session for a child."""
        if not child_session_id:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT parent_session_id FROM financial_parent_sessions WHERE child_session_id = ?",
                    (child_session_id,),
                ).fetchone()
                if row:
                    return str(row["parent_session_id"])
        except Exception as exc:
            log.error("Failed to query parent session: %s", exc)
        return None

    # -------------------------------------------------------------------------
    # Session Snapshots
    # -------------------------------------------------------------------------

    def save_session_snapshot(
        self,
        session_id: str,
        root_session_id: str,
        parent_session_id: str | None,
        tracker_data: dict[str, Any],
        budget_config_json: str = "{}",
    ) -> bool:
        """Persist or update a session snapshot transactionally."""
        try:
            now = time.time()
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    INSERT INTO financial_session_snapshots (
                        session_id, root_session_id, parent_session_id,
                        cumulative_input_tokens, cumulative_output_tokens, cumulative_cached_tokens, cumulative_cache_write_tokens, cumulative_total_tokens,
                        cumulative_cost_usd, cumulative_cost_inr, has_unknown_spend,
                        unrated_calls_count, unrated_tokens_count,
                        cheap_calls_count, standard_calls_count, premium_calls_count, total_calls_count,
                        current_turn_id, turn_tokens, turn_cached_tokens, turn_cache_write_tokens,
                        turn_cost_usd, turn_cost_inr,
                        turn_calls_cheap, turn_calls_standard, turn_calls_premium,
                        budget_config_json, schema_version, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    ON CONFLICT(session_id) DO UPDATE SET
                        root_session_id=excluded.root_session_id,
                        parent_session_id=COALESCE(excluded.parent_session_id, financial_session_snapshots.parent_session_id),
                        cumulative_input_tokens=excluded.cumulative_input_tokens,
                        cumulative_output_tokens=excluded.cumulative_output_tokens,
                        cumulative_cached_tokens=excluded.cumulative_cached_tokens,
                        cumulative_cache_write_tokens=excluded.cumulative_cache_write_tokens,
                        cumulative_total_tokens=excluded.cumulative_total_tokens,
                        cumulative_cost_usd=excluded.cumulative_cost_usd,
                        cumulative_cost_inr=excluded.cumulative_cost_inr,
                        has_unknown_spend=excluded.has_unknown_spend,
                        unrated_calls_count=excluded.unrated_calls_count,
                        unrated_tokens_count=excluded.unrated_tokens_count,
                        cheap_calls_count=excluded.cheap_calls_count,
                        standard_calls_count=excluded.standard_calls_count,
                        premium_calls_count=excluded.premium_calls_count,
                        total_calls_count=excluded.total_calls_count,
                        current_turn_id=excluded.current_turn_id,
                        turn_tokens=excluded.turn_tokens,
                        turn_cached_tokens=excluded.turn_cached_tokens,
                        turn_cache_write_tokens=excluded.turn_cache_write_tokens,
                        turn_cost_usd=excluded.turn_cost_usd,
                        turn_cost_inr=excluded.turn_cost_inr,
                        turn_calls_cheap=excluded.turn_calls_cheap,
                        turn_calls_standard=excluded.turn_calls_standard,
                        turn_calls_premium=excluded.turn_calls_premium,
                        budget_config_json=excluded.budget_config_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        session_id,
                        root_session_id,
                        parent_session_id,
                        int(tracker_data.get("cumulative_input_tokens", 0)),
                        int(tracker_data.get("cumulative_output_tokens", 0)),
                        int(tracker_data.get("session_cached_tokens", 0)),
                        int(tracker_data.get("session_cache_write_tokens", 0)),
                        int(tracker_data.get("session_tokens", 0)),
                        str(tracker_data.get("session_cost_usd", "0.000000")),
                        str(tracker_data.get("session_cost_inr", "0.000000")),
                        1 if tracker_data.get("session_has_unknown_spend") else 0,
                        int(tracker_data.get("unrated_calls_session", 0)),
                        int(tracker_data.get("unrated_tokens_session", 0)),
                        int(tracker_data.get("session_calls_cheap", 0)),
                        int(tracker_data.get("session_calls_standard", 0)),
                        int(tracker_data.get("session_calls_premium", 0)),
                        int(tracker_data.get("total_calls_count", 0)),
                        int(tracker_data.get("current_turn_id", 1)),
                        int(tracker_data.get("turn_tokens", 0)),
                        int(tracker_data.get("turn_cached_tokens", 0)),
                        int(tracker_data.get("turn_cache_write_tokens", 0)),
                        str(tracker_data.get("turn_cost_usd", "0.000000")),
                        str(tracker_data.get("turn_cost_inr", "0.000000")),
                        int(tracker_data.get("turn_calls_cheap", 0)),
                        int(tracker_data.get("turn_calls_standard", 0)),
                        int(tracker_data.get("turn_calls_premium", 0)),
                        budget_config_json,
                        _SCHEMA_VERSION,
                        now,
                        now,
                    ),
                )
            return True
        except Exception as exc:
            log.error("Failed to save session snapshot for %s: %s", session_id, exc)
            return False

    def load_session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        """Load a persisted session snapshot from database."""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM financial_session_snapshots WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row:
                    return dict(row)
        except Exception as exc:
            log.error("Failed to load session snapshot for %s: %s", session_id, exc)
        return None

    # -------------------------------------------------------------------------
    # Call Ledger Events
    # -------------------------------------------------------------------------

    def _upsert_snapshot_in_conn(
        self,
        conn: sqlite3.Connection,
        snapshot: dict[str, Any],
        now: float,
    ) -> None:
        """Helper to execute snapshot upsert within an existing transaction."""
        session_id = snapshot["session_id"]
        root_session_id = snapshot.get("root_session_id", session_id)
        parent_session_id = snapshot.get("parent_session_id")
        tracker_data = snapshot.get("tracker_data", {})
        budget_config_json = snapshot.get("budget_config_json", "{}")

        conn.execute(
            """
            INSERT INTO financial_session_snapshots (
                session_id, root_session_id, parent_session_id,
                cumulative_input_tokens, cumulative_output_tokens, cumulative_cached_tokens, cumulative_cache_write_tokens, cumulative_total_tokens,
                cumulative_cost_usd, cumulative_cost_inr, has_unknown_spend,
                unrated_calls_count, unrated_tokens_count,
                cheap_calls_count, standard_calls_count, premium_calls_count, total_calls_count,
                current_turn_id, turn_tokens, turn_cached_tokens, turn_cache_write_tokens,
                turn_cost_usd, turn_cost_inr,
                turn_calls_cheap, turn_calls_standard, turn_calls_premium,
                budget_config_json, schema_version, created_at, updated_at
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            )
            ON CONFLICT(session_id) DO UPDATE SET
                root_session_id=excluded.root_session_id,
                parent_session_id=COALESCE(excluded.parent_session_id, financial_session_snapshots.parent_session_id),
                cumulative_input_tokens=excluded.cumulative_input_tokens,
                cumulative_output_tokens=excluded.cumulative_output_tokens,
                cumulative_cached_tokens=excluded.cumulative_cached_tokens,
                cumulative_cache_write_tokens=excluded.cumulative_cache_write_tokens,
                cumulative_total_tokens=excluded.cumulative_total_tokens,
                cumulative_cost_usd=excluded.cumulative_cost_usd,
                cumulative_cost_inr=excluded.cumulative_cost_inr,
                has_unknown_spend=excluded.has_unknown_spend,
                unrated_calls_count=excluded.unrated_calls_count,
                unrated_tokens_count=excluded.unrated_tokens_count,
                cheap_calls_count=excluded.cheap_calls_count,
                standard_calls_count=excluded.standard_calls_count,
                premium_calls_count=excluded.premium_calls_count,
                total_calls_count=excluded.total_calls_count,
                current_turn_id=excluded.current_turn_id,
                turn_tokens=excluded.turn_tokens,
                turn_cached_tokens=excluded.turn_cached_tokens,
                turn_cache_write_tokens=excluded.turn_cache_write_tokens,
                turn_cost_usd=excluded.turn_cost_usd,
                turn_cost_inr=excluded.turn_cost_inr,
                turn_calls_cheap=excluded.turn_calls_cheap,
                turn_calls_standard=excluded.turn_calls_standard,
                turn_calls_premium=excluded.turn_calls_premium,
                budget_config_json=excluded.budget_config_json,
                schema_version=excluded.schema_version,
                updated_at=excluded.updated_at
            """,
            (
                session_id,
                root_session_id,
                parent_session_id,
                int(tracker_data.get("cumulative_input_tokens", 0)),
                int(tracker_data.get("cumulative_output_tokens", 0)),
                int(tracker_data.get("session_cached_tokens", 0)),
                int(tracker_data.get("session_cache_write_tokens", 0)),
                int(tracker_data.get("session_tokens", 0)),
                str(tracker_data.get("session_cost_usd", "0.000000")),
                str(tracker_data.get("session_cost_inr", "0.000000")),
                1 if tracker_data.get("has_unknown_spend", tracker_data.get("session_has_unknown_spend", False)) else 0,
                int(tracker_data.get("unrated_calls_session", 0)),
                int(tracker_data.get("unrated_tokens_session", 0)),
                int(tracker_data.get("session_calls_cheap", 0)),
                int(tracker_data.get("session_calls_standard", 0)),
                int(tracker_data.get("session_calls_premium", 0)),
                int(tracker_data.get("total_calls_count", 0)),
                int(tracker_data.get("current_turn_id", 1)),
                int(tracker_data.get("turn_tokens", 0)),
                int(tracker_data.get("turn_cached_tokens", 0)),
                int(tracker_data.get("turn_cache_write_tokens", 0)),
                str(tracker_data.get("turn_cost_usd", "0.000000")),
                str(tracker_data.get("turn_cost_inr", "0.000000")),
                int(tracker_data.get("turn_calls_cheap", 0)),
                int(tracker_data.get("turn_calls_standard", 0)),
                int(tracker_data.get("turn_calls_premium", 0)),
                budget_config_json,
                _SCHEMA_VERSION,
                now,
                now,
            ),
        )

    def record_call_and_snapshot(
        self,
        event_dict: dict[str, Any],
        root_snapshot: dict[str, Any],
        child_snapshot: dict[str, Any] | None = None,
        reservation_id: str | None = None,
        parent_link: tuple[str, str] | None = None,
        _failpoint: str | None = None,
    ) -> bool:
        """
        Atomically persist:
        1. Call ledger event in financial_call_ledger (idempotent on event_id).
        2. Associated reservation state update to 'reconciled' in financial_reservations.
        3. Root session snapshot in financial_session_snapshots.
        4. Optional child session snapshot in financial_session_snapshots.
        5. Optional parent-child linkage in financial_parent_sessions.

        Executed within a single SQLite transaction (BEGIN IMMEDIATE ... COMMIT).
        On any error or simulated failpoint, the entire transaction is rolled back.
        """
        try:
            now = time.time()
            call_evt_id = event_dict["event_id"]

            if _failpoint == "before_transaction":
                raise SimulatedCrashError("crash before transaction")

            with self._lock, self._conn:
                if _failpoint == "before_ledger":
                    raise SimulatedCrashError("crash before ledger")

                # 1. Idempotency check: if event already exists in ledger, do nothing
                existing = self._conn.execute(
                    "SELECT 1 FROM financial_call_ledger WHERE event_id = ?",
                    (call_evt_id,),
                ).fetchone()
                if existing:
                    log.info("Event %s already recorded; idempotent skip in atomic transaction", call_evt_id)
                    return True

                # 2. Insert call ledger event
                self._conn.execute(
                    """
                    INSERT INTO financial_call_ledger (
                        event_id, root_session_id, child_session_id, turn_id,
                        provider, model, tier, purpose,
                        input_tokens, output_tokens, cached_tokens, cache_write_tokens, total_tokens,
                        estimated_cost_usd, estimated_cost_inr,
                        actual_cost_usd, actual_cost_inr,
                        cost_known, pricing_status, reservation_id,
                        call_outcome, created_at
                    ) VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?, ?,
                        ?, ?
                    )
                    """,
                    (
                        call_evt_id,
                        event_dict["root_session_id"],
                        event_dict.get("child_session_id"),
                        event_dict.get("turn_id", 1),
                        event_dict.get("provider", "unknown"),
                        event_dict.get("model", "unknown"),
                        event_dict.get("tier", "cheap"),
                        event_dict.get("purpose", "work"),
                        int(event_dict.get("input_tokens", 0)),
                        int(event_dict.get("output_tokens", 0)),
                        int(event_dict.get("cached_tokens", 0)),
                        int(event_dict.get("cache_write_tokens", 0)),
                        int(event_dict.get("total_tokens", 0)),
                        event_dict.get("estimated_cost_usd"),
                        event_dict.get("estimated_cost_inr"),
                        event_dict.get("actual_cost_usd"),
                        event_dict.get("actual_cost_inr"),
                        1 if event_dict.get("cost_known", True) else 0,
                        event_dict.get("pricing_status", "fresh"),
                        reservation_id,
                        event_dict.get("call_outcome", "completed"),
                        now,
                    ),
                )

                if _failpoint == "after_ledger":
                    raise SimulatedCrashError("crash after ledger")

                # 3. Update reservation status to reconciled if provided
                if reservation_id:
                    self._conn.execute(
                        "UPDATE financial_reservations SET status = 'reconciled', updated_at = ? WHERE reservation_id = ?",
                        (now, reservation_id),
                    )

                if _failpoint == "after_reservation":
                    raise SimulatedCrashError("crash after reservation")

                # 4. Upsert root session snapshot
                self._upsert_snapshot_in_conn(self._conn, root_snapshot, now)

                # 5. Upsert child session snapshot if present
                if child_snapshot:
                    self._upsert_snapshot_in_conn(self._conn, child_snapshot, now)

                if _failpoint == "after_snapshot":
                    raise SimulatedCrashError("crash after snapshot")

                # 6. Save parent link if present
                if parent_link:
                    c_id, p_id = parent_link
                    self._conn.execute(
                        """
                        INSERT INTO financial_parent_sessions (child_session_id, parent_session_id, created_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(child_session_id) DO UPDATE SET parent_session_id=excluded.parent_session_id
                        """,
                        (str(c_id), str(p_id), now),
                    )

                if _failpoint == "before_commit":
                    raise SimulatedCrashError("crash immediately before commit")

            return True
        except SimulatedCrashError:
            raise
        except Exception as exc:
            log.error("Failed atomic record_call_and_snapshot for %s: %s", event_dict.get("event_id"), exc)
            return False

    def record_call_event(self, event: dict[str, Any]) -> bool:
        """
        Record a model invocation into the durable ledger.
        Idempotent: uses INSERT OR IGNORE on event_id.
        """
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO financial_call_ledger (
                        event_id, root_session_id, child_session_id, turn_id,
                        provider, model, tier, purpose,
                        input_tokens, output_tokens, cached_tokens, cache_write_tokens, total_tokens,
                        estimated_cost_usd, estimated_cost_inr, actual_cost_usd, actual_cost_inr,
                        cost_known, pricing_status, reservation_id, call_outcome, created_at
                    ) VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        str(event["event_id"]),
                        str(event["root_session_id"]),
                        event.get("child_session_id"),
                        int(event.get("turn_id", 1)),
                        str(event.get("provider", "")),
                        str(event.get("model", "")),
                        str(event.get("tier", "standard")),
                        str(event.get("purpose", "work")),
                        int(event.get("input_tokens", 0)),
                        int(event.get("output_tokens", 0)),
                        int(event.get("cached_tokens", 0)),
                        int(event.get("cache_write_tokens", 0)),
                        int(event.get("total_tokens", 0)),
                        str(event["estimated_cost_usd"]) if event.get("estimated_cost_usd") is not None else None,
                        str(event["estimated_cost_inr"]) if event.get("estimated_cost_inr") is not None else None,
                        str(event["actual_cost_usd"]) if event.get("actual_cost_usd") is not None else None,
                        str(event["actual_cost_inr"]) if event.get("actual_cost_inr") is not None else None,
                        1 if event.get("cost_known", True) else 0,
                        str(event.get("pricing_status", "fresh")),
                        event.get("reservation_id"),
                        str(event.get("call_outcome", "completed")),
                        float(event.get("created_at", time.time())),
                    ),
                )
            return True
        except Exception as exc:
            log.error("Failed to record call event %s: %s", event.get("event_id"), exc)
            return False

    def has_call_event(self, event_id: str) -> bool:
        """Check whether a call event ID is already persisted (deduplication check)."""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT 1 FROM financial_call_ledger WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def get_session_call_history(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve full call ledger history for a root or child session."""
        try:
            with self._lock:
                cursor = self._conn.execute(
                    """
                    SELECT * FROM financial_call_ledger
                    WHERE root_session_id = ? OR child_session_id = ?
                    ORDER BY created_at ASC
                    """,
                    (session_id, session_id),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            log.error("Failed to query call history for %s: %s", session_id, exc)
            return []

    # -------------------------------------------------------------------------
    # Reservations Lifecycle
    # -------------------------------------------------------------------------

    def save_reservation(
        self,
        reservation_id: str,
        root_session_id: str,
        session_id: str,
        turn_id: int,
        estimated_cost_inr: Decimal,
        estimated_tokens: int,
        purpose: str,
        status: str = "reserved",
    ) -> bool:
        """Persist a new budget reservation."""
        try:
            now = time.time()
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    INSERT INTO financial_reservations (
                        reservation_id, root_session_id, session_id, turn_id,
                        estimated_cost_inr, estimated_tokens, purpose, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(reservation_id) DO UPDATE SET
                        status=excluded.status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        reservation_id,
                        root_session_id,
                        session_id,
                        turn_id,
                        str(estimated_cost_inr),
                        estimated_tokens,
                        purpose,
                        status,
                        now,
                        now,
                    ),
                )
            return True
        except Exception as exc:
            log.error("Failed to save reservation %s: %s", reservation_id, exc)
            return False

    def update_reservation_status(self, reservation_id: str, status: str) -> bool:
        """Update reservation state: reserved -> in_flight -> reconciled | released | uncertain."""
        try:
            now = time.time()
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE financial_reservations SET status = ?, updated_at = ? WHERE reservation_id = ?",
                    (status, now, reservation_id),
                )
            return True
        except Exception as exc:
            log.error("Failed to update reservation %s to %s: %s", reservation_id, status, exc)
            return False

    def load_unresolved_reservations(self, root_session_id: str) -> list[dict[str, Any]]:
        """
        Query reservations that are active or in-flight or uncertain.
        """
        try:
            with self._lock:
                cursor = self._conn.execute(
                    """
                    SELECT * FROM financial_reservations
                    WHERE root_session_id = ? AND status IN ('reserved', 'in_flight', 'uncertain')
                    ORDER BY created_at ASC
                    """,
                    (root_session_id,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            log.error("Failed to load unresolved reservations for %s: %s", root_session_id, exc)
            return []

    # -------------------------------------------------------------------------
    # Uncertain Reservation Lifecycle & Administrative Resolution (Phase 9.1.6)
    # -------------------------------------------------------------------------

    def get_uncertain_reservations(self, root_session_id: str | None = None) -> list[dict[str, Any]]:
        """Query all reservations currently in 'uncertain' state."""
        try:
            with self._lock:
                if root_session_id:
                    cursor = self._conn.execute(
                        """
                        SELECT * FROM financial_reservations
                        WHERE root_session_id = ? AND status = 'uncertain'
                        ORDER BY updated_at ASC
                        """,
                        (root_session_id,),
                    )
                else:
                    cursor = self._conn.execute(
                        """
                        SELECT * FROM financial_reservations
                        WHERE status = 'uncertain'
                        ORDER BY updated_at ASC
                        """
                    )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            log.error("Failed to query uncertain reservations: %s", exc)
            return []

    def get_reservations_eligible_for_reconciliation(self, min_age_seconds: float = 1800.0) -> list[dict[str, Any]]:
        """
        Stage B — Reconciliation eligibility query:
        Returns uncertain reservations whose age >= min_age_seconds (default 30 mins).
        NOTE: Meeting this threshold flags the reservation for review; it NEVER automatically releases.
        """
        try:
            now = time.time()
            cutoff = now - min_age_seconds
            with self._lock:
                cursor = self._conn.execute(
                    """
                    SELECT * FROM financial_reservations
                    WHERE status = 'uncertain' AND updated_at <= ?
                    ORDER BY updated_at ASC
                    """,
                    (cutoff,),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            log.error("Failed to query eligible uncertain reservations: %s", exc)
            return []

    def resolve_uncertain_reservation(
        self,
        reservation_id: str,
        action: str,
        actual_cost_inr: Any = None,
        resolution_notes: str = "",
        resolved_by: str = "admin",
    ) -> tuple[bool, str]:
        """
        Stage C — Explicit administrative or verified resolution:
        Actions allowed: 'release', 'reconcile'.
        Validates state is strictly 'uncertain', updates reservation status,
        and logs full audit record in financial_reservation_resolutions.
        """
        action_clean = str(action).strip().lower()
        if action_clean not in {"release", "reconcile"}:
            return False, f"Invalid resolution action '{action}'. Must be 'release' or 'reconcile'."

        try:
            now = time.time()
            with self._lock, self._conn:
                row = self._conn.execute(
                    "SELECT * FROM financial_reservations WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if not row:
                    return False, f"Reservation '{reservation_id}' not found."

                current_status = row["status"]
                if current_status != "uncertain":
                    return False, f"Cannot resolve reservation with status '{current_status}'. Status must be 'uncertain'."

                new_status = "released" if action_clean == "release" else "reconciled"

                # Update reservation status
                self._conn.execute(
                    "UPDATE financial_reservations SET status = ?, updated_at = ? WHERE reservation_id = ?",
                    (new_status, now, reservation_id),
                )

                # Insert audit log
                import uuid
                resolv_id = f"resolv_{int(now*1000)}_{uuid.uuid4().hex[:8]}"
                self._conn.execute(
                    """
                    INSERT INTO financial_reservation_resolutions (
                        resolution_id, reservation_id, session_id, action,
                        actual_cost_inr, resolution_notes, resolved_by, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolv_id,
                        reservation_id,
                        row["session_id"],
                        action_clean,
                        str(actual_cost_inr) if actual_cost_inr is not None else None,
                        resolution_notes,
                        resolved_by,
                        now,
                    ),
                )
            log.info("Uncertain reservation %s resolved via %s by %s", reservation_id, action_clean, resolved_by)
            return True, f"Reservation '{reservation_id}' successfully resolved via {action_clean}."
        except Exception as exc:
            log.error("Failed resolving uncertain reservation %s: %s", reservation_id, exc)
            return False, f"Database error during resolution: {exc}"

    def get_reservation_resolution(self, reservation_id: str) -> dict[str, Any] | None:
        """Fetch resolution audit record for a reservation."""
        try:
            with self._lock:
                row = self._conn.execute(
                    """
                    SELECT * FROM financial_reservation_resolutions
                    WHERE reservation_id = ?
                    ORDER BY resolved_at DESC LIMIT 1
                    """,
                    (reservation_id,),
                ).fetchone()
                return dict(row) if row else None
        except Exception as exc:
            log.error("Failed to query reservation resolution for %s: %s", reservation_id, exc)
            return None

    def recover_interrupted_reservations_on_startup(self, root_session_id: str) -> list[dict[str, Any]]:
        """
        Crash recovery inspection:
        Any reservation left in 'reserved' or 'in_flight' across a process restart:
        1. Check if a corresponding completed call exists in financial_call_ledger.
        2. If call exists -> mark 'reconciled'.
        3. If no call exists -> mark 'uncertain' so its reserved budget is retained.
        """
        unresolved = self.load_unresolved_reservations(root_session_id)
        recovered = []
        try:
            with self._lock, self._conn:
                for res in unresolved:
                    rid = res["reservation_id"]
                    status = res["status"]
                    if status in ("reserved", "in_flight"):
                        # Check if a ledger event exists for this reservation
                        row = self._conn.execute(
                            "SELECT 1 FROM financial_call_ledger WHERE reservation_id = ?",
                            (rid,),
                        ).fetchone()
                        if row:
                            self._conn.execute(
                                "UPDATE financial_reservations SET status = 'reconciled', updated_at = ? WHERE reservation_id = ?",
                                (time.time(), rid),
                            )
                            res["status"] = "reconciled"
                        else:
                            # Interrupted request! Mark uncertain
                            self._conn.execute(
                                "UPDATE financial_reservations SET status = 'uncertain', updated_at = ? WHERE reservation_id = ?",
                                (time.time(), rid),
                            )
                            res["status"] = "uncertain"
                            recovered.append(res)
                    elif status == "uncertain":
                        recovered.append(res)
        except Exception as exc:
            log.error("Failed during reservation recovery for %s: %s", root_session_id, exc)
        return recovered


# Default singleton instance
_GLOBAL_STORE: FinancialStore | None = None
_STORE_LOCK = threading.Lock()


def get_financial_store(db_path: str | Path | None = None) -> FinancialStore:
    """Return the global FinancialStore instance or instantiate for specified path."""
    global _GLOBAL_STORE
    if db_path is not None:
        return FinancialStore(db_path)
    with _STORE_LOCK:
        if _GLOBAL_STORE is None:
            _GLOBAL_STORE = FinancialStore()
        return _GLOBAL_STORE

def reset_financial_store() -> None:
    """Reset the global FinancialStore singleton."""
    global _GLOBAL_STORE
    with _STORE_LOCK:
        if _GLOBAL_STORE is not None:
            try:
                _GLOBAL_STORE.close()
            except Exception:
                pass
            _GLOBAL_STORE = None

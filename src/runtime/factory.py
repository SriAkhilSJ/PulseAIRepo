"""Runtime service factory—one construction seam, isolated instances in tests."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from src.context.verification_evidence import VerificationLedger
from src.runtime.event_journal import EventJournal
from src.runtime.turn_control import TurnControlRegistry, turn_controls
from src.runtime.recovery_engine import GlobalRecoveryBudgetTracker


class RecoveryBudgetRegistry:
    def __init__(self) -> None:
        self._trackers: dict[str, GlobalRecoveryBudgetTracker] = {}
        self._lock = threading.Lock()

    def get_tracker(
        self, session_id: str, state_dict: dict | None = None
    ) -> GlobalRecoveryBudgetTracker:
        with self._lock:
            if session_id not in self._trackers:
                if state_dict:
                    self._trackers[session_id] = GlobalRecoveryBudgetTracker.from_dict(state_dict)
                else:
                    self._trackers[session_id] = GlobalRecoveryBudgetTracker(session_id=session_id)
            elif state_dict and self._trackers[session_id].get_stats()["total_attempts"] == 0 and state_dict.get("total_attempts", 0) > 0:
                self._trackers[session_id] = GlobalRecoveryBudgetTracker.from_dict(state_dict)
            return self._trackers[session_id]

    def reset_for_tests(self) -> None:
        with self._lock:
            self._trackers.clear()


@dataclass
class RuntimeServices:
    journal: EventJournal
    verification: VerificationLedger
    controls: TurnControlRegistry
    recovery_budgets: RecoveryBudgetRegistry = field(default_factory=RecoveryBudgetRegistry)

    def close(self) -> None:
        self.journal.close()
        try:
            self.verification.close()
        except Exception:  # noqa: BLE001,S110 - best-effort shutdown
            pass


def _runtime_home() -> Path:
    configured = os.getenv("CRUSORAI_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".crusorai"


def create_runtime_services(home: str | Path | None = None) -> RuntimeServices:
    root = Path(home).expanduser() if home is not None else _runtime_home()
    root.mkdir(parents=True, exist_ok=True)
    return RuntimeServices(
        journal=EventJournal(root / "runtime_events.db"),
        verification=VerificationLedger(root / "verification.db"),
        controls=TurnControlRegistry(),
    )

_default: RuntimeServices | None = None
_lock = threading.Lock()


def get_runtime_services() -> RuntimeServices:
    global _default
    if _default is None:
        with _lock:
            if _default is None:
                root = _runtime_home()
                _default = RuntimeServices(
                    journal=EventJournal(root / "runtime_events.db"),
                    verification=VerificationLedger(root / "verification.db"),
                    controls=turn_controls,
                )
    return _default


def reset_runtime_services_for_tests() -> None:
    global _default
    with _lock:
        if _default is not None:
            _default.close()
        _default = None

"""Runtime service factory—one construction seam, isolated instances in tests."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from src.context.verification_evidence import VerificationLedger
from src.runtime.event_journal import EventJournal
from src.runtime.turn_control import TurnControlRegistry, turn_controls


@dataclass
class RuntimeServices:
    journal: EventJournal
    verification: VerificationLedger
    controls: TurnControlRegistry

    def close(self) -> None:
        self.journal.close()
        try:
            self.verification._conn.close()
        except Exception:
            pass


def create_runtime_services(home: str | Path | None = None) -> RuntimeServices:
    root = Path(home or (Path.home() / ".pulseai"))
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
                root = Path.home() / ".pulseai"
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

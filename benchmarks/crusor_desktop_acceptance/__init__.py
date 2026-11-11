"""P0.6.4 — Desktop acceptance observability harness.

Offline-first evidence capture for the real Crusor Electron application:

* process observability (launch, PID/PPID, build identity, exit code)
* local-only Chrome DevTools Protocol (CDP) renderer attachment
* renderer DOM/composer inspection and console-error capture
* bridge lifecycle probe (real ``python -m src.bridge``, no paid frames)
* cross-layer correlation of one immutable acceptance run id
* Code OSS Invariant 7 (selective manifest) drift check

The harness never submits an engineering prompt and never invokes a model
provider. It is the evidence substrate for the next live desktop turn; the
live turn itself is a separate, explicitly authorised milestone.
"""
from __future__ import annotations

from benchmarks.crusor_desktop_acceptance.correlation import (
    LAYERS,
    CorrelationError,
    Correlator,
    EvidenceRecord,
    RunContext,
)
from benchmarks.crusor_desktop_acceptance.harness import DesktopAcceptanceHarness, HarnessOptions

__all__ = [
    "LAYERS",
    "CorrelationError",
    "Correlator",
    "DesktopAcceptanceHarness",
    "EvidenceRecord",
    "HarnessOptions",
    "RunContext",
]

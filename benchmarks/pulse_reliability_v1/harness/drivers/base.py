"""Driver abstraction for the Pulse Reliability Benchmark harness.

A driver is the harness's pair of eyes into the system under test. Three
drivers exist today:

- ``echo``   : in-process test lane against the bridge's echo test-runner.
               Proves the harness pipeline end-to-end with zero model calls.
- ``bridge`` : the real engine over Bridge Protocol v2 (stdio sidecar).
               Covers engine-level checks (protocol frames, cancel semantics).
- ``cdp``    : the full desktop IDE over Chrome DevTools Protocol. The only
               driver that can satisfy DOM checks; runs on a machine with the
               built PulseAI IDE (launch command required).

Every driver records into a :class:`Recorder`; nothing is graded by the
driver itself.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from benchmarks.pulse_reliability_v1.harness.recorder import Recorder

#: Check types that require the desktop IDE (DOM) or host process/network
#: observation that only the desktop lane can produce today.
DOM_CHECK_TYPES = frozenset({"dom"})
HOST_CHECK_TYPES = frozenset({"process", "command", "workspace-hash"})


class DriverError(Exception):
    """A driver-level failure (launch, handshake, protocol, timeout)."""


@dataclass
class TurnSummary:
    """Outcome of one prompt turn as observed by the harness."""
    started: bool = False
    completed: bool = False
    cancelled: bool = False
    first_token_ms: int | None = None
    completion_ms: int | None = None
    frames_since: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class DriverCapabilities:
    """Which kinds of evidence a driver can truthfully produce."""
    kind: str
    dom: bool = False
    processes: bool = False
    network: bool = False
    commands: bool = False
    host_hashes: bool = False
    engine_events: bool = False
    real_model: bool = False

    def covers_check(self, check_type: str) -> bool:
        if check_type in DOM_CHECK_TYPES:
            return self.dom
        if check_type in HOST_CHECK_TYPES:
            return {
                "process": self.processes,
                "command": self.commands,
                "workspace-hash": self.host_hashes,
            }.get(check_type, False)
        # event / protocol / context-ranking checks: engine-facing.
        return True


class Driver(abc.ABC):
    """Base driver contract."""

    kind: str = "base"

    def __init__(self, recorder: Recorder, *, python_command: tuple[str, ...] = ("python",)):
        self.recorder = recorder
        self.python_command = python_command

    @property
    @abc.abstractmethod
    def capabilities(self) -> DriverCapabilities:
        ...

    @abc.abstractmethod
    def connect(self, timeout_s: float = 30.0) -> None:
        """Launch/attach and complete the hello handshake."""

    @abc.abstractmethod
    def open_workspace(self, root: str) -> None:
        """Bind the session to a real project folder (protocol-enforced)."""

    @abc.abstractmethod
    def send_prompt(self, text: str) -> None:
        """Submit a prompt and return once the engine accepted it."""

    @abc.abstractmethod
    def wait_turn(self, timeout_s: float) -> TurnSummary:
        """Block until turn_done/turn_failed or timeout; record frames/timing."""

    @abc.abstractmethod
    def cancel(self) -> None:
        """Request cancellation of the active turn."""

    @abc.abstractmethod
    def observe_dom(self, selector: str) -> None:
        """Record a DOM observation for a selector (desktop lane only)."""

    @abc.abstractmethod
    def collect_processes(self) -> None:
        """Snapshot host processes relevant to the task."""

    @abc.abstractmethod
    def shutdown(self, timeout_s: float = 10.0) -> None:
        """Clean shutdown; record shutdown_ms."""

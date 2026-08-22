"""Task scenarios: what the harness does for each benchmark task.

Each scenario is a small, explicit script over driver primitives. A scenario
declares the minimum driver lane it needs; the runner refuses to run a task
on a lane that cannot cover any of its checks (the harness never produces a
silently meaningless pass).

Lanes:
- ``echo``   : bridge echo test-runner (zero model calls; pipeline proof)
- ``bridge`` : real engine over protocol v2 (engine semantics; needs provider
               for model-backed tasks, keyless for workspace/cancel/context)
- ``cdp``    : built desktop IDE over CDP (DOM checks; host machine)

Coverage is reported per task so a report card always shows exactly which
checks a lane could possibly satisfy — no hidden assumptions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from benchmarks.pulse_reliability_v1.contract import TaskManifest
from benchmarks.pulse_reliability_v1.harness.drivers.base import (
    Driver,
    DriverCapabilities,
    DriverError,
)
from benchmarks.pulse_reliability_v1.harness.recorder import Recorder

# ---------------------------------------------------------------------------
# Coverage model
# ---------------------------------------------------------------------------


def covered_check_ids(task: TaskManifest, caps: DriverCapabilities) -> set[str]:
    """Checks this driver lane can truthfully satisfy for this task."""
    covered: set[str] = set()
    for check in task.checks:
        if check.type == "dom":
            if caps.dom:
                covered.add(check.id)
        elif check.type == "process":
            if caps.processes:
                covered.add(check.id)
        elif check.type in ("command", "workspace-hash"):
            if caps.commands or caps.host_hashes:
                covered.add(check.id)
        elif check.type == "event":
            # Event checks that only assert the ABSENCE of engine activity
            # (e.g. no llm.request after cancel) are meaningful on any lane
            # that records frames/events; engine-emitted event checks need
            # the real engine lane.
            expected = check.expected or {}
            if caps.engine_events or "count_after_cancel" in expected:
                covered.add(check.id)
        else:  # protocol / context-ranking: engine-facing, any lane records frames
            covered.add(check.id)
    return covered


def uncovered_check_ids(task: TaskManifest, caps: DriverCapabilities) -> set[str]:
    return {c.id for c in task.checks} - covered_check_ids(task, caps)


# ---------------------------------------------------------------------------
# Scenario primitives (shared by several tasks)
# ---------------------------------------------------------------------------


def _open_and_ping(recorder: Recorder, driver: Driver, workspace: str, prompt: str,
                   timeout_s: float, *, cancel_after_start_ms: int | None = None) -> None:
    """Open a workspace, submit a prompt, wait for the turn to finish.

    When ``cancel_after_start_ms`` is set, cancel shortly after turn_started
    (used by PBR-012) and assert the cancelled receipt.
    """
    driver.open_workspace(workspace)
    driver.send_prompt(prompt)
    if cancel_after_start_ms is not None:
        started = _wait_for_frame(driver, "turn_started", timeout_s)
        if not started:
            raise DriverError("turn_started never arrived before cancel window")
        time.sleep(cancel_after_start_ms / 1000.0)
        driver.cancel()
    summary = driver.wait_turn(timeout_s)
    if cancel_after_start_ms is not None and not summary.cancelled:
        raise DriverError("expected a cancelled turn, got completed=True")


def _wait_for_frame(driver: Driver, frame_type: str, timeout_s: float) -> bool:
    """Block until a frame type arrives (used to time the cancel)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        # BridgeDriver exposes _lines only; scenarios poll via wait_turn-less
        # peek by draining the driver's recorder. Simpler: wait_turn is not
        # used here — drivers that support cancellation expose wait_for_frame.
        waiter = getattr(driver, "wait_for_frame", None)
        if waiter is None:
            raise DriverError(f"driver {driver.kind} cannot wait for frames")
        if waiter(frame_type, 0.5):
            return True
    return False


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    task_id: str
    min_lane: str  # echo | bridge | cdp | desktop
    run: Callable[[Recorder, Driver, dict], None]
    description: str


def _scenario_pbr_001(recorder: Recorder, driver: Driver, opts: dict) -> None:
    """Block prompts when no folder is open. No session may be created."""
    # No session_create / prompt frames may exist: the scenario simply never
    # sends them. DOM evidence (composer disabled + hint) needs the desktop
    # lane and is recorded when the driver supports it.
    try:
        driver.observe_dom("textarea.pulseai-composer-input")
        driver.observe_dom(".pulseai-composer-hint")
    except DriverError:
        pass  # desktop-lane evidence only
    recorder.claim("prompts are blocked with no folder open",
                   status="unverified", evidence_ids=())


def _scenario_pbr_002(recorder: Recorder, driver: Driver, opts: dict) -> None:
    """Route the exact opened workspace through every layer."""
    workspace = opts["workspace"]
    _open_and_ping(recorder, driver, workspace, "Explain workspace_proof.py", 60.0)
    recorder.claim("workspace routed through the stack", status="unverified")


def _scenario_pbr_003(recorder: Recorder, driver: Driver, opts: dict) -> None:
    """Require explicit selection in a multi-root workspace."""
    workspace = opts["workspace"]
    try:
        driver.observe_dom("select[aria-label='Workspace folder']")
    except DriverError:
        pass
    recorder.selection_ms = recorder.frames[0].ts_ms if recorder.frames else None
    # Selection then prompt: on the desktop lane the harness would select the
    # root and record selection_ms at that moment; on engine lanes the
    # workspace argument IS the selection, recorded before the prompt.
    _open_and_ping(recorder, driver, workspace, "Use the selected folder.", 60.0)


def _scenario_pbr_004(recorder: Recorder, driver: Driver, opts: dict) -> None:
    """Bound initial context for a 20k-entry workspace."""
    workspace = opts["workspace"]
    recorder.claim("context preparation is bounded", status="unverified")
    _open_and_ping(recorder, driver, workspace, "Summarize the workspace.", 60.0)


def _scenario_pbr_011(recorder: Recorder, driver: Driver, opts: dict) -> None:
    """Recover from a timed-out command tree without orphaning children."""
    workspace = opts["workspace"]
    # The engine's terminal tool must time out a long foreground command and
    # kill its tree; process evidence needs the real engine / desktop lane.
    _open_and_ping(recorder, driver, workspace, "Run: python -c \"import time; time.sleep(300)\"", 60.0)
    recorder.claim("timed-out command tree cleaned up", status="unverified")


def _scenario_pbr_012(recorder: Recorder, driver: Driver, opts: dict) -> None:
    """Cancel a turn during bounded context preparation."""
    workspace = opts["workspace"]
    _open_and_ping(
        recorder, driver, workspace,
        "Prepare context and then reply.", 30.0,
        cancel_after_start_ms=int(opts.get("cancel_after_start_ms", 100)),
    )
    recorder.claim("turn cancelled cleanly", status="unverified")


SCENARIOS: dict[str, Scenario] = {
    "PBR-001": Scenario("PBR-001", "cdp", _scenario_pbr_001,
                        "Block prompts when no folder is open"),
    "PBR-002": Scenario("PBR-002", "bridge", _scenario_pbr_002,
                        "Route the exact opened workspace through every layer"),
    "PBR-003": Scenario("PBR-003", "cdp", _scenario_pbr_003,
                        "Require explicit selection in a multi-root workspace"),
    "PBR-004": Scenario("PBR-004", "bridge", _scenario_pbr_004,
                        "Bound initial context for a 20k-entry workspace"),
    "PBR-011": Scenario("PBR-011", "bridge", _scenario_pbr_011,
                        "Recover from a timed-out command tree without orphaning children"),
    "PBR-012": Scenario("PBR-012", "echo", _scenario_pbr_012,
                        "Cancel a turn during bounded context preparation"),
}

#: Tasks whose checks can ALL be satisfied on the zero-cost echo lane.
ECHO_FULL_COVERAGE = {"PBR-012"}

#: Zero-cost tasks: no model calls allowed, keyless by design.
ZERO_COST_TASKS = {"PBR-001", "PBR-002", "PBR-003", "PBR-004", "PBR-011", "PBR-012"}

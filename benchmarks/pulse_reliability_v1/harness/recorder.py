"""Harness recorder: turn raw observations into a validated RunRecord.

The recorder is the single funnel through which every driver (echo, bridge,
cdp) reports what it saw. It is import-safe and performs no I/O at import
time; building a RunRecord is an explicit action.

Design rules (from benchmarks/pulse_reliability_v1/README.md):
- the harness never grades itself: it only records; the evaluator grades;
- everything recorded is timestamped in ms since the Unix epoch;
- usage numbers (model_calls, tokens, cost) MUST eventually be reconciled
  against engine telemetry frames, never trusted from the harness alone.
"""

from __future__ import annotations

import time
from pathlib import Path

from benchmarks.pulse_reliability_v1.evaluator import (
    ClaimInput,
    CommandResult,
    ContextEntry,
    DomObservation,
    NetworkAttempt,
    ObservedValue,
    PathHash,
    ProcessObservation,
    ProtocolFrame,
    RunEvent,
    RunRecord,
)


def now_ms() -> int:
    return int(time.time() * 1000)


class Recorder:
    """Collects everything a driver observes during one task run."""

    def __init__(self) -> None:
        self.frames: list[ProtocolFrame] = []
        self.events: list[RunEvent] = []
        self.dom: list[DomObservation] = []
        self.commands: list[CommandResult] = []
        self.processes_after: list[ProcessObservation] = []
        self.network_attempts: list[NetworkAttempt] = []
        self.observations: list[ObservedValue] = []
        self.claims: list[ClaimInput] = []
        self.changed_files: list[str] = []
        self.outside_scope_changes: list[str] = []
        self.baseline_hashes: list[PathHash] = []
        self.final_hashes: list[PathHash] = []
        self.context_entries: list[ContextEntry] = []
        self.artifacts: list[str] = []
        # Scalar timings (ms since epoch); all optional.
        self.startup_ms: int | None = None
        self.selection_ms: int | None = None
        self.cancelled_at_ms: int | None = None
        self.first_progress_ms: int | None = None
        self.first_token_ms: int | None = None
        self.completion_ms: int | None = None
        self.verification_ms: int | None = None
        self.shutdown_ms: int | None = None
        # Scalar usage (harness-reported until telemetry reconciliation lands).
        self.model_calls: int = 0
        self.tool_calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_tokens: int = 0
        self.estimated_cost_usd: float = 0.0

    # -- recorders ---------------------------------------------------------

    def record_frame(self, type_: str, payload: dict | None = None, *,
                     cancelled: bool = False) -> None:
        self.frames.append(ProtocolFrame(
            ts_ms=now_ms(), type=type_,
            payload=dict(payload or {}), cancelled=cancelled,
        ))

    def record_event(self, type_: str, payload: dict | None = None) -> None:
        self.events.append(RunEvent(ts_ms=now_ms(), type=type_, payload=dict(payload or {})))

    def record_dom(self, selector: str, *, enabled: bool | None = None,
                   visible: bool | None = None, text: str | None = None,
                   count: int | None = None,
                   responsive_during_turn: bool | None = None) -> None:
        self.dom.append(DomObservation(
            selector=selector, enabled=enabled, visible=visible,
            text=text, count=count, responsive_during_turn=responsive_during_turn,
        ))

    def record_command(self, argv: tuple[str, ...], *, exit_code: int | None = None,
                       status: str | None = None, stdout: str = "", stderr: str = "",
                       duration_ms: int = 0) -> None:
        self.commands.append(CommandResult(
            argv=argv, exit_code=exit_code,
            status=status if status in ("completed", "timeout", "killed") else None,
            stdout=stdout, stderr=stderr, duration_ms=duration_ms,
        ))

    def record_process(self, name: str, *, owner: str = "unrelated",
                       alive: bool = True, pid: int = 1, parent_pid: int | None = None) -> None:
        self.processes_after.append(ProcessObservation(
            name=name, owner=owner, alive=alive, pid=pid, parent_pid=parent_pid,
        ))

    def record_network(self, destination: str, kind: str = "connect") -> None:
        self.network_attempts.append(NetworkAttempt(ts_ms=now_ms(), destination=destination, kind=kind))

    def observe(self, key: str, value: bool | int | str, scope: str | None = None) -> None:
        self.observations.append(ObservedValue(key=key, value=value, scope=scope))

    def claim(self, claim: str, status: str = "unverified",
              evidence_ids: tuple[str, ...] = ()) -> None:
        self.claims.append(ClaimInput(claim=claim, status=status, evidence_ids=evidence_ids))

    def add_usage(self, *, model_calls: int = 0, tool_calls: int = 0,
                  input_tokens: int = 0, output_tokens: int = 0,
                  cache_tokens: int = 0, estimated_cost_usd: float = 0.0) -> None:
        self.model_calls += model_calls
        self.tool_calls += tool_calls
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_tokens += cache_tokens
        self.estimated_cost_usd += estimated_cost_usd

    # -- build -------------------------------------------------------------

    def build_run_record(self, *, run_id: str, task_id: str, task_version: int,
                         pulse_commit: str, python_command: tuple[str, ...] = ("python",),
                         fixture_root: str | None = None,
                         selected_root: str | None = None,
                         harness_error: str | None = None,
                         environment_notes: tuple[str, ...] = ()) -> RunRecord:
        return RunRecord(
            schema_id="pulse-benchmark-run/v1",
            run_id=run_id,
            task_id=task_id,
            task_version=task_version,
            pulse_commit=pulse_commit,
            fixture_root=fixture_root,
            selected_root=selected_root,
            selection_ms=self.selection_ms,
            cancelled_at_ms=self.cancelled_at_ms,
            harness_error=harness_error,
            environment_notes=environment_notes,
            events=tuple(self.events),
            frames=tuple(self.frames),
            dom=tuple(self.dom),
            commands=tuple(self.commands),
            changed_files=tuple(self.changed_files),
            outside_scope_changes=tuple(self.outside_scope_changes),
            baseline_hashes=tuple(self.baseline_hashes),
            final_hashes=tuple(self.final_hashes),
            context_entries=tuple(self.context_entries),
            processes_after=tuple(self.processes_after),
            network_attempts=tuple(self.network_attempts),
            observations=tuple(self.observations),
            claims=tuple(self.claims),
            artifacts=tuple(self.artifacts),
            python_command=python_command,
            startup_ms=self.startup_ms or 0,
            first_progress_ms=self.first_progress_ms or 0,
            first_token_ms=self.first_token_ms or 0,
            completion_ms=self.completion_ms or 0,
            verification_ms=self.verification_ms or 0,
            shutdown_ms=self.shutdown_ms or 0,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_tokens=self.cache_tokens,
            estimated_cost_usd=self.estimated_cost_usd,
        )

    def hash_tree_into(self, root: str | Path) -> dict[str, str]:
        """Record baseline/final hashes of a fixture tree (sha256 per file)."""
        from benchmarks.pulse_reliability_v1.fixtures import hash_tree
        return hash_tree(Path(root))

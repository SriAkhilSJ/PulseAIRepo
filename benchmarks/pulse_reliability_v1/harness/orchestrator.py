"""Harness orchestrator: run a task against a driver lane, record everything,
grade with the evaluator, and persist run + result artifacts.

The orchestrator enforces the benchmark's honesty rules:
- a task is refused on a lane that cannot cover ANY of its checks;
- the harness never grades itself — the evaluator owns the outcome;
- usage numbers are labelled harness-reported until engine telemetry
  reconciliation lands (see docs/CTO_BENCHMARK_REVIEW_PR7.md, gap 3).
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from benchmarks.pulse_reliability_v1.contract import load_suite
from benchmarks.pulse_reliability_v1.evaluator import evaluate_suite
from benchmarks.pulse_reliability_v1.harness.drivers.base import Driver, DriverError
from benchmarks.pulse_reliability_v1.harness.drivers.bridge import driver_from_kind
from benchmarks.pulse_reliability_v1.harness.drivers.cdp import CdpDriver
from benchmarks.pulse_reliability_v1.harness.recorder import Recorder
from benchmarks.pulse_reliability_v1.harness.scenarios import (
    SCENARIOS,
    covered_check_ids,
)

LANE_ORDER = {"echo": 0, "bridge": 1, "cdp": 2}

#: Suite path relative to the repository root (override with --suite).
DEFAULT_SUITE = "benchmarks/pulse_reliability_v1/manifest.json"


def git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5.0,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def make_driver(kind: str, recorder: Recorder, *, python_command: tuple[str, ...],
                echo_delay_ms: int, workspace: str,
                launch_command: tuple[str, ...] | None, port: int) -> Driver:
    if kind in ("echo", "bridge"):
        return driver_from_kind(
            kind, recorder, python_command=python_command,
            echo_delay_ms=echo_delay_ms, workspace=workspace,
        )
    if kind == "cdp":
        return CdpDriver(
            recorder, python_command=python_command,
            launch_command=launch_command, port=port, workspace=workspace,
        )
    raise DriverError(f"unknown driver lane {kind!r}")


def run_task(*, task_id: str, driver_kind: str,
             workspace: str | None = None,
             suite_path: str | Path = DEFAULT_SUITE,
             python_command: tuple[str, ...] = ("python",),
             echo_delay_ms: int = 0,
             cancel_after_start_ms: int = 100,
             launch_command: tuple[str, ...] | None = None,
             port: int = 9222,
             run_id: str | None = None,
             environment_notes: tuple[str, ...] = ()) -> tuple[object, object, Path]:
    """Run one task on one lane; returns (RunRecord, BenchmarkResult, run_dir)."""
    suite = load_suite(suite_path)
    task = next((t for t in suite.tasks if t.id == task_id), None)
    if task is None:
        raise DriverError(f"task {task_id!r} not in suite {suite_path}")
    scenario = SCENARIOS.get(task_id)
    if scenario is None:
        raise DriverError(f"no harness scenario for {task_id} (v0.1 covers the zero-cost set)")

    if LANE_ORDER[driver_kind] < LANE_ORDER[scenario.min_lane]:
        raise DriverError(
            f"task {task_id} needs at least the {scenario.min_lane!r} lane "
            f"(driver={driver_kind!r} cannot cover any of its checks)"
        )

    if workspace is None:
        raise DriverError("--workspace is required (the harness never runs against '.' or the repo root)")
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        raise DriverError(f"workspace does not exist: {workspace_path}")

    recorder = Recorder()
    driver = make_driver(
        driver_kind, recorder, python_command=python_command,
        echo_delay_ms=echo_delay_ms, workspace=str(workspace_path),
        launch_command=launch_command, port=port,
    )
    caps = driver.capabilities
    covered = covered_check_ids(task, caps)
    if not covered:
        raise DriverError(f"driver lane {driver_kind!r} cannot cover any check of {task_id}")

    harness_error = None
    try:
        driver.connect()
        scenario.run(recorder, driver, {
            "workspace": str(workspace_path),
            "cancel_after_start_ms": cancel_after_start_ms,
        })
    except Exception as exc:  # record, then grade — the evaluator decides
        harness_error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            driver.shutdown()
        except Exception:
            pass

    final_run_id = run_id or f"{task_id.lower()}-{uuid.uuid4().hex[:12]}"
    record = recorder.build_run_record(
        run_id=final_run_id,
        task_id=task_id,
        task_version=task.version,
        pulse_commit=git_head(),
        python_command=python_command,
        fixture_root=str(workspace_path),
        selected_root=str(workspace_path),
        harness_error=harness_error,
        environment_notes=environment_notes,
    )
    result = evaluate_suite(suite, record)

    run_dir = Path("bench-results") / final_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result_payload = result.model_dump(mode="json")
    # Lane + coverage metadata for the report card (not part of the evaluator
    # contract; the evaluator itself stays pure).
    result_payload["lane"] = driver_kind
    result_payload["checks_covered"] = len(covered)
    result_payload["checks_covered_ids"] = sorted(covered)
    (run_dir / "result.json").write_text(
        json.dumps(result_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "result.md").write_text(
        _render_result_markdown(result, task.title, covered), encoding="utf-8",
    )
    return record, result, run_dir


def _render_result_markdown(result: object, title: str, covered: set[str]) -> str:
    from benchmarks.pulse_reliability_v1.evaluator import render_markdown
    md = render_markdown(result)
    lines = md.splitlines()
    lines.insert(1, f"- **Task:** {title}")
    lines.insert(2, f"- **Checks coverable on this lane:** {len(covered)}")
    return "\n".join(lines) + "\n"

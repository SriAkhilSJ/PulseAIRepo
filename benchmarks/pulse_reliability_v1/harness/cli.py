"""Pulse Reliability Benchmark harness (v0.1).

Commands:

    python -m benchmarks.pulse_reliability_v1.harness run \\
        --task PBR-012 --driver echo --workspace /path/to/workspace

    python -m benchmarks.pulse_reliability_v1.harness run-all \\
        --workspace /path/to/workspace --launch "path/to/PulseAI.exe --remote-debugging-port=9222"

    python -m benchmarks.pulse_reliability_v1.harness report \\
        --results-dir bench-results --out bench-results/report-card.md

Lanes:
    echo    zero-cost pipeline proof (bridge echo test-runner, no model)
    bridge  real engine over Bridge Protocol v2 (engine semantics)
    cdp     built PulseAI IDE over CDP (DOM checks; host machine)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmarks.pulse_reliability_v1.harness.drivers.base import DriverError
from benchmarks.pulse_reliability_v1.harness.orchestrator import DEFAULT_SUITE, run_task
from benchmarks.pulse_reliability_v1.harness.report import render_report
from benchmarks.pulse_reliability_v1.harness.scenarios import SCENARIOS

#: Keyless tasks, each on its best lane. Model tasks (PBR-005..010) and
#: engine-event tasks (PBR-002/004/011) wait for the provider key.
KEYLESS_PLAN: list[tuple[str, str]] = [
    ("PBR-012", "echo"),
    ("PBR-001", "cdp"),
    ("PBR-003", "cdp"),
]


def _parse_python(value: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in value.split() if p.strip())
    return parts or ("python",)


def cmd_run_all(args: argparse.Namespace) -> int:
    """Run every keyless task on its best lane, then render the report card."""
    failures = 0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for task_id, lane in KEYLESS_PLAN:
        # PBR-012 cancels a turn in flight: the echo lane must simulate a
        # long-enough turn or the cancel window is meaningless.
        echo_delay = args.echo_delay_ms if task_id != "PBR-012" else max(args.echo_delay_ms, 1200)
        try:
            record, result, run_dir = run_task(
                task_id=task_id,
                driver_kind=lane,
                workspace=args.workspace,
                suite_path=args.suite,
                python_command=_parse_python(args.python),
                echo_delay_ms=echo_delay,
                cancel_after_start_ms=args.cancel_after_start_ms,
                launch_command=tuple(args.launch.split()) if args.launch else None,
                port=args.port,
                environment_notes=("run-all",),
                connect_timeout_s=args.connect_timeout,
                results_root=out_dir,
            )
            if record.harness_error:
                failures += 1
                print(f"task={task_id} lane={lane} ERROR: {record.harness_error} ({run_dir})")
            else:
                outcome = result.outcome.value
                print(f"task={task_id} lane={lane} outcome={outcome} ({run_dir})")
                if outcome != "passed":
                    failures += 1
        except DriverError as exc:
            failures += 1
            print(f"task={task_id} lane={lane} ERROR: {exc}")
    card = out_dir / "report-card.md"
    card.write_text(render_report(out_dir, suite_path=args.suite), encoding="utf-8")
    print(f"report card: {card}")
    return 1 if failures else 0


def cmd_run(args: argparse.Namespace) -> int:
    _, result, run_dir = run_task(
        task_id=args.task,
        driver_kind=args.driver,
        workspace=args.workspace,
        suite_path=args.suite,
        python_command=_parse_python(args.python),
        echo_delay_ms=args.echo_delay_ms,
        cancel_after_start_ms=args.cancel_after_start_ms,
        launch_command=tuple(args.launch.split()) if args.launch else None,
        port=args.port,
        run_id=args.run_id,
        environment_notes=tuple(args.env_note),
        connect_timeout_s=args.connect_timeout,
        results_root=args.results_root,
    )
    outcome = result.outcome.value
    hard = f" hard_failure={result.hard_failure.value}" if result.hard_failure else ""
    print(f"task={args.task} lane={args.driver} outcome={outcome}{hard}")
    print(f"artifacts: {run_dir}")
    return 0 if outcome == "passed" else 1


def cmd_report(args: argparse.Namespace) -> int:
    md = render_report(args.results_dir, suite_path=args.suite)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"report card: {args.out}")
    else:
        print(md)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pulse Reliability Benchmark harness")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run one task on one lane")
    p_run.add_argument("--task", required=True, choices=sorted(SCENARIOS),
                       help="task id (v0.1 covers the zero-cost set)")
    p_run.add_argument("--driver", required=True, choices=["echo", "bridge", "cdp"],
                       help="driver lane")
    p_run.add_argument("--workspace", default=None,
                       help="absolute path to the fixture workspace (never '.')")
    p_run.add_argument("--suite", default=DEFAULT_SUITE)
    p_run.add_argument("--python", default="python", help="python command for the bridge")
    p_run.add_argument("--echo-delay-ms", type=int, default=0,
                       help="echo lane: simulate an in-flight turn of N ms")
    p_run.add_argument("--cancel-after-start-ms", type=int, default=100,
                       help="PBR-012: cancel N ms after turn_started")
    p_run.add_argument("--launch", default=None,
                       help="cdp lane: command that launches the built PulseAI IDE")
    p_run.add_argument("--port", type=int, default=9222, help="cdp lane: debugging port")
    p_run.add_argument("--connect-timeout", type=float, default=30.0,
                       help="seconds to wait for the CDP endpoint (default 30)")
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--env-note", action="append", default=[])
    p_run.add_argument("--results-root", default="bench-results",
                       help="where run artifacts are written (keep test runs out of the real scoreboard)")
    p_run.set_defaults(func=cmd_run)

    p_rep = sub.add_parser("report", help="render the aggregate report card")
    p_rep.add_argument("--results-dir", required=True)
    p_rep.add_argument("--out", default=None)
    p_rep.add_argument("--suite", default=DEFAULT_SUITE)
    p_rep.set_defaults(func=cmd_report)

    p_all = sub.add_parser("run-all", help="run every keyless task, then render the card")
    p_all.add_argument("--workspace", required=True,
                       help="absolute path to the fixture workspace (never '.')")
    p_all.add_argument("--suite", default=DEFAULT_SUITE)
    p_all.add_argument("--python", default="python")
    p_all.add_argument("--echo-delay-ms", type=int, default=0)
    p_all.add_argument("--cancel-after-start-ms", type=int, default=100)
    p_all.add_argument("--launch", default=None,
                       help="command that launches the built PulseAI IDE (cdp tasks)")
    p_all.add_argument("--port", type=int, default=9222)
    p_all.add_argument("--connect-timeout", type=float, default=30.0,
                       help="seconds to wait for the CDP endpoint (default 30)")
    p_all.add_argument("--out-dir", default="bench-results")
    p_all.set_defaults(func=cmd_run_all)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

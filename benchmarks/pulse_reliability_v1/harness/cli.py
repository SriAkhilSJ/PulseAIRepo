"""Pulse Reliability Benchmark harness (v0.1).

Commands:

    python -m benchmarks.pulse_reliability_v1.harness run \\
        --task PBR-012 --driver echo --workspace /path/to/workspace

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

from benchmarks.pulse_reliability_v1.harness.orchestrator import DEFAULT_SUITE, run_task
from benchmarks.pulse_reliability_v1.harness.report import render_report
from benchmarks.pulse_reliability_v1.harness.scenarios import SCENARIOS


def _parse_python(value: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in value.split() if p.strip())
    return parts or ("python",)


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
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--env-note", action="append", default=[])
    p_run.set_defaults(func=cmd_run)

    p_rep = sub.add_parser("report", help="render the aggregate report card")
    p_rep.add_argument("--results-dir", required=True)
    p_rep.add_argument("--out", default=None)
    p_rep.add_argument("--suite", default=DEFAULT_SUITE)
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

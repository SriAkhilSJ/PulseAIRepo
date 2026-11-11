"""CLI: ``python -m benchmarks.crusor_desktop_acceptance``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.crusor_desktop_acceptance.harness import DesktopAcceptanceHarness, HarnessOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crusor-desktop-acceptance",
        description="P0.6.4 desktop observability + acceptance harness (offline; no provider calls).",
    )
    parser.add_argument("--evidence-dir", type=Path, default=None,
                        help="where to write evidence.json / evidence.jsonl / report.md (default diagnostics/p0_6_4)")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="folder opened in the desktop app (default: fresh temp dir)")
    parser.add_argument("--port", type=int, default=0,
                        help="localhost CDP port (default 0 = allocate a free loopback port)")
    parser.add_argument("--launch-timeout", type=float, default=120.0, help="seconds to wait for the app/CDP")
    parser.add_argument("--max-output-tokens", type=int, default=2048, help="output ceiling used in the offline budget estimate")
    parser.add_argument("--skip-desktop", action="store_true", help="skip the Electron/CDP lane")
    parser.add_argument("--skip-bridge", action="store_true", help="skip the bridge lifecycle lane")
    parser.add_argument("--keep-app", action="store_true", help="leave the desktop app running after capture")
    parser.add_argument("--json", action="store_true", help="print the summary JSON instead of the report path")
    parser.add_argument("--live-turn", action="store_true",
                        help="P0.6.5: drive ONE real prompt through the actual desktop UI (spends provider credits)")
    parser.add_argument("--prompt-file", type=Path, default=None,
                        help="prompt text for --live-turn (default: the built-in email-validator task)")
    parser.add_argument("--max-dispatches", type=int, default=5, help="acceptance dispatch budget (default 5)")
    parser.add_argument("--budget-inr", type=float, default=5.00, help="hard budget for the live turn (default 5)")
    parser.add_argument("--turn-timeout", type=float, default=900.0, help="seconds to wait for the turn to finish")
    parser.add_argument("--stop-before-submit", action="store_true",
                        help="validate every gate and type the prompt, then stop WITHOUT submitting (no credits)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.live_turn:
        from benchmarks.crusor_desktop_acceptance.live_acceptance import (
            DEFAULT_PROMPT,
            LiveAcceptance,
            LiveTurnOptions,
        )

        prompt = DEFAULT_PROMPT
        if args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
        state = LiveAcceptance(LiveTurnOptions(
            evidence_dir=args.evidence_dir,
            workspace=args.workspace,
            prompt=prompt,
            max_dispatches=args.max_dispatches,
            budget_inr=args.budget_inr,
            launch_timeout_s=args.launch_timeout,
            turn_timeout_s=args.turn_timeout,
            stop_before_submit=args.stop_before_submit,
        )).run()
        print(f"run_id: {state['run_id']}")
        print(f"verdict: {state.get('verdict')}")
        for name, gate in state.get("gates", {}).items():
            print(f"  [{'PASS' if gate.get('ok') else 'FAIL'}] {name}")
        if state.get("correlation"):
            print("correlation:", json.dumps(state["correlation"], default=str))
        if state.get("stopped_before_submit"):
            print("stopped before submit (provider-free preflight)")
            return 0
        # Accept every token the current harness can emit; a stale token here
        # turns an accepted run into exit code 1 for scripting and CI.
        accepted = {
            "P0.6.9_ACCEPTANCE_PASSED",
            "P0.6.8_ACCEPTANCE_PASSED",
            "P0.6.7_ACCEPTANCE_PASSED",
            "P0.6.6_LIVE_ACCEPTED",
            "P0.6.5_DESKTOP_ACCEPTED",  # historical evidence only
        }
        return 0 if state.get("verdict") in accepted else 1

    options = HarnessOptions(
        evidence_dir=args.evidence_dir,
        workspace=args.workspace,
        port=args.port,
        launch_timeout_s=args.launch_timeout,
        skip_desktop=args.skip_desktop,
        skip_bridge=args.skip_bridge,
        keep_app_running=args.keep_app,
        max_output_tokens=args.max_output_tokens,
    )
    summary = DesktopAcceptanceHarness(options).run()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"run_id: {summary['run_id']}")
        print(f"evidence: {summary['evidence_dir']}")
        print(f"report: {Path(summary['evidence_dir']) / 'report.md'}")
        print(f"provider dispatches: {summary['provider_dispatches']}")
        for name, value in summary["criteria"].items():
            print(f"  [{value}] {name}")
        if summary["errors"]:
            print("errors:")
            for err in summary["errors"]:
                print(f"  - {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

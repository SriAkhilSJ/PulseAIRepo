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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

#!/usr/bin/env python3
"""Multi-platform toolchain doctor + plan preview for the Crusor agent.

    python scripts/targets_doctor.py                      # host toolchain report
    python scripts/targets_doctor.py --workspace .        # + detect targets here
    python scripts/targets_doctor.py -w app --target android --plan
    python scripts/targets_doctor.py -w app --require android   # CI gate (exit 1)

This is what the agent calls internally (`check_target_toolchains`,
`detect_targets`), exposed as a CLI so a developer, a CI job or the desktop
"Connectors" panel can ask the same questions and get the same answers — second
surfaces that agree are how a platform stays debuggable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.targets import registry  # noqa: E402
from src.targets.runner import TargetRequest  # noqa: E402
from src.targets.toolchain import doctor_report, target_readiness  # noqa: E402


def _print_workspace_report(workspace: Path, target: str, plan: bool, assertions: list[str]) -> int:
    candidates = registry.detect(workspace)
    print(f"Workspace: {workspace}")
    print(registry.detect_report(workspace))
    if not candidates:
        return 0
    print()
    for candidate in candidates:
        readiness = target_readiness(targets=[candidate.target]).get(candidate.target, {})
        if not readiness.get("host_supported", True):
            print(f"  {candidate.target:<14} HOST-UNSUPPORTED — {readiness.get('host_reason')}")
        elif readiness.get("ready"):
            print(f"  {candidate.target:<14} READY")
        else:
            print(f"  {candidate.target:<14} MISSING {', '.join(readiness.get('missing', []))}")
    if plan:
        print()
        request = TargetRequest(mode="verify", assertions=tuple(("text", value) for value in assertions))
        print(registry.run(workspace, target or candidates[0].target, request, dry_run=True).to_text())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Target toolchain doctor (mobile/desktop/web).")
    parser.add_argument("-w", "--workspace", default="", help="workspace to detect targets in")
    parser.add_argument("-t", "--target", default="", help="target id or alias (android, ios, flutter, ...)")
    parser.add_argument("--plan", action="store_true", help="print the dry-run plan for --target")
    parser.add_argument("--assert-text", dest="assert_text", action="append", default=[],
                        help="planned UI assertion (repeatable), e.g. --assert-text 'Sign in'")
    parser.add_argument("--require", action="append", default=[],
                        help="target id that must be READY (CI gate; exit 1 when not)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    host_report = doctor_report(targets=[args.target] if args.target else None)
    readiness = target_readiness(targets=[args.target] if args.target else None)

    if args.json:
        payload = {
            "host": next(iter(readiness.values()))["host"] if readiness else "",
            "readiness": {key: {k: v for k, v in value.items() if k != "missing_detail"}
                          for key, value in readiness.items()},
            "readiness_detail": readiness,
        }
        if args.workspace:
            payload["workspace"] = args.workspace
            payload["detected"] = [
                {"target": c.target, "confidence": c.confidence, "app_id": c.app_id,
                 "framework": c.framework, "evidence": list(c.evidence)}
                for c in registry.detect(Path(args.workspace).expanduser().resolve())
            ]
        print(json.dumps(payload, indent=2))
    else:
        print(host_report)
        if args.workspace:
            print()
            _print_workspace_report(
                Path(args.workspace).expanduser().resolve(), args.target, args.plan,
                list(args.assert_text),
            )

    exit_code = 0
    for required in args.require:
        resolved = registry.get_provider(required)
        if resolved is None:
            print(f"⛔ unknown required target {required!r}", file=sys.stderr)
            exit_code = 2
            continue
        info = readiness.get(resolved.id, {})
        if not info.get("ready"):
            reason = info.get("host_reason") or ("missing " + ", ".join(info.get("missing", [])))
            print(f"⛔ {required} is not ready: {reason}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

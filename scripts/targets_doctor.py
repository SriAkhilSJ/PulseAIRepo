#!/usr/bin/env python3
"""Multi-platform toolchain doctor + plan preview for the Crusor agent.

    python scripts/targets_doctor.py                      # host toolchain report
    python scripts/targets_doctor.py --workspace .        # + detect targets here
    python scripts/targets_doctor.py -w app --target android --plan
    python scripts/targets_doctor.py -w app --require android   # CI gate (exit 1)
    python scripts/targets_doctor.py --setup android        # copy-paste install plan

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
from src.targets.contract import HOST_LINUX, HOST_MACOS, HOST_WINDOWS  # noqa: E402
from src.targets.toolchain import (  # noqa: E402
    TOOLS_BY_ID,
    doctor_report,
    host_platform,
    target_readiness,
)


#: One command per SDK tool per host, as the vendor actually spells it. Only the
#: Android emulator path is spelled out end to end: it is the one every platform
#: gets wrong (a bare "install Android Studio" leaves no AVD to boot into).
_SETUP_COMMANDS: dict[str, dict[str, tuple[str, ...]]] = {
    HOST_WINDOWS: {
        "base": (
            '# Windows PowerShell — Android Studio brings the SDK, JDK and emulator',
            'winget install Google.AndroidStudio',
            '$sdk = "$env:LOCALAPPDATA\\Android\\Sdk"',
            '& "$sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat" --licenses',
            '& "$sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat" "platform-tools" "emulator" "platforms;android-35" "system-images;android-35;google_apis;x86_64"',
            '& "$sdk\\cmdline-tools\\latest\\bin\\avdmanager.bat" create avd -n crusor -k "system-images;android-35;google_apis;x86_64" -d pixel_7',
            '# Then confirm this tool sees everything (no PATH edits needed):',
            'python -m scripts.targets_doctor --require android',
        ),
        "accelerated": (
            '# Hardware acceleration: Windows Hypervisor Platform (needs a reboot)',
            'dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart',
        ),
    },
    HOST_MACOS: {
        "base": (
            '# macOS — command line tools, then the same SDK steps',
            'brew install --cask android-commandlinetools',
            'export ANDROID_HOME="$HOME/Library/Android/sdk"',
            'sdkmanager --licenses',
            'sdkmanager "platform-tools" "emulator" "platforms;android-35" "system-images;android-35;google_apis;arm64-v8a"',
            'avdmanager create avd -n crusor -k "system-images;android-35;google_apis;arm64-v8a" -d pixel_7',
            'python -m scripts.targets_doctor --require android',
        ),
    },
    HOST_LINUX: {
        "base": (
            '# Linux — KVM is required for an emulator worth waiting for',
            'sudo apt install openjdk-21-jdk android-sdk-platform-tools android-sdk adb',
            'ls -l /dev/kvm || echo "no /dev/kvm: enable virtualization in BIOS, or use a physical device"',
            'sdkmanager --licenses',
            'sdkmanager "platform-tools" "emulator" "platforms;android-35" "system-images;android-35;google_apis;x86_64"',
            'avdmanager create avd -n crusor -k "system-images;android-35;google_apis;x86_64" -d pixel_7',
            'python -m scripts.targets_doctor --require android',
        ),
    },
}


def _setup_plan(targets: list[str]) -> int:
    """Print the shortest honest path from this host to a runnable target.

    Only the tools the requested target actually needs are reported, and only when
    they are missing: a page of instructions for hardware you already have is how
    a setup guide stops being read.
    """
    host = host_platform()
    wanted = [name.strip().lower() for name in (targets or ["android"]) if name.strip()]
    exit_code = 0
    print(f"Setup plan — host {host}")
    print("=" * 62)
    for name in wanted:
        try:
            readiness = target_readiness(targets=[name]).get(name) or {}
        except Exception as exc:  # unknown target id
            print(f"\n⛔ unknown target {name!r}: {exc}")
            exit_code = 2
            continue
        missing = [str(tool_id) for tool_id in (readiness.get("missing") or ())]
        ready = readiness.get("ready")
        mark = "✅" if ready else "⛔"
        reason = readiness.get("host_reason") if not readiness.get("host_supported", True) else ""
        summary = "ready" if ready else (reason or f"missing {', '.join(missing)}" if missing else "not ready")
        print(f"\n{mark} {name}: {summary}")
        if ready:
            print("   Nothing to install. Prove it:  python -m scripts.targets_doctor --require " + name)
            continue
        if not readiness.get("host_supported", True):
            print("   This host cannot run it at all — no command fixes that. See the limits section of docs/MULTI_PLATFORM_TARGETS.md.")
            exit_code = 1
            continue
        exit_code = 1
        for tool_id in missing:
            spec = TOOLS_BY_ID.get(tool_id)
            if spec is None:
                continue
            print(f"   missing: {tool_id:<12} {spec.hint_for(host) or spec.label}")
        commands = _SETUP_COMMANDS.get(host, {})
        for block in ("base", "accelerated"):
            lines = commands.get(block)
            if not lines:
                continue
            if block == "accelerated" and name != "android":
                continue
            print()
            for line in lines:
                print(f"   {line}" if line.startswith("#") else f"     {line}")
    return exit_code


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
    parser.add_argument(
        "--setup", nargs="*", metavar="TARGET",
        help="copy-paste install plan for a target's missing tools "
             "(default target: android), and exit non-zero while it is incomplete",
    )
    args = parser.parse_args(argv)

    if args.setup is not None:
        return _setup_plan(list(args.setup))

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

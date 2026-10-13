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
    TARGET_REQUIREMENTS,
    TOOLS_BY_ID,
    doctor_report,
    host_platform,
    target_readiness,
)


#: Per-target copy/paste recipes. Generic tools (Flutter, Rust, .NET, etc.)
#: do not share one install command; never print Android instructions for an
#: unrelated target. Android is the one end-to-end bootstrap because the
#: Windows SDK/AVD layout is especially easy to get wrong.
_SETUP_COMMANDS: dict[tuple[str, str], dict[str, tuple[str, ...]]] = {
    (HOST_WINDOWS, "android"): {
        "base": (
            '# Windows PowerShell — Android CLI + SDK only; Android Studio is NOT required',
            '# Install the JDK and Android CLI; close/reopen PowerShell after winget finishes.',
            'winget install --id Microsoft.OpenJDK.21 --exact',
            'winget install --id Google.AndroidCLI --exact',
            '# In a NEW PowerShell window, use the standard per-user Android SDK location:',
            r'$sdk = "$env:LOCALAPPDATA\Android\Sdk"',
            '$env:ANDROID_HOME = $sdk',
            '$env:ANDROID_SDK_ROOT = $sdk',
            '[Environment]::SetEnvironmentVariable("ANDROID_HOME", $sdk, "User")',
            '[Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $sdk, "User")',
            'android "--sdk=$sdk" init',
            'android "--sdk=$sdk" sdk install platform-tools emulator cmdline-tools/latest platforms/android-35 build-tools/35.0.0 system-images/android-35/google_apis/x86_64',
            r'& "$sdk\cmdline-tools\latest\bin\sdkmanager.bat" --licenses',
            r'echo no | & "$sdk\cmdline-tools\latest\bin\avdmanager.bat" create avd -n crusor -k "system-images;android-35;google_apis;x86_64" -d pixel_7',
            '# The Android CLI emulator subcommand is currently disabled on Windows; start the SDK emulator directly.',
            r'& "$sdk\emulator\emulator.exe" -accel-check',
            'python -m scripts.targets_doctor --require android',
        ),
        "accelerated": (
            '# Run as Administrator; enables Windows Hypervisor Platform. Reboot afterwards.',
            'dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart',
        ),
    },
    (HOST_MACOS, "android"): {
        "base": (
            '# macOS — Android CLI + SDK; no Android Studio required',
            'brew install openjdk@21',
            '# Apple Silicon: use darwin_arm64; Intel Macs: replace with darwin_x86_64.',
            'curl -fsSL https://dl.google.com/android/cli/latest/darwin_arm64/install.sh | bash',
            'android init',
            'android sdk install platform-tools emulator cmdline-tools/latest platforms/android-35 build-tools/35.0.0 system-images/android-35/google_apis/arm64-v8a',
            'sdkmanager --licenses',
            'avdmanager create avd -n crusor -k "system-images;android-35;google_apis;arm64-v8a" -d pixel_7',
            'python -m scripts.targets_doctor --require android',
        ),
    },
    (HOST_LINUX, "android"): {
        "base": (
            '# Linux — Android CLI + SDK; no Android Studio required',
            'sudo apt install openjdk-21-jdk',
            'curl -fsSL https://dl.google.com/android/cli/latest/linux_x86_64/install.sh | bash',
            'android init',
            'android sdk install platform-tools emulator cmdline-tools/latest platforms/android-35 build-tools/35.0.0 system-images/android-35/google_apis/x86_64',
            'sdkmanager --licenses',
            'avdmanager create avd -n crusor -k "system-images;android-35;google_apis;x86_64" -d pixel_7',
            'ls -l /dev/kvm || echo "no /dev/kvm: enable virtualization in BIOS or use a physical device"',
            'python -m scripts.targets_doctor --require android',
        ),
    },
    (HOST_WINDOWS, "ios"): {
        "base": (
            '# Windows cannot build an Xcode project or run the iOS Simulator.',
            '# This installs only the optional physical-device path for a prebuilt IPA:',
            'python -m pip install pymobiledevice3',
            '# Build and Simulator verification still require a macOS host with full Xcode.',
        ),
    },
    (HOST_LINUX, "ios"): {
        "base": (
            '# Linux cannot build an Xcode project or run the iOS Simulator.',
            '# This installs only the optional physical-device path for a prebuilt IPA:',
            'python -m pip install pymobiledevice3',
            '# Build and Simulator verification still require a macOS host with full Xcode.',
        ),
    },
    (HOST_MACOS, "ios"): {
        "base": (
            '# macOS — install full Xcode from the App Store (Command Line Tools alone do not include Simulator).',
            'xcode-select --install',
            'sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer',
            'sudo xcodebuild -license accept',
            '# CocoaPods is needed only when this project has a Podfile:',
            'sudo gem install cocoapods',
        ),
    },
    (HOST_WINDOWS, "flutter"): {
        "base": ('# Install Flutter for Windows: https://docs.flutter.dev/get-started/install/windows',
                 '# For Android targets, run: python -m scripts.targets_doctor --setup android'),
    },
    (HOST_MACOS, "flutter"): {
        "base": ('# Install Flutter for macOS: https://docs.flutter.dev/get-started/install/macos',
                 '# Then install the platform SDK required by this project (Android or Xcode).'),
    },
    (HOST_LINUX, "flutter"): {
        "base": ('# Install Flutter for Linux: https://docs.flutter.dev/get-started/install/linux',
                 '# For Android targets, run: python -m scripts.targets_doctor --setup android'),
    },
    (HOST_WINDOWS, "react-native"): {
        "base": ('winget install --id OpenJS.NodeJS.LTS --exact',
                 'winget install --id Microsoft.OpenJDK.21 --exact',
                 '# Reopen PowerShell, then run: python -m scripts.targets_doctor --setup android'),
    },
    (HOST_MACOS, "react-native"): {
        "base": ('brew install node@22 openjdk@21',
                 '# iOS builds/tests additionally require full Xcode and CocoaPods.'),
    },
    (HOST_LINUX, "react-native"): {
        "base": ('sudo apt install nodejs npm openjdk-21-jdk',
                 '# For Android targets, run: python -m scripts.targets_doctor --setup android'),
    },
    (HOST_WINDOWS, "desktop"): {
        "base": ('winget install --id OpenJS.NodeJS.LTS --exact',
                 '# Tauri also needs Rust + Microsoft C++ Build Tools; Wails needs Go; .NET apps need the .NET SDK.',
                 '# Use --setup tauri, --setup wails, or --setup dotnet-desktop for the shell-specific hints.'),
    },
    (HOST_MACOS, "desktop"): {
        "base": ('brew install node@22',
                 '# Tauri needs rustup; Wails needs Go; .NET apps need the .NET SDK.'),
    },
    (HOST_LINUX, "desktop"): {
        "base": ('sudo apt install nodejs npm',
                 '# Tauri also needs Rust and WebKitGTK build dependencies; Wails needs Go.'),
    },
    (HOST_WINDOWS, "tauri"): {
        "base": ('winget install --id OpenJS.NodeJS.LTS --exact',
                 'winget install --id Rustlang.Rustup --exact',
                 '# Also install Microsoft C++ Build Tools (Desktop development with C++).'),
    },
    (HOST_MACOS, "tauri"): {
        "base": ('brew install node@22 rustup', 'rustup-init'),
    },
    (HOST_LINUX, "tauri"): {
        "base": ('sudo apt install nodejs npm build-essential libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev',
                 'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh'),
    },
    (HOST_WINDOWS, "wails"): {
        "base": ('winget install --id GoLang.Go --exact',
                 'go install github.com/wailsapp/wails/v2/cmd/wails@latest'),
    },
    (HOST_MACOS, "wails"): {
        "base": ('brew install go', 'go install github.com/wailsapp/wails/v2/cmd/wails@latest'),
    },
    (HOST_LINUX, "wails"): {
        "base": ('sudo apt install golang-go', 'go install github.com/wailsapp/wails/v2/cmd/wails@latest'),
    },
    (HOST_WINDOWS, "dotnet-desktop"): {
        "base": ('winget install --id Microsoft.DotNet.SDK.10 --exact',),
    },
    (HOST_MACOS, "dotnet-desktop"): {
        "base": ('Install the .NET SDK for macOS: https://dotnet.microsoft.com/download',),
    },
    (HOST_LINUX, "dotnet-desktop"): {
        "base": ('Install the .NET SDK for Linux: https://dotnet.microsoft.com/download',),
    },
}


def _configure_console_output() -> None:
    """Keep status icons from crashing on legacy Windows console encodings.

    CPython's Windows stdout/stderr may use cp1252, which cannot encode the
    status icons in the report. ``backslashreplace`` preserves readable output
    (and leaves Unicode intact on UTF-8 terminals) instead of raising while the
    setup plan is being printed. Streams such as pytest's capture wrappers do
    not always expose ``reconfigure``; those are left untouched.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, TypeError, ValueError):
            # Some embedded or already-used streams cannot be reconfigured.
            # Do not make diagnostics less usable by failing before the report.
            continue


def _setup_plan(targets: list[str]) -> int:
    """Print a host- and target-specific setup recipe, without installing it."""
    host = host_platform()
    wanted = [name.strip().lower() for name in (targets or ["android"]) if name.strip()]
    exit_code = 0
    print(f"Setup plan — host {host}")
    print("=" * 62)
    for name in wanted:
        # Some aliases also have a more precise readiness row (e.g. tauri,
        # electron, ios-device); keep that instead of flattening everything to
        # the provider id. Other friendly names resolve through the registry.
        target_id = name
        if target_id not in TARGET_REQUIREMENTS:
            provider = registry.get_provider(name)
            target_id = provider.id if provider else ""
        if not target_id:
            print(f"\n⛔ unknown target {name!r}. Known targets: {', '.join(sorted(TARGET_REQUIREMENTS))}")
            exit_code = 2
            continue
        try:
            readiness = target_readiness(targets=[target_id]).get(target_id) or {}
        except Exception as exc:  # unknown/broken target readiness
            print(f"\n⛔ unknown target {name!r}: {exc}")
            exit_code = 2
            continue
        if not readiness:
            print(f"\n⛔ no readiness data for {target_id!r}")
            exit_code = 2
            continue

        missing = list(dict.fromkeys(str(tool_id) for tool_id in (readiness.get("missing") or ())))
        # `android` can build against a USB phone with adb+Java, but this
        # workstation setup plan explicitly provisions the requested emulator
        # path and Google's agent-facing CLI too. Neither is a runtime
        # requirement for a phone-only build.
        if target_id == "android":
            for tool_id in readiness.get("optional_missing") or ():
                tool_id = str(tool_id)
                if tool_id in {"android-cli", "emulator", "sdkmanager", "avdmanager"} and tool_id not in missing:
                    missing.append(tool_id)
        ready = bool(readiness.get("ready")) and not missing
        supported = bool(readiness.get("host_supported", True))
        reason = str(readiness.get("host_reason") or "")
        summary = "ready" if ready else (reason if not supported else f"missing {', '.join(missing)}" if missing else "not ready")
        mark = "✅" if ready else "⛔"
        print(f"\n{mark} {target_id}: {summary}")
        if not supported:
            print("   This host cannot run it at all — no command fixes that. See docs/MULTI_PLATFORM_TARGETS.md.")
            exit_code = 1
            continue
        if reason:
            print(f"   path: {reason}")
        if ready:
            print("   Nothing to install. Prove it:  python -m scripts.targets_doctor --require " + target_id)
            continue

        exit_code = 1
        for tool_id in missing:
            spec = TOOLS_BY_ID.get(tool_id)
            if spec is not None:
                print(f"   missing: {tool_id:<14} {spec.hint_for(host) or spec.label}")
        commands = _SETUP_COMMANDS.get((host, target_id), {})
        for block in ("base", "accelerated"):
            lines = commands.get(block)
            if not lines:
                continue
            if block == "accelerated" and target_id != "android":
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
    _configure_console_output()
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

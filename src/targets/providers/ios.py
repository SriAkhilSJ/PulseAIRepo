"""iOS target provider — honest about what a host can actually do.

Apple's toolchain gates this platform, and no abstraction removes that gate:

* **macOS + Xcode** — the supported path. Build for the Simulator, boot it,
  install, launch, screenshot, and read the unified log. This is what
  ``docs/pipelines/ios.yml`` runs on a ``macos-*`` runner.
* **Linux / Windows** — you cannot build an Xcode project and cannot run a
  Simulator. Two real options exist and both are supported here as *explicit,
  labelled* paths: prove a **physical device** with ``pymobiledevice3``
  (install/launch/screenshot of an already-built ``.ipa``/``.app``), or run the
  build on a cloud Mac (GitHub macOS runner, MacStadium, Scaleway Apple
  silicon, Codemagic, Bitrise, Xcode Cloud).

The provider never pretends the second case is equivalent: the receipt says
exactly how deep the proof went.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from src.targets.contract import (
    KIND_CLEANUP,
    KIND_LAUNCH,
    KIND_PROBE,
    RunPlan,
    Stage,
    TargetReceipt,
)
from src.targets.detect import (
    TargetCandidate,
    any_path,
    ios_bundle_id,
    ios_scheme,
)
from src.targets.evidence import scan_crashes, screenshot_quality
from src.targets.providers.base import (
    PlanUnavailable,
    TargetProvider,
    artifact_for_evidence,
    evidence_path,
    tool_path,
)
from src.targets.runner import RunOutcome, TargetRequest
from src.targets.toolchain import HOST_MACOS, host_platform

APP_BUNDLE_PATTERNS: tuple[str, ...] = (
    "build/ios/iphonesimulator/*.app",
    "**/Build/Products/Debug-iphonesimulator/*.app",
    "build/ios/iphoneos/*.app",
    "**/Build/Products/Debug-iphoneos/*.app",
)
IPA_PATTERNS: tuple[str, ...] = ("build/ios/ipa/*.ipa", "*.ipa", "build/**/*.ipa")
JUNIT_PATTERNS: tuple[str, ...] = ("**/TestResults/*.xml", "**/*.xcresult/**/*.xml")


def _run(argv: list[str], *, timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"
    except (OSError, FileNotFoundError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")


# --------------------------------------------------------------------------- #
# resolvers
# --------------------------------------------------------------------------- #


def resolve_simulator(workspace: Path, request: TargetRequest, tokens: dict[str, str]) -> str:
    """A booted-capable simulator UDID: explicit request → env → first iPhone."""
    requested = (request.device or os.environ.get("CRUSORAI_IOS_SIMULATOR", "")).strip()
    if requested:
        return requested
    xcrun = tool_path("xcrun", fallback="xcrun")
    code, out = _run([xcrun, "simctl", "list", "devices", "available", "--json"], timeout=60)
    if code == 0:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = {}
        devices = data.get("devices") if isinstance(data, dict) else {}
        for runtime in sorted(devices or {}, reverse=True):
            if "iOS" not in runtime:
                continue
            for device in devices.get(runtime) or []:
                name = str(device.get("name") or "")
                if "iPhone" in name and device.get("udid"):
                    return str(device["udid"])
    raise RuntimeError(
        "no iOS Simulator is available — install a simulator runtime in Xcode "
        "(Settings → Components), or pass device=<UDID>"
    )


def resolve_app_bundle(workspace: Path, request: TargetRequest, tokens: dict[str, str]) -> str:
    from src.targets.providers.base import newest_file

    app = newest_file(workspace, APP_BUNDLE_PATTERNS, suffixes=(".app",))
    if app:
        return app
    ipa = newest_file(workspace, IPA_PATTERNS, suffixes=(".ipa",))
    if ipa:
        return ipa
    raise RuntimeError(
        "no built .app/.ipa found under build/ (or Build/Products) — run the build stage "
        "first, or point the plan at an artifact with an explicit path"
    )


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #


def simulator_booted(ctx: dict) -> tuple[int, str]:
    """Block until the simulator reports ``booted`` (``simctl bootstatus -b``)."""
    tokens = dict(ctx.get("tokens") or {})
    args = {str(k): str(v) for k, v in dict(ctx.get("args") or {}).items()}
    token = str(args.get("simulator") or tokens.get("sim") or "").strip()
    if not token:
        return 1, "simulator UDID unresolved"
    xcrun = tool_path("xcrun", fallback="xcrun")
    code, out = _run([xcrun, "simctl", "bootstatus", token, "-b"], timeout=300)
    state = "booted" if code == 0 else "not booted"
    return (0 if code == 0 else 1), f"simulator {state}: {out.strip()[-400:]}"


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #


class IOSProvider(TargetProvider):
    id = "ios"
    label = "iOS app (Xcode/simctl on macOS, pymobiledevice3 for devices)"
    requires = ("xcrun", "xcodebuild")
    recommended = ("pod", "idevicesyslog")

    RESOLVERS = {
        "sim": "src.targets.providers.ios:resolve_simulator",
        "app": "src.targets.providers.ios:resolve_app_bundle",
    }

    # ---- host ----------------------------------------------------------- #

    def host_support(self, host: str | None = None) -> tuple[bool, str]:
        resolved = host_platform(host)
        if resolved == HOST_MACOS:
            return True, ""
        from src.targets.toolchain import probe

        statuses = probe(resolved)
        device_tool = statuses.get("pymobiledevice3")
        if device_tool is not None and device_tool.available:
            return True, (
                "physical-device only: Xcode project builds and the iOS Simulator require macOS. "
                "This host can install/launch an already-built .ipa via pymobiledevice3."
            )
        return False, (
            "iOS build/verify requires macOS + Xcode (xcodebuild/simctl). On Linux/Windows: "
            "install pymobiledevice3 to prove an already-built .ipa on a physical device, or run "
            "the iOS job on a macOS runner / cloud Mac (docs/pipelines/ios.yml)."
        )

    def requirements(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        if host_platform() == HOST_MACOS:
            return self.requires
        return ("pymobiledevice3",)

    # ---- detection ------------------------------------------------------ #

    def detect(self, workspace: str | Path) -> list[TargetCandidate]:
        root = Path(workspace)
        projects = any_path(root, (
            "*.xcodeproj", "*.xcworkspace", "ios/*.xcodeproj", "ios/*.xcworkspace",
        ))
        podfile = any_path(root, ("Podfile", "ios/Podfile"))
        info_plists = any_path(root, ("*/Info.plist", "ios/*/Info.plist", "**/Info.plist"))
        if not projects and not podfile:
            return []
        confidence = 0.95 if projects else 0.6
        details = {
            "scheme": ios_scheme(root),
            "podfile": podfile[0] if podfile else "",
            "project": projects[0] if projects else "",
            "swiftpm": bool(any_path(root, ("Package.swift",))),
        }
        return [TargetCandidate(
            target=self.id, label=self.label, confidence=confidence,
            evidence=tuple(projects[:2]) + tuple(podfile[:1]) + tuple(info_plists[:1]),
            app_id=ios_bundle_id(root), details=details,
        )]

    # ---- planning ------------------------------------------------------- #

    def plan(self, workspace: str | Path, request: TargetRequest) -> RunPlan:
        root = Path(workspace)
        host = host_platform()
        detected = self.detect(root)
        app_id = request.app_id or (detected[0].app_id if detected else "")
        if host == HOST_MACOS:
            return self._simulator_plan(root, request, app_id)
        return self._device_plan(root, request, app_id)

    def _simulator_plan(self, root: Path, request: TargetRequest, app_id: str) -> RunPlan:
        detected = self.detect(root)
        details = detected[0].details if detected else {}
        scheme = str(details.get("scheme") or root.name)
        project = str(details.get("project") or "")
        stages: list[Stage] = []
        podfile = str(details.get("podfile") or "")
        if podfile:
            stages.append(Stage(
                name="pods", kind="build", required=False, timeout_s=900,
                cwd=str(Path(podfile).parent) if Path(podfile).parent != Path(".") else ".",
                argv=(tool_path("pod", fallback="pod"), "install"),
                note="CocoaPods projects need a resolved Pods directory before xcodebuild",
            ))
        container: list[str] = []
        if project.endswith(".xcworkspace"):
            container = ["-workspace", project]
        elif project:
            container = ["-project", project]
        build_argv = [
            tool_path("xcodebuild", fallback="xcodebuild"),
            *container,
            "-scheme", scheme,
            "-configuration", os.environ.get("CRUSORAI_IOS_CONFIGURATION", "Debug"),
            "-sdk", "iphonesimulator",
            "-destination", "platform=iOS Simulator,id={sim}",
            "-derivedDataPath", "build/ios-derived",
            "CODE_SIGNING_ALLOWED=NO",
            "build",
        ]
        stages.extend([
            Stage(name="build", kind="build", timeout_s=3600, argv=tuple(build_argv),
                  artifact_globs=APP_BUNDLE_PATTERNS, note=f"xcodebuild -scheme {scheme}"),
        ])
        if request.mode == "build":
            return RunPlan(target=self.id, provider=self.id, stages=tuple(stages),
                           app_id=app_id, requires=self.requirements(root, request),
                           notes=(f"scheme={scheme}", "simulator build only (CODE_SIGNING_ALLOWED=NO)"))
        if not app_id:
            raise PlanUnavailable(
                "no iOS bundle identifier found — add PRODUCT_BUNDLE_IDENTIFIER to the target, "
                "or pass app_id explicitly"
            )
        stages.extend(self.device_stages(
            container=container, scheme=scheme, request=request, app_id=app_id,
        ))
        notes = [f"scheme={scheme}", "simulator proof on macOS"]
        if details.get("swiftpm"):
            notes.append("SwiftPM project: `swift build` works on any host, but UIKit/SwiftUI "
                         "targets still need the iOS SDK (Xcode) to link")
        return RunPlan(target=self.id, provider=self.id, stages=tuple(stages), app_id=app_id,
                       requires=self.requirements(root, request), notes=tuple(notes))

    def device_stages(self, *, container: list[str], scheme: str,
                      request: TargetRequest, app_id: str) -> list[Stage]:
        """Boot → install → launch → capture, on the Simulator.

        Factored out so framework providers (Flutter, React Native) can reuse the
        exact same proof after producing their own ``.app`` bundle.
        """
        xcrun = tool_path("xcrun", fallback="xcrun")
        stages: list[Stage] = [
            Stage(name="boot_simulator", kind=KIND_PROBE, required=False, timeout_s=240,
                  argv=(xcrun, "simctl", "boot", "{sim}")),
            Stage(name="simulator_ready", kind=KIND_PROBE, required=True, timeout_s=360,
                  argv=(), handler="src.targets.providers.ios:simulator_booted"),
            Stage(name="install", kind="install", required=True, timeout_s=600,
                  argv=(xcrun, "simctl", "install", "{sim}", "{app}")),
            Stage(name="launch", kind=KIND_LAUNCH, required=True, timeout_s=180,
                  argv=(xcrun, "simctl", "launch", "--terminate-running-process", "{sim}", "{app_id}")),
            Stage(name="settle", kind=KIND_PROBE, argv=(), handler="src.targets.probes:sleep",
                  env=(("seconds", "5"),)),
            Stage(name="screenshot", kind=KIND_PROBE, required=False, timeout_s=180,
                  argv=(xcrun, "simctl", "io", "{sim}", "screenshot", "{artifacts}/screen.png")),
            Stage(name="screenshot_quality", kind=KIND_PROBE, required=False, argv=(),
                  handler="src.targets.probes:screenshot_quality", env=(("file", "screen.png"),)),
            Stage(name="process_alive", kind=KIND_PROBE, required=False, timeout_s=60,
                  argv=(xcrun, "simctl", "spawn", "{sim}", "launchctl", "list", "{app_id}")),
            Stage(name="logs", kind=KIND_PROBE, required=False, timeout_s=180,
                  argv=(xcrun, "simctl", "spawn", "{sim}", "log", "show", "--last", "45s",
                        "--style", "compact")),
        ]
        if request.mode == "test":
            stages.append(Stage(
                name="xctest", kind="test", timeout_s=3600,
                argv=(tool_path("xcodebuild", fallback="xcodebuild"), *container, "-scheme", scheme,
                      "-destination", "platform=iOS Simulator,id={sim}",
                      "-resultBundlePath", "build/ios-tests.xcresult", "test"),
                artifact_globs=JUNIT_PATTERNS,
            ))
        if not request.keep_running:
            stages.append(Stage(name="cleanup", kind=KIND_CLEANUP, required=False, timeout_s=120,
                                argv=(xcrun, "simctl", "terminate", "{sim}", "{app_id}")))
        return stages

    def _device_plan(self, root: Path, request: TargetRequest, app_id: str) -> RunPlan:
        """Physical-device path for Linux/Windows (needs a prebuilt ipa/app)."""
        stages = [
            Stage(name="device_list", kind=KIND_PROBE, required=False, timeout_s=60,
                  argv=(tool_path("pymobiledevice3", fallback="pymobiledevice3"), "usbmux", "list")),
            Stage(name="install", kind="install", required=True, timeout_s=900,
                  argv=(tool_path("pymobiledevice3", fallback="pymobiledevice3"), "apps", "install",
                        "{app}")),
            # Launch support varies across pymobiledevice3 releases, so the stage
            # is explicit and optional instead of pretending to be reliable.
            Stage(name="launch", kind=KIND_LAUNCH, required=False, timeout_s=180,
                  argv=(tool_path("pymobiledevice3", fallback="pymobiledevice3"), "developer", "dvt",
                        "launch", "{app_id}")),
            Stage(name="settle", kind=KIND_PROBE, argv=(), handler="src.targets.probes:sleep",
                  env=(("seconds", "5"),)),
            Stage(name="screenshot", kind=KIND_PROBE, required=False, timeout_s=120,
                  argv=(tool_path("idevicescreenshot", fallback="idevicescreenshot"),
                        "{artifacts}/screen.png")),
            Stage(name="screenshot_quality", kind=KIND_PROBE, required=False, argv=(),
                  handler="src.targets.probes:screenshot_quality", env=(("file", "screen.png"),)),
        ]
        notes = (
            "PHYSICAL-DEVICE / best-effort path: this host cannot run xcodebuild or a Simulator.",
            "For the supported proof, run the iOS job on macOS (docs/pipelines/ios.yml) or a cloud Mac.",
            "Build the .ipa elsewhere (Xcode, EAS, or `xtool build` for SwiftPM projects) and keep it "
            "under build/ios/ipa/ so this plan can install it.",
        )
        return RunPlan(target=self.id, provider=self.id, stages=tuple(stages), app_id=app_id,
                       requires=self.requirements(root, request), notes=notes)

    # ---- interpretation ------------------------------------------------ #

    def interpret(self, workspace: str | Path, request: TargetRequest,
                  outcome: RunOutcome) -> TargetReceipt:
        receipt = super().interpret(workspace, request, outcome)
        app_id = outcome.plan.app_id
        receipt.app_id = app_id
        if host_platform() != HOST_MACOS:
            receipt.notes.append(
                "device-path verification: build provenance is NOT proven by this host "
                "(no xcodebuild) — CI on macOS is the source of truth"
            )

        screenshot = artifact_for_evidence(outcome, "screen.png", "screenshot")
        if screenshot:
            receipt.artifacts.append(screenshot)
            receipt.visual_quality = screenshot_quality(evidence_path(outcome, "screen.png"))

        logs = outcome.output_of("logs")
        receipt.crash_findings = scan_crashes(logs, "ios", app_id=app_id)

        launch_output = outcome.output_of("launch")
        if launch_output:
            receipt.notes.append(f"launch: {launch_output.strip().splitlines()[0][:200]}")
        if request.assertions:
            receipt.notes.append(
                "text/selector assertions on iOS need XCTest/XCUITest (run the xctest stage) or a "
                "Maestro flow — the screenshot is the only UI proof this plan can capture: "
                + ", ".join(f"{kind}={value}" for kind, value in request.assertions)
            )
        return receipt


__all__ = [
    "APP_BUNDLE_PATTERNS", "IOSProvider", "IPA_PATTERNS", "resolve_app_bundle",
    "resolve_simulator", "simulator_booted",
]

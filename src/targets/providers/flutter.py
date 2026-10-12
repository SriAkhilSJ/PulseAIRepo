"""Flutter provider: one framework, several real targets.

Flutter is the clearest case for the framework→platform delegation pattern.
The framework owns *building* (``flutter build <target>``), while the proof
still belongs to the platform: an APK must be installed and launched on a
device (Android provider), an ``.app`` must run in the Simulator (iOS
provider), and a desktop build must open a window (desktop provider).

Handoff map (``CRUSORAI_FLUTTER_TARGET`` selects explicitly):

===============  ==========================================  ==========================
Flutter target   Build stage                                 Proof stages from
===============  ==========================================  ==========================
``android``      ``flutter build apk --debug``                ``AndroidProvider``
``ios``          ``flutter build ios --simulator --debug``    ``IOSProvider`` (macOS)
``windows`` /    ``flutter build <desktop> --debug``          ``DesktopProvider`` binary
``linux`` /                                                   launch + liveness
``macos``
===============  ==========================================  ==========================

``flutter test`` (widget tests) is appended in ``test`` mode; integration
tests belong to ``flutter drive``/``integration_test`` on a real device.
"""
from __future__ import annotations

import os
from pathlib import Path

from src.targets.contract import (
    KIND_LAUNCH,
    KIND_PROBE,
    RunPlan,
    Stage,
    TargetReceipt,
)
from src.targets.detect import (
    TargetCandidate,
    android_app_id,
    android_manifest_paths,
    ios_bundle_id,
    ios_scheme,
    read_text,
)
from src.targets.providers.android import AndroidProvider
from src.targets.providers.base import (
    PlanUnavailable,
    TargetProvider,
    read_evidence,
    tool_path,
)
from src.targets.providers.desktop import DesktopProvider
from src.targets.providers.ios import IOSProvider
from src.targets.runner import RunOutcome, TargetRequest
from src.targets.toolchain import HOST_MACOS, HOST_WINDOWS, host_platform

FLUTTER_APK_PATTERNS = ("build/app/outputs/flutter-apk/*.apk",)
FLUTTER_APP_PATTERNS = ("build/ios/iphonesimulator/*.app",)

_DESKTOP_TARGETS = {
    HOST_WINDOWS: "windows",
    "macos": "macos",
    "linux": "linux",
}


def _default_target(root: Path) -> str:
    override = os.environ.get("CRUSORAI_FLUTTER_TARGET", "").strip().lower()
    if override in ("android", "ios", "windows", "linux", "macos", "web"):
        return override
    if (root / "android").is_dir():
        return "android"
    host = host_platform()
    if (root / host).is_dir() or (root / "windows").is_dir():
        return _DESKTOP_TARGETS.get(host, "linux")
    if (root / "ios").is_dir():
        return "ios"
    return "android"


class FlutterProvider(TargetProvider):
    id = "flutter"
    label = "Flutter app (Android / iOS / desktop)"
    kind = "framework"
    requires = ("flutter",)
    recommended = ("dart", "adb", "java", "emulator")

    def _flutter(self) -> str:
        return tool_path("flutter", fallback="flutter")

    # ---- detection ------------------------------------------------------ #

    def detect(self, workspace: str | Path) -> list[TargetCandidate]:
        root = Path(workspace)
        pubspec = root / "pubspec.yaml"
        main_dart = root / "lib/main.dart"
        if not pubspec.is_file() and not main_dart.is_file():
            return []
        text = read_text(root, "pubspec.yaml", limit=40_000)
        platforms = tuple(
            name for name in ("android", "ios", "web", "windows", "linux", "macos")
            if (root / name).is_dir()
        )
        details = {
            "platforms": platforms,
            "target": _default_target(root),
            "is_flutter": "flutter:" in text or "sdk: flutter" in text,
            "integration_test": (root / "integration_test").is_dir(),
        }
        app_id = (
            android_app_id(root, android_manifest_paths(root))
            or ios_bundle_id(root)
        )
        return [TargetCandidate(
            target=self.id, label=self.label,
            confidence=0.9 if details["is_flutter"] else 0.7,
            evidence=tuple(item for item in ("pubspec.yaml", "lib/main.dart") if (root / item).is_file()),
            framework="flutter", app_id=app_id, details=details,
            host_supported=details["target"] != "ios" or host_platform() == HOST_MACOS,
        )]

    # ---- planning ------------------------------------------------------- #

    def requirements(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        root = Path(workspace)
        target = _default_target(root)
        needs = ["flutter"]
        if target == "android":
            needs.extend(AndroidProvider().requirements(root, request))
        elif target == "ios":
            needs.extend(IOSProvider().requirements(root, request))
        return tuple(dict.fromkeys(needs))

    def plan(self, workspace: str | Path, request: TargetRequest) -> RunPlan:
        root = Path(workspace)
        target = _default_target(root)
        detected = self.detect(root)
        app_id = request.app_id or (detected[0].app_id if detected else "")
        stages: list[Stage] = [
            Stage(name="pub_get", kind="build", required=False, timeout_s=900,
                  argv=(self._flutter(), "pub", "get"),
                  note="dependency resolution receipt (the build stage needs it anyway)"),
        ]
        notes: list[str] = [f"flutter target={target}"]

        if target == "android":
            stages.append(Stage(
                name="build", kind="build", required=True, timeout_s=3600,
                argv=(self._flutter(), "build", "apk", "--debug"),
                artifact_globs=FLUTTER_APK_PATTERNS,
                note="Flutter debug APK (Metro-equivalent: the Dart bundle is embedded)",
            ))
            stages.append(Stage(
                name="dart_analyze", kind="build", required=False, timeout_s=900,
                argv=(self._flutter(), "analyze", "--no-pub"),
                note="static analysis; failures are reported but do not hide runtime proof",
            ))
            if request.mode != "build":
                if not app_id:
                    raise PlanUnavailable(
                        "no Android application id found for this Flutter project — check "
                        "android/app/build.gradle(.kts) applicationId or pass app_id"
                    )
                android = AndroidProvider()
                stages.extend(android.device_stages(root, request, app_id=app_id))
                stages.extend(android.probe_stages(root, request))
        elif target == "ios":
            if host_platform() != HOST_MACOS:
                raise PlanUnavailable(
                    "Flutter iOS builds need macOS (Xcode). Run the iOS job on a macOS runner or "
                    "cloud Mac; docs/pipelines/flutter.yml shows the matrix."
                )
            stages.append(Stage(
                name="build", kind="build", required=True, timeout_s=3600,
                argv=(self._flutter(), "build", "ios", "--simulator", "--debug"),
                artifact_globs=FLUTTER_APP_PATTERNS,
            ))
            if request.mode != "build":
                if not app_id:
                    raise PlanUnavailable("no iOS bundle identifier found (ios/Runner.xcodeproj)")
                stages.extend(IOSProvider().device_stages(
                    container=[], scheme=ios_scheme(root), request=request, app_id=app_id,
                ))
        else:
            desktop_word = target if target in ("windows", "linux", "macos") else "windows"
            stages.append(Stage(
                name="build", kind="build", required=True, timeout_s=3600,
                argv=(self._flutter(), "build", desktop_word, "--debug"),
            ))
            if request.mode != "build":
                desktop = DesktopProvider()
                stages.append(Stage(
                    name="launch", kind=KIND_LAUNCH, background=True, required=True, timeout_s=180,
                    argv=tuple(desktop.launch_argv(["{exe}"])),
                ))
                stages.append(Stage(
                    name="process_alive", kind=KIND_PROBE, required=True, timeout_s=90,
                    argv=(), handler="src.targets.probes:process_alive",
                    env=(("name", "launch"), ("timeout_s", "25")),
                ))
                notes.append(
                    "Flutter desktop shells embed the Dart VM: for element-level assertions use "
                    "`flutter test`/integration_test, or the platform accessibility APIs"
                )

        if request.mode == "test":
            stages.append(Stage(
                name="widget_tests", kind="test", required=True, timeout_s=1800,
                argv=(self._flutter(), "test", "--reporter", "expanded"),
                artifact_globs=("test/**/*.dart",),
            ))
        return RunPlan(
            target=self.id, provider=self.id, stages=tuple(stages), app_id=app_id,
            requires=self.requirements(root, request), notes=tuple(notes),
        )

    # ---- interpretation ------------------------------------------------ #

    def interpret(self, workspace: str | Path, request: TargetRequest,
                  outcome: RunOutcome) -> TargetReceipt:
        target = str(outcome.plan.notes[0]).split("=")[-1] if outcome.plan.notes else "android"
        base = {
            "android": AndroidProvider(),
            "ios": IOSProvider(),
        }.get(target, DesktopProvider())
        receipt = base.interpret(workspace, request, outcome)
        receipt.provider = self.id
        receipt.target = f"{self.id}:{target}"
        receipt.notes.append(f"flutter target={target} (framework build, platform proof)")

        analyze = outcome.output_of("dart_analyze")
        if analyze.strip():
            lowered = analyze.lower()
            if "issues found" in lowered or " error " in lowered:
                receipt.notes.append("flutter analyze reported issues:\n" + analyze.strip()[-800:])
        widget_tests = outcome.output_of("widget_tests")
        if widget_tests.strip():
            passed = "All tests passed" in widget_tests
            receipt.notes.append(
                "flutter test: " + ("all widget tests passed" if passed else "FAILURES reported")
            )
            if not passed:
                receipt.failed("widget_tests", "flutter test did not report all tests passing")
        evidence = read_evidence(outcome, "ui.xml")
        if evidence and target == "android":
            receipt.notes.append("uiautomator dump captured for Flutter's Android render surface")
        return receipt


__all__ = ["FlutterProvider", "FLUTTER_APK_PATTERNS", "FLUTTER_APP_PATTERNS"]

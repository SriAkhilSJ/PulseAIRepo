"""React Native / Expo provider.

React Native is a *framework over two native projects*: ``android/`` is a Gradle
project, ``ios/`` is an Xcode project. So this provider owns exactly two things
the platform providers cannot know:

1. **Metro** — a debug build loads its JavaScript bundle from the packager at
   runtime. Building and installing without Metro is a green build that shows a
   red screen, which is precisely the failure mode the platform providers are
   built to catch. The plan starts Metro in the background and probes
   ``/status`` before touching the device.
2. **Expo prebuild** — managed Expo projects have no ``android/`` directory
   until ``expo prebuild`` generates one.

Everything else (install, launch, foreground check, UI dump, logcat) is the
Android provider's job, unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

from src.targets.contract import KIND_PROBE, RunPlan, Stage, TargetReceipt
from src.targets.detect import (
    TargetCandidate,
    android_app_id,
    android_manifest_paths,
    expo_config,
    has_dependency,
    has_script,
    node_manifest,
    package_manager,
)
from src.targets.providers.android import AndroidProvider
from src.targets.providers.base import (
    PlanUnavailable,
    TargetProvider,
    npm_run_argv,
    tool_path,
)
from src.targets.providers.ios import IOSProvider
from src.targets.runner import RunOutcome, TargetRequest
from src.targets.toolchain import HOST_MACOS, host_platform

METRO_PORT_ENV = "CRUSORAI_METRO_PORT"
DEFAULT_METRO_PORT = "8081"


def metro_port() -> str:
    return os.environ.get(METRO_PORT_ENV, DEFAULT_METRO_PORT).strip() or DEFAULT_METRO_PORT


class ReactNativeProvider(TargetProvider):
    id = "react-native"
    label = "React Native / Expo app"
    kind = "framework"
    requires = ("node",)
    recommended = ("npm", "adb", "java", "emulator", "maestro")

    def _is_expo(self, root: Path) -> bool:
        return bool(expo_config(root)) or (root / "app.config.js").is_file() \
            or (root / "app.config.ts").is_file()

    # ---- detection ------------------------------------------------------ #

    def detect(self, workspace: str | Path) -> list[TargetCandidate]:
        root = Path(workspace)
        manifest = node_manifest(root)
        if not manifest:
            return []
        rn = has_dependency(manifest, "react-native")
        expo = has_dependency(manifest, "expo")
        if not (rn or expo):
            return []
        config = expo_config(root) if expo else {}
        android_cfg = config.get("android") if isinstance(config.get("android"), dict) else {}
        ios_cfg = config.get("ios") if isinstance(config.get("ios"), dict) else {}
        app_id = (
            str((android_cfg or {}).get("package") or "")
            or str((ios_cfg or {}).get("bundleIdentifier") or "")
            # prebuilt (bare) projects keep the id in the native project, not in app.json
            or android_app_id(root, android_manifest_paths(root))
        )
        target = os.environ.get("CRUSORAI_RN_TARGET", "").strip().lower()
        if target not in ("android", "ios"):
            target = "ios" if host_platform() == HOST_MACOS and (root / "ios").is_dir() else "android"
        details = {
            "expo": expo,
            "react_native": rn,
            "prebuilt_android": (root / "android").is_dir(),
            "prebuilt_ios": (root / "ios").is_dir(),
            "target": target,
            "has_start": has_script(manifest, "start"),
            "manager": package_manager(root)[0],
        }
        return [TargetCandidate(
            target=self.id, label=self.label + (" (Expo)" if expo else ""),
            confidence=0.95 if rn else 0.85,
            evidence=tuple(item for item in ("package.json", "app.json", "metro.config.js")
                           if (root / item).is_file()),
            framework="expo" if expo else "react-native", app_id=app_id, details=details,
        )]

    # ---- planning ------------------------------------------------------- #

    def requirements(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        root = Path(workspace)
        manifest = node_manifest(root)
        needs = ["node", "npm"] if has_script(manifest, "start") else ["node"]
        detected = self.detect(root)
        target = str(detected[0].details.get("target") if detected else "android")
        if target == "android":
            needs.extend(AndroidProvider().requirements(root, request))
        else:
            needs.extend(IOSProvider().requirements(root, request))
        return tuple(dict.fromkeys(needs))

    def plan(self, workspace: str | Path, request: TargetRequest) -> RunPlan:
        root = Path(workspace)
        manifest = node_manifest(root)
        detected = self.detect(root)
        details = detected[0].details if detected else {}
        target = str(details.get("target") or "android")
        expo = bool(details.get("expo"))
        app_id = request.app_id or (detected[0].app_id if detected else "")
        stages: list[Stage] = []
        notes: list[str] = [f"react-native target={target}"]
        if expo:
            notes.append("Expo project: expo prebuild generates the native project when missing")

        if not (root / "node_modules").exists():
            stages.append(Stage(
                name="install_deps", kind="build", required=True, timeout_s=2400,
                argv=tuple(npm_run_argv(root, "install")),
                note=f"dependency install ({details.get('manager', 'npm')})",
            ))

        # Metro must be up before a debug build is installed, or the app opens on
        # a red screen and every downstream probe misreports the cause.
        if has_script(manifest, "start") and request.mode != "build":
            stages.extend([
                Stage(
                    name="metro", kind=KIND_PROBE, background=True, required=False, timeout_s=120,
                    argv=tuple(npm_run_argv(root, "start", "--", "--port", metro_port())),
                    note="the JS packager is started when the project defines a start script",
                ),
                Stage(
                    name="metro_ready", kind=KIND_PROBE, required=False, timeout_s=180,
                    argv=(), handler="src.targets.probes:http_ready",
                    env=(("url", f"http://127.0.0.1:{metro_port()}/status"),
                         ("expect_text", "packager-status"), ("timeout_s", "120")),
                ),
            ])

        if target == "android":
            if expo and not (root / "android").is_dir():
                stages.append(Stage(
                    name="prebuild", kind="build", required=True, timeout_s=1800,
                    argv=(tool_path("npx", fallback="npx"), "expo", "prebuild", "--platform", "android",
                          "--no-install"),
                    note="managed Expo project: generate the android/ project",
                ))
            stages.append(Stage(
                name="build", kind="build", required=True, timeout_s=3600,
                argv=AndroidProvider().build_argv(root, request),
                artifact_globs=AndroidProvider.APK_GLOBS,
                note="Gradle debug APK (shared with the Android provider)",
            ))
            if request.mode != "build":
                if not app_id:
                    raise PlanUnavailable(
                        "no Android package name found — for Expo add expo.android.package to app.json, "
                        "or pass app_id"
                    )
                android = AndroidProvider()
                stages.extend(android.device_stages(root, request, app_id=app_id))
                stages.extend(android.probe_stages(root, request))
                notes.append(
                    "monorepo? Metro must resolve from the repo root: set metro.config.js watchFolders "
                    "(see the react-native-best-practices skill)"
                )
        else:
            if host_platform() != HOST_MACOS:
                raise PlanUnavailable(
                    "React Native iOS verification needs macOS (Xcode + Simulator); run it on a "
                    "macOS runner or cloud Mac (docs/pipelines/react-native.yml)"
                )
            ios_provider = IOSProvider()
            ios_plan = ios_provider.plan(root, request)
            stages.extend(ios_plan.stages)
            notes.extend(ios_plan.notes)
        return RunPlan(
            target=self.id, provider=self.id, stages=tuple(stages), app_id=app_id,
            requires=self.requirements(root, request), notes=tuple(notes),
        )

    # ---- interpretation ------------------------------------------------ #

    def interpret(self, workspace: str | Path, request: TargetRequest,
                  outcome: RunOutcome) -> TargetReceipt:
        target = "android"
        for note in outcome.plan.notes:
            if note.startswith("react-native target="):
                target = note.split("=", 1)[1].strip()
        base = AndroidProvider() if target == "android" else IOSProvider()
        receipt = base.interpret(workspace, request, outcome)
        receipt.provider = self.id
        receipt.target = f"{self.id}:{target}"
        metro = outcome.output_of("metro_ready")
        if metro.strip():
            receipt.notes.append(metro.strip().splitlines()[0])
        elif outcome.result("metro_ready") is not None and not outcome.result("metro_ready").ok:
            receipt.notes.append(
                "Metro never answered /status — a debug build will open on a red screen; check the "
                "metro log in the evidence directory"
            )
        return receipt


__all__ = ["ReactNativeProvider", "metro_port"]

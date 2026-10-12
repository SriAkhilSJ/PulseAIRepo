"""Android target provider: Gradle build → adb install → launch → real UI proof.

"Did the app work?" is answered with four independent pieces of evidence, none
of which is an exit code alone:

* the APK was produced and installed on a named device;
* the app is in the **foreground** (``am start`` succeeding proves nothing);
* the live UI hierarchy contains the elements the task promised;
* the log slice for this run is free of the app's own fatal errors.

Simulator/emulator choice, boot waiting and device claiming live here so the
model never spends a turn on ``adb devices``.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

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
    android_app_id,
    android_launcher_activity,
    android_manifest_paths,
    android_module,
    any_path,
    gradle_wrapper,
)
from src.targets.evidence import (
    EvidenceBundle,
    check_assertions,
    junit_report_files,
    parse_junit_summary,
    parse_ui_dump,
    scan_crashes,
    screenshot_quality,
    ui_dump_text,
)
from src.targets.providers.base import (
    PlanUnavailable,
    TargetProvider,
    artifact_for_evidence,
    evidence_path,
    gradle_argv,
    read_evidence,
    tool_path,
)
from src.targets.runner import RunOutcome, TargetRequest

APK_PATTERNS: tuple[str, ...] = (
    "app/build/outputs/apk/**/*.apk",
    "*/build/outputs/apk/**/*.apk",
    "build/outputs/apk/**/*.apk",
    "build/app/outputs/flutter-apk/*.apk",
    "android/app/build/outputs/apk/**/*.apk",
)
JUNIT_PATTERNS: tuple[str, ...] = (
    "**/build/outputs/androidTest-results/**/*.xml",
    "**/build/test-results/**/*.xml",
)

_BOOT_TIMEOUT_S = 300
_DEVICE_CACHE: dict[str, str] = {}
_OWNED_EMULATORS: set[str] = set()


# --------------------------------------------------------------------------- #
# adb plumbing (shared by resolvers and handlers)
# --------------------------------------------------------------------------- #


def _run(argv: list[str], *, timeout: int = 90) -> tuple[int, str]:
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s: {' '.join(argv[:4])}"
    except FileNotFoundError:
        return 127, f"executable not found: {argv[0]}"
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")


def _adb(*args: str, timeout: int = 90) -> tuple[int, str]:
    return _run([tool_path("adb", fallback="adb"), *args], timeout=timeout)


def connected_devices() -> list[str]:
    """Serials in the ``device`` state (emulators first, then USB devices)."""
    code, out = _adb("devices")
    if code != 0:
        return []
    serials: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    serials.sort(key=lambda serial: (not serial.startswith("emulator-"), serial))
    return serials


def _avd_name() -> str:
    override = os.environ.get("CRUSORAI_AVD", "").strip()
    if override:
        return override
    code, out = _run([tool_path("emulator", fallback="emulator"), "-list-avds"], timeout=30)
    if code == 0:
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("INFO"):
                return line
    return ""


def _boot_completed(serial: str) -> bool:
    code, out = _adb("-s", serial, "shell", "getprop", "sys.boot_completed", timeout=30)
    return code == 0 and out.strip().endswith("1")


def _start_emulator() -> str:
    """Boot an AVD and wait for it to be usable. Returns the serial."""
    avd = _avd_name()
    if not avd:
        raise RuntimeError(
            "no Android device is attached and no AVD exists — create one with "
            "`avdmanager create avd -n crusor -k 'system-images;android-35;google_apis;x86_64'` "
            "or set CRUSORAI_AVD"
        )
    emulator = tool_path("emulator", fallback="emulator")
    headless = os.environ.get("CRUSORAI_EMULATOR_HEADLESS", "").strip().lower() in ("1", "true", "yes")
    argv = [
        emulator, "-avd", avd,
        "-no-snapshot-save", "-no-boot-anim",
        "-gpu", os.environ.get("CRUSORAI_EMULATOR_GPU", "swiftshader_indirect"),
    ]
    if headless:
        argv += ["-no-window", "-no-audio"]
    before = set(connected_devices())
    log_dir = Path(os.environ.get("CRUSORAI_TARGET_EVIDENCE_DIR") or os.path.expanduser("~/.crusorai"))
    log_dir.mkdir(parents=True, exist_ok=True)
    handle = open(log_dir / "emulator-launch.log", "ab")
    Popen_options: dict[str, Any] = {"stdout": handle, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        Popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        Popen_options["start_new_session"] = True
    subprocess.Popen(argv, **Popen_options)  # noqa: S603 - argv list
    deadline = time.monotonic() + _BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        new = [serial for serial in connected_devices() if serial not in before]
        for serial in new:
            if _boot_completed(serial):
                _OWNED_EMULATORS.add(serial)
                return serial
        time.sleep(3)
    raise RuntimeError(
        f"emulator '{avd}' did not finish booting in {_BOOT_TIMEOUT_S}s "
        f"(log: {log_dir / 'emulator-launch.log'}); check KVM/HAXM availability and disk space"
    )


# --------------------------------------------------------------------------- #
# resolvers referenced from stage argv
# --------------------------------------------------------------------------- #


def resolve_device(workspace: Path, request: TargetRequest, tokens: Mapping[str, str]) -> str:
    """Explicit device → attached device → boot an emulator (cached per run)."""
    if request.device.strip():
        return request.device.strip()
    cached = _DEVICE_CACHE.get(str(workspace))
    if cached:
        return cached
    devices = connected_devices()
    if devices:
        _DEVICE_CACHE[str(workspace)] = devices[0]
        return devices[0]
    if not request.start_emulator:
        raise RuntimeError(
            "no Android device or emulator is attached (`adb devices` is empty) — "
            "start one, plug in a device, or allow emulator autostart"
        )
    serial = _start_emulator()
    _DEVICE_CACHE[str(workspace)] = serial
    return serial


def resolve_apk(workspace: Path, request: TargetRequest, tokens: Mapping[str, str]) -> str:
    """Newest installable APK this plan produced (test APKs excluded)."""
    candidates: list[Path] = []
    for pattern in APK_PATTERNS:
        try:
            candidates.extend(path for path in workspace.glob(pattern) if path.is_file())
        except (OSError, ValueError):
            continue
    usable = [
        path for path in candidates
        if "androidTest" not in path.as_posix()
        and "unaligned" not in path.name
        and path.stat().st_size > 4096
    ]
    if not usable:
        raise RuntimeError(
            "no APK found after the build step (looked for app/build/outputs/apk/**, "
            "*/build/outputs/apk/**) — read the build log above for the real failure"
        )
    newest = max(usable, key=lambda path: path.stat().st_mtime)
    return str(newest)


# --------------------------------------------------------------------------- #
# handlers referenced from stage plans
# --------------------------------------------------------------------------- #


def _ctx_device(ctx: Mapping[str, Any]) -> str:
    tokens = dict(ctx.get("tokens") or {})
    request = ctx.get("request")
    return str(tokens.get("device") or getattr(request, "device", "") or "").strip()


def _ctx_app_id(ctx: Mapping[str, Any]) -> str:
    tokens = dict(ctx.get("tokens") or {})
    request = ctx.get("request")
    plan = ctx.get("plan")
    return str(
        getattr(request, "app_id", "")
        or tokens.get("app_id")
        or getattr(plan, "app_id", "")
        or ""
    ).strip()


def resolve_activity_name(device: str, app_id: str, workspace: Path | None = None) -> str:
    """Resolve the launcher component for an installed package (best effort)."""
    if device and app_id:
        code, out = _adb("-s", device, "shell", "cmd", "package", "resolve-activity", "--brief", app_id,
                         timeout=30)
        if code == 0:
            for line in reversed(out.splitlines()):
                line = line.strip()
                if "/" in line and app_id in line and not line.startswith("priority"):
                    short = line.split("/", 1)[1].strip()
                    if short.startswith("."):
                        return f"{app_id}/{short}"
                    if short.startswith(app_id):
                        return f"{app_id}/{short}"
                    return f"{app_id}/.{short}" if not short.startswith(app_id) else f"{app_id}/{short}"
    if workspace is not None and app_id:
        declared = android_launcher_activity(Path(workspace), android_manifest_paths(Path(workspace)))
        if declared:
            component = declared if declared.startswith(".") else f".{declared.split('.')[-1]}"
            return f"{app_id}/{component}"
    return ""


def launch_app(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Launch the installed app and report how it was launched."""
    device, app_id = _ctx_device(ctx), _ctx_app_id(ctx)
    workspace = ctx.get("workspace")
    if not device:
        return 1, "no Android device serial was resolved for this plan"
    if not app_id:
        return 1, "no application id (package) is known for this workspace"
    component = resolve_activity_name(device, app_id, Path(workspace) if workspace else None)
    if component:
        code, out = _adb("-s", device, "shell", "am", "start", "-W", "-S", "-n", component, timeout=120)
        mode = f"am start -n {component}"
    else:
        code, out = _adb("-s", device, "shell", "monkey", "-p", app_id,
                         "-c", "android.intent.category.LAUNCHER", "1", timeout=120)
        mode = f"monkey -p {app_id} (launcher intent fallback)"
    lowered = out.lower()
    failure = code != 0 or "error:" in lowered or "exception" in lowered
    status = "LAUNCH FAILED" if failure else "LAUNCH OK"
    return (1 if failure else 0), f"{status} via {mode}\n{out.strip()[-1200:]}"


def foreground_is_app(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """The only honest launch check: the package owns the foreground window."""
    args = {str(k): str(v) for k, v in dict(ctx.get("args") or {}).items()}
    timeout = float(args.get("timeout_s", 25) or 25)
    device, app_id = _ctx_device(ctx), _ctx_app_id(ctx)
    if not (device and app_id):
        return 1, "foreground check needs both a device and an application id"
    deadline = time.monotonic() + max(3.0, timeout)
    last = ""
    while True:
        code, out = _adb("-s", device, "shell", "dumpsys", "activity", "activities", timeout=60)
        if code == 0:
            for line in out.splitlines():
                if any(marker in line for marker in ("topResumedActivity", "ResumedActivity", "mResumedActivity")):
                    last = line.strip()
                    if app_id in line:
                        return 0, f"FOREGROUND OK: {line.strip()[:200]}"
            if not last:
                code2, out2 = _adb("-s", device, "shell", "dumpsys", "window", "windows", timeout=60)
                if code2 == 0:
                    for line in out2.splitlines():
                        if "mCurrentFocus" in line or "mFocusedApp" in line:
                            last = line.strip()
                            if app_id in line:
                                return 0, f"FOREGROUND OK: {line.strip()[:200]}"
        if time.monotonic() >= deadline:
            return 1, (
                f"{app_id} never reached the foreground within {timeout:.0f}s "
                f"(last activity line: {last or 'none observed'})"
            )
        time.sleep(1.5)


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #


class AndroidProvider(TargetProvider):
    id = "android"
    label = "Android app (Gradle + adb + emulator/device)"
    requires = ("adb", "java")
    recommended = ("emulator", "sdkmanager", "scrcpy", "maestro")
    APK_GLOBS = APK_PATTERNS

    #: ``{token}`` -> ``module:function`` resolvers referenced from stage argv.
    RESOLVERS = {
        "adb": "src.targets.providers.android:resolve_adb",
        "device": "src.targets.providers.android:resolve_device",
        "apk": "src.targets.providers.android:resolve_apk",
    }

    # ---- detection ------------------------------------------------------ #

    def detect(self, workspace: str | Path) -> list[TargetCandidate]:
        root = Path(workspace)
        manifests = android_manifest_paths(root)
        gradle_markers = any_path(root, (
            "settings.gradle.kts", "settings.gradle", "build.gradle.kts", "build.gradle",
        ))
        if not manifests and not gradle_markers:
            return []
        manifest_hit = bool(manifests)
        wrapper = gradle_wrapper(root)
        confidence = 0.0
        if manifest_hit:
            confidence = 0.97 if wrapper else 0.85
        elif gradle_markers:
            confidence = 0.45
        if not manifest_hit:
            # A bare Gradle build (JVM library) is not necessarily an app.
            return [TargetCandidate(
                target=self.id, label=self.label, confidence=confidence,
                evidence=tuple(gradle_markers), app_id="",
                details={"gradle": True, "app": False},
            )]
        module = android_module(root, manifests)
        app_id = android_app_id(root, manifests)
        details = {
            "app": True,
            "module": module,
            "wrapper": wrapper,
            "manifest": manifests[0] if manifests else "",
            "launcher_activity": android_launcher_activity(root, manifests),
        }
        return [TargetCandidate(
            target=self.id, label=self.label, confidence=confidence,
            evidence=tuple(manifests[:2]) + tuple(gradle_markers[:2]),
            app_id=app_id, details=details,
        )]

    # ---- planning ------------------------------------------------------- #

    def requirements(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        detected = self.detect(workspace)
        details = detected[0].details if detected else {}
        needs = ["adb", "java"]
        if not details.get("wrapper"):
            needs.append("gradle")
        if not request.device and not connected_devices():
            needs.append("emulator")
        return tuple(needs)

    def build_argv(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        """Gradle argv for a debug build (shared with framework providers)."""
        root = Path(workspace)
        detected = self.detect(root)
        details = detected[0].details if detected else {}
        module = str(details.get("module") or "app")
        variant = os.environ.get("CRUSORAI_ANDROID_VARIANT", "Debug").strip() or "Debug"
        return tuple(gradle_argv(
            root, f":{module}:assemble{variant}", "--console=plain", *request.extra_args,
        ))

    def device_stages(self, workspace: str | Path, request: TargetRequest,
                      *, app_id: str, apk_glob_note: str = "") -> list[Stage]:
        """Install → launch → prove → capture, reusable by framework providers."""
        stages: list[Stage] = [
            Stage(
                name="install", kind="install",
                argv=("{adb}", "-s", "{device}", "install", "-r", "-t", "{apk}"),
                timeout_s=600,
                note=apk_glob_note or "installs the newest APK the build produced",
                artifact_globs=("app/build/outputs/apk/**/*.apk", "*/build/outputs/apk/**/*.apk"),
            ),
            Stage(name="launch", kind=KIND_LAUNCH, argv=(),
                  handler="src.targets.providers.android:launch_app", required=True, timeout_s=180),
            Stage(name="settle", kind=KIND_PROBE, argv=(), handler="src.targets.probes:sleep",
                  env=(("seconds", "4"),)),
            Stage(name="foreground", kind=KIND_PROBE, argv=(),
                  handler="src.targets.providers.android:foreground_is_app", required=True,
                  timeout_s=90, env=(("timeout_s", "25"),)),
        ]
        return stages

    def probe_stages(self, workspace: str | Path, request: TargetRequest) -> list[Stage]:
        return [
            Stage(name="ui_dump", kind=KIND_PROBE, required=False, timeout_s=120,
                  argv=("{adb}", "-s", "{device}", "shell", "uiautomator", "dump", "/sdcard/crusorai-ui.xml")),
            Stage(name="ui_pull", kind=KIND_PROBE, required=False, timeout_s=120,
                  argv=("{adb}", "-s", "{device}", "pull", "/sdcard/crusorai-ui.xml",
                        "{artifacts}/ui.xml")),
            Stage(name="screenshot", kind=KIND_PROBE, required=False, timeout_s=120,
                  argv=("{adb}", "-s", "{device}", "exec-out", "screencap", "-p"),
                  stdout_file="screen.png"),
            Stage(name="screenshot_quality", kind=KIND_PROBE, required=False, argv=(),
                  handler="src.targets.probes:screenshot_quality", env=(("file", "screen.png"),)),
            Stage(name="logcat", kind=KIND_PROBE, required=False, timeout_s=120,
                  argv=("{adb}", "-s", "{device}", "logcat", "-d", "-t", "800")),
        ]

    def plan(self, workspace: str | Path, request: TargetRequest) -> RunPlan:
        root = Path(workspace)
        detected = self.detect(root)
        if not detected or not detected[0].details.get("app", True):
            raise PlanUnavailable(
                "no Android application was found in this workspace "
                "(expected a src/main/AndroidManifest.xml and a Gradle wrapper)"
            )
        details = detected[0].details
        app_id = request.app_id or detected[0].app_id
        module = str(details.get("module") or "app")
        variant = os.environ.get("CRUSORAI_ANDROID_VARIANT", "Debug").strip() or "Debug"

        stages: list[Stage] = [
            Stage(
                name="build", kind="build", timeout_s=2400,
                argv=self.build_argv(root, request),
                artifact_globs=APK_PATTERNS,
                note=f"Gradle task :{module}:assemble{variant}",
            )
        ]
        if request.mode != "build":
            if not app_id:
                raise PlanUnavailable(
                    "the Android application id (package) could not be determined; pass app_id "
                    "explicitly or add a namespace/applicationId to the module's build.gradle"
                )
            stages.extend(self.device_stages(root, request, app_id=app_id))
            stages.extend(self.probe_stages(root, request))
        if request.mode == "test":
            stages.append(Stage(
                name="instrumented_tests", kind="test", timeout_s=3600,
                argv=tuple(gradle_argv(root, f":{module}:connected{variant}AndroidTest", "--console=plain")),
                artifact_globs=JUNIT_PATTERNS,
            ))
        if not request.keep_running and request.mode != "build":
            stages.append(Stage(
                name="cleanup", kind=KIND_CLEANUP, required=False, timeout_s=60,
                argv=("{adb}", "-s", "{device}", "shell", "am", "force-stop", "{app_id}"),
            ))
            if os.environ.get("CRUSORAI_EMULATOR_EPHEMERAL", "").strip() in ("1", "true", "yes"):
                stages.append(Stage(
                    name="stop_emulator", kind=KIND_CLEANUP, required=False, timeout_s=60,
                    argv=("{adb}", "-s", "{device}", "emu", "kill"),
                    note="CRUSORAI_EMULATOR_EPHEMERAL=1: the emulator this plan booted is disposable",
                ))
        return RunPlan(
            target=self.id, provider=self.id, stages=tuple(stages),
            app_id=app_id, device=request.device,
            requires=self.requirements(root, request),
            notes=(
                f"module={module}",
                "emulator autostart is enabled; set CRUSORAI_EMULATOR_HEADLESS=1 for CI",
            ),
        )

    def interpret(self, workspace: str | Path, request: TargetRequest,
                  outcome: RunOutcome) -> TargetReceipt:
        receipt = super().interpret(workspace, request, outcome)
        app_id = outcome.plan.app_id or outcome.tokens.get("app_id", "")
        receipt.app_id = app_id
        bundle = EvidenceBundle()

        dump_text = read_evidence(outcome, "ui.xml")
        elements = parse_ui_dump(dump_text)
        foreground_output = outcome.output_of("foreground")
        if elements:
            bundle.notes.append(f"UI hierarchy: {len(elements)} nodes parsed from uiautomator dump")
        elif request.mode != "build":
            bundle.notes.append(
                "no uiautomator dump was captured — UI assertions fall back to the screenshot only"
            )
        if request.assertions:
            if not elements:
                bundle.assertions = check_assertions(
                    request.assertions, [], app_id=app_id, foreground_app="",
                )
            else:
                bundle.assertions = check_assertions(
                    request.assertions, elements, app_id=app_id,
                    foreground_app=_foreground_package(foreground_output),
                )
        receipt.assertions = bundle.assertions

        screenshot = artifact_for_evidence(outcome, "screen.png", "screenshot")
        if screenshot:
            receipt.artifacts.append(screenshot)
            bundle.visual_quality = screenshot_quality(evidence_path(outcome, "screen.png"))
            receipt.visual_quality = bundle.visual_quality

        logcat = outcome.output_of("logcat")
        bundle.crashes = scan_crashes(logcat, "android", app_id=app_id)
        receipt.crash_findings = bundle.crashes

        tests = parse_junit_summary(junit_report_files(workspace, JUNIT_PATTERNS))
        if tests.get("total"):
            bundle.tests = tests
            receipt.notes.append(
                f"instrumented tests: {tests['passed']}/{tests['total']} passed "
                f"({tests['failures']} failures, {tests['errors']} errors)"
            )
            if tests["failures"] or tests["errors"]:
                receipt.failed("instrumented_tests",
                               f"{tests['failures'] + tests['errors']} instrumented test failure(s)")
        if dump_text and not elements:
            bundle.notes.append("uiautomator dump was empty or unparsable")
        if outcome.tokens.get("device", "").startswith("emulator-"):
            bundle.notes.append(
                "screen mirroring: `scrcpy -s " + outcome.tokens.get("device", "") + "` (optional)"
            )
        receipt.notes.extend(bundle.notes)
        render_proof(elements, receipt)
        return receipt


def _foreground_package(foreground_output: str) -> str:
    match = re.search(r"([A-Za-z][\w.]+\.[\w.]+)/[\w.$]+", foreground_output or "")
    return match.group(1) if match else ""


def resolve_adb(workspace: Path, request: TargetRequest, tokens: Mapping[str, str]) -> str:
    """The adb binary this plan must use (honours ``CRUSORAI_ADB``)."""
    return tool_path("adb", fallback="adb")


def render_proof(elements: list[Any], receipt: TargetReceipt) -> None:
    """Attach a bounded, human-readable slice of what the device showed."""
    if not elements:
        return
    text = ui_dump_text(elements)
    excerpt = "\n".join(text.splitlines()[:25])
    if excerpt:
        receipt.notes.append("UI TEXT (first 25 labels):\n" + excerpt)


__all__ = [
    "APK_PATTERNS", "AndroidProvider", "JUNIT_PATTERNS", "connected_devices",
    "foreground_is_app", "launch_app", "resolve_activity_name", "resolve_adb",
    "resolve_apk", "resolve_device",
]

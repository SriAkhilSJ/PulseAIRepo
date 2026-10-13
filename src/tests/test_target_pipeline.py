"""Behaviour contracts for the multi-platform target layer (mobile/desktop/web).

These tests are hermetic: no device, no emulator, no network, no model. They pin
the rules that make a target receipt trustworthy, because every one of them is a
place where an agent could otherwise claim success without evidence:

* a green build alone is not a pass (foreground/window/liveness proof is required);
* an ⛔ receipt is returned — never a silent skip — when a toolchain is missing
  or the host cannot run the target (iOS on Linux);
* a missing UI assertion, a crash finding or a near-blank screenshot fails it;
* dry runs show the plan and can never render as ✅;
* the runner stops at the first required failure and reaps background processes.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.targets import registry
from src.targets.contract import (
    DRY_PREFIX,
    FAIL_PREFIX,
    PASS_PREFIX,
    UNAVAILABLE_PREFIX,
    Assertion,
    RunPlan,
    Stage,
    StageResult,
    TargetReceipt,
)
from src.targets.evidence import (
    check_assertions,
    parse_junit_summary,
    parse_ui_dump,
    scan_crashes,
)
from src.targets.probes import cdp_ready, process_alive, screenshot_quality
from src.targets.runner import (
    TargetRequest,
    TokenResolutionError,
    execute_plan,
    resolve_tokens,
)
from src.targets.toolchain import (
    TOOLS_BY_ID,
    ToolStatus,
    doctor_report,
    missing as missing_tools,
    target_readiness,
)


@pytest.fixture(autouse=True)
def _default_adb_adapter(monkeypatch):
    """Keep ADB-plan contracts stable when a host image bundles Android CLI.

    Tests for the optional Android CLI explicitly select that adapter; the rest
    of this module models the ADB fallback regardless of tools on the runner's
    PATH.
    """
    monkeypatch.setenv("CRUSORAI_ANDROID_RUNNER", "adb")


ANDROID_MANIFEST = """<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.acme.demo">
  <application android:label="Demo">
    <activity android:name=".MainActivity">
      <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
      </intent-filter>
    </activity>
  </application>
</manifest>
"""

UI_DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" clickable="false" bounds="[0,0][1080,2280]">
    <node index="1" text="Sign in" resource-id="com.acme.demo:id/title" class="android.widget.TextView"
          content-desc="welcome heading" clickable="false" enabled="true" bounds="[40,200][400,280]"/>
    <node index="2" text="Continue" resource-id="com.acme.demo:id/cta" class="android.widget.Button"
          content-desc="" clickable="true" enabled="true" bounds="[40,400][1040,520]"/>
  </node>
</hierarchy>
"""


# --------------------------------------------------------------------------- #
# fixtures: synthetic workspaces
# --------------------------------------------------------------------------- #


def _android_workspace(root: Path) -> Path:
    (root / "app/src/main").mkdir(parents=True)
    (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "settings.gradle.kts").write_text('rootProject.name = "demo"\n', encoding="utf-8")
    (root / "app/src/main/AndroidManifest.xml").write_text(ANDROID_MANIFEST, encoding="utf-8")
    (root / "app/build.gradle.kts").write_text('android { namespace = "com.acme.demo" }\n', encoding="utf-8")
    return root


def _electron_workspace(root: Path) -> Path:
    (root / "electron").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "package.json").write_text(json.dumps({
        "name": "demo", "main": "electron/main.js",
        "scripts": {"start": "electron .", "build": "vite build"},
        "devDependencies": {"electron": "^31"},
    }), encoding="utf-8")
    (root / "electron/main.js").write_text("// main\n", encoding="utf-8")
    return root


def _tauri_workspace(root: Path) -> Path:
    (root / "src-tauri").mkdir(parents=True)
    (root / "src-tauri/tauri.conf.json").write_text(json.dumps({
        "productName": "Demo", "identifier": "com.acme.demo",
    }), encoding="utf-8")
    (root / "src-tauri/Cargo.toml").write_text("[package]\nname = 'demo'\n", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"name": "demo"}), encoding="utf-8")
    return root


def _flutter_workspace(root: Path) -> Path:
    """A realistic Flutter project: Dart source + the generated android/ project."""
    (root / "lib").mkdir(parents=True)
    (root / "android/app/src/main").mkdir(parents=True)
    (root / "pubspec.yaml").write_text(
        "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
    (root / "lib/main.dart").write_text("void main() {}\n", encoding="utf-8")
    (root / "android/app/src/main/AndroidManifest.xml").write_text(
        ANDROID_MANIFEST.replace("com.acme.demo", "com.acme.flutter"), encoding="utf-8")
    (root / "android/app/build.gradle.kts").write_text(
        'applicationId = "com.acme.flutter"\n', encoding="utf-8")
    return root


def _rn_workspace(root: Path) -> Path:
    (root / "android/app/src/main").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "package.json").write_text(json.dumps({
        "name": "demo", "dependencies": {"react-native": "0.76"},
        "scripts": {"start": "react-native start"},
    }), encoding="utf-8")
    (root / "android/settings.gradle").write_text("rootProject.name='demo'\n", encoding="utf-8")
    (root / "android/app/src/main/AndroidManifest.xml").write_text(
        ANDROID_MANIFEST.replace("com.acme.demo", "com.acme.rn"), encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #


def test_detects_android_with_app_id_and_module(tmp_path):
    workspace = _android_workspace(tmp_path / "android")
    candidates = registry.detect(workspace)
    assert [c.target for c in candidates] == ["android"]
    assert candidates[0].app_id == "com.acme.demo"
    assert candidates[0].details["module"] == "app"
    assert "AndroidManifest.xml" in " ".join(candidates[0].evidence)


def test_detects_electron_and_tauri_as_desktop(tmp_path):
    electron = registry.detect(_electron_workspace(tmp_path / "electron-app"))
    tauri = registry.detect(_tauri_workspace(tmp_path / "tauri-app"))
    assert electron[0].target == "desktop" and electron[0].framework == "electron"
    assert tauri[0].target == "desktop" and tauri[0].framework == "tauri"
    assert tauri[0].app_id == "com.acme.demo"


def test_detects_flutter_and_react_native_as_frameworks(tmp_path):
    flutter = registry.detect(_flutter_workspace(tmp_path / "flutter-app"))
    rn = registry.detect(_rn_workspace(tmp_path / "rn-app"))
    assert flutter[0].target == "flutter" and "android" in flutter[0].details["platforms"]
    assert rn[0].target == "react-native"
    # a framework project still exposes the platform target for a precise ask
    assert "android" in [candidate.target for candidate in rn]


def test_empty_workspace_reports_no_target(tmp_path):
    report = registry.detect_report(tmp_path)
    assert "No target detected" in report
    receipt = registry.run(tmp_path, "", TargetRequest())
    assert receipt.to_text().startswith(UNAVAILABLE_PREFIX)


# --------------------------------------------------------------------------- #
# plans
# --------------------------------------------------------------------------- #


def test_android_plan_is_the_full_proof_sequence(tmp_path):
    workspace = _android_workspace(tmp_path / "android")
    plan = registry.build_plan(workspace, "android", TargetRequest(mode="verify"))
    names = [stage.name for stage in plan.stages]
    assert names == [
        "build", "install", "launch", "settle", "foreground", "ui_dump", "ui_pull",
        "screenshot", "screenshot_quality", "logcat", "cleanup",
    ]
    assert plan.app_id == "com.acme.demo"
    # the launch proof is a deterministic foreground check, not "am start returned 0"
    foreground = next(stage for stage in plan.stages if stage.name == "foreground")
    assert foreground.handler.endswith("foreground_is_app")
    assert foreground.required is True
    screenshot = next(stage for stage in plan.stages if stage.name == "screenshot")
    assert screenshot.stdout_file == "screen.png"      # raw binary capture
    assert "adb" in plan.requires


def test_android_build_only_plan_never_touches_a_device(tmp_path):
    workspace = _android_workspace(tmp_path / "android")
    plan = registry.build_plan(workspace, "android", TargetRequest(mode="build"))
    assert [stage.name for stage in plan.stages] == ["build"]


def test_flutter_android_plan_delegates_device_stages_to_android(tmp_path):
    workspace = _flutter_workspace(tmp_path / "flutter-app")
    plan = registry.build_plan(workspace, "flutter", TargetRequest(mode="verify"))
    names = [stage.name for stage in plan.stages]
    assert names[0] == "pub_get"
    assert "build" in names
    assert {"install", "launch", "foreground", "screenshot"}.issubset(set(names))
    assert any("flutter" in " ".join(stage.argv) for stage in plan.stages)


def test_react_native_plan_starts_metro_before_the_device_stage(tmp_path, monkeypatch):
    workspace = _rn_workspace(tmp_path / "rn-app")
    monkeypatch.setenv("CRUSORAI_RN_TARGET", "android")
    plan = registry.build_plan(workspace, "react-native", TargetRequest(mode="verify"))
    names = [stage.name for stage in plan.stages]
    assert names.index("metro") < names.index("build") < names.index("install")
    metro_ready = next(stage for stage in plan.stages if stage.name == "metro_ready")
    assert metro_ready.env[0][1].endswith("/status")


def test_desktop_electron_plan_proves_a_debuggable_window(tmp_path):
    workspace = _electron_workspace(tmp_path / "electron-app")
    plan = registry.build_plan(workspace, "electron", TargetRequest(mode="verify"))
    names = [stage.name for stage in plan.stages]
    assert "launch" in names and "cdp_ready" in names
    launch = next(stage for stage in plan.stages if stage.name == "launch")
    assert launch.background is True
    cdp = next(stage for stage in plan.stages if stage.name == "cdp_ready")
    assert cdp.handler.endswith("cdp_ready") and cdp.required is True


def test_web_plan_starts_the_dev_server_and_probes_readiness(tmp_path, monkeypatch):
    workspace = tmp_path / "web"
    workspace.mkdir()
    (workspace / "package.json").write_text(json.dumps({
        "name": "demo", "dependencies": {"next": "15"},
        "scripts": {"dev": "next dev", "build": "next build"},
    }), encoding="utf-8")
    monkeypatch.setenv("CRUSORAI_WEB_PORT", "3199")
    plan = registry.build_plan(workspace, "web", TargetRequest(mode="verify"))
    ready = next(stage for stage in plan.stages if stage.name == "http_ready")
    assert dict(ready.env)["url"] == "http://127.0.0.1:3199"


# --------------------------------------------------------------------------- #
# receipts: the verdict must follow the evidence
# --------------------------------------------------------------------------- #


def _clean_stage(name: str = "build") -> StageResult:
    stage = Stage(name=name, argv=("true",))
    return StageResult(stage=stage, exit_code=0, output="ok", resolved_argv=("true",))


def test_receipt_passes_only_with_clean_required_stages():
    receipt = TargetReceipt(target="android", provider="android", stages=[_clean_stage()])
    assert receipt.passed
    failed = TargetReceipt(
        target="android", provider="android",
        stages=[StageResult(stage=Stage(name="build", argv=("false",)), exit_code=1, output="boom")],
    )
    assert not failed.passed
    assert failed.to_text().startswith(FAIL_PREFIX)


def test_receipt_fails_on_missing_assertion_crash_or_blank_frame():
    base = [_clean_stage()]
    missing_assertion = TargetReceipt(
        target="android", provider="android", stages=base,
        assertions=[Assertion(kind="text", expected="Sign in", found=False)],
    )
    assert not missing_assertion.passed
    crashed = TargetReceipt(
        target="android", provider="android", stages=base,
        crash_findings=["FATAL EXCEPTION: main"],
    )
    assert not crashed.passed
    blank = TargetReceipt(
        target="desktop", provider="desktop", stages=base,
        visual_quality={"passed": False, "reason": "near-uniform/low-detail capture"},
    )
    assert not blank.passed


def test_optional_stage_failure_does_not_fail_the_receipt():
    receipt = TargetReceipt(
        target="android", provider="android",
        stages=[
            _clean_stage("build"),
            StageResult(stage=Stage(name="logcat", argv=("adb",), required=False, kind="probe"),
                        exit_code=1, output="device offline"),
        ],
    )
    assert receipt.passed


def test_unavailable_receipt_never_claims_a_pass():
    receipt = TargetReceipt(
        target="ios", provider="ios",
        unavailable_reason="iOS build/verify requires macOS + Xcode",
    )
    text = receipt.to_text()
    assert text.startswith(UNAVAILABLE_PREFIX)
    assert "requires macOS" in text
    assert not receipt.passed


def test_dry_run_receipt_renders_neither_pass_nor_fail():
    receipt = TargetReceipt(target="android", provider="android", stages=[_clean_stage()],
                            dry_run=True)
    text = receipt.to_text()
    assert text.startswith(DRY_PREFIX)
    assert not receipt.passed
    assert PASS_PREFIX not in text


# --------------------------------------------------------------------------- #
# evidence decoding
# --------------------------------------------------------------------------- #


def test_ui_dump_parsing_and_assertions():
    elements = parse_ui_dump(UI_DUMP)
    assert len(elements) == 3
    button = next(element for element in elements if element.class_name == "android.widget.Button")
    assert button.clickable and button.center == (540, 460)
    checks = check_assertions(
        [("text", "sign in"), ("id", "com.acme.demo:id/cta"), ("text", "Nope")], elements,
    )
    assert [assertion.found for assertion in checks] == [True, True, False]
    # a truncated dump must still yield the nodes it contained
    truncated = UI_DUMP.split("<node index=\"2\"")[0]
    assert parse_ui_dump(truncated + "</hierarchy>")
    assert parse_ui_dump("not xml at all") == []


def test_crash_scan_finds_app_failures_and_ignores_system_noise():
    logcat = "\n".join([
        "I/ActivityManager: Start proc com.acme.demo",
        "FATAL EXCEPTION: main",
        "Process: com.acme.demo, PID: 4242",
        "java.lang.IllegalStateException: boom",
        "E AndroidRuntime: FATAL EXCEPTION: main",
        "I/SystemUI: irrelevant chatter",
    ])
    findings = scan_crashes(logcat, "android", app_id="com.acme.demo")
    assert findings and any("FATAL EXCEPTION" in finding for finding in findings)
    assert scan_crashes("I/ActivityManager: all good", "android", app_id="com.acme.demo") == []
    desktop = scan_crashes("Uncaught Error: Cannot find module './main'", "desktop")
    assert desktop


def test_junit_summary_rolls_up_results(tmp_path):
    report = tmp_path / "TEST-demo.xml"
    report.write_text(
        '<testsuites><testsuite name="com.acme.DemoTest" tests="4" failures="1" errors="0" '
        'skipped="1"/></testsuites>', encoding="utf-8")
    summary = parse_junit_summary([report])
    assert summary["total"] == 4 and summary["failures"] == 1
    assert summary["passed"] == 2          # skipped tests are not passes


def test_screenshot_quality_rejects_a_uniform_capture(tmp_path):
    pillow = pytest.importorskip("PIL.Image")
    blank = tmp_path / "blank.png"
    pillow.new("RGB", (400, 800), (12, 12, 12)).save(blank)
    real = tmp_path / "real.png"
    image = pillow.new("RGB", (400, 800), (250, 250, 250))
    for x in range(20, 380, 20):
        for y in range(20, 780, 20):
            image.putpixel((x, y), (10, 10, 200))
    image.save(real)
    blank_verdict = screenshot_quality({"artifacts_dir": str(tmp_path), "args": {"file": "blank.png"}})
    real_verdict = screenshot_quality({"artifacts_dir": str(tmp_path), "args": {"file": "real.png"}})
    assert blank_verdict[0] == 1 and "rejected" in blank_verdict[1]
    assert real_verdict[0] == 0


# --------------------------------------------------------------------------- #
# runner mechanics
# --------------------------------------------------------------------------- #


def test_token_resolution_uses_the_provider_resolvers(tmp_path):
    """Explicit device wins; the APK token resolves to the newest build output."""
    apk = tmp_path / "app/build/outputs/apk/debug/app-debug.apk"
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"PK\x03\x04" + b"0" * 4096)
    plan = RunPlan(target="android", provider="android", stages=())
    request = TargetRequest(mode="verify", device="emulator-9999")
    sink: dict[str, str] = {}
    argv = resolve_tokens(
        ("adb", "-s", "{device}", "install", "{apk}"),
        workspace=tmp_path, request=request, plan=plan, artifacts_dir=tmp_path,
        resolvers={
            "device": "src.targets.providers.android:resolve_device",
            "apk": "src.targets.providers.android:resolve_apk",
        },
        sink=sink,
    )
    assert argv[2] == "emulator-9999"
    assert Path(argv[-1]) == apk and sink["apk"] == str(apk)


def test_unknown_token_fails_the_stage_instead_of_running_something_wrong(tmp_path):
    plan = RunPlan(target="android", provider="android", stages=(
        Stage(name="install", argv=("adb", "install", "{mystery}"), required=True),
    ))
    outcome = execute_plan(plan, TargetRequest(), workspace=tmp_path)
    assert outcome.blocked
    assert "mystery" in outcome.failure_reason
    assert "plan error" in outcome.results[0].output


def test_resolution_error_is_explicit():
    with pytest.raises(TokenResolutionError):
        resolve_tokens(
            ("{nope}",), workspace=Path("/tmp"), request=TargetRequest(), plan=RunPlan(
                target="x", provider="x", stages=()),
            artifacts_dir=Path("/tmp"), resolvers={},
        )


def test_runner_halts_after_a_required_failure_and_skips_the_rest(tmp_path):
    plan = RunPlan(target="desktop", provider="desktop", stages=(
        Stage(name="build", argv=(sys.executable, "-c", "import sys; sys.exit(3)"), required=True),
        Stage(name="launch", argv=(sys.executable, "-c", "print('never')"), required=True,
              kind="launch"),
        Stage(name="cleanup", argv=(sys.executable, "-c", "print('cleanup ran')"),
              required=False, kind="cleanup"),
    ))
    outcome = execute_plan(plan, TargetRequest(), workspace=tmp_path)
    assert outcome.blocked and outcome.failure_stage == "build"
    skipped = outcome.result("launch")
    assert skipped is not None and skipped.skipped
    cleanup = outcome.result("cleanup")
    assert cleanup is not None and not cleanup.skipped      # cleanup always runs


def test_runner_marks_timeouts_as_failures(tmp_path):
    plan = RunPlan(target="web", provider="web", stages=(
        Stage(name="slow", argv=(sys.executable, "-c", "import time; time.sleep(30)"),
              required=True, timeout_s=1),
    ))
    outcome = execute_plan(plan, TargetRequest(timeout_multiplier=0.25), workspace=tmp_path)
    result = outcome.result("slow")
    assert result is not None and result.timed_out and not result.ok
    assert "timed out" in outcome.failure_reason


def test_background_stage_is_reaped_unless_kept_running(tmp_path):
    plan = RunPlan(target="web", provider="web", stages=(
        Stage(name="dev_server", argv=(sys.executable, "-c", "import time; time.sleep(60)"),
              kind="probe", background=True, required=True),
    ))
    outcome = execute_plan(plan, TargetRequest(keep_running=False), workspace=tmp_path)
    assert outcome.background
    assert outcome.handles and all(handle.returncode is not None for handle in outcome.handles)
    assert outcome.background[0]["stopped"] is True
    pid_file = Path(outcome.artifacts_dir) / "background-pids.json"
    assert json.loads(pid_file.read_text(encoding="utf-8"))[0]["stopped"] is True


def test_windows_reaper_kills_owned_child_when_taskkill_fails(tmp_path, monkeypatch):
    import src.targets.runner as runner

    plan = RunPlan(target="web", provider="web", stages=(
        Stage(name="dev_server", argv=(sys.executable, "-c", "import time; time.sleep(60)"),
              kind="probe", background=True, required=True),
    ))
    outcome = execute_plan(plan, TargetRequest(keep_running=True), workspace=tmp_path)
    try:
        assert outcome.handles and outcome.handles[0].poll() is None
        monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
        monkeypatch.setattr(
            runner.subprocess, "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=1),
        )
        runner._reap_background(outcome)
        assert outcome.handles[0].returncode is not None
        assert outcome.background[0]["stopped"] is True
    finally:
        if outcome.handles and outcome.handles[0].poll() is None:
            outcome.handles[0].kill()
            outcome.handles[0].wait(timeout=5)


def test_process_alive_probe_reports_a_dead_launch(tmp_path):
    plan = RunPlan(target="desktop", provider="desktop", stages=(
        Stage(name="launch", argv=(sys.executable, "-c", "pass"), kind="launch", background=True),
    ))
    outcome = execute_plan(plan, TargetRequest(keep_running=True), workspace=tmp_path)
    Path(outcome.artifacts_dir, "background-pids.json").write_text(
        json.dumps(outcome.background), encoding="utf-8")
    time.sleep(0.4)
    code, text = process_alive({
        "artifacts_dir": outcome.artifacts_dir, "args": {"name": "launch", "timeout_s": "1"},
        "request": TargetRequest(), "plan": plan,
    })
    assert code == 1 and "died" in text


def test_cdp_probe_fails_closed_when_nothing_listens():
    code, text = cdp_ready({
        "artifacts_dir": "/tmp", "args": {"port": "9", "timeout_s": "1"},
        "request": TargetRequest(), "plan": RunPlan(target="desktop", provider="desktop", stages=()),
    })
    assert code == 1 and "CDP NOT READY" in text


# --------------------------------------------------------------------------- #
# toolchain gate + registry behaviour
# --------------------------------------------------------------------------- #


def test_doctor_report_lists_targets_and_install_hints():
    report = doctor_report()
    assert "Target toolchains" in report and "Readiness:" in report
    assert "android" in report and "ios" in report and "desktop" in report


def test_missing_toolchain_is_reported_with_remediation(tmp_path, monkeypatch):
    # Hosted macOS/Windows images may already have an Android SDK. This contract
    # tests the missing-tools path, so stub it instead of depending on runner PATH.
    monkeypatch.setattr(
        registry,
        "missing_tools",
        lambda _required: [ToolStatus(TOOLS_BY_ID["adb"], available=False)],
    )
    workspace = _android_workspace(tmp_path / "android")
    receipt = registry.run(workspace, "android", TargetRequest(mode="verify"))
    text = receipt.to_text()
    assert text.startswith(UNAVAILABLE_PREFIX)
    assert "missing required toolchain" in text
    assert "Install:" in text or "adb" in text


def test_unknown_tool_id_fails_closed():
    statuses = missing_tools(["totally-unknown-tool"])
    assert [status.spec.id for status in statuses] == ["totally-unknown-tool"]
    assert not statuses[0].available


def test_ios_readiness_reports_physical_device_path_on_non_macos():
    readiness = target_readiness("linux", targets=["ios"])
    info = readiness["ios"]
    assert info["host_supported"]  # a prebuilt IPA can be installed on a physical device
    assert "physical-device" in str(info["host_reason"])
    if not info["ready"]:
        assert info["missing"] == ["pymobiledevice3"]
    macos = target_readiness("darwin", targets=["ios"])
    assert macos["ios"]["host_supported"]
    assert "xcodebuild" in macos["ios"]["missing"] or macos["ios"]["ready"]


def test_registry_aliases_resolve_to_providers():
    assert registry.get_provider("electron").id == "desktop"
    assert registry.get_provider("expo").id == "react-native"
    assert registry.get_provider("apk").id == "android"
    assert registry.get_provider("flutter:android").id == "flutter"
    assert registry.get_provider("blackberry") is None
    receipt = registry.run("/tmp", "blackberry", TargetRequest())
    assert receipt.to_text().startswith(UNAVAILABLE_PREFIX)
    assert "Known targets" in receipt.to_text()


def test_dry_run_plan_preview_never_claims_success(tmp_path):
    workspace = _android_workspace(tmp_path / "android")
    text = registry.plan_preview(workspace, "android")
    assert text.startswith(DRY_PREFIX)
    assert "{device}" in text or "gradlew" in text
    assert PASS_PREFIX not in text


# --------------------------------------------------------------------------- #
# live probe sanity (loopback only, no external network)
# --------------------------------------------------------------------------- #


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        body = b"<html><head><title>Probe</title></head><body>ok</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the test server
        return


def test_http_ready_probe_confirms_a_live_server():
    from src.targets.probes import http_ready

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        code, text = http_ready({
            "artifacts_dir": "/tmp", "args": {"url": url, "timeout_s": "5"},
            "request": TargetRequest(), "plan": RunPlan(target="web", provider="web", stages=()),
        })
        assert code == 0 and "HTTP READY" in text and "Probe" in text
    finally:
        server.shutdown()
        server.server_close()


def test_http_ready_probe_times_out_on_a_dead_port():
    from src.targets.probes import http_ready

    code, text = http_ready({
        "artifacts_dir": "/tmp", "args": {"url": "http://127.0.0.1:9/", "timeout_s": "1"},
        "request": TargetRequest(), "plan": RunPlan(target="web", provider="web", stages=()),
    })
    assert code == 1 and "HTTP NOT READY" in text


# --------------------------------------------------------------------------- #
# agent tools (skip cleanly when the agent runtime deps are absent)
# --------------------------------------------------------------------------- #


def test_agent_tools_expose_the_multiplatform_surface(tmp_path):
    pytest.importorskip("langchain_core")
    from src.tools.target_tools import TARGET_TOOLS

    names = {tool.name for tool in TARGET_TOOLS}
    assert names == {
        "detect_targets", "check_target_toolchains", "build_target", "verify_target_app",
        "device_action", "device_screenshot", "device_ui", "device_logs",
        # Mirrors the device into the IDE's preview window (src/preview/device.py).
        "device_preview",
    }
    for tool in TARGET_TOOLS:
        assert tool.description


def test_device_ui_prefers_android_cli_layout_json(tmp_path, monkeypatch):
    pytest.importorskip("langchain_core")
    from types import SimpleNamespace

    import src.tools.target_tools as target_tools
    import src.targets.toolchain as toolchain

    sdk = tmp_path / "Sdk"
    sdk.mkdir()
    layout = json.dumps({"root": {"text": "Sign in", "resourceId": "com.acme:id/login"}})
    captured = []

    monkeypatch.setattr(target_tools, "_adb_serial", lambda device: ("adb", "emulator-5554"))
    monkeypatch.setattr(target_tools, "android_cli_path", lambda: r"C:\Android\android.exe")
    monkeypatch.setattr(target_tools, "android_runner", lambda: "android-cli")
    monkeypatch.setattr(toolchain, "sdk_roots", lambda: [sdk])

    def fake_run(argv, **kwargs):
        captured.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0, stdout=layout, stderr="")

    monkeypatch.setattr(target_tools.subprocess, "run", fake_run)
    result = target_tools.device_ui.invoke({"device": "emulator-5554"})

    assert result.startswith("ANDROID CLI UI LAYOUT on emulator-5554")
    assert '"Sign in"' in result
    argv, kwargs = captured[0]
    assert argv == [r"C:\Android\android.exe", f"--sdk={sdk}", "layout",
                    "--device=emulator-5554", "--pretty"]
    assert kwargs["timeout"] == 120


def test_device_ui_falls_back_to_adb_when_android_cli_layout_is_not_json(tmp_path, monkeypatch):
    pytest.importorskip("langchain_core")
    from types import SimpleNamespace

    import src.tools.target_tools as target_tools
    import src.targets.toolchain as toolchain

    monkeypatch.setattr(target_tools, "_adb_serial", lambda device: ("adb", "emulator-5554"))
    monkeypatch.setattr(target_tools, "android_cli_path", lambda: "android")
    monkeypatch.setattr(target_tools, "android_runner", lambda: "android-cli")
    monkeypatch.setattr(toolchain, "sdk_roots", lambda: [])
    monkeypatch.setattr(
        target_tools.subprocess, "run",
        lambda argv, **kwargs: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )

    adb_calls = []

    def fake_adb(serial, *args, timeout=90):
        adb_calls.append((serial, args))
        if "uiautomator" in args:
            return 0, "UI hierchary dumped"
        return 0, (
            '<hierarchy><node text="Home" resource-id="com.acme:id/home" '
            'bounds="[0,0][100,100]" clickable="true" /></hierarchy>'
        )

    monkeypatch.setattr(target_tools, "_adb_run", fake_adb)
    result = target_tools.device_ui.invoke({"device": "emulator-5554"})

    assert "UI hierarchy on emulator-5554" in result
    assert "Home" in result and "fell back to adb" in result
    assert [args[1][0] for args in adb_calls] == ["shell", "exec-out"]


def test_verify_target_app_dry_run_is_a_plan_not_a_pass(tmp_path):
    pytest.importorskip("langchain_core")
    from src.tools.target_tools import build_target, verify_target_app

    # A long root mimics Windows pytest/temp paths and ensures the rendered plan
    # preserves the executable name when an absolute argv would otherwise be clipped.
    workspace = _android_workspace(tmp_path / ("workspace-" + "x" * 48) / "android")
    config = {"configurable": {"workspace": str(workspace)}}
    preview = build_target.invoke({"target": "android", "dry_run": True}, config=config)
    assert preview.startswith(DRY_PREFIX) and "gradlew" in preview
    verify = verify_target_app.invoke(
        {"target": "android", "assertions": ["text=Sign in"], "dry_run": True}, config=config)
    assert verify.startswith(DRY_PREFIX)
    assert "gradlew" in verify
    assert "PLANNED ASSERTIONS" in verify and "Sign in" in verify
    assert PASS_PREFIX not in verify


# --------------------------------------------------------------------------- #
# verification gate integration (needs the graph deps: langgraph)
# --------------------------------------------------------------------------- #

ANDROID_RECEIPT = """✅ TARGET VERIFICATION PASSED (android:emulator-5554)
TARGET: android  PROVIDER: android  DEVICE: emulator-5554  APP: com.acme.demo  HOST: linux
STAGE build        exit 0       41.2s  ./gradlew :app:assembleDebug --console=plain
STAGE install      exit 0        3.1s  adb -s emulator-5554 install -r -t app-debug.apk
STAGE foreground   exit 0        2.0s  [deterministic] foreground_is_app
ASSERT text 'Sign in' -> found (text match in dump)
VISUAL QUALITY PASSED (dominant=0.31, luma_stddev=52.1, edge_density=0.19).
CRASH SCAN clean
"""

WEB_TARGET_RECEIPT = """✅ TARGET VERIFICATION PASSED (web)
TARGET: web  PROVIDER: web  HOST: linux
STAGE dev_server   exit 0        0.0s  npm run dev
STAGE http_ready   exit 0        0.7s  [deterministic] http_ready
"""


def _gate_state(workspace: Path, registry_message: tuple[str, str]) -> dict:
    from langchain_core.messages import ToolMessage

    name, content = registry_message
    return {
        "current_task": "Build an Android app and verify it on the emulator",
        "workspace": str(workspace),
        "messages": [ToolMessage(content=content, name=name, tool_call_id="call-1")],
        "steps_completed": ["wrote file: MainActivity.kt"],
        "verify_nudges": 0,
    }


def test_device_receipt_satisfies_the_render_requirement(tmp_path):
    pytest.importorskip("langgraph")
    from src.graphs.gates import _verification_receipt_status

    status = _verification_receipt_status(_gate_state(tmp_path, ("verify_target_app", ANDROID_RECEIPT)))
    assert status["ui_task"] is True                 # "app" makes it a rendered surface
    assert status["static"] and status["typecheck"]
    assert status["navigate"] and status["snapshot"] and status["screenshot"]
    assert status["passed"] is True


def test_failed_target_receipt_does_not_satisfy_the_gate(tmp_path):
    pytest.importorskip("langgraph")
    from src.graphs.gates import _verification_receipt_status

    failed = ANDROID_RECEIPT.replace(
        "✅ TARGET VERIFICATION PASSED (android:emulator-5554)",
        "❌ TARGET VERIFICATION FAILED at foreground: com.acme.demo never reached the foreground",
    )
    status = _verification_receipt_status(_gate_state(tmp_path, ("verify_target_app", failed)))
    assert status["passed"] is False
    assert "navigate" in status["missing"]


def test_web_target_receipt_does_not_replace_browser_proof(tmp_path):
    """A dev server answering HTTP is not a rendered page: web keeps owing the
    browser pipeline its navigate/snapshot receipt."""
    pytest.importorskip("langgraph")
    from src.graphs.gates import _target_receipt_proves_render, _verification_receipt_status

    assert _target_receipt_proves_render(ANDROID_RECEIPT) is True
    assert _target_receipt_proves_render(WEB_TARGET_RECEIPT) is False
    state = _gate_state(tmp_path, ("verify_target_app", WEB_TARGET_RECEIPT))
    state["current_task"] = "Build and verify a Next.js web app in the browser"
    status = _verification_receipt_status(state)
    assert status["passed"] is False
    assert "navigate" in status["missing"]


def test_target_build_receipt_is_static_evidence_only(tmp_path):
    pytest.importorskip("langgraph")
    from src.graphs.gates import _verification_receipt_status

    state = _gate_state(tmp_path, ("build_target", ANDROID_RECEIPT))
    status = _verification_receipt_status(state)
    assert status["static"] and status["typecheck"]
    assert not status["navigate"]          # a build is not runtime proof
    assert status["passed"] is False


def test_android_cli_adapter_uses_android_run_for_a_prebuilt_apk(tmp_path, monkeypatch):
    from src.targets.providers import android as android_provider

    workspace = _android_workspace(tmp_path / "android-cli")
    monkeypatch.setenv("CRUSORAI_ANDROID_RUNNER", "android-cli")
    monkeypatch.setattr(android_provider, "android_cli_path", lambda: str(tmp_path / "android.exe"))
    monkeypatch.setattr(android_provider, "connected_devices", lambda: ["emulator-5554"])

    plan = registry.build_plan(
        workspace, "android", TargetRequest(mode="verify", device="emulator-5554")
    )
    run_stage = next(stage for stage in plan.stages if stage.name == "run")
    assert run_stage.handler.endswith("android_cli_run")
    assert run_stage.argv == ("{device}", "{apk}")
    assert "Gradle" in run_stage.note and "does not" not in run_stage.note
    assert "{adb}" not in " ".join(run_stage.argv)


def test_android_cli_run_passes_device_apk_and_discovered_sdk(tmp_path, monkeypatch):
    from src.targets.providers import android as android_provider

    cli = tmp_path / "android.exe"
    sdk = tmp_path / "Sdk"
    sdk.mkdir()
    apk = tmp_path / "app-debug.apk"
    apk.write_bytes(b"apk")
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    monkeypatch.setattr(android_provider, "android_cli_path", lambda: str(cli))
    captured = []

    def fake_run(argv, *, timeout=90):
        captured.append((list(argv), timeout))
        return 0, "run complete"

    monkeypatch.setattr(android_provider, "_run", fake_run)
    code, output = android_provider.android_cli_run({
        "tokens": {"device": "emulator-5554", "apk": str(apk)},
        "workspace": tmp_path,
    })
    assert code == 0 and "Gradle already built" in output
    argv, timeout = captured[0]
    assert argv == [str(cli), f"--sdk={sdk}", "run", "--device=emulator-5554", f"--apks={apk}"]
    assert timeout == 600

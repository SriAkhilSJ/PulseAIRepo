"""Agent tools for multi-platform targets (mobile, desktop, web).

Same law as ``ui_verification.py``: the model decides *what* must be verified
once, and deterministic runtime code owns the mechanical sequence. These tools
are therefore thin — they translate a tool call into a
:class:`~src.targets.runner.TargetRequest`, run one plan, and return one receipt.

Tools
-----
``detect_targets``
    What is this workspace? Ranked candidates with evidence and host support.
``check_target_toolchains``
    The "doctor": what is installed, what is missing, how to install it.
``build_target``
    Build only (no device, no emulator) — the fast compile receipt.
``verify_target_app``
    The composite pipeline: build → install → launch → foreground/window proof →
    UI dump/assertions → screenshot quality → crash scan → cleanup. One call,
    one receipt, no model turns in the middle.
``device_action``
    Reach *into* a running mobile target when a flow needs a tap, a swipe, text
    or a key (interactive exploration after a passing verify).
``device_screenshot`` / ``device_ui`` / ``device_logs``
    Focused evidence reads from the currently attached device.
``device_preview``
    Mirror the attached device into the IDE's Crusor Preview window (live pane +
    real taps), so the human watches the same device the agent is driving.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.targets.providers.android import android_cli_path, android_runner, connected_devices
from src.targets.providers.base import tool_path
from src.targets.registry import (
    detect,
    detect_report,
    get_provider,
    provider_ids,
    run as run_target,
)
from src.targets.runner import TargetRequest
from src.targets.toolchain import doctor_report, target_readiness
from src.tools.toolchain_install import canonical_sdk


def _workspace(config: RunnableConfig) -> Path:
    return Path(config["configurable"]["workspace"]).resolve()


def _request(
    *,
    mode: str,
    device: str = "",
    app_id: str = "",
    url: str = "",
    assertions: list[str] | None = None,
    start_emulator: bool = True,
    keep_running: bool = False,
    timeout_multiplier: float = 1.0,
    extra_args: list[str] | None = None,
) -> TargetRequest:
    parsed: list[tuple[str, str]] = []
    for item in assertions or []:
        if "=" in item:
            kind, value = item.split("=", 1)
        elif ":" in item:
            kind, value = item.split(":", 1)
        else:
            kind, value = "text", item
        if value.strip():
            parsed.append((kind.strip().lower() or "text", value.strip()))
    return TargetRequest(
        mode=mode, device=device.strip(), app_id=app_id.strip(), url=url.strip(),
        assertions=tuple(parsed), start_emulator=start_emulator, keep_running=keep_running,
        timeout_multiplier=max(0.25, float(timeout_multiplier or 1.0)),
        extra_args=tuple(extra_args or ()),
    )


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


@tool
def detect_targets(config: RunnableConfig) -> str:
    """Report which build targets this workspace contains (Android, iOS, Flutter,
    React Native, desktop shell, web) with the evidence and host support.

    Call this FIRST when a user asks for a mobile or desktop app: it tells you
    whether the project already exists (build it) or must be created (scaffold
    it), and which target id to pass to `verify_target_app`.
    """
    workspace = _workspace(config)
    candidates = detect(workspace)
    lines = [detect_report(workspace)]
    if candidates:
        readiness = target_readiness(targets=[candidate.target for candidate in candidates])
        lines.append("")
        for candidate in candidates:
            info = readiness.get(candidate.target, {})
            if not info:
                continue
            if not info.get("host_supported", True):
                lines.append(f"{candidate.target}: HOST-UNSUPPORTED — {info.get('host_reason')}")
            elif info.get("ready"):
                lines.append(f"{candidate.target}: toolchain READY")
            else:
                lines.append(f"{candidate.target}: missing {', '.join(info.get('missing', []))}")
        lines.append("")
        lines.append(
            "Next: verify_target_app(target=<id>, ...). For a workspace with no target yet, "
            "scaffold one (flutter create / create-expo-app / create-tauri-app) then re-detect."
        )
    return "\n".join(lines)


@tool
def check_target_toolchains(target: str, config: RunnableConfig) -> str:
    """Show the toolchain doctor report for one target (or all): what is
    installed, its version, what is missing and the exact install command.

    Use before a long build when `verify_target_app` returned an ⛔ receipt, and
    when telling the user what to install on their machine.
    """
    del config  # host-scoped, no workspace state involved
    requested = target.strip().lower()
    targets = None
    if requested and requested not in ("all", "*", ""):
        if get_provider(requested) is None:
            return (
                f"⛔ unknown target {target!r}. Known targets: {', '.join(provider_ids())}"
            )
        resolved = get_provider(requested)
        targets = [resolved.id] if resolved else None
    report = doctor_report(targets=targets)
    # Missing SDKs are installable, not a dead end (founder 2026-10-18):
    # name the tool so the model offers the install instead of faking a
    # generated project by hand.
    readiness = target_readiness(targets=targets)
    installable: list[str] = []
    for info in readiness.values():
        for tool_id in info.get("missing", []):
            bundle = canonical_sdk(str(tool_id))
            if bundle in ("flutter", "android", "node", "java", "rust", "xcode") \
                    and bundle not in installable:
                installable.append(bundle)
    if installable:
        calls = ", ".join(f'install_toolchain(sdk="{name}")' for name in installable)
        report += (
            f"\n\nMissing SDKs can be installed automatically (asks the "
            f"user first): {calls}. Do NOT hand-author a project "
            f"generator's files (pubspec.yaml, package.json scaffolds) "
            f"as a substitute for a missing SDK — offer the install, "
            f"then create the project with the real generator."
        )
    return report


@tool
def build_target(
    target: str,
    config: RunnableConfig,
    timeout_multiplier: float = 1.0,
    extra_args: list[str] | None = None,
    dry_run: bool = False,
) -> str:
    """Build a target without touching a device (fast compile receipt).

    Use for compile-only iterations on Android (`assembleDebug`), iOS
    (`xcodebuild build`), Flutter, React Native, Tauri/Electron or web. `target`
    accepts provider ids and common aliases (`electron`, `tauri`, `rn`, `expo`,
    `apk`, `ios`, `flutter`, `web`). Set `dry_run=True` to see the exact commands
    without running them.
    """
    workspace = _workspace(config)
    request = _request(mode="build", timeout_multiplier=timeout_multiplier,
                       extra_args=list(extra_args or []))
    receipt = run_target(workspace, target, request, dry_run=dry_run)
    return receipt.to_text()


@tool
def verify_target_app(
    target: str,
    config: RunnableConfig,
    device: str = "",
    app_id: str = "",
    url: str = "",
    assertions: list[str] | None = None,
    start_emulator: bool = True,
    keep_running: bool = False,
    run_tests: bool = False,
    timeout_multiplier: float = 1.0,
    dry_run: bool = False,
    extra_args: list[str] | None = None,
) -> str:
    """Build, run and PROVE a non-web or web target in one deterministic call.

    This is the multi-platform equivalent of `verify_ui_workspace`: it owns
    build → install → launch → foreground/window proof → UI assertions →
    screenshot quality → crash scan → cleanup, and returns ONE receipt.

    * `target` — provider id or alias (`android`, `apk`, `ios`, `flutter`,
      `react-native`, `expo`, `desktop`, `electron`, `tauri`, `dotnet`, `web`).
    * `assertions` — what the app must show, e.g. `["text=Sign in",
      "id=com.acme.demo:id/title"]`; each is checked against the live UI dump and
      a MISSING entry fails the receipt.
    * `run_tests=True` — add the target's own test stage (Gradle
      connectedAndroidTest / xcodebuild test / flutter test).
    * `keep_running=True` — leave the app or dev server up for a follow-up
      interactive turn (the preview window can then attach).
    * `dry_run=True` — print the plan (commands, device tokens, requirements)
      without executing anything.
    * Deliberately do NOT report success without a ✅ receipt: an ⛔ receipt names
      the missing toolchain or the unsupported host, and a ❌ names the exact
      failing stage.
    """
    workspace = _workspace(config)
    mode = "test" if run_tests else "verify"
    request = _request(
        mode=mode, device=device, app_id=app_id, url=url, assertions=assertions,
        start_emulator=start_emulator, keep_running=keep_running,
        timeout_multiplier=timeout_multiplier, extra_args=list(extra_args or []),
    )
    receipt = run_target(workspace, target, request, dry_run=dry_run)
    return receipt.to_text()


# --------------------------------------------------------------------------- #
# device interaction (mobile)
# --------------------------------------------------------------------------- #


def _adb_serial(device: str) -> tuple[str, str]:
    """Pick the device to drive: explicit serial → first attached."""
    if device.strip():
        return tool_path("adb", fallback="adb"), device.strip()
    devices = connected_devices()
    if not devices:
        return "", ""
    return tool_path("adb", fallback="adb"), devices[0]


def _adb_run(serial: str, *args: str, timeout: int = 90) -> tuple[int, str]:
    adb = tool_path("adb", fallback="adb")
    try:
        proc = subprocess.run([adb, "-s", serial, *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"adb timed out after {timeout}s"
    except (OSError, FileNotFoundError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")


@tool
def device_action(
    action: str,
    config: RunnableConfig,
    device: str = "",
    x: int = 0,
    y: int = 0,
    x2: int = 0,
    y2: int = 0,
    text: str = "",
    key: str = "",
    package: str = "",
) -> str:
    """Drive a live mobile target: tap, swipe, type, key, launch, stop, rotate.

    Actions: `tap` (x,y) · `swipe` (x,y → x2,y2) · `type` (text) · `key`
    (BACK/HOME/ENTER/…) · `launch` (package) · `stop` (package) · `rotate` ·
    `list` (attached devices) · `stop_emulator` (emulators only).

    Use this for interactive exploration AFTER `verify_target_app` returned a ✅
    receipt — not as a substitute for it.
    """
    del config
    adb, serial = _adb_serial(device)
    if action.strip().lower() == "list":
        devices = connected_devices()
        if not devices:
            return (
                "no device or emulator is attached (`adb devices` empty). Start one with "
                "`emulator -avd <name>` or plug in a device with USB debugging enabled."
            )
        lines: list[str] = []
        for item in devices:
            code, model = _adb_run(item, "shell", "getprop", "ro.product.model", timeout=30)
            lines.append(f"{item}: {model.strip() or 'unknown model'}")
        return "attached devices:\n" + "\n".join(lines)
    if not serial:
        return (
            "⛔ device_action needs a device: none is attached and none was named. "
            "Start an emulator or pass device=<serial>."
        )
    verb = action.strip().lower()
    if verb == "tap":
        code, out = _adb_run(serial, "shell", "input", "tap", str(int(x)), str(int(y)))
    elif verb == "swipe":
        code, out = _adb_run(serial, "shell", "input", "swipe", str(int(x)), str(int(y)),
                             str(int(x2)), str(int(y2)), "300")
    elif verb == "type":
        escaped = text.replace(" ", "%s")
        code, out = _adb_run(serial, "shell", "input", "text", escaped)
    elif verb == "key":
        code, out = _adb_run(serial, "shell", "input", "keyevent",
                             (key or "KEYCODE_BACK").upper().replace("KEYCODE_", "") if key else "4")
    elif verb == "launch":
        if not package.strip():
            return "⛔ launch needs package=<application id>"
        code, out = _adb_run(serial, "shell", "monkey", "-p", package.strip(),
                             "-c", "android.intent.category.LAUNCHER", "1")
    elif verb == "stop":
        if not package.strip():
            return "⛔ stop needs package=<application id>"
        code, out = _adb_run(serial, "shell", "am", "force-stop", package.strip())
    elif verb == "rotate":
        code, out = _adb_run(serial, "shell", "settings", "put", "system",
                             "user_rotation", str(int(x) % 4))
    elif verb == "stop_emulator":
        if not serial.startswith("emulator-"):
            return f"⛔ refusing to kill {serial}: that is not an emulator"
        code, out = _adb_run(serial, "emu", "kill")
    else:
        return (
            f"⛔ unknown action {action!r}. Use tap | swipe | type | key | launch | stop | "
            "rotate | list | stop_emulator."
        )
    verdict = "✅" if code == 0 else "❌"
    return f"{verdict} device_action {verb} on {serial} (exit {code})\n{out.strip()[-800:]}"


@tool
def device_screenshot(name: str, config: RunnableConfig, device: str = "") -> str:
    """Capture the current mobile screen into the evidence directory.

    Returns the artifact path plus the near-blank quality verdict, so a uniform
    capture can never be presented as proof of a rendered UI.
    """
    workspace = _workspace(config)
    _, serial = _adb_serial(device)
    if not serial:
        return "⛔ device_screenshot: no device attached (start an emulator or pass device=)"
    from src.targets.evidence import artifact_for
    from src.targets.runner import evidence_dir
    from src.tools.visual_quality import format_quality_receipt

    target_dir = evidence_dir(workspace, "device", base=os.environ.get("CRUSORAI_TARGET_EVIDENCE_DIR"))
    path = Path(target_dir) / f"{(name or 'screen').strip()}.png"
    try:
        with open(path, "wb") as handle:
            proc = subprocess.run(
                [tool_path("adb", fallback="adb"), "-s", serial, "exec-out", "screencap", "-p"],
                stdout=handle, stderr=subprocess.PIPE, timeout=90, check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"❌ device_screenshot failed: {exc}"
    if proc.returncode != 0 or not path.exists() or path.stat().st_size == 0:
        return f"❌ device_screenshot failed on {serial}: {proc.stderr.decode('utf-8', 'replace')[:400]}"
    artifact = artifact_for(path, kind="screenshot")
    from src.targets.evidence import screenshot_quality

    quality = screenshot_quality(path)
    return (
        f"EVIDENCE {artifact.render()}\n{format_quality_receipt(quality)}"
        f"\nread it with read_file / attach it to the answer as visual proof"
    )


@tool
def device_ui(device: str = "", config: RunnableConfig | None = None) -> str:
    """Dump the live mobile UI hierarchy as text (what the user can actually see).

    Prefer this over guessing coordinates: it lists the real labels, resource
    ids and content descriptions, in the order they appear.
    """
    _, serial = _adb_serial(device)
    if not serial:
        return "⛔ device_ui: no device attached (start an emulator or pass device=)"

    # Prefer the official Android CLI's structured accessibility layout when
    # installed. Keep the direct adb/uiautomator path as the reliable fallback
    # (and for users who pin CRUSORAI_ANDROID_RUNNER=adb).
    layout_fallback = ""
    try:
        cli = android_cli_path()
        if cli and android_runner() == "android-cli":
            from src.targets.toolchain import sdk_roots

            argv = [cli]
            sdk_root = next((root for root in sdk_roots() if root.is_dir()), None)
            if sdk_root is not None:
                argv.append(f"--sdk={sdk_root}")
            argv.extend(("layout", f"--device={serial}", "--pretty"))
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
            output = (proc.stdout or "").strip()
            if proc.returncode == 0 and output:
                try:
                    json.loads(output)
                    return f"ANDROID CLI UI LAYOUT on {serial}\n{output[:6000]}"
                except json.JSONDecodeError:
                    layout_fallback = "Android CLI layout returned non-JSON output; fell back to adb."
            else:
                layout_fallback = f"Android CLI layout exited {proc.returncode}; fell back to adb."
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        layout_fallback = f"Android CLI layout unavailable ({type(exc).__name__}); fell back to adb."

    dump_path = "/sdcard/crusorai-ui-dump.xml"
    code, out = _adb_run(serial, "shell", "uiautomator", "dump", dump_path, timeout=120)
    if code != 0:
        return (
            f"❌ uiautomator dump failed on {serial} (exit {code})\n{out.strip()[-600:]}\n"
            "Retry while the UI is idle, or use device_screenshot for visual evidence."
        )
    code, xml = _adb_run(serial, "exec-out", "cat", dump_path, timeout=120)
    if code != 0 or not xml.strip():
        return f"❌ could not read the UI dump from {serial}: {out.strip()[-400:]}"
    from src.targets.evidence import parse_ui_dump, ui_dump_text

    elements = parse_ui_dump(xml)
    if not elements:
        return "⚠️ the UI dump parsed to zero elements (unusual) — use device_screenshot instead"
    clickable = [element for element in elements if element.clickable]
    lines = [
        f"UI hierarchy on {serial}: {len(elements)} nodes, {len(clickable)} clickable",
        ui_dump_text(elements)[:4000],
    ]
    if clickable:
        lines.append("")
        lines.append("clickable centers (x,y):")
        for element in clickable[:20]:
            center = element.center
            if center:
                lines.append(f"  ({center[0]},{center[1]}) {element.label()[:70]}")
    if layout_fallback:
        lines.append("\n" + layout_fallback)
    return "\n".join(lines)


@tool
def device_logs(lines: int = 200, device: str = "", config: RunnableConfig | None = None) -> str:
    """Tail the device log and scan it for this app's crashes (FATAL/ANR/native).

    Returns the crash findings first (if any), then the raw tail.
    """
    _, serial = _adb_serial(device)
    if not serial:
        return "⛔ device_logs: no device attached (start an emulator or pass device=)"
    count = max(20, min(int(lines or 200), 2000))
    code, out = _adb_run(serial, "logcat", "-d", "-t", str(count), timeout=120)
    if code != 0:
        return f"❌ logcat failed on {serial} (exit {code}): {out.strip()[-400:]}"
    from src.targets.evidence import scan_crashes

    findings = scan_crashes(out, "android")
    header = f"CRASH SCAN: {len(findings)} finding(s) in the last {count} lines"
    body = "\n".join(f"- {finding}" for finding in findings) if findings else "clean"
    tail = "\n".join(out.splitlines()[-60:])
    return f"{header}\n{body}\n\nLAST 60 LINES\n{tail}"


@tool
def device_preview(
    device: str = "",
    label: str = "",
    fps: float = 4.0,
    open_in_ide: bool = True,
    config: RunnableConfig = None,
) -> str:
    """Mirror the attached Android device into the IDE's Crusor Preview window.

    USE after the app is installed (and typically after `verify_target_app` passed) when a human
    should watch or poke the running app: the pane streams the real device screen and taps,
    swipes and typing inside it are real input, while `device_action` stays the way for the
    agent to drive precisely. The pane appears as a normal preview window next to the web
    preview. ``device`` is an adb serial (default: the single attached device);
    ``fps`` is 0.5–10 frames per second (screen-grab mirroring, not screen casting).
    """
    from src.preview.autostart import DEFAULT_SESSION, ensure_proxy
    from src.preview.endpoint import read_endpoint

    workspace = _workspace(config)
    handle = ensure_proxy(workspace)
    if handle is None:
        return (
            "⛔ device_preview could not start the preview proxy for this workspace. "
            "Check that the engine can run `python -m src.preview.server` and retry."
        )
    endpoint = read_endpoint(DEFAULT_SESSION) or {}
    secret = str(endpoint.get("secret") or "")
    origin = str(handle.origin or endpoint.get("origin") or "").rstrip("/")
    if not origin:
        return "⛔ device_preview has no proxy origin to register against."

    body = json.dumps({"serial": device.strip(), "label": label.strip(), "fps": fps}).encode("utf-8")
    request = urllib.request.Request(
        f"{origin}/crusor-preview/device", data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Crusor-Preview-Secret": secret,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - loopback proxy
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8") or "{}").get("error", "")
        except (ValueError, OSError):
            detail = ""
        reason = detail or f"the preview proxy answered {exc.code}"
        if exc.code == 409:
            return f"⛔ device_preview found nothing to mirror: {reason}"
        return f"⛔ device_preview refused ({exc.code}): {reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"⛔ device_preview could not reach the preview proxy at {origin}: {exc}"

    if not payload.get("ok"):
        return f"⛔ device_preview failed: {payload.get('error') or 'unknown error'}"

    pane_url = f"{origin}{payload.get('paneUrl') or ''}"
    size = f"{payload.get('width')}×{payload.get('height')}" if payload.get("width") else "size pending"
    lines = [
        f"🖥️ DEVICE PREVIEW (android) — {payload.get('serial')}  {payload.get('model') or 'unknown model'}  {size}",
        f"FPS {payload.get('fps')} (screen-grab mirror; use `device_screenshot` for a pinned frame)",
        f"PANE {pane_url}",
        f"API stream {origin}{payload.get('streamUrl')} · status {origin}{payload.get('statusUrl')}",
        "INTERACT taps, swipes and typing in the pane are real input on the device; "
        "`device_action` remains the precise, scripted path.",
    ]
    if open_in_ide:
        opened = ""
        try:
            from src.tools.host_tools import open_preview

            opened = open_preview.func(pane_url, config)  # type: ignore[attr-defined]
        except Exception as exc:  # the desktop is optional (CLI/headless runs)
            opened = f"preview window not opened ({type(exc).__name__}: {exc})"
        if opened:
            lines.append(f"IDE {opened.strip()}")
    return "\n".join(lines)


TARGET_TOOLS = [
    detect_targets,
    check_target_toolchains,
    build_target,
    verify_target_app,
    device_action,
    device_screenshot,
    device_ui,
    device_logs,
    device_preview,
]

__all__ = [
    "TARGET_TOOLS",
    "build_target",
    "check_target_toolchains",
    "detect_targets",
    "device_action",
    "device_logs",
    "device_preview",
    "device_screenshot",
    "device_ui",
    "verify_target_app",
]

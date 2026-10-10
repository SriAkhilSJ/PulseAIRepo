"""One-receipt Android verification: build → install → launch → prove → evidence.

The model decides WHAT must be verified once. Deterministic runtime code owns
the mechanical sequence, so no API call is spent between predictable steps —
the same shape as `ui_verification.verify_ui_workspace`, for a phone.

Three rules make this trustworthy rather than merely green:

1. **The exit code is read from the process, not from rendered text.** The
   stop gate elsewhere tests `"exit code: 0" in output`; here we hold the real
   `returncode`. Nothing is piped, so nothing can mask it.
2. **Tiers.** A claim is only as strong as its evidence. Tier 1 = the APK is
   structurally real; Tier 2 = it actually ran on a device; Tier 3 = an
   assertion was evaluated with an observed value. The receipt names the tier
   it reached and refuses to claim a higher one.
3. **`unavailable` is not `failed` and neither is `passed`.** No JDK, no SDK,
   no device — the run reports what is missing and stops. A user reading
   `passed` believes it.

Evidence lands in `<workspace>/.crusorai/android-evidence/<run-id>/` so a human
can re-derive the result without trusting the summary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# A cold Gradle build downloads the whole dependency tree; 10 minutes is
# routine. Timing out early produces a confusing failure that looks like a
# broken project rather than a slow first build.
_BUILD_TIMEOUT_S = int(os.environ.get("CRUSORAI_ANDROID_BUILD_TIMEOUT", "1800"))
_STEP_TIMEOUT_S = 120
# How long to let the process come up before asserting on it. Env-tunable so
# tests are not paying three seconds per case for a real device's cold start.
_LAUNCH_SETTLE_S = float(os.environ.get("CRUSORAI_ANDROID_LAUNCH_SETTLE", "3"))

_FATAL_RE = re.compile(r"\bFATAL EXCEPTION\b|\bANR in\b|\bAndroidRuntime\s*:\s*FATAL\b")


def _run(argv: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    """Run a step. Returns the REAL returncode — never piped, never parsed
    out of text. A command we cannot run is 127, a timeout is 124."""
    full_env = dict(os.environ)
    full_env.update({"CI": "1", "NO_COLOR": "1"})
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, env=full_env,
        )
    except FileNotFoundError:
        return 127, f"command not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(argv)}"
    except OSError as exc:
        return 1, f"could not run: {exc}"
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, out.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _gradle_command(workspace: Path) -> list[str] | None:
    """Prefer the wrapper; fall back to a system gradle. Windows needs the
    .bat and cannot exec the shell script."""
    wrapper = workspace / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if wrapper.is_file():
        return [str(wrapper)]
    system = shutil.which("gradle.bat" if os.name == "nt" else "gradle")
    return [system] if system else None


def _find_apk(workspace: Path) -> Path | None:
    candidates = sorted(workspace.glob("app/build/outputs/apk/**/*.apk"))
    return candidates[0] if candidates else None


def _aapt_badging(apk: Path) -> dict:
    """Parse the APK's real identity. Tier 1 evidence: proves the artifact is
    the app it claims to be, not merely a file with a .apk extension."""
    for name in ("aapt2", "aapt"):
        aapt = shutil.which(name)
        if not aapt:
            continue
        code, out = _run([aapt, "dump", "badging", str(apk)], apk.parent, _STEP_TIMEOUT_S)
        if code != 0:
            continue
        info: dict = {}
        pkg = re.search(r"package:\s*name='([^']+)'", out)
        version_code = re.search(r"versionCode='([^']+)'", out)
        version_name = re.search(r"versionName='([^']+)'", out)
        sdk = re.search(r"sdkVersion:'([^']+)'", out)
        launcher = re.search(r"launchable-activity:\s*name='([^']+)'", out)
        if pkg:
            info["package"] = pkg.group(1)
        if version_code:
            info["versionCode"] = version_code.group(1)
        if version_name:
            info["versionName"] = version_name.group(1)
        if sdk:
            info["minSdk"] = sdk.group(1)
        if launcher:
            info["launchableActivity"] = launcher.group(1)
        return info
    return {}


@tool
def verify_android_app(
    package_id: str,
    config: RunnableConfig,
    flow_yaml: str = "",
    run_tests: bool = False,
) -> str:
    """Build the Android app, install it, and prove it actually ran.

    USE after writing or changing Android code, instead of claiming the build
    works. One call runs the whole sequence: Gradle assembleDebug, APK
    validation, adb install, launch, process-alive proof, and a logcat crash
    scan — then writes an evidence bundle to
    `.crusorai/android-evidence/<run-id>/`.

    `package_id` is the applicationId, e.g. "com.example.notes". Pass
    `flow_yaml` to also drive the UI through agent-device (Tier 3). Set
    `run_tests` to run the project's own Gradle tests.

    The receipt names the evidence tier it reached. It returns `unavailable`
    — never `passed` — when the toolchain or device is missing, and it never
    pipes a build, so the exit code cannot be masked.
    """
    workspace = Path(str(config["configurable"]["workspace"])).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    evidence_dir = workspace / ".crusorai" / "android-evidence" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)

    pkg = (package_id or "").strip()
    checks: dict[str, dict] = {}
    tier = 0
    artifacts: list[str] = []

    def record(name: str, *, status: str, level: int = 0, exit_code: int | None = None,
               observed: dict | None = None, artifact: str = "") -> None:
        checks[name] = {
            "status": status, "tier": level,
            **({"exit": exit_code} if exit_code is not None else {}),
            **({"observed": observed} if observed else {}),
            **({"artifact": artifact} if artifact else {}),
        }

    def write(name: str, content: str) -> str:
        path = evidence_dir / name
        try:
            path.write_text(content, encoding="utf-8")
            artifacts.append(name)
        except OSError:
            pass
        return name

    def finish(overall: str, summary: str) -> str:
        manifest = {
            "schema": "crusor.android.evidence/1",
            "run_id": run_id,
            "tier_reached": tier,
            "overall": overall,
            "workspace": str(workspace),
            "package_id": pkg,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "artifacts": artifacts,
        }
        write("evidence.json", json.dumps(manifest, indent=2))
        lines = [f"{overall} — Android verification · tier {tier} · {run_id}", ""]
        for name, check in checks.items():
            mark = {"passed": "✅", "failed": "❌"}.get(check["status"], "⚠️")
            extra = ""
            if check.get("exit") is not None:
                extra += f" exit={check['exit']}"
            if check.get("observed"):
                extra += " " + json.dumps(check["observed"])
            lines.append(f"{mark} {name}{extra}")
        lines += ["", summary, "", f"Evidence: {evidence_dir}"]
        return "\n".join(lines)

    # ---- preflight -------------------------------------------------------
    # Failing fast here is the difference between a named gap and a Gradle
    # stack trace the model has to interpret.
    if not shutil.which("java"):
        record("preflight_jdk", status="unavailable")
        return finish("⛔ UNAVAILABLE", (
            "No JDK on PATH, so nothing can be built. Install a JDK 17+ and "
            "re-run. This is NOT a failure of the code — no build was attempted."
        ))
    gradle = _gradle_command(workspace)
    if not gradle:
        record("preflight_gradle", status="unavailable")
        return finish("⛔ UNAVAILABLE", (
            "No Gradle wrapper at the workspace root and no system gradle on "
            "PATH. Run scaffold_android, or `gradle wrapper` in an existing "
            "project. No build was attempted."
        ))

    # ---- build -----------------------------------------------------------
    build_task = "assembleDebug"
    code, output = _run([*gradle, build_task], workspace, _BUILD_TIMEOUT_S)
    write("build.log", output)
    record("gradle_assembleDebug", status="passed" if code == 0 else "failed",
           level=1, exit_code=code, artifact="build.log")
    if code != 0:
        tail = output[-1500:]
        return finish("❌ FAILED", (
            f"`{' '.join(gradle)} {build_task}` exited {code}. The build log is "
            f"saved untruncated at {evidence_dir / 'build.log'}; the tail is "
            f"below.\n\n{tail}"
        ))
    tier = 1

    # ---- artifact identity ----------------------------------------------
    apk = _find_apk(workspace)
    if apk is None:
        record("apk_present", status="failed", level=1)
        return finish("❌ FAILED", (
            "The build exited 0 but no APK was produced under "
            "app/build/outputs/apk/. A green exit code with no artifact is not "
            "a successful build."
        ))
    badging = _aapt_badging(apk)
    size = apk.stat().st_size
    digest = _sha256(apk)
    write("apk.sha256", f"{digest}  {apk.name}\n")
    record("apk_identity", status="passed", level=1,
           observed={"file": apk.name, "bytes": size, "sha256": digest[:16], **badging})
    if badging.get("package") and badging["package"] != pkg:
        record("apk_package_matches_request", status="failed", level=1,
               observed={"expected": pkg, "actual": badging["package"]})
        return finish("❌ FAILED", (
            f"The APK's real package is {badging['package']!r}, not the "
            f"requested {pkg!r}. Installing it would put a different app on the "
            "device than the one being verified."
        ))

    # ---- device ----------------------------------------------------------
    adb = shutil.which("adb")
    if not adb:
        record("adb_present", status="unavailable")
        return finish("⚠️ PARTIAL", (
            "Tier 1 reached: the app builds and the APK is structurally real "
            f"({apk.name}, {size} bytes). No adb on PATH, so it was never "
            "installed or run — do not describe this as a working app."
        ))
    code, devices_out = _run([adb, "devices"], workspace, _STEP_TIMEOUT_S)
    serials = [
        line.split()[0] for line in devices_out.splitlines()[1:]
        if line.strip() and "\tdevice" in line
    ]
    if not serials:
        record("device_online", status="unavailable", observed={"adb_devices": devices_out})
        return finish("⚠️ PARTIAL", (
            "Tier 1 reached: the app builds and the APK is real. No device or "
            "emulator is attached (`adb devices` shows none), so nothing was "
            "installed or launched. Start an emulator or plug in a device with "
            "USB debugging, then re-run for Tier 2."
        ))
    serial = serials[0]
    record("device_online", status="passed", level=2,
           observed={"serial": serial, "count": len(serials)})
    tier = 2

    # ---- install ---------------------------------------------------------
    code, out = _run([adb, "-s", serial, "install", "-r", "-t", str(apk)],
                     workspace, _STEP_TIMEOUT_S * 3)
    write("install.log", out)
    ok = code == 0 and "Success" in out
    record("adb_install", status="passed" if ok else "failed", level=2,
           exit_code=code, artifact="install.log")
    if not ok:
        return finish("❌ FAILED", f"adb install failed (exit {code}):\n{out[-1200:]}")

    # ---- launch + prove it is alive -------------------------------------
    launcher = badging.get("launchableActivity")
    if launcher:
        component = launcher if "/" in launcher else f"{pkg}/{launcher}"
        code, out = _run(
            [adb, "-s", serial, "shell", "am", "start", "-n", component],
            workspace, _STEP_TIMEOUT_S,
        )
        write("launch.log", out)
        record("am_start", status="passed" if code == 0 else "failed", level=2,
               exit_code=code, observed={"component": component})
    else:
        # monkey is the fallback launcher when aapt could not name the activity.
        code, out = _run(
            [adb, "-s", serial, "shell", "monkey", "-p", pkg,
             "-c", "android.intent.category.LAUNCHER", "1"],
            workspace, _STEP_TIMEOUT_S,
        )
        write("launch.log", out)
        record("launch", status="passed" if code == 0 else "failed", level=2, exit_code=code)

    time.sleep(_LAUNCH_SETTLE_S)
    code, out = _run([adb, "-s", serial, "shell", "pidof", pkg], workspace, _STEP_TIMEOUT_S)
    pid = out.strip()
    alive = code == 0 and pid.isdigit()
    record("process_alive", status="passed" if alive else "failed", level=2,
           observed={"pid": pid or None})
    if not alive:
        return finish("❌ FAILED", (
            f"The app installed and was launched, but `pidof {pkg}` returned "
            f"nothing — it is not running. It most likely crashed on start. "
            f"Check {evidence_dir / 'logcat.txt'}."
        ))

    # ---- crash scan ------------------------------------------------------
    code, out = _run([adb, "-s", serial, "logcat", "-d"], workspace, _STEP_TIMEOUT_S)
    relevant = "\n".join(
        line for line in out.splitlines() if _FATAL_RE.search(line) or pkg in line
    )[-20000:]
    write("logcat.txt", relevant or "(no lines mentioning the package or a fatal error)")
    fatals = len(_FATAL_RE.findall(out))
    record("no_fatal_in_logcat", status="passed" if fatals == 0 else "failed", level=2,
           observed={"fatal": fatals})
    if fatals:
        return finish("❌ FAILED", (
            f"The app is running but logcat shows {fatals} fatal error(s). "
            f"See {evidence_dir / 'logcat.txt'}."
        ))

    # ---- optional: the project's own tests ------------------------------
    if run_tests:
        code, out = _run([*gradle, "test"], workspace, _BUILD_TIMEOUT_S)
        write("test.log", out)
        record("gradle_test", status="passed" if code == 0 else "failed",
               level=2, exit_code=code, artifact="test.log")
        if code != 0:
            return finish("❌ FAILED", f"`gradle test` exited {code}:\n{out[-1500:]}")

    # ---- optional: drive the UI (Tier 3) --------------------------------
    if flow_yaml.strip():
        agent_device = shutil.which("agent-device")
        if not agent_device:
            record("ui_flow", status="unavailable",
                   observed={"reason": "agent-device not on PATH"})
            return finish("⚠️ PARTIAL", (
                "Tier 2 reached: the app builds, installs, launches, and stays "
                "alive with no fatal errors. A UI flow was requested but "
                "agent-device is not installed, so no assertion was evaluated — "
                "do not describe the UI as verified."
            ))
        flow_path = evidence_dir / "flow.yaml"
        write("flow.yaml", flow_yaml)
        code, out = _run([agent_device, "replay", str(flow_path)], workspace, _STEP_TIMEOUT_S * 5)
        write("ui-flow.log", out)
        record("ui_flow", status="passed" if code == 0 else "failed", level=3,
               exit_code=code, artifact="ui-flow.log")
        if code == 0:
            tier = 3
        else:
            return finish("❌ FAILED", f"The UI flow failed (exit {code}):\n{out[-1500:]}")

    reached = {
        1: "the app builds and the APK is structurally real",
        2: "the app builds, installs, launches, and runs without fatal errors",
        3: "the above, plus a UI flow was driven and its assertions evaluated",
    }[tier]
    return finish("✅ PASSED", f"Tier {tier} — {reached}.")

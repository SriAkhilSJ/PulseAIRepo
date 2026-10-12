"""Android toolchain doctor — one call, one honest environment report.

An agent that cannot tell "the build failed" from "there is no JDK" will burn
a dozen turns guessing. This tool answers the environment question once, with
named versions and the exact next action for each gap.

Contract (D17): returns a string, never raises. Every probe is best-effort and
wrapped, so a broken `java` binary degrades to one ❌ line rather than an
exception into the turn.

Deliberately does NOT boot a device, install anything, or run a build. It is a
read-only probe, so it is safe to call at any point and cheap enough to call
before the first Gradle invocation.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

_PROBE_TIMEOUT_S = 15

# agent-device requires Node 22.12+; web automation needs 24+.
# Maestro requires Java 17+. Gradle 8.x + AGP 8.x want JDK 17.
_MIN_NODE = (22, 12)
_MIN_JAVA = (17,)


def _run(argv: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run a probe command, never raising. Returns (exit, combined output)."""
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S,
        )
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {_PROBE_TIMEOUT_S}s"
    except OSError as exc:
        return 1, f"could not run: {exc}"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _version_tuple(text: str) -> tuple[int, ...] | None:
    """First dotted integer run in the text, as a tuple. None if absent."""
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text or "")
    if not match:
        return None
    return tuple(int(p) for p in match.groups() if p is not None)


def _at_least(found: tuple[int, ...] | None, required: tuple[int, ...]) -> bool:
    if not found:
        return False
    return found >= required


def _java_probe() -> tuple[str, str, str]:
    """(status, version, hint). status is one of ok/warn/missing."""
    java = shutil.which("java")
    if not java:
        return "missing", "", (
            "install a JDK 17+ (Temurin/Adoptium or Android Studio's bundled "
            "JBR) and put it on PATH, or set JAVA_HOME"
        )
    code, out = _run([java, "-version"])
    version = _version_tuple(out)
    if code != 0 or not version:
        return "warn", out.splitlines()[0][:80] if out else "", (
            "java is on PATH but `java -version` failed — check JAVA_HOME"
        )
    # `java -version` prints `1.8.0_402` for Java 8 and `17.0.11` for 17+.
    effective = version[1:] if version[:1] == (1,) and len(version) > 1 else version
    if not _at_least(effective, _MIN_JAVA):
        return "warn", ".".join(str(p) for p in version), (
            f"Java {'.'.join(str(p) for p in version)} is below the "
            f"{'.'.join(str(p) for p in _MIN_JAVA)} required by Gradle 8.x/AGP "
            "8.x and by Maestro"
        )
    return "ok", ".".join(str(p) for p in version), ""


def _sdk_probe(workspace: Path) -> tuple[str, str, str]:
    """Locate the Android SDK. Order: env, local.properties, common paths."""
    candidates: list[tuple[str, Path]] = []
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        raw = os.environ.get(var, "").strip()
        if raw:
            candidates.append((var, Path(raw)))
    local_props = workspace / "local.properties"
    if local_props.is_file():
        try:
            for line in local_props.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().lower().startswith("sdk.dir="):
                    raw = line.split("=", 1)[1].strip()
                    # local.properties escapes Windows separators.
                    candidates.append(("local.properties", Path(raw.replace("\\:", ":").replace("\\\\", "\\"))))
        except OSError:
            pass
    home = Path.home()
    candidates += [
        ("~/Library/Android/sdk", home / "Library/Android/sdk"),
        ("~/AppData/Local/Android/Sdk", home / "AppData/Local/Android/Sdk"),
        ("~/Android/Sdk", home / "Android/Sdk"),
    ]
    for source, path in candidates:
        try:
            if path.is_dir() and (path / "platform-tools").is_dir():
                return "ok", f"{path} (via {source})", ""
        except OSError:
            continue
    found = next((str(p) for _s, p in candidates), "")
    return "missing", found, (
        "install the Android SDK command-line tools, or open the project once "
        "in Android Studio, then set ANDROID_HOME"
    )


def _binary_probe(name: str, args: list[str], label: str) -> tuple[str, str, str]:
    path = shutil.which(name)
    if not path:
        return "missing", "", f"install {label} and put it on PATH"
    code, out = _run([path, *args])
    version = _version_tuple(out)
    if code != 0:
        return "warn", "", f"{name} is on PATH but `{name} {' '.join(args)}` failed"
    return "ok", ".".join(str(p) for p in version) if version else "present", ""


def _avd_probe() -> tuple[str, str, str]:
    """List AVDs without booting anything."""
    emulator = shutil.which("emulator")
    if not emulator:
        return "missing", "", "the emulator package is not installed (SDK Manager → Android Emulator)"
    code, out = _run([emulator, "-list-avds"])
    if code != 0:
        return "warn", "", "`emulator -list-avds` failed"
    avds = [line.strip() for line in out.splitlines() if line.strip()]
    if not avds:
        return "warn", "none defined", (
            "create one: `avdmanager create avd -n pixel7 -k "
            "\"system-images;android-34;google_apis;x86_64\"`"
        )
    return "ok", f"{len(avds)}: {', '.join(avds[:5])}", ""


def _gradlew_probe(workspace: Path) -> tuple[str, str, str]:
    if (workspace / "gradlew").is_file() or (workspace / "gradlew.bat").is_file():
        return "ok", "wrapper present at workspace root", ""
    if any(workspace.glob("*/gradlew*")):
        return "warn", "found in a subdirectory", (
            "the wrapper is not at the workspace root — Gradle commands must run "
            "from the directory that holds it"
        )
    return "missing", "", (
        "no Gradle wrapper here yet — scaffold an Android project first, or run "
        "`gradle wrapper` in an existing one"
    )


def _node_probe() -> tuple[str, str, str]:
    node = shutil.which("node")
    if not node:
        return "missing", "", "install Node.js 22.12+ (required by agent-device)"
    code, out = _run([node, "--version"])
    version = _version_tuple(out)
    if code != 0 or not version:
        return "warn", "", "`node --version` failed"
    if not _at_least(version, _MIN_NODE):
        return "warn", ".".join(str(p) for p in version), (
            f"Node {'.'.join(str(p) for p in version)} is below the "
            f"{'.'.join(str(p) for p in _MIN_NODE)} required by agent-device"
        )
    return "ok", ".".join(str(p) for p in version), ""


_ICON = {"ok": "✅", "warn": "⚠️", "missing": "❌"}


@tool
def android_doctor(config: RunnableConfig) -> str:
    """Check the Android toolchain and report exactly what is missing.

    USE before building, installing, or UI-testing an Android app, and again
    after a toolchain failure. Probes JDK, Android SDK, adb, emulator and AVDs,
    the Gradle wrapper in the workspace, and Node.js plus the device automation
    backends (agent-device or mobile-mcp) used for UI testing.

    Read-only: it never boots a device, installs anything, or runs a build.
    Returns one line per component with its version and the exact next action
    for any gap, then a verdict. Call it instead of guessing at a failed build.
    """
    workspace = Path(str(config["configurable"]["workspace"])).resolve()

    probes: list[tuple[str, tuple[str, str, str]]] = [
        ("JDK (17+ required)", _java_probe()),
        ("Android SDK", _sdk_probe(workspace)),
        ("adb", _binary_probe("adb", ["version"], "Android platform-tools")),
        ("emulator", _binary_probe("emulator", ["-version"], "the Android Emulator package")),
        ("AVDs", _avd_probe()),
        ("Gradle wrapper", _gradlew_probe(workspace)),
        ("Node.js (22.12+, for agent-device)", _node_probe()),
        (
            "agent-device (UI testing)",
            _binary_probe("agent-device", ["--version"], "agent-device (`npm i -g agent-device@latest`)"),
        ),
        # Either backend is sufficient, so this one is reported but never on
        # its own blocks the verdict — see the either/or check below.
        (
            "mobile-mcp (UI testing, alternative)",
            _binary_probe("mcp-server-mobile", ["--version"],
                          "@mobilenext/mobile-mcp (`npm i -g @mobilenext/mobile-mcp`, "
                          "only needed if agent-device is absent)"),
        ),
    ]

    # A device backend is required, but not a specific one. Reporting
    # "mobile-mcp missing" as blocking would tell a user with a perfectly good
    # agent-device install that their toolchain is broken.
    _OPTIONAL = {"mobile-mcp (UI testing, alternative)"}

    lines = [f"Android toolchain — {workspace}", ""]
    counts = {"ok": 0, "warn": 0, "missing": 0}
    actions: list[str] = []
    for label, (status, detail, hint) in probes:
        counts[status] += 1
        lines.append(f"{_ICON[status]} {label}: {detail or 'not found'}")
        if hint:
            lines.append(f"    → {hint}")
            actions.append(hint)

    # The verdict names the BLOCKING gap, not just a tally: a missing JDK makes
    # every later step fail regardless of how green the rest of the list is.
    blocking = [label for label, (status, _d, _h) in probes
                if status == "missing" and label not in _OPTIONAL]
    _statuses = {label: status for label, (status, _d, _h) in probes}
    if (_statuses.get("agent-device (UI testing)") == "missing"
            and _statuses.get("mobile-mcp (UI testing, alternative)") == "missing"):
        blocking.append("a device automation backend (agent-device or mobile-mcp)")
    lines.append("")
    if counts["missing"] == 0 and counts["warn"] == 0:
        lines.append(
            f"✅ READY — {counts['ok']}/{len(probes)} components present. "
            "Safe to build and UI-test."
        )
    elif blocking:
        lines.append(
            f"⛔ NOT READY — {len(blocking)} missing: {', '.join(blocking)}. "
            "Android builds and device tests will fail until these are fixed."
        )
    else:
        lines.append(
            f"⚠️ DEGRADED — {counts['warn']} warning(s), nothing missing. "
            "Try the build, but expect version-related failures."
        )
    if actions:
        lines.append("")
        lines.append("Next actions, in order:")
        for i, action in enumerate(dict.fromkeys(actions), 1):
            lines.append(f"  {i}. {action}")
    return "\n".join(lines)

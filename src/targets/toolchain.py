"""Toolchain discovery for multi-platform targets ("doctor" for the agent).

A capability the host cannot run must fail as an explicit, actionable refusal —
never as a mysterious build error 40 seconds into a Gradle run, and never as a
fabricated pass. This module is the single place that knows which executable
each target needs, how to find it (including the environment override used by
CI and by the desktop sidecar), how to read its version, and what to tell the
developer when it is missing.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.targets.contract import HOST_LINUX, HOST_MACOS, HOST_WINDOWS

ALL_HOSTS = (HOST_WINDOWS, HOST_MACOS, HOST_LINUX)


def host_platform(platform: str | None = None) -> str:
    """Normalize ``sys.platform`` (or an override) into the target vocabulary.

    Both spellings arrive here: Python's (``win32``, ``darwin``, ``linux``) and the
    target vocabulary's own (``windows``, ``macos``, ``linux``). Accepting the
    vocabulary form matters — ``host_platform("macos")`` used to fall through to
    ``linux``, which silently handed every macOS caller the Linux SDK roots.
    """
    value = (platform or sys.platform).strip().lower()
    if value in {HOST_WINDOWS, HOST_MACOS, HOST_LINUX}:
        return value
    if value.startswith("win"):
        return HOST_WINDOWS
    if value.startswith(("darwin", "mac", "osx")):
        return HOST_MACOS
    return HOST_LINUX


@dataclass(frozen=True)
class ToolSpec:
    """One external executable a target may depend on."""

    id: str
    label: str
    commands: tuple[str, ...]
    env_override: str = ""
    version_argv: tuple[str, ...] = ("--version",)
    hosts: tuple[str, ...] = ALL_HOSTS
    hint: Mapping[str, str] = field(default_factory=dict)
    required: bool = True
    #: Relative paths inside a platform SDK root (``ANDROID_HOME``-style). This is
    #: what makes a stock Android Studio install work on Windows: ``adb.exe`` and
    #: ``emulator.exe`` live under the SDK, and the installer never touches PATH.
    sdk_subpaths: tuple[str, ...] = ()

    def hint_for(self, host: str) -> str:
        return self.hint.get(host) or self.hint.get("any") or ""


_ANDROID_HINT = {
    HOST_WINDOWS: (
        'No Android Studio required: winget install --id Google.AndroidCLI, then install SDK packages; '
        'the doctor resolves %LOCALAPPDATA%\\Android\\Sdk without PATH edits'
    ),
    HOST_MACOS: (
        'Install Android CLI from developer.android.com/tools/agents/android-cli/download, '
        'then android sdk install platform-tools emulator'
    ),
    HOST_LINUX: (
        'Install Android CLI from developer.android.com/tools/agents/android-cli/download, '
        'then android sdk install platform-tools emulator'
    ),
}

#: Env vars that name an Android SDK root, most explicit first.
_SDK_ROOT_ENVS: tuple[str, ...] = ("ANDROID_HOME", "ANDROID_SDK_ROOT")
#: Default install locations per host (Android Studio's own choices).
_SDK_ROOT_DEFAULTS: dict[str, tuple[str, ...]] = {
    HOST_WINDOWS: (
        "~/AppData/Local/Android/Sdk",
        "~/AppData/Local/Android/sdk",
        "~/Android/Sdk",
    ),
    HOST_MACOS: ("~/Library/Android/sdk", "~/Android/Sdk"),
    HOST_LINUX: ("~/Android/Sdk", "~/Android/sdk", "/usr/lib/android-sdk", "/opt/android-sdk"),
}
_CMD_LINE_TOOLS_BIN = re.compile(r"cmdline-tools[\\/][^\\/]+[\\/]bin[\\/]?$")

TOOLS: tuple[ToolSpec, ...] = (
    # ---- Android -------------------------------------------------------- #
    ToolSpec("android-cli", "Android CLI (agent-facing build/device tools)",
             ("android", "android.exe"), "CRUSORAI_ANDROID_CLI", ("--version",), ALL_HOSTS, {
                 HOST_WINDOWS: "winget install --id Google.AndroidCLI  (Android Studio is not required)",
                 HOST_MACOS: "developer.android.com/tools/agents/android-cli/download  (macOS CLI installer)",
                 HOST_LINUX: "developer.android.com/tools/agents/android-cli/download  (Linux CLI installer)",
             }, required=False),
    ToolSpec("adb", "Android Debug Bridge", ("adb", "adb.exe"), "CRUSORAI_ADB",
             ("version",), ALL_HOSTS, _ANDROID_HINT,
             sdk_subpaths=("platform-tools/adb", "platform-tools/adb.exe")),
    ToolSpec("emulator", "Android Emulator", ("emulator", "emulator.exe"), "CRUSORAI_EMULATOR",
             ("-version",), ALL_HOSTS, _ANDROID_HINT,
             sdk_subpaths=("emulator/emulator", "emulator/emulator.exe")),
    ToolSpec("sdkmanager", "Android SDK manager", ("sdkmanager", "sdkmanager.bat"), "CRUSORAI_SDKMANAGER",
             ("--version",), ALL_HOSTS, _ANDROID_HINT,
             sdk_subpaths=(
                 "cmdline-tools/latest/bin/sdkmanager", "cmdline-tools/latest/bin/sdkmanager.bat",
                 "tools/bin/sdkmanager", "tools/bin/sdkmanager.bat",
             )),
    ToolSpec("avdmanager", "Android AVD manager", ("avdmanager", "avdmanager.bat"), "CRUSORAI_AVDMANAGER",
             (), ALL_HOSTS, _ANDROID_HINT,
             sdk_subpaths=(
                 "cmdline-tools/latest/bin/avdmanager", "cmdline-tools/latest/bin/avdmanager.bat",
                 "tools/bin/avdmanager", "tools/bin/avdmanager.bat",
             )),
    ToolSpec("java", "JDK (Gradle)", ("java", "java.exe"), "CRUSORAI_JAVA",
             ("-version",), ALL_HOSTS, {
                 HOST_WINDOWS: "winget install Microsoft.OpenJDK.21",
                 HOST_MACOS: "brew install openjdk@21",
                 HOST_LINUX: "apt install openjdk-21-jdk",
             }),
    ToolSpec("gradle", "Gradle (wrapper preferred)", ("gradle",), "CRUSORAI_GRADLE",
             ("--version",), ALL_HOSTS, {
                 "any": "gradle wrapper --gradle-version 8.13 (a committed ./gradlew is preferred)",
             }, required=False),
    ToolSpec("scrcpy", "Device screen mirroring", ("scrcpy",), "CRUSORAI_SCRCPY",
             ("--version",), ALL_HOSTS, {
                 HOST_WINDOWS: "winget install Genymobile.scrcpy",
                 HOST_MACOS: "brew install scrcpy",
                 HOST_LINUX: "apt install scrcpy",
             }, required=False),
    ToolSpec("maestro", "Maestro UI flows", ("maestro",), "CRUSORAI_MAESTRO",
             ("--version",), ALL_HOSTS, {
                 "any": "curl -fsSL https://get.maestro.mobile.dev | bash  (or install the maestro-mobile-testing skill skill)",
             }, required=False),
    # ---- iOS ------------------------------------------------------------ #
    ToolSpec("xcodebuild", "Xcode build", ("xcodebuild",), "",
             ("-version",), (HOST_MACOS,), {
                 HOST_MACOS: "xcode-select --install  ·  full Xcode from the App Store",
             }),
    ToolSpec("xcrun", "Xcode tool launcher (simctl)", ("xcrun",), "",
             ("--version",), (HOST_MACOS,), {
                 HOST_MACOS: "comes with Xcode command line tools",
             }),
    ToolSpec("pod", "CocoaPods", ("pod",), "",
             ("--version",), (HOST_MACOS,), {
                 HOST_MACOS: "gem install cocoapods  (only needed for Podfile projects)",
             }, required=False),
    ToolSpec("pymobiledevice3", "iOS device access without macOS", ("pymobiledevice3",), "",
             ("version",), ALL_HOSTS, {
                 "any": "pip install pymobiledevice3  (install an .ipa/app bundle on a physical iPhone from Linux/Windows)",
             }, required=False),
    ToolSpec("idevicesyslog", "iOS device console", ("idevicesyslog",), "",
             ("-h",), ALL_HOSTS, {
                 HOST_MACOS: "brew install libimobiledevice",
                 HOST_LINUX: "apt install libimobiledevice-utils",
                 HOST_WINDOWS: "scoop install libimobiledevice",
             }, required=False),
    ToolSpec("idevicescreenshot", "iOS device screenshot", ("idevicescreenshot",), "",
             ("-h",), ALL_HOSTS, {
                 HOST_MACOS: "brew install libimobiledevice",
                 HOST_LINUX: "apt install libimobiledevice-utils",
                 HOST_WINDOWS: "scoop install libimobiledevice",
             }, required=False),
    ToolSpec("xtool", "iOS build without Xcode", ("xtool",), "",
             ("--version",), (HOST_LINUX, HOST_WINDOWS), {
                 "any": "see https://github.com/xtool-org/xtool (SwiftPM iOS builds on Linux/Windows; needs an iOS SDK)",
             }, required=False),
    # ---- Cross-platform frameworks -------------------------------------- #
    ToolSpec("flutter", "Flutter SDK", ("flutter", "flutter.bat"), "CRUSORAI_FLUTTER",
             ("--version",), ALL_HOSTS, {
                 "any": "https://docs.flutter.dev/get-started/install",
             }),
    ToolSpec("dart", "Dart (ships with Flutter)", ("dart", "dart.exe"), "CRUSORAI_DART",
             ("--version",), ALL_HOSTS, {"any": "installed with the Flutter SDK"}, required=False),
    ToolSpec("node", "Node.js", ("node",), "CRUSORAI_NODE",
             ("--version",), ALL_HOSTS, {
                 HOST_WINDOWS: "winget install OpenJS.NodeJS.LTS",
                 HOST_MACOS: "brew install node@22",
                 HOST_LINUX: "apt install nodejs npm  ·  or nvm install 22",
             }),
    ToolSpec("npm", "npm", ("npm", "npm.cmd"), "CRUSORAI_NPM",
             ("--version",), ALL_HOSTS, {"any": "installed with Node.js"}, required=False),
    ToolSpec("pnpm", "pnpm", ("pnpm", "pnpm.cmd"), "", ("--version",), ALL_HOSTS, {
        "any": "corepack enable pnpm",
    }, required=False),
    ToolSpec("yarn", "Yarn", ("yarn", "yarn.cmd"), "", ("--version",), ALL_HOSTS, {
        "any": "corepack enable yarn",
    }, required=False),
    ToolSpec("bun", "Bun", ("bun", "bun.exe"), "", ("--version",), ALL_HOSTS, {
        "any": "https://bun.sh",
    }, required=False),
    ToolSpec("expo", "Expo CLI", ("expo",), "", ("--version",), ALL_HOSTS, {
        "any": "npx expo  (no global install needed)",
    }, required=False),
    # ---- Desktop -------------------------------------------------------- #
    ToolSpec("cargo", "Rust / Cargo (Tauri)", ("cargo",), "CRUSORAI_CARGO",
             ("--version",), ALL_HOSTS, {
                 HOST_WINDOWS: "winget install Rustlang.Rustup",
                 HOST_MACOS: "brew install rustup",
                 HOST_LINUX: "curl https://sh.rustup.rs -sSf | sh",
             }, required=False),
    ToolSpec("rustc", "rustc", ("rustc",), "", ("--version",), ALL_HOSTS, {
        "any": "installed with cargo",
    }, required=False),
    ToolSpec("tauri-driver", "Tauri WebDriver", ("tauri-driver",), "",
             ("--version",), (HOST_LINUX, HOST_WINDOWS), {
                 "any": "cargo install tauri-driver --locked",
             }, required=False),
    ToolSpec("go", "Go toolchain (Wails)", ("go", "go.exe"), "", ("version",), ALL_HOSTS, {
        "any": "https://go.dev/dl  (only needed for Wails desktop apps)",
    }, required=False),
    ToolSpec("wails", "Wails CLI", ("wails", "wails.exe"), "", ("version",), ALL_HOSTS, {
        "any": "go install github.com/wailsapp/wails/v2/cmd/wails@latest",
    }, required=False),
    ToolSpec("dotnet", ".NET SDK (WPF / WinUI / MAUI)", ("dotnet", "dotnet.exe"), "",
             ("--version",), ALL_HOSTS, {
                 "any": "https://dotnet.microsoft.com/download",
             }, required=False),
    ToolSpec("xvfb-run", "Virtual X display", ("xvfb-run",), "",
             ("--help",), (HOST_LINUX,), {
                 HOST_LINUX: "apt install xvfb  (headless Linux CI: needed to launch any GUI binary)",
             }, required=False),
    ToolSpec("playwright", "Playwright (Electron / WebView driving)", ("playwright",), "",
             ("--version",), ALL_HOSTS, {
                 "any": "npm i -D playwright  (or npx playwright install)",
             }, required=False),
    ToolSpec("gh", "GitHub CLI", ("gh",), "", ("--version",), ALL_HOSTS, {
        "any": "https://cli.github.com  (used by the CI pipelines to publish evidence)",
    }, required=False),
)

TOOLS_BY_ID: dict[str, ToolSpec] = {spec.id: spec for spec in TOOLS}


@dataclass
class ToolStatus:
    spec: ToolSpec
    available: bool
    path: str = ""
    version: str = ""
    reason: str = ""

    def render(self) -> str:
        mark = "ok  " if self.available else "miss"
        version = self.version or "—"
        location = self.path or self.reason or "not found"
        return f"[{mark}] {self.spec.id:<16} {version[:28]:<28} {location}"


def sdk_roots(host: str | None = None) -> list[Path]:
    """Android SDK roots on this machine, most explicit first.

    ``ANDROID_HOME``/``ANDROID_SDK_ROOT`` win; then the locations Android Studio
    actually installs to on each host. Existence is *not* required — a caller may
    want to report the path it looked in — but non-existent roots sort last.
    """
    resolved = host_platform(host)
    roots: list[Path] = []
    for name in _SDK_ROOT_ENVS:
        value = os.environ.get(name, "").strip()
        if value:
            roots.append(Path(value).expanduser())
    roots.extend(Path(item).expanduser() for item in _SDK_ROOT_DEFAULTS.get(resolved, ()))
    seen: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.append(root)
    return seen


def sdk_candidates(spec: ToolSpec, host: str | None = None) -> list[str]:
    """Absolute paths this tool would occupy inside a discovered SDK root.

    ``platform-tools/adb``, ``emulator/emulator`` and the ``cmdline-tools`` pair are
    the three shapes Android ships; on Windows every leaf is ``.exe``/``.bat``. For
    ``cmdline-tools`` a versioned directory (``cmdline-tools/13.0/bin/…``) is as valid
    as ``latest``, so those are globbed — nothing else is scanned.
    """
    if not spec.sdk_subpaths:
        return []
    resolved = host_platform(host)
    windows = resolved == HOST_WINDOWS
    found: list[str] = []
    for root in sdk_roots(resolved):
        for rel in spec.sdk_subpaths:
            candidate = root / rel
            if not candidate.suffix:
                if windows:
                    # Native binaries (platform-tools, emulator) ship .exe; the Java
                    # launchers (cmdline-tools, the legacy tools/ layout) ship .bat.
                    native = rel.startswith(("platform-tools/", "emulator/"))
                    candidate = candidate.with_suffix(".exe" if native else ".bat")
            elif not windows and candidate.suffix.lower() in {".exe", ".bat"}:
                continue
            found.append(str(candidate))
        # Any versioned cmdline-tools install, newest directory name first.
        if any(rel.startswith("cmdline-tools/") for rel in spec.sdk_subpaths):
            leaf = "sdkmanager" if spec.id == "sdkmanager" else "avdmanager"
            suffix = ".bat" if windows else ""
            try:
                versions = sorted(
                    (entry for entry in (root / "cmdline-tools").iterdir()
                     if entry.is_dir() and entry.name != "latest"),
                    reverse=True,
                )
            except OSError:
                versions = []
            for entry in versions:
                candidate = entry / "bin" / f"{leaf}{suffix}"
                if candidate.exists():
                    found.insert(0, str(candidate))
    return list(dict.fromkeys(found))


def _probe_binary(spec: ToolSpec, host: str) -> tuple[str, str]:
    """Locate the executable (env override → PATH → SDK root) and read its version."""
    if host not in spec.hosts:
        return "", "unsupported on this host"
    override = os.environ.get(spec.env_override, "").strip() if spec.env_override else ""
    candidates: list[str] = []
    if override:
        candidates.append(override)
    candidates.extend(spec.commands)
    for candidate in candidates:
        path = candidate if os.path.isabs(candidate) and os.path.exists(candidate) else shutil.which(candidate)
        if not path:
            continue
        version = ""
        if spec.version_argv:
            try:
                proc = subprocess.run(
                    [path, *spec.version_argv], capture_output=True, text=True,
                    timeout=15, check=False,
                )
                raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
                for line in raw.splitlines():
                    line = line.strip()
                    if line:
                        version = line
                        break
            except (OSError, subprocess.SubprocessError):
                version = "version probe failed"
        return path, version
    # Not on PATH: an SDK root is the normal case for Android tooling, where the
    # installer deliberately leaves PATH alone (Windows especially).
    for candidate in sdk_candidates(spec, host):
        if Path(candidate).exists():
            version = ""
            if spec.version_argv:
                try:
                    proc = subprocess.run(
                        [candidate, *spec.version_argv], capture_output=True, text=True,
                        timeout=15, check=False,
                    )
                    raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
                    for line in raw.splitlines():
                        if line.strip():
                            version = line.strip()
                            break
                except (OSError, subprocess.SubprocessError):
                    version = "version probe failed"
            located = sdk_roots(host)
            where = next((str(root) for root in located if candidate.startswith(str(root))), "SDK")
            return candidate, version or f"found in SDK root {where}"
    searched = [str(root) for root in sdk_roots(host)] if spec.sdk_subpaths else []
    tail = f" (also looked in {', '.join(searched)})" if searched else ""
    return "", "not found on PATH" + tail + (f" (or ${spec.env_override})" if spec.env_override else "")


def probe(host: str | None = None, *, fresh: bool = False) -> dict[str, ToolStatus]:
    """Probe every known tool once per process (``fresh=True`` re-reads PATH)."""
    resolved_host = host_platform(host)
    if fresh:
        _probe_cached.cache_clear()
    return dict(_probe_cached(resolved_host))


@lru_cache(maxsize=4)
def _probe_cached(host: str) -> tuple[tuple[str, ToolStatus], ...]:
    out: list[tuple[str, ToolStatus]] = []
    for spec in TOOLS:
        path, version = _probe_binary(spec, host)
        available = bool(path)
        out.append((spec.id, ToolStatus(
            spec=spec, available=available, path=path,
            version=version if available else "",
            reason="" if available else version,
        )))
    return tuple(out)


def missing(required: Iterable[str], host: str | None = None) -> list[ToolStatus]:
    """Required tool ids that are NOT available on this host (ordered, deduped).

    An unknown tool id is reported as missing (fail closed): a provider that
    asks for a tool nobody can check must not look satisfied.
    """
    statuses = probe(host)
    out: list[ToolStatus] = []
    seen: set[str] = set()
    for tool_id in required:
        if tool_id in seen:
            continue
        seen.add(tool_id)
        status = statuses.get(tool_id)
        if status is None:
            status = ToolStatus(
                spec=ToolSpec(id=tool_id, label=tool_id, commands=(tool_id,)),
                available=False, reason="no toolchain spec is registered for this id",
            )
        if not status.available:
            out.append(status)
    return out


def requirement_report(required: Sequence[str], host: str | None = None) -> str:
    """One-line-per-tool explanation of what is missing and how to install it."""
    resolved = host_platform(host)
    lines: list[str] = []
    for status in missing(required, resolved):
        hint = status.spec.hint_for(resolved) or "see the project documentation"
        lines.append(f"{status.spec.id} ({status.spec.label}): {status.reason}. Install: {hint}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Per-target readiness (the "doctor" surface)
# --------------------------------------------------------------------------- #

TARGET_REQUIREMENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # target id -> (required, recommended). The target-specific provider performs
    # a stricter workspace-aware check before execution; this is the host-level
    # doctor summary and the default setup-plan input.
    "android": (("adb", "java"), ("android-cli", "emulator", "sdkmanager", "avdmanager", "scrcpy", "maestro")),
    "ios": (("xcrun", "xcodebuild"), ("pod", "idevicesyslog", "idevicescreenshot")),
    "ios-device": (("pymobiledevice3",), ("idevicesyslog", "idevicescreenshot")),
    "flutter": (("flutter", "java", "adb"), ("dart", "emulator", "scrcpy")),
    "react-native": (("node", "java", "adb"), ("npm", "emulator", "maestro")),
    "desktop": (("node",), ("playwright", "xvfb-run", "cargo", "dotnet", "tauri-driver")),
    "electron": (("node",), ("npm", "playwright")),
    "tauri": (("cargo", "node"), ("rustc", "tauri-driver")),
    "wails": (("go", "wails"), ("node",)),
    "dotnet-desktop": (("dotnet",), ()),
    "web": (("node",), ("npm", "pnpm")),
}


def target_readiness(host: str | None = None, *, targets: Iterable[str] | None = None) -> dict[str, dict[str, object]]:
    """READY / MISSING verdict per target id, plus the tool details behind it.

    iOS is intentionally host-dependent: macOS is the build + Simulator path;
    Windows/Linux can install and inspect a prebuilt IPA on a physical device via
    pymobiledevice3, but cannot build an Xcode project or run Simulator.
    """
    resolved = host_platform(host)
    statuses = probe(resolved)
    selected = set(targets) if targets is not None else None
    report: dict[str, dict[str, object]] = {}
    for target_id, (required, recommended) in TARGET_REQUIREMENTS.items():
        if selected is not None and target_id not in selected:
            continue
        host_gate = _host_supported(target_id, resolved)
        if target_id == "ios" and resolved != HOST_MACOS:
            required = ("pymobiledevice3",)
            recommended = ("idevicesyslog", "idevicescreenshot")
        absent = [statuses[t] for t in required if t in statuses and not statuses[t].available]
        report[target_id] = {
            "host": resolved,
            "host_supported": host_gate[0],
            "host_reason": host_gate[1],
            "ready": host_gate[0] and not absent,
            "missing": [status.spec.id for status in absent],
            "missing_detail": [
                f"{status.spec.id}: {status.reason}. Install: {status.spec.hint_for(resolved) or 'see docs'}"
                for status in absent
            ],
            "optional_missing": [
                t for t in recommended if t in statuses and not statuses[t].available
            ],
        }
    return report


def _host_supported(target_id: str, host: str) -> tuple[bool, str]:
    if target_id == "ios" and host != HOST_MACOS:
        return True, (
            "physical-device proof only on this host: a prebuilt IPA and pymobiledevice3 are needed; "
            "building the app or using iOS Simulator requires macOS + Xcode"
        )
    return True, ""


def doctor_report(host: str | None = None, *, targets: Iterable[str] | None = None) -> str:
    """Human- and model-readable toolchain report (also printed by
    ``scripts/targets_doctor.py``)."""
    resolved = host_platform(host)
    statuses = probe(resolved)
    lines = [f"Target toolchains — host: {resolved}", ""]
    for status in statuses.values():
        lines.append(status.render())
    lines.append("")
    lines.append("Readiness:")
    for target_id, info in target_readiness(resolved, targets=targets).items():
        if not info["host_supported"]:
            lines.append(f"  {target_id:<14} HOST-UNSUPPORTED — {info['host_reason']}")
            continue
        if info["ready"]:
            optional = info["optional_missing"]
            suffix = f" (optional missing: {', '.join(optional)})" if optional else ""
            lines.append(f"  {target_id:<14} READY{suffix}")
        else:
            lines.append(f"  {target_id:<14} MISSING {', '.join(info['missing'])}")
            for detail in info["missing_detail"]:
                lines.append(f"      - {detail}")
        if info.get("host_reason"):
            lines.append(f"      NOTE: {info['host_reason']}")
    return "\n".join(lines)

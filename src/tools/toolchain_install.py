"""Install a missing SDK/toolchain on the host machine.

Founder 2026-10-18: the agent, asked for a Flutter app on a machine with
no Flutter SDK, hand-wrote the generator's project files instead — a
skeleton that only becomes real once a human installs the SDK by hand.
His fix: "a tool card, which helps to install SDKs related to the topic
the agent is building — Android platform → Android SDK, Flutter, Xcode."

So project creation keeps riding the terminal (his call the same day:
the scaffold tools were deleted because the terminal does the job), but
when the terminal cannot run because the toolchain itself is absent,
this tool installs the real SDK first. The recipes are FIXED data in
this file — the model chooses *which* SDK, never the commands — and the
permission layer asks the human before any of it runs
(``install_toolchain`` asserts an ``ask`` by default).

Installs land where the toolchain probe already looks:
- Flutter → ``~/.crusorai/sdks/flutter`` (probe checks managed SDK dirs;
  its ``bin`` joins this session's PATH, so ``flutter create`` works in
  the very next terminal call and in later sessions via probe + PATH
  activation at toolchain import).
- Android → the first Android SDK root the probe scans
  (``%LOCALAPPDATA%\\Android\\Sdk`` on Windows): cmdline-tools + JDK 21 +
  platform-tools / android-35 / build-tools / emulator via sdkmanager.
- Node / JDK / Rust → the OS package manager (winget / Homebrew).
- Xcode → macOS only; anything else is an honest refusal, never a fake.

Receipts follow the target family's prose grammar: ✅ installed and
probe-verified, ℹ️ already present, ⚠️ partial (some bundle tools still
missing), ⛔ refused/failed with the failing step and the manual route.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.request
import zipfile
from collections import deque
from pathlib import Path
from typing import Callable

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.targets import toolchain
from src.targets.toolchain import HOST_MACOS, HOST_WINDOWS, host_platform

#: (percent 0..100, or None while a step has no honest measure, label)
ProgressFn = Callable[[float | None, str], None]

_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def _frac_from_line(line: str) -> float | None:
    """Last percentage a package manager printed on this line, as 0..1."""
    found = _PERCENT_RE.findall(line or "")
    if not found:
        return None
    return max(0.0, min(1.0, float(found[-1]) / 100.0))

#: Where Crusor-managed SDKs live (the probe's managed-candidates root).
MANAGED_ROOT = Path.home() / ".crusorai" / "sdks"

#: Pinned Android command-line-tools build (dl.google.com). The URL 404s
#: when Google rotates builds; the failure receipt names the manual route.
_CMDLINE_TOOLS_BUILD = "11076708"
_ANDROID_PACKAGES = (
    "platform-tools",
    "platforms;android-35",
    "build-tools;35.0.0",
    "emulator",
)

_LABELS: dict[str, str] = {
    "flutter": "Flutter SDK",
    "android": "Android SDK",
    "node": "Node.js",
    "java": "JDK 21",
    "rust": "Rust (rustup)",
    "xcode": "Xcode",
}

#: Whatever id the toolchain checker reported, the bundle that fixes it.
_ALIASES: dict[str, str] = {
    "dart": "flutter",
    "npm": "node",
    "jdk": "java",
    "openjdk": "java",
    "cargo": "rust",
    "rustc": "rust",
    "rustup": "rust",
    "adb": "android",
    "sdkmanager": "android",
    "avdmanager": "android",
    "emulator": "android",
    "android-sdk": "android",
    "android_sdk": "android",
    "xcodebuild": "xcode",
    "xcrun": "xcode",
}

#: Toolchain-probe ids that must all read available for a ✅ receipt.
_BUNDLE_TOOLS: dict[str, tuple[str, ...]] = {
    "flutter": ("flutter", "dart"),
    "android": ("java", "sdkmanager", "adb"),
    "node": ("node",),
    "java": ("java",),
    "rust": ("cargo",),
    "xcode": ("xcodebuild",),
}


def canonical_sdk(raw: str) -> str:
    """Map any reported tool id / loose name to its install bundle."""
    key = (raw or "").strip().lower()
    return _ALIASES.get(key, key)


class _StepFailed(Exception):
    def __init__(self, step: str, tail: str):
        super().__init__(step)
        self.step = step
        self.tail = (tail or "")[-1500:]


# --------------------------------------------------------------------- #
# step executors (fixed commands only — nothing here is model-composed)
# --------------------------------------------------------------------- #

def _run(argv: list[str], *, timeout: int = 900, input_text: str | None = None) -> tuple[int, str]:
    argv = [str(a) for a in argv]
    if os.name == "nt" and argv and argv[0].lower().endswith((".bat", ".cmd")):
        argv = ["cmd", "/c", *argv]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            input=input_text, stdin=subprocess.DEVNULL if input_text is None else None,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, f"could not start: {exc}"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-3000:]


def _run_stream(argv: list[str], *, timeout: int = 900, input_text: str | None = None,
                on_line: Callable[[str], None] | None = None) -> tuple[int, str]:
    """Streaming twin of _run: output lines flow to on_line as they land
    (package managers print their real percentages there — the loader's
    honest numbers). Bounded tail, bounded wait, like _run."""
    argv = [str(a) for a in argv]
    if os.name == "nt" and argv and argv[0].lower().endswith((".bat", ".cmd")):
        argv = ["cmd", "/c", *argv]
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError as exc:
        return 127, f"could not start: {exc}"
    if input_text is not None and proc.stdin is not None:
        try:
            proc.stdin.write(input_text)
            proc.stdin.close()
        except OSError:
            pass
    tail: deque[str] = deque(maxlen=120)
    started = time.monotonic()
    assert proc.stdout is not None
    for line in proc.stdout:
        tail.append(line)
        if on_line is not None:
            try:
                on_line(line)
            except Exception:  # noqa: BLE001 - progress must never break installs
                pass
        if time.monotonic() - started > timeout:
            proc.kill()
            return 124, "".join(tail) + f"\n(timed out after {timeout}s)"
    return proc.wait(), "".join(tail)


def _sh(step: str, argv: list[str], *, timeout: int = 900, input_text: str | None = None,
        on_line: Callable[[str], None] | None = None) -> str:
    if on_line is None:
        code, out = _run(argv, timeout=timeout, input_text=input_text)
    else:
        code, out = _run_stream(argv, timeout=timeout, input_text=input_text, on_line=on_line)
    if code != 0:
        raise _StepFailed(step, out or f"exit {code}")
    return out


def _band(report: ProgressFn, lo: float, hi: float, label: str) -> Callable[[float | None], None]:
    """Map one step's own 0..1 onto its slice of the 0..100 loader."""
    def emit(frac: float | None) -> None:
        if frac is None:
            report(None, label)
        else:
            report(lo + (hi - lo) * max(0.0, min(1.0, frac)), label)
    return emit


def _line_progress(emit: Callable[[float | None], None]) -> Callable[[str], None]:
    def on_line(line: str) -> None:
        emit(_frac_from_line(line))
    return on_line


def _download(step: str, url: str, dest: Path,
              on_bytes: Callable[[int, int | None], None] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "CrusorAI"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response, open(part, "wb") as handle:
            total = response.headers.get("Content-Length")
            total = int(total) if total and total.isdigit() else None
            done = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if on_bytes is not None:
                    on_bytes(done, total)
    except Exception as exc:  # noqa: BLE001 - one honest step failure
        raise _StepFailed(step, f"{type(exc).__name__}: {exc} ({url})") from exc
    part.replace(dest)


def _extract(step: str, archive: Path, dest: Path,
             on_file: Callable[[float], None] | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                for name in names:
                    if not (root / name).resolve().is_relative_to(root):
                        raise _StepFailed(step, f"unsafe path in archive: {name}")
                for index, name in enumerate(names):
                    bundle.extract(name, dest)
                    if on_file is not None:
                        on_file((index + 1) / max(1, len(names)))
        else:
            with tarfile.open(archive, "r:*") as bundle:
                members = bundle.getmembers()
                for member in members:
                    if not (root / member.name).resolve().is_relative_to(root):
                        raise _StepFailed(step, f"unsafe path in archive: {member.name}")
                for index, member in enumerate(members):
                    if not (member.islnk() or member.issym()):
                        bundle.extract(member, dest)
                    if on_file is not None:
                        on_file((index + 1) / max(1, len(members)))
    except _StepFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _StepFailed(step, f"{type(exc).__name__}: {exc}") from exc


def _activate(bin_dir: Path) -> None:
    """Session-local PATH: later probes and terminal calls in this
    process (and the children it spawns) resolve the new SDK at once."""
    entry = str(bin_dir)
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if entry not in parts:
        os.environ["PATH"] = entry + os.pathsep + os.environ.get("PATH", "")


def _winget(step: str, package_id: str, emit: Callable[[float | None], None] | None = None) -> str:
    if not shutil.which("winget"):
        raise _StepFailed(step, "winget is not available on this machine")
    return _sh(step, [
        "winget", "install", "-e", "--id", package_id,
        "--accept-package-agreements", "--accept-source-agreements",
    ], timeout=1800, on_line=_line_progress(emit) if emit else None)


def _brew(step: str, formula: str, emit: Callable[[float | None], None] | None = None) -> str:
    if not shutil.which("brew"):
        raise _StepFailed(step, "Homebrew is not available on this machine")
    return _sh(step, ["brew", "install", formula], timeout=1800,
               on_line=_line_progress(emit) if emit else None)


# --------------------------------------------------------------------- #
# recipes
# --------------------------------------------------------------------- #

def _install_flutter(host: str, log: list[str], report: ProgressFn) -> None:
    dest = MANAGED_ROOT / "flutter"
    if not (dest / "bin").is_dir():
        os_name = {"windows": "windows", "macos": "macos"}.get(host, "linux")
        manifest_url = (
            "https://storage.googleapis.com/flutter_infra_release"
            f"/releases/releases_{os_name}.json"
        )
        report(1, "Checking the latest Flutter release…")
        try:
            with urllib.request.urlopen(manifest_url, timeout=60) as response:
                manifest = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise _StepFailed("release lookup", f"{type(exc).__name__}: {exc}") from exc
        stable_hash = manifest.get("current_release", {}).get("stable", "")
        release = next(
            (r for r in manifest.get("releases", []) if r.get("hash") == stable_hash),
            None,
        )
        if release is None:
            raise _StepFailed("release lookup", "no stable release in the Flutter manifest")
        archive_name = str(release["archive"])
        archive = MANAGED_ROOT / Path(archive_name).name

        def on_bytes(done: int, total: int | None) -> None:
            mb = done / 1_000_000
            if total:
                report(2 + 63 * (done / total), f"Downloading Flutter SDK… {mb:.0f} MB")
            else:
                report(None, f"Downloading Flutter SDK… {mb:.0f} MB")

        _download("download", f"{manifest['base_url']}/{archive_name}", archive, on_bytes=on_bytes)
        log.append(f"downloaded Flutter {release.get('version', '?')} ({archive.name})")
        _extract("extract", archive, MANAGED_ROOT,
                 on_file=_band(report, 65, 82, "Extracting Flutter SDK…"))
        archive.unlink(missing_ok=True)
        if host != HOST_WINDOWS:
            _run(["chmod", "-R", "+x", str(dest / "bin")], timeout=300)
    _activate(dest / "bin")
    report(84, "First run — building the Flutter tool (a minute or two)…")
    binary = dest / "bin" / ("flutter.bat" if host == HOST_WINDOWS else "flutter")
    out = _sh("first run", [str(binary), "--version"], timeout=1200)
    log.append(out.splitlines()[0] if out.splitlines() else "flutter --version ok")
    report(95, "Verifying the installation…")


def _ensure_java_env(host: str) -> None:
    """winget/brew JDK installs update the MACHINE path, not this
    process — find the JDK and put it on our own PATH/JAVA_HOME."""
    status = toolchain.probe(fresh=True).get("java")
    if status and status.available and status.path:
        home = Path(status.path).parent.parent
        os.environ.setdefault("JAVA_HOME", str(home))
        _activate(Path(status.path).parent)
        return
    candidates: list[Path] = []
    if host == HOST_WINDOWS:
        for base in (Path("C:/Program Files/Microsoft"), Path("C:/Program Files/Eclipse Adoptium")):
            candidates += sorted(base.glob("jdk-*/bin/java.exe")) if base.exists() else []
    elif host == HOST_MACOS:
        brew_home = Path("/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java")
        if brew_home.exists():
            candidates.append(brew_home)
        code, out = _run(["/usr/libexec/java_home", "-v", "21"], timeout=30)
        if code == 0 and out.strip():
            candidates.append(Path(out.strip()) / "bin" / "java")
    else:
        candidates += sorted(Path("/usr/lib/jvm").glob("*/bin/java")) if Path("/usr/lib/jvm").exists() else []
    if candidates:
        java_bin = candidates[-1]
        os.environ["JAVA_HOME"] = str(java_bin.parent.parent)
        _activate(java_bin.parent)


def _install_java(host: str, log: list[str], report: ProgressFn,
                  band: tuple[float, float] = (0, 90)) -> None:
    emit = _band(report, band[0], band[1], "Installing JDK 21…")
    if host == HOST_WINDOWS:
        _winget("winget", "Microsoft.OpenJDK.21", emit)
    elif host == HOST_MACOS:
        _brew("brew", "openjdk@21", emit)
    else:
        raise _StepFailed(
            "package manager",
            "automatic JDK install needs winget or Homebrew; on Linux run "
            "`sudo apt install openjdk-21-jdk`, then ask again",
        )
    _ensure_java_env(host)
    log.append("JDK 21 installed")


def _android_root(host: str) -> Path:
    roots = toolchain.sdk_roots(host)
    for root in roots:
        if root.exists():
            return root
    return roots[0] if roots else Path.home() / "Android" / "Sdk"


def _install_android(host: str, log: list[str], report: ProgressFn) -> None:
    if not toolchain.probe(fresh=True)["java"].available:
        _install_java(host, log, report, band=(0, 12))
    _ensure_java_env(host)
    root = _android_root(host)
    latest = root / "cmdline-tools" / "latest"
    if not (latest / "bin").is_dir():
        flavour = {"windows": "win", "macos": "mac"}.get(host, "linux")
        url = (
            "https://dl.google.com/android/repository/"
            f"commandlinetools-{flavour}-{_CMDLINE_TOOLS_BUILD}_latest.zip"
        )
        archive = root / "commandlinetools.zip"

        def on_bytes(done: int, total: int | None) -> None:
            if total:
                report(12 + 20 * (done / total), "Downloading Android command-line tools…")
            else:
                report(None, f"Downloading Android command-line tools… {done / 1_000_000:.0f} MB")

        _download("download", url, archive, on_bytes=on_bytes)
        _extract("extract", archive, root / "cmdline-tools",
                 on_file=_band(report, 32, 38, "Extracting Android command-line tools…"))
        archive.unlink(missing_ok=True)
        inner = root / "cmdline-tools" / "cmdline-tools"
        if inner.is_dir() and not latest.exists():
            inner.rename(latest)
        log.append(f"command-line tools in {latest}")
    manager = latest / "bin" / ("sdkmanager.bat" if host == HOST_WINDOWS else "sdkmanager")
    if not manager.exists():
        raise _StepFailed("sdkmanager", f"not found at {manager}")
    report(40, "Accepting Android SDK licenses…")
    _sh("licenses", [str(manager), f"--sdk_root={root}", "--licenses"],
        timeout=600, input_text="y\n" * 24)
    _sh("sdk packages", [str(manager), f"--sdk_root={root}", *_ANDROID_PACKAGES],
        timeout=1800,
        on_line=_line_progress(_band(report, 42, 96, "Installing Android SDK packages (platform-tools, android-35, emulator)…")))
    log.append("installed " + ", ".join(_ANDROID_PACKAGES))
    report(97, "Verifying the installation…")


def _install_node(host: str, log: list[str], report: ProgressFn) -> None:
    emit = _band(report, 0, 90, "Installing Node.js…")
    if host == HOST_WINDOWS:
        _winget("winget", "OpenJS.NodeJS.LTS", emit)
        node_dir = Path("C:/Program Files/nodejs")
        if node_dir.is_dir():
            _activate(node_dir)
    elif host == HOST_MACOS:
        _brew("brew", "node@22", emit)
        for candidate in (Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
            if (candidate / "node").exists():
                _activate(candidate)
    else:
        raise _StepFailed(
            "package manager",
            "automatic Node install needs winget or Homebrew; on Linux use "
            "nvm (`nvm install 22`) or your distro packages, then ask again",
        )
    log.append("Node.js installed")


def _install_rust(host: str, log: list[str], report: ProgressFn) -> None:
    cargo_bin = Path.home() / ".cargo" / "bin"
    emit = _band(report, 0, 90, "Installing Rust…")
    if host == HOST_WINDOWS:
        _winget("winget", "Rustlang.Rustup", emit)
    elif host == HOST_MACOS and shutil.which("brew"):
        _brew("brew", "rustup", emit)
        init = shutil.which("rustup-init") or "/opt/homebrew/bin/rustup-init"
        _sh("rustup-init", [init, "-y"], timeout=1200)
    else:
        _sh("rustup",
            ["sh", "-c", "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"],
            timeout=1200)
    if cargo_bin.is_dir():
        _activate(cargo_bin)
    log.append("Rust toolchain installed")


def _install_xcode(host: str, log: list[str], report: ProgressFn) -> None:
    if host != HOST_MACOS:
        raise _StepFailed(
            "host",
            "Xcode exists only on macOS — iOS apps cannot be built on this "
            "machine. Use a Mac, or a cloud Mac, for iOS targets",
        )
    code, out = _run(["xcode-select", "--install"], timeout=120)
    if code != 0 and "already installed" not in out.lower():
        raise _StepFailed("xcode-select", out)
    log.append(
        "command-line tools requested — if a system dialog opened, finish "
        "it there. Full Xcode comes from the App Store (it cannot be "
        "installed from the command line) and is required for device builds"
    )


_INSTALLERS = {
    "flutter": _install_flutter,
    "android": _install_android,
    "node": _install_node,
    "java": _install_java,
    "rust": _install_rust,
    "xcode": _install_xcode,
}

_MANUAL_HINTS = {
    "flutter": "https://docs.flutter.dev/get-started/install",
    "android": "https://developer.android.com/studio (Android Studio bundles the SDK)",
    "node": "https://nodejs.org",
    "java": "winget install Microsoft.OpenJDK.21 / brew install openjdk@21",
    "rust": "https://rustup.rs",
    "xcode": "App Store → Xcode (macOS only)",
}


# --------------------------------------------------------------------- #
# UI-test kit: the raw materials UI verification drives with (founder
# 2026-10-18: "not only SDKs — raw materials which help for UI Testing
# also"). Best-effort by design: a skipped extra never fails the SDK
# install it rode along with; the receipt says what landed.
# --------------------------------------------------------------------- #

def _kit_scrcpy(host: str) -> str:
    if host == HOST_WINDOWS:
        _winget("winget", "Genymobile.scrcpy")
    elif shutil.which("brew"):
        _brew("brew", "scrcpy")
    else:
        raise _StepFailed("package manager", "install scrcpy with your OS package manager")
    return "scrcpy (device mirroring)"


def _kit_maestro(host: str) -> str:
    if host == HOST_WINDOWS:
        raise _StepFailed(
            "host", "Maestro ships a Windows zip: https://docs.maestro.dev/get-started/installing-maestro/windows")
    _sh("maestro", ["sh", "-c", "curl -fsSL https://get.maestro.mobile.dev | bash"], timeout=900)
    return "Maestro (UI flows)"


def _kit_playwright(host: str) -> str:
    if not toolchain.probe(fresh=True)["node"].available:
        raise _StepFailed("node", "Playwright browsers need Node.js first")
    _sh("playwright", ["npx", "-y", "playwright@latest", "install", "chromium"],
        timeout=1500)
    return "Playwright Chromium (browser UI tests)"


def _kit_tauri_driver(host: str) -> str:
    if not toolchain.probe(fresh=True)["cargo"].available:
        raise _StepFailed("cargo", "tauri-driver builds with cargo — install Rust first")
    _sh("tauri-driver", ["cargo", "install", "tauri-driver", "--locked"], timeout=1800)
    return "tauri-driver (desktop UI tests)"


#: bundle -> [(receipt name, installer, probe id that proves it)]
_KIT_STEPS: dict[str, tuple[tuple[str, Callable[[str], str], str], ...]] = {
    "flutter": (("scrcpy", _kit_scrcpy, "scrcpy"), ("maestro", _kit_maestro, "maestro")),
    "android": (("scrcpy", _kit_scrcpy, "scrcpy"), ("maestro", _kit_maestro, "maestro")),
    "node": (("playwright", _kit_playwright, "playwright"),),
    "rust": (("tauri-driver", _kit_tauri_driver, "tauri-driver"),),
}


def _install_kit(bundle: str, host: str, report: ProgressFn) -> list[str]:
    notes: list[str] = []
    for name, installer, probe_id in _KIT_STEPS.get(bundle, ()):
        report(None, f"UI test kit: installing {name}…")
        try:
            landed = installer(host)
        except _StepFailed as failure:
            reason = (failure.tail or failure.step).strip().splitlines()
            notes.append(f"{name} skipped ({reason[-1][:90] if reason else failure.step})")
            continue
        except Exception as exc:  # noqa: BLE001 - extras never fail the install
            notes.append(f"{name} skipped ({type(exc).__name__})")
            continue
        status = toolchain.probe(fresh=True).get(probe_id)
        notes.append(landed if status and status.available else f"{landed} — installed, resolves next session")
    return notes


def _install(sdk: str, host: str | None = None, progress: ProgressFn | None = None,
             ui_test_kit: bool = False) -> str:
    report: ProgressFn = progress or (lambda _pct, _label: None)
    resolved_host = host_platform(host)
    canonical = canonical_sdk(sdk)
    label = _LABELS.get(canonical)
    if label is None:
        choices = ", ".join(sorted(_LABELS))
        return f"⛔ unknown SDK {sdk!r}. Installable: {choices}."
    wanted = _BUNDLE_TOOLS[canonical]
    before = toolchain.probe(resolved_host, fresh=True)
    kit_notes: list[str] = []
    if all(before[tool_id].available for tool_id in wanted):
        found = "; ".join(
            f"{tool_id} {(before[tool_id].version or before[tool_id].path)[:60]}".strip()
            for tool_id in wanted
        )
        if ui_test_kit:
            kit_notes = _install_kit(canonical, resolved_host, report)
        receipt = f"ℹ️ {label} already installed ({found}). Nothing to do."
        if kit_notes:
            receipt += " UI test kit: " + " · ".join(kit_notes) + "."
        return receipt
    log: list[str] = []
    report(0, f"Installing {label}…")
    try:
        _INSTALLERS[canonical](resolved_host, log, report)
    except _StepFailed as failure:
        return (
            f"⛔ {label} install failed at step '{failure.step}':\n{failure.tail}\n"
            f"Manual install: {_MANUAL_HINTS[canonical]}"
        )
    after = toolchain.probe(resolved_host, fresh=True)
    ready = [t for t in wanted if after[t].available]
    missing = [t for t in wanted if not after[t].available]
    detail = "; ".join(
        f"{t} {(after[t].version or after[t].path)[:60]}".strip() for t in ready
    )
    steps = " · ".join(log)
    if ready and ui_test_kit:
        kit_notes = _install_kit(canonical, resolved_host, report)
    kit_text = (" UI test kit: " + " · ".join(kit_notes) + ".") if kit_notes else ""
    if not missing:
        report(100, f"{label} ready")
        return (
            f"✅ {label} installed and verified ({detail})."
            + (f" Steps: {steps}." if steps else "")
            + " The SDK resolves in this session now — create/build with "
            "the terminal (e.g. `flutter create <name>`)."
            + kit_text
        )
    if ready:
        return (
            f"⚠️ {label} partially installed ({detail}); still missing: "
            f"{', '.join(missing)}. Re-run check_target_toolchains for the "
            f"remaining pieces. Steps: {steps}."
            + kit_text
        )
    return (
        f"⛔ {label} install ran but the toolchain probe still cannot find "
        f"{', '.join(missing)} — the machine may need a restart or a PATH "
        f"refresh. Steps: {steps}. Manual install: {_MANUAL_HINTS[canonical]}"
    )


def _bus_progress(thread_id: str) -> ProgressFn:
    """Throttled `tool.progress` events for the card's 0→100 loader
    (founder 2026-10-18: a visible loader is what makes a user wait
    instead of closing the app). Emits on label change, on ≥1% steps,
    and never more than ~4/second; progress plumbing must never break
    the install itself, so every emit is best-effort."""
    state = {"pct": None, "label": "", "at": 0.0}

    def report(percent: float | None, label: str) -> None:
        pct = None if percent is None else round(max(0.0, min(100.0, float(percent))), 1)
        now = time.monotonic()
        if pct == state["pct"] and label == state["label"]:
            return
        if pct is not None and state["pct"] is not None and label == state["label"] \
                and abs(pct - state["pct"]) < 1.0 and now - state["at"] < 0.25:
            return
        state.update(pct=pct, label=label, at=now)
        try:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("tool.progress", {
                "thread_id": thread_id,
                "tool_name": "install_toolchain",
                "percent": pct,
                "label": label,
            })
        except Exception:  # noqa: BLE001
            pass

    return report


@tool
def install_toolchain(sdk: str, config: RunnableConfig, ui_test_kit: bool = False) -> str:
    """Install a missing SDK/toolchain on this machine (Flutter, Android
    SDK, Node.js, JDK 21, Rust, Xcode command-line tools).

    USE when `check_target_toolchains` (or a failed create/build command)
    shows the SDK for the thing being built is absent — e.g. build a
    Flutter app with no `flutter` on the machine. `sdk` accepts the
    bundle name (flutter, android, node, java, rust, xcode) or any tool
    id the checker reported (adb, sdkmanager, dart, cargo, xcodebuild…).

    Downloads official packages (up to ~1 GB) and installs OUTSIDE the
    workspace, so the user is asked for approval first; an install can
    take several minutes (the card shows live 0→100 progress). Set
    `ui_test_kit` when the task will also verify UI: the same approval
    then also lands the testing raw materials for the platform
    (device mirroring + Maestro for mobile, Playwright Chromium for
    web, tauri-driver for Tauri). Afterwards the SDK resolves
    immediately — create and build through the terminal
    (`flutter create <name>`), then CONTINUE the original task.
    Never hand-author a project generator's files (pubspec.yaml,
    package.json scaffolds) as a substitute for a missing SDK: offer
    this install instead.
    """
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    thread_id = str(configurable.get("thread_id") or "")
    return _install(sdk, progress=_bus_progress(thread_id), ui_test_kit=ui_test_kit)

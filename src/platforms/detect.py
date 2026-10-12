"""Project platform detection and per-platform build/test/e2e recipes.

Pure logic: no subprocesses are started here. The tools in
`src/tools/platform_tools.py` turn a recipe into a command and run it through
the existing terminal tool (so approvals and hardline guards still apply).

Supported platform ids:
    web, electron, tauri, flutter, react_native, android, ios, desktop_python
"""
from __future__ import annotations

import json
import platform as _platform
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PLATFORMS = (
    "web", "electron", "tauri", "flutter", "react_native",
    "android", "ios", "desktop_python",
)

_SKIP_DIRS = {
    ".git", "node_modules", "build", "dist", "out", "target", ".gradle",
    ".idea", "Pods", "DerivedData", ".dart_tool", "coverage", ".next",
    "venv", ".venv", "__pycache__", ".maestro",
}
_MAX_DEPTH = 2
_MAX_DIRS = 300

_WEB_DEPS = ("vite", "next", "react", "vue", "svelte", "@angular/core", "astro", "webpack", "parcel")
_PY_DESKTOP_MARKERS = ("pyside6", "pyside2", "pyqt5", "pyqt6", "customtkinter")


@dataclass
class PlatformProject:
    platform: str
    root: str                      # path relative to the workspace ("." = workspace root)
    evidence: list[str] = field(default_factory=list)


@dataclass
class Recipe:
    """What the agent should run for one platform, or why it cannot."""
    platform: str
    root: str
    build: str | None = None
    unit_test: str | None = None
    e2e: str | None = None
    requires: tuple[str, ...] = ()     # executables that must be on PATH
    host_os: tuple[str, ...] = ()      # empty = any OS; else e.g. ("Darwin",)
    notes: list[str] = field(default_factory=list)
    e2e_hint: str = ""                 # what to scaffold if no e2e suite exists


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _candidate_roots(workspace: Path) -> list[Path]:
    """Workspace root plus folders up to _MAX_DEPTH below it (bounded BFS)."""
    roots: list[Path] = [workspace]
    frontier = [workspace]
    seen = 1
    for _ in range(_MAX_DEPTH):
        nxt: list[Path] = []
        for folder in frontier:
            try:
                children = sorted(folder.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir() or child.name in _SKIP_DIRS or child.name.startswith("."):
                    continue
                if seen >= _MAX_DIRS:
                    return roots
                seen += 1
                roots.append(child)
                nxt.append(child)
        frontier = nxt
    return roots


def _deps(pkg: dict) -> set[str]:
    out: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        block = pkg.get(key)
        if isinstance(block, dict):
            out.update(str(k).lower() for k in block)
    return out


def _detect_root(root: Path, workspace: Path) -> list[PlatformProject]:
    rel = "." if root == workspace else str(root.relative_to(workspace)).replace("\\", "/")
    found: list[PlatformProject] = []

    def add(platform: str, *evidence: str) -> None:
        found.append(PlatformProject(platform, rel, list(evidence)))

    # Flutter: pubspec.yaml that depends on the flutter SDK.
    pubspec = root / "pubspec.yaml"
    if pubspec.is_file() and "sdk: flutter" in _read_text(pubspec):
        add("flutter", "pubspec.yaml depends on Flutter")

    pkg_path = root / "package.json"
    pkg = _read_json(pkg_path) if pkg_path.is_file() else {}
    deps = _deps(pkg)

    # Tauri: src-tauri config (desktop shell around a web frontend).
    if (root / "src-tauri" / "tauri.conf.json").is_file() or (root / "tauri.conf.json").is_file():
        add("tauri", "tauri.conf.json present")

    # React Native / Expo (mobile).
    if "react-native" in deps or "expo" in deps:
        add("react_native", "package.json depends on react-native/expo")

    # Electron (desktop).
    if "electron" in deps:
        add("electron", "package.json depends on electron")

    # Native Android (Gradle + com.android.application).
    gradle_files = [root / n for n in ("settings.gradle", "settings.gradle.kts",
                                       "build.gradle", "build.gradle.kts",
                                       "app/build.gradle", "app/build.gradle.kts")]
    # An `app/` module folder belongs to the Gradle project one level up (its
    # parent checks app/build.gradle directly), so it is never a second project.
    inside_gradle_module = root.name == "app" and root != workspace
    android_hit = not inside_gradle_module and (any(
        g.is_file() and "com.android.application" in _read_text(g) for g in gradle_files
    ) or (root / "app" / "src" / "main" / "AndroidManifest.xml").is_file())
    if android_hit:
        add("android", "Gradle Android application module")

    # iOS (Xcode project).
    if any(root.glob("*.xcodeproj")) or any(root.glob("*.xcworkspace")):
        add("ios", "Xcode project present")

    # Python desktop GUI toolkits.
    py_text = ""
    for name in ("pyproject.toml", "requirements.txt"):
        py_text += _read_text(root / name).lower()
    if any(marker in py_text for marker in _PY_DESKTOP_MARKERS):
        add("desktop_python", "Python desktop GUI toolkit declared")

    # Web: JS web framework, or a plain static site.
    specialized = {p.platform for p in found}
    if not (specialized & {"electron", "tauri", "react_native", "flutter"}):
        if any(dep in deps or any(dep == d or d.startswith(dep + "/") for d in deps) for dep in _WEB_DEPS):
            add("web", "package.json depends on a web framework")
        elif (root / "index.html").is_file() and not pkg_path.is_file():
            add("web", "static index.html")
        elif pkg_path.is_file() and (root / "index.html").is_file():
            add("web", "package.json with index.html")

    return found


def detect_platforms(workspace: str | Path) -> list[PlatformProject]:
    """Return every platform found in the workspace, most specific first."""
    ws = Path(workspace).resolve()
    if not ws.is_dir():
        return []
    results: list[PlatformProject] = []
    for root in _candidate_roots(ws):
        results.extend(_detect_root(root, ws))
    # De-duplicate (platform, root); keep the first evidence.
    unique: dict[tuple[str, str], PlatformProject] = {}
    for item in results:
        unique.setdefault((item.platform, item.root), item)
    return list(unique.values())


# --------------------------------------------------------------------------- #
# Recipes
# --------------------------------------------------------------------------- #

def _js_runner(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _script(root: Path, name: str) -> str | None:
    """Return the package.json script body, ignoring npm's placeholder test."""
    scripts = _read_json(root / "package.json").get("scripts") or {}
    body = scripts.get(name) if isinstance(scripts, dict) else None
    if not isinstance(body, str) or not body.strip():
        return None
    if "no test specified" in body:
        return None
    return body


def _npm_run(root: Path, name: str) -> str:
    runner = _js_runner(root)
    return f"{runner} run {name}" if runner != "npm" else f"npm run {name}"


def _playwright_config(root: Path) -> bool:
    return any((root / n).is_file() for n in (
        "playwright.config.ts", "playwright.config.js", "playwright.config.mjs",
    ))


def _gradle(root: Path) -> str:
    if _platform.system() == "Windows":
        return "gradlew.bat" if (root / "gradlew.bat").is_file() else "gradle"
    return "./gradlew" if (root / "gradlew").is_file() else "gradle"


def _maestro_flows(root: Path) -> bool:
    flows = root / ".maestro"
    return flows.is_dir() and any(flows.glob("*.y*ml"))


def _recipe_web(p: PlatformProject, root: Path) -> Recipe:
    r = Recipe("web", p.root, requires=("node",) if (root / "package.json").is_file() else ())
    if (root / "package.json").is_file():
        if _script(root, "build"):
            r.build = _npm_run(root, "build")
        if _script(root, "test"):
            r.unit_test = _npm_run(root, "test")
        if _script(root, "test:e2e") or _script(root, "e2e"):
            r.e2e = _npm_run(root, "test:e2e" if _script(root, "test:e2e") else "e2e")
        elif _playwright_config(root):
            r.e2e = "npx playwright test"
        r.requires = ("node", "npx") if r.e2e and "npx" in r.e2e else ("node",)
    r.e2e_hint = "playwright"
    return r


def _recipe_electron(p: PlatformProject, root: Path) -> Recipe:
    r = Recipe("electron", p.root, requires=("node",))
    if _script(root, "build"):
        r.build = _npm_run(root, "build")
    if _script(root, "test"):
        r.unit_test = _npm_run(root, "test")
    if _script(root, "test:e2e") or _script(root, "e2e"):
        r.e2e = _npm_run(root, "test:e2e" if _script(root, "test:e2e") else "e2e")
    elif _playwright_config(root):
        r.e2e = "npx playwright test"
    r.e2e_hint = "playwright-electron"
    return r


def _recipe_tauri(p: PlatformProject, root: Path) -> Recipe:
    manifest = "src-tauri/Cargo.toml" if (root / "src-tauri" / "Cargo.toml").is_file() else "Cargo.toml"
    r = Recipe("tauri", p.root, requires=("cargo", "node"))
    r.build = f"cargo check --manifest-path {manifest}"
    r.unit_test = f"cargo test --manifest-path {manifest}"
    if _script(root, "test:e2e") or _script(root, "e2e"):
        r.e2e = _npm_run(root, "test:e2e" if _script(root, "test:e2e") else "e2e")
    elif _playwright_config(root):
        r.e2e = "npx playwright test"
    r.e2e_hint = "playwright"
    r.notes.append("Tauri UI tests run against the web frontend; native window tests need tauri-driver.")
    return r


def _recipe_flutter(p: PlatformProject, root: Path) -> Recipe:
    r = Recipe("flutter", p.root, requires=("flutter",))
    r.build = "flutter analyze"
    r.unit_test = "flutter test"
    if (root / "integration_test").is_dir():
        r.e2e = "flutter test integration_test"
        r.notes.append("integration_test needs a running emulator or device.")
    r.e2e_hint = "flutter-integration"
    return r


def _recipe_react_native(p: PlatformProject, root: Path) -> Recipe:
    r = Recipe("react_native", p.root, requires=("node",))
    if (root / "tsconfig.json").is_file():
        r.build = "npx tsc --noEmit"
    if _script(root, "test"):
        r.unit_test = _npm_run(root, "test")
    if _maestro_flows(root):
        r.e2e = "maestro test .maestro/"
        r.requires = ("node", "maestro")
    elif _script(root, "e2e") or _script(root, "test:e2e"):
        r.e2e = _npm_run(root, "test:e2e" if _script(root, "test:e2e") else "e2e")
    r.e2e_hint = "maestro"
    r.notes.append("UI tests need an emulator or device with the app installed.")
    return r


def _recipe_android(p: PlatformProject, root: Path) -> Recipe:
    gradle = _gradle(root)
    r = Recipe("android", p.root, requires=("java",) if gradle != "gradle" else ("java", "gradle"))
    r.build = f"{gradle} assembleDebug"
    r.unit_test = f"{gradle} testDebugUnitTest"
    if (root / "app" / "src" / "androidTest").is_dir():
        r.e2e = f"{gradle} connectedDebugAndroidTest"
        r.notes.append("Instrumented UI tests need a running emulator or connected device.")
    elif _maestro_flows(root):
        r.e2e = "maestro test .maestro/"
        r.requires = r.requires + ("maestro",)
        r.notes.append("Maestro UI flows need an emulator or connected device.")
    r.e2e_hint = "maestro"
    return r


def _recipe_ios(p: PlatformProject, root: Path) -> Recipe:
    r = Recipe("ios", p.root, requires=("xcodebuild",), host_os=("Darwin",))
    projects = sorted(root.glob("*.xcodeproj"))
    if projects:
        name = projects[0].stem
        r.build = f'xcodebuild -project "{projects[0].name}" -scheme "{name}" build'
        r.unit_test = f'xcodebuild -project "{projects[0].name}" -scheme "{name}" test'
    r.notes.append("iOS builds and UI tests only run on macOS with Xcode.")
    r.e2e_hint = "xcui"
    return r


def _recipe_desktop_python(p: PlatformProject, root: Path) -> Recipe:
    r = Recipe("desktop_python", p.root, requires=("python",))
    r.build = "python -m compileall -q ."
    if (root / "tests").is_dir():
        r.unit_test = "python -m pytest -q"
    if (root / "tests" / "e2e").is_dir():
        r.e2e = "python -m pytest -q tests/e2e"
    r.e2e_hint = "pytest-qt"
    return r


_RECIPE_BUILDERS: dict[str, Callable[[PlatformProject, Path], Recipe]] = {
    "web": _recipe_web,
    "electron": _recipe_electron,
    "tauri": _recipe_tauri,
    "flutter": _recipe_flutter,
    "react_native": _recipe_react_native,
    "android": _recipe_android,
    "ios": _recipe_ios,
    "desktop_python": _recipe_desktop_python,
}


def recipe_for(workspace: str | Path, project: PlatformProject) -> Recipe:
    root = Path(workspace).resolve() / project.root
    return _RECIPE_BUILDERS[project.platform](project, root)


def missing_requirements(recipe: Recipe) -> list[str]:
    """Executables a recipe needs that are absent, plus host-OS mismatches."""
    problems: list[str] = []
    if recipe.host_os and _platform.system() not in recipe.host_os:
        problems.append(
            f"{recipe.platform} needs {'/'.join(recipe.host_os)} "
            f"(this machine is {_platform.system()})"
        )
    for exe in recipe.requires:
        if shutil.which(exe) is None:
            problems.append(f"'{exe}' is not on PATH")
    return problems


_EXIT_RE = re.compile(r"exit code[:\s(]+(-?\d+)", re.IGNORECASE)


def exit_code_of(output: str) -> int | None:
    match = _EXIT_RE.search(output or "")
    return int(match.group(1)) if match else None


__all__ = [
    "PLATFORMS", "PlatformProject", "Recipe", "detect_platforms", "recipe_for",
    "missing_requirements", "exit_code_of",
]

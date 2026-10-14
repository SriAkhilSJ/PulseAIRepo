"""Bounded workspace fingerprinting: what did the agent (or the user) build?

Detection is deliberately cheap and bounded — a coding agent asks "what is this
workspace?" on every non-trivial turn, and the answer must not cost a full
tree walk of a 400k-file IDE checkout. Everything here is stdlib, side-effect
free, and limited by ``max_files``/``max_depth``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".gradle", ".idea", ".vscode",
    "build", "dist", "out", "target", "bin", "obj", "__pycache__", ".venv",
    "venv", ".next", ".nuxt", ".dart_tool", "Pods", ".terraform", "coverage",
    "vendor", ".cache", ".turbo", ".parcel-cache", "DerivedData",
})

LOCKFILES = (
    ("pnpm", "pnpm-lock.yaml"),
    ("yarn", "yarn.lock"),
    ("bun", "bun.lockb"),
    ("npm", "package-lock.json"),
)


@dataclass(frozen=True)
class TargetCandidate:
    """One plausible target for this workspace."""

    target: str                       # provider id (see src/targets/registry.py)
    label: str
    confidence: float
    evidence: tuple[str, ...] = ()
    framework: str = ""
    app_id: str = ""
    host_supported: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        files = ", ".join(self.evidence[:4]) or "no file evidence"
        app = f" app={self.app_id}" if self.app_id else ""
        return f"{self.target:<14} {self.confidence:0.2f}  {self.label}{app}  [{files}]"


def _wall(workspace: Path, *, max_files: int, max_depth: int) -> list[str]:
    """Relative POSIX paths under ``workspace``, bounded and skip-listed."""
    root = Path(workspace).resolve()
    found: list[str] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and len(found) < max_files:
        directory, depth = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if len(found) >= max_files:
                break
            name = entry.name
            try:
                if entry.is_dir():
                    if name in SKIP_DIRS or name.startswith("."):
                        continue
                    if depth < max_depth:
                        stack.append((entry, depth + 1))
                    continue
                found.append(entry.relative_to(root).as_posix())
            except OSError:
                continue
    return found


def scan(workspace: str | Path, *, max_files: int = 6000, max_depth: int = 5) -> list[str]:
    return _wall(Path(workspace), max_files=max_files, max_depth=max_depth)


def _present(workspace: Path, relatives: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    for rel in relatives:
        if (workspace / rel).exists():
            out.append(rel)
    return tuple(out)


def any_path(workspace: Path, patterns: Iterable[str]) -> tuple[str, ...]:
    """First match per glob (skipping vendored directories)."""
    found: list[str] = []
    for pattern in patterns:
        for match in sorted(_iter_glob(workspace, pattern)):
            found.append(match)
            break
    return tuple(found)


def _iter_glob(workspace: Path, pattern: str) -> Iterator[str]:
    try:
        for match in workspace.glob(pattern):
            parts = set(match.parts)
            if parts & SKIP_DIRS:
                continue
            yield match.relative_to(workspace).as_posix()
    except (OSError, ValueError):
        return


def read_text(workspace: Path, rel: str, *, limit: int = 400_000) -> str:
    try:
        return (workspace / rel).read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, UnicodeError):
        return ""


def read_json(workspace: Path, rel: str) -> dict[str, Any]:
    try:
        data = json.loads(read_text(workspace, rel))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def package_manager(workspace: Path) -> tuple[str, str]:
    """Detect the JS package manager from lockfiles (default ``npm``)."""
    for name, lockfile in LOCKFILES:
        if (workspace / lockfile).is_file():
            return name, lockfile
    return "npm", ""


def node_manifest(workspace: Path) -> dict[str, Any]:
    return read_json(workspace, "package.json")


def node_dependencies(manifest: dict[str, Any]) -> dict[str, str]:
    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = manifest.get(key)
        if isinstance(section, dict):
            deps.update({str(k): str(v) for k, v in section.items()})
    return deps


def has_dependency(manifest: dict[str, Any], *names: str) -> bool:
    deps = node_dependencies(manifest)
    keys = {name.lower() for name in deps}
    return any(name.lower() in keys for name in names)


def has_script(manifest: dict[str, Any], *names: str) -> bool:
    scripts = manifest.get("scripts")
    if not isinstance(scripts, dict):
        return False
    return any(name in scripts for name in names)


# --------------------------------------------------------------------------- #
# Android / iOS identifiers
# --------------------------------------------------------------------------- #

_NAMESPACE_RE = re.compile(r"namespace\s*[=(\s]\s*['\"]([\w.]+)['\"]")
_APP_ID_RE = re.compile(r"applicationId\s*[=(\s]\s*['\"]([\w.]+)['\"]")
_MANIFEST_PKG_RE = re.compile(r'package\s*=\s*"([\w.]+)"')
_ACTIVITY_RE = re.compile(r"<activity[\s\S]{0,400}?android:name\s*=\s*\"([^\"]+)\"")
_ACTIVITY_ALIAS_RE = re.compile(r"<activity-alias[\s\S]{0,400}?android:targetActivity\s*=\s*\"([^\"]+)\"")
_BUNDLE_ID_RE = re.compile(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*\"?([\w.\-$(){}]+)\"?")
_SCHEME_RE = re.compile(r"^\s*name\s*=\s*\"([^\"]+)\"\s*$", re.MULTILINE)


def android_manifest_paths(workspace: Path) -> tuple[str, ...]:
    return any_path(workspace, (
        "app/src/main/AndroidManifest.xml",
        "*/src/main/AndroidManifest.xml",
        "*/*/src/main/AndroidManifest.xml",
        "android/app/src/main/AndroidManifest.xml",
    ))


def android_module(workspace: Path, manifests: Iterable[str]) -> str:
    """The Gradle module that owns the launcher activity (default ``app``)."""
    for rel in manifests:
        if "src/main/AndroidManifest.xml" not in rel:
            continue
        module = rel.split("/src/main/")[0]
        return module or "app"
    return "app"


def android_app_id(workspace: Path, manifests: Iterable[str] | None = None) -> str:
    """Package/applicationId for the Android app, best effort."""
    for rel in (manifests if manifests is not None else android_manifest_paths(workspace)):
        text = read_text(workspace, rel, limit=60_000)
        match = _MANIFEST_PKG_RE.search(text)
        if match and not match.group(1).startswith("${"):
            return match.group(1)
    for rel in any_path(workspace, (
        "app/build.gradle.kts", "app/build.gradle",
        "*/build.gradle.kts", "*/build.gradle", "build.gradle.kts", "build.gradle",
    )):
        text = read_text(workspace, rel, limit=120_000)
        for regex in (_APP_ID_RE, _NAMESPACE_RE):
            match = regex.search(text)
            if match:
                return match.group(1)
    return ""


def android_launcher_activity(workspace: Path, manifests: Iterable[str] | None = None) -> str:
    """Launcher activity/alias name, best effort (``.MainActivity`` style)."""
    for rel in (manifests if manifests is not None else android_manifest_paths(workspace)):
        text = read_text(workspace, rel, limit=80_000)
        launcher_block = ""
        for block in re.findall(r"<(?:activity|activity-alias)\b[\s\S]*?</(?:activity|activity-alias)>", text):
            if "android.intent.category.LAUNCHER" in block:
                launcher_block = block
                break
        if not launcher_block:
            continue
        match = _ACTIVITY_ALIAS_RE.search(launcher_block) or _ACTIVITY_RE.search(launcher_block)
        if match:
            name = match.group(1)
            return name if name.startswith(".") else name
    return ""


def gradle_wrapper(workspace: Path) -> str:
    for rel in ("gradlew.bat", "gradlew"):
        if (workspace / rel).is_file():
            return rel
    return ""


def ios_bundle_id(workspace: Path) -> str:
    for rel in any_path(workspace, (
        "ios/*.xcodeproj/project.pbxproj", "*.xcodeproj/project.pbxproj",
        "macos/*.xcodeproj/project.pbxproj",
    )):
        text = read_text(workspace, rel, limit=400_000)
        for match in _BUNDLE_ID_RE.finditer(text):
            value = match.group(1)
            if value and "$(" not in value and "PRODUCT" not in value:
                return value
    expo = read_json(workspace, "app.json")
    ios = (expo.get("expo") or {}).get("ios") if isinstance(expo.get("expo"), dict) else None
    if isinstance(ios, dict) and ios.get("bundleIdentifier"):
        return str(ios["bundleIdentifier"])
    tauri = read_json(workspace, "src-tauri/tauri.conf.json")
    return str(tauri.get("identifier") or "")


def ios_scheme(workspace: Path) -> str:
    for rel in any_path(workspace, (
        "ios/*.xcodeproj/xcshareddata/xcschemes/*.xcscheme",
        "*.xcodeproj/xcshareddata/xcschemes/*.xcscheme",
    )):
        text = read_text(workspace, rel, limit=20_000)
        match = _SCHEME_RE.search(text)
        if match:
            return match.group(1)
        return Path(rel).stem
    for rel in any_path(workspace, ("ios/*.xcodeproj", "*.xcodeproj")):
        return Path(rel).stem
    return ""


def expo_config(workspace: Path) -> dict[str, Any]:
    data = read_json(workspace, "app.json")
    config = data.get("expo") if isinstance(data.get("expo"), dict) else data
    return config if isinstance(config, dict) else {}


def tauri_config(workspace: Path) -> dict[str, Any]:
    return read_json(workspace, "src-tauri/tauri.conf.json")


def electron_entry(workspace: Path, manifest: dict[str, Any]) -> str:
    """Best-effort Electron main entry (as a workspace-relative path)."""
    for candidate in (
        str(manifest.get("main") or ""),
        "electron/main.js", "electron/main.ts", "src/main.js", "src/main.ts",
        "main.js", "main.cjs", "dist-electron/main.js", ".vite/build/main.js",
    ):
        if candidate and (workspace / candidate).is_file():
            return candidate
    for rel in any_path(workspace, ("out/main/*.js", "dist/main/*.js", ".vite/build/main.js")):
        return rel
    return ""


def python_entry(workspace: Path) -> str:
    for rel in ("main.py", "app.py", "src/main.py"):
        if (workspace / rel).is_file():
            return rel
    return ""


def screenshot_dir(workspace: Path) -> Path:
    """Where target evidence lands (kept out of source trees when possible)."""
    return workspace / ".crusorai" / "target-evidence"


__all__ = [
    "SKIP_DIRS", "TargetCandidate", "android_app_id", "android_launcher_activity",
    "android_manifest_paths", "android_module", "any_path", "electron_entry",
    "expo_config", "gradle_wrapper", "has_dependency", "has_script", "ios_bundle_id",
    "ios_scheme", "node_dependencies", "node_manifest", "package_manager",
    "python_entry", "read_json", "read_text", "scan", "screenshot_dir", "tauri_config",
]

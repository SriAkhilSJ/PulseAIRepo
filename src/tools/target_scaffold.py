"""Deterministic scaffolding for the non-web targets of ``src/targets``.

Same contract as ``scaffold_tools.scaffold_nextjs`` (the web case):

* generate in a temporary sibling directory, then merge into the real
  workspace — ``flutter create .`` / ``npm create tauri-app`` behave badly when
  ``_provided/`` already exists or when the generator decides to nest
  ``<workspace>/<workspace>/``;
* preserve ``_provided`` and every other input the user handed us;
* install exactly once, at the correct root, and only after the merge;
* refuse — loudly — rather than merge over an existing project.

The generators are the vendors' own CLIs (``flutter create``,
``create-expo-app``, ``create-tauri-app``); this module owns only the boring
environment transition, which is the part models get wrong repeatedly.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.targets import toolchain

# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #

# pub/npm-compatible project name (lowercase, digits, underscore, dot/hyphen
# are legal in npm but illegal in a Dart package name — stay on the strict,
# portable subset).
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
# reverse-DNS application id: com.acme.app / io.github.user.app
_ORG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+$")
# npm dependency spec ("axios", "@react-three/fiber", "three@^0.170.0")
_NPM_PACKAGE_RE = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+(?:@[a-zA-Z0-9._~^*<>=|-]+)?$")
# pub package spec ("http", "http:^1.2.0")
_PUB_PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(?::[^\s]+)?$")

_FLUTTER_PLATFORMS: tuple[str, ...] = (
    "android", "ios", "web", "macos", "windows", "linux",
)
_RN_TEMPLATES: tuple[str, ...] = (
    "default", "blank", "blank-typescript", "tabs", "bare-minimum",
)
# create-tauri-app --template choices (see `npx create-tauri-app@latest --help`)
_TAURI_TEMPLATES: tuple[str, ...] = (
    "vanilla", "vanilla-ts", "vue", "vue-ts", "svelte", "svelte-ts",
    "react", "react-ts", "solid", "solid-ts", "yew", "leptos", "sycamore",
    "angular", "preact", "preact-ts", "blazor", "dioxus",
)

# Entries this tool tolerates at the workspace root before scaffolding. Anything
# else means the user already has a project there and we must not merge.
_ALLOWED_EXISTING = {"_provided", ".git", ".gitignore", ".crusorai"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _resolve_tool(*tool_ids: str) -> str:
    """Resolve an executable by toolchain id, honouring ``CRUSORAI_*`` overrides.

    Deliberately bypasses ``toolchain.probe()``'s per-process cache: a scaffold
    call is rare, and the user may have just installed the SDK it needs.
    """
    for tool_id in tool_ids:
        spec = toolchain.TOOLS_BY_ID.get(tool_id)
        if spec is None:
            continue
        override = os.environ.get(spec.env_override, "").strip() if spec.env_override else ""
        if override and Path(override).exists():
            return override
        for command in spec.commands:
            found = shutil.which(command)
            if found:
                return found
    return ""


def _run(argv: list[str], *, cwd: Path, timeout: int) -> tuple[int, str]:
    env = dict(os.environ)
    env.update({"CI": "1", "NO_COLOR": "1"})
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout}s: {' '.join(argv)}"
    except OSError as exc:
        return 127, f"Could not execute {' '.join(argv)}: {exc}"
    output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return proc.returncode, output


def _workspace(config: RunnableConfig) -> Path:
    return Path(config["configurable"]["workspace"]).resolve()


def _guard(tool_name: str, workspace: Path, marker: str) -> str | None:
    """Return a refusal message, or ``None`` when scaffolding may proceed."""
    if (workspace / marker).exists():
        return (
            f"ℹ️ {tool_name} skipped: {marker} already exists at the workspace root. "
            "Inspect the existing project and continue there."
        )
    existing = {p.name for p in workspace.iterdir()} if workspace.exists() else set()
    unexpected = sorted(existing - _ALLOWED_EXISTING)
    if unexpected:
        return (
            f"⛔ {tool_name} refused to merge over an existing project. "
            f"Unexpected workspace entries: {unexpected[:12]}. Inspect and use the existing setup."
        )
    return None


def _validate_name(tool_name: str, project_name: str) -> str | None:
    if not _NAME_RE.fullmatch(project_name or ""):
        return (
            f"⛔ {tool_name} refused invalid project_name {project_name!r}: use 2–31 lowercase "
            "letters/digits/underscores starting with a letter (portable across pub and npm)."
        )
    return None


def _validate_packages(tool_name: str, packages: list[str], pattern: re.Pattern[str]) -> tuple[list[str], str | None]:
    extras = [str(p).strip() for p in (packages or []) if str(p).strip()]
    invalid = [p for p in extras if not pattern.fullmatch(p)]
    if invalid:
        return [], f"⛔ {tool_name} refused invalid package name(s): {invalid}"
    return extras, None


def _merge_tree(temp_project: Path, workspace: Path) -> None:
    """Copy the generated project into the workspace, minus build/install junk."""
    skip = {".git", "node_modules", "target", ".dart_tool", "build", ".expo", "Pods"}
    for item in temp_project.iterdir():
        if item.name in skip:
            continue
        destination = workspace / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)


def _checkpoint(workspace: Path, tool_name: str) -> None:
    try:
        from src.tools.shadow_checkpoints import checkpoint_before_mutation
        checkpoint_before_mutation(str(workspace), tool_name)
    except Exception:
        pass


def _record_edit(config: RunnableConfig, workspace: Path) -> None:
    try:
        from src.context.repo_map import invalidate_repo_map
        invalidate_repo_map(str(workspace))
    except Exception:
        pass
    try:
        from src.tools.file_tools import _record_workspace_edit
        changed = [str(p) for p in workspace.iterdir() if p.name not in _ALLOWED_EXISTING]
        _record_workspace_edit(config, str(workspace), changed)
    except Exception:
        pass


def _generated_ok(temp_project: Path, marker: Path) -> bool:
    return (temp_project / marker).is_file()


# --------------------------------------------------------------------------- #
# Flutter
# --------------------------------------------------------------------------- #

@tool
def scaffold_flutter(
    project_name: str = "app",
    org: str = "com.example",
    platforms: str = "android,ios",
    packages: list[str] | None = None,
    config: RunnableConfig = None,
) -> str:
    """Scaffold a Flutter app into the active workspace (mobile + desktop shells).

    USE when the task asks for a Flutter app (or one codebase targeting Android,
    iOS, macOS, Windows and Linux) and the workspace has no ``pubspec.yaml``.
    ``platforms`` is a comma list drawn from android, ios, web, macos, windows,
    linux. ``org`` is the reverse-DNS prefix for the bundle/application id.
    ``packages`` lists extra pub dependencies, e.g. ["http", "provider"].
    Preserves ``_provided/`` and never nests ``<workspace>/<workspace>/``.
    """
    workspace = _workspace(config)
    tool_name = "scaffold_flutter"
    refusal = _guard(tool_name, workspace, "pubspec.yaml") or _validate_name(tool_name, project_name)
    if refusal:
        return refusal
    if not _ORG_RE.fullmatch(org or ""):
        return f"⛔ {tool_name} refused invalid org {org!r}: expected a reverse-DNS prefix like com.acme."

    requested = [p.strip() for p in (platforms or "").split(",") if p.strip()]
    invalid_platforms = [p for p in requested if p not in _FLUTTER_PLATFORMS]
    if invalid_platforms:
        return (
            f"⛔ {tool_name} refused unknown platform(s): {invalid_platforms}. "
            f"Choose from {list(_FLUTTER_PLATFORMS)}."
        )
    selected = requested or ["android", "ios"]

    extras, invalid = _validate_packages(tool_name, packages, _PUB_PACKAGE_RE)
    if invalid:
        return invalid

    flutter = _resolve_tool("flutter")
    if not flutter:
        return (
            "⛔ scaffold_flutter unavailable: the Flutter SDK is not installed or not on PATH "
            "(set $CRUSORAI_FLUTTER to its absolute path). Install: "
            "https://docs.flutter.dev/get-started/install"
        )

    workspace.mkdir(parents=True, exist_ok=True)
    temp_project = workspace.parent / f"crusor-scaffold-{uuid.uuid4().hex[:8]}"
    _checkpoint(workspace, tool_name)
    try:
        code, output = _run(
            [
                flutter, "create", "--org", org, "--project-name", project_name,
                "--platforms", ",".join(selected), "--empty", str(temp_project),
            ],
            cwd=workspace.parent, timeout=300,
        )
        if code != 0 or not _generated_ok(temp_project, "pubspec.yaml"):
            return f"⛔ {tool_name} generate step failed (exit {code}):\n{output[-4000:]}"
        _merge_tree(temp_project, workspace)
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)

    install = _run([flutter, "pub", "get"], cwd=workspace, timeout=300)
    added = ""
    if extras and install[0] == 0:
        code, output = _run([flutter, "pub", "add", *extras], cwd=workspace, timeout=300)
        if code != 0:
            return (
                f"⚠️ {tool_name} created the project at the correct root, but adding {extras} "
                f"failed (exit {code}). Fix the dependencies before finishing:\n{output[-3000:]}"
            )
        added = f" Added dependencies: {extras}."
    if install[0] != 0:
        return (
            f"⚠️ {tool_name} created the project at the correct root, but `flutter pub get` "
            f"failed (exit {install[0]}). Fix the install before finishing:\n{install[1][-3000:]}"
        )

    _record_edit(config, workspace)
    return (
        f"✅ {tool_name} completed at the workspace root for platforms "
        f"{','.join(selected)} (org {org}).{added} The `_provided` directory was preserved. "
        "Next: build and prove it with `verify_target_app` instead of only compiling."
    )


# --------------------------------------------------------------------------- #
# React Native / Expo
# --------------------------------------------------------------------------- #

@tool
def scaffold_react_native(
    project_name: str = "app",
    template: str = "blank-typescript",
    packages: list[str] | None = None,
    config: RunnableConfig = None,
) -> str:
    """Scaffold an Expo React Native app into the active workspace (iOS + Android).

    USE when the task asks for a React Native / Expo app and the workspace has
    no ``package.json``. ``template`` is one of default, blank, blank-typescript,
    tabs, bare-minimum. ``packages`` lists extra npm dependencies, e.g.
    ["axios", "@react-navigation/native"]. The Expo provider in ``src/targets``
    starts Metro before installing, so a debug build is provable immediately.
    """
    workspace = _workspace(config)
    tool_name = "scaffold_react_native"
    refusal = _guard(tool_name, workspace, "package.json") or _validate_name(tool_name, project_name)
    if refusal:
        return refusal
    if template not in _RN_TEMPLATES:
        return f"⛔ {tool_name} refused unknown template {template!r}. Choose from {list(_RN_TEMPLATES)}."

    extras, invalid = _validate_packages(tool_name, packages, _NPM_PACKAGE_RE)
    if invalid:
        return invalid

    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx") or shutil.which("npx")
    npm = _resolve_tool("npm")
    if not npx or not npm:
        return "⛔ scaffold_react_native unavailable: npm/npx is not installed or not on PATH."

    workspace.mkdir(parents=True, exist_ok=True)
    temp_project = workspace.parent / f"crusor-scaffold-{uuid.uuid4().hex[:8]}"
    _checkpoint(workspace, tool_name)
    try:
        code, output = _run(
            [
                npx, "create-expo-app@latest", str(temp_project),
                "--template", template, "--no-install", "--yes",
            ],
            cwd=workspace.parent, timeout=300,
        )
        if code != 0 or not _generated_ok(temp_project, "package.json"):
            return f"⛔ {tool_name} generate step failed (exit {code}):\n{output[-4000:]}"
        _merge_tree(temp_project, workspace)
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)

    code, install_output = _run(
        [npm, "install", *extras, "--legacy-peer-deps"], cwd=workspace, timeout=600,
    )
    if code != 0:
        return (
            f"⚠️ {tool_name} created the project at the correct root, but npm install "
            f"failed (exit {code}). Fix the install before finishing:\n{install_output[-3000:]}"
        )

    _record_edit(config, workspace)
    return (
        f"✅ {tool_name} completed at the workspace root (template {template}). "
        f"Installed base dependencies plus: {extras or '(none)'}. The `_provided` directory "
        "was preserved. Next: `verify_target_app` with target 'react-native'."
    )


# --------------------------------------------------------------------------- #
# Tauri (desktop)
# --------------------------------------------------------------------------- #

@tool
def scaffold_tauri(
    project_name: str = "app",
    identifier: str = "com.example.app",
    frontend: str = "react-ts",
    packages: list[str] | None = None,
    config: RunnableConfig = None,
) -> str:
    """Scaffold a Tauri v2 desktop app into the active workspace (mac/Windows/Linux).

    USE when the task asks for a desktop app and the workspace has no
    ``src-tauri/tauri.conf.json``. ``frontend`` selects the UI template
    (react-ts, vue-ts, svelte-ts, solid-ts, vanilla-ts, …); ``identifier`` is the
    reverse-DNS bundle id used for signing and updates. ``packages`` lists extra
    npm dependencies. Rust toolchain (``cargo``) is required to build.
    """
    workspace = _workspace(config)
    tool_name = "scaffold_tauri"
    refusal = _guard(tool_name, workspace, "src-tauri") or _validate_name(tool_name, project_name)
    if refusal:
        return refusal
    if frontend not in _TAURI_TEMPLATES:
        return f"⛔ {tool_name} refused unknown frontend {frontend!r}. Choose from {list(_TAURI_TEMPLATES)}."
    if not _ORG_RE.fullmatch(identifier or ""):
        return f"⛔ {tool_name} refused invalid identifier {identifier!r}: expected com.acme.app."

    extras, invalid = _validate_packages(tool_name, packages, _NPM_PACKAGE_RE)
    if invalid:
        return invalid

    npm = _resolve_tool("npm")
    if not npm:
        return "⛔ scaffold_tauri unavailable: npm is not installed or not on PATH."

    workspace.mkdir(parents=True, exist_ok=True)
    temp_project = workspace.parent / f"crusor-scaffold-{uuid.uuid4().hex[:8]}"
    _checkpoint(workspace, tool_name)
    try:
        # create-tauri-app has no --no-install: it runs its own install inside the
        # temp directory. We drop node_modules on the merge and install once at
        # the root, so the lockfile ends up in the right place.
        code, output = _run(
            [
                npm, "create", "tauri-app@latest", str(temp_project),
                "--", "--template", frontend, "--manager", "npm",
                "--identifier", identifier, "--yes",
            ],
            cwd=workspace.parent, timeout=600,
        )
        if code != 0 or not _generated_ok(temp_project, Path("src-tauri") / "tauri.conf.json"):
            return f"⛔ {tool_name} generate step failed (exit {code}):\n{output[-4000:]}"
        _merge_tree(temp_project, workspace)
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)

    code, install_output = _run(
        [npm, "install", *extras, "--legacy-peer-deps"], cwd=workspace, timeout=600,
    )
    if code != 0:
        return (
            f"⚠️ {tool_name} created the project at the correct root, but npm install "
            f"failed (exit {code}). Fix the install before finishing:\n{install_output[-3000:]}"
        )

    cargo = _resolve_tool("cargo")
    rust_note = "" if cargo else (
        " Rust is not installed, so `cargo`/`tauri build` will fail: "
        "curl https://sh.rustup.rs -sSf | sh"
    )
    _record_edit(config, workspace)
    return (
        f"✅ {tool_name} completed at the workspace root (frontend {frontend}, id {identifier}). "
        f"Installed base dependencies plus: {extras or '(none)'}.{rust_note} "
        "The `_provided` directory was preserved. Next: `verify_target_app` with target 'tauri'."
    )


TARGET_SCAFFOLD_TOOLS = (scaffold_flutter, scaffold_react_native, scaffold_tauri)

__all__ = [
    "TARGET_SCAFFOLD_TOOLS",
    "scaffold_flutter",
    "scaffold_react_native",
    "scaffold_tauri",
]

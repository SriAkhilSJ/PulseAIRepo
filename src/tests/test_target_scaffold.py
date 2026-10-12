"""Hermetic contracts for the deterministic mobile/desktop scaffolders.

No Flutter SDK, no Expo, no Rust: each test puts a *fake* generator on PATH and
asserts the boilerplate this module actually owns — validation, refusal to merge
over an existing project, generation in a temp sibling, one install at the
correct root, and ``_provided`` preservation.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.tools.target_scaffold import (
    TARGET_SCAFFOLD_TOOLS,
    scaffold_flutter,
    scaffold_react_native,
    scaffold_tauri,
)

_ENV_OVERRIDES = ("CRUSORAI_FLUTTER", "CRUSORAI_NPM", "CRUSORAI_CARGO")


def _config(workspace: Path) -> dict:
    return {"configurable": {"workspace": str(workspace)}}


def _fake_bin(directory: Path, name: str, script: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nset -eu\n" + script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture()
def clean_env(monkeypatch):
    for key in _ENV_OVERRIDES:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# --------------------------------------------------------------------------- #
# validation and refusal (no generators involved)
# --------------------------------------------------------------------------- #

def test_scaffold_tools_are_registered_with_workspace_injection():
    names = {t.name for t in TARGET_SCAFFOLD_TOOLS}
    assert names == {"scaffold_flutter", "scaffold_react_native", "scaffold_tauri"}
    for tool in TARGET_SCAFFOLD_TOOLS:
        assert "config" not in tool.args  # injected, never model-visible


def test_flutter_refuses_invalid_project_name(tmp_path, clean_env):
    message = scaffold_flutter.invoke(
        {"project_name": "Bad Name", "org": "com.acme"}, config=_config(tmp_path)
    )
    assert message.startswith("⛔") and "invalid project_name" in message
    assert not (tmp_path / "pubspec.yaml").exists()


def test_flutter_refuses_invalid_org_and_unknown_platforms(tmp_path, clean_env):
    assert "invalid org" in scaffold_flutter.invoke(
        {"project_name": "demo", "org": "acme"}, config=_config(tmp_path)
    )
    assert "unknown platform" in scaffold_flutter.invoke(
        {"project_name": "demo", "org": "com.acme", "platforms": "android,visionos"},
        config=_config(tmp_path),
    )


def test_flutter_refuses_invalid_pub_package(tmp_path, clean_env):
    message = scaffold_flutter.invoke(
        {"project_name": "demo", "org": "com.acme", "packages": ["http", "{rm -rf}"]},
        config=_config(tmp_path),
    )
    assert message.startswith("⛔") and "invalid package name" in message


def test_flutter_reports_missing_sdk_without_touching_the_workspace(tmp_path, clean_env):
    clean_env.setenv("PATH", str(tmp_path / "empty-bin"))
    message = scaffold_flutter.invoke({"project_name": "demo", "org": "com.acme"}, config=_config(tmp_path))
    assert message.startswith("⛔") and "Flutter SDK is not installed" in message
    assert not (tmp_path / "pubspec.yaml").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_existing_project_is_skipped_not_overwritten(tmp_path, clean_env):
    (tmp_path / "pubspec.yaml").write_text("name: existing\n", encoding="utf-8")
    message = scaffold_flutter.invoke({"project_name": "demo", "org": "com.acme"}, config=_config(tmp_path))
    assert message.startswith("ℹ️") and "already exists" in message
    assert (tmp_path / "pubspec.yaml").read_text(encoding="utf-8") == "name: existing\n"


def test_refuses_to_merge_over_unexpected_workspace_entries(tmp_path, clean_env):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('user work')\n", encoding="utf-8")
    message = scaffold_react_native.invoke({"project_name": "demo"}, config=_config(tmp_path))
    assert message.startswith("⛔") and "refused to merge" in message
    assert (tmp_path / "src" / "main.py").exists()


def test_react_native_rejects_unknown_template(tmp_path, clean_env):
    message = scaffold_react_native.invoke(
        {"project_name": "demo", "template": "typescript"}, config=_config(tmp_path)
    )
    assert "unknown template" in message


def test_tauri_rejects_unknown_frontend_and_identifier(tmp_path, clean_env):
    assert "unknown frontend" in scaffold_tauri.invoke(
        {"project_name": "demo", "identifier": "com.acme.app", "frontend": "elm"},
        config=_config(tmp_path),
    )
    assert "invalid identifier" in scaffold_tauri.invoke(
        {"project_name": "demo", "identifier": "acme"}, config=_config(tmp_path)
    )


# --------------------------------------------------------------------------- #
# happy paths against fake generators
# --------------------------------------------------------------------------- #

def test_flutter_happy_path_merges_installs_and_preserves_inputs(tmp_path, clean_env):
    workspace = tmp_path / "workspace"
    (workspace / "_provided").mkdir(parents=True)
    (workspace / "_provided" / "brief.md").write_text("# brief\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _fake_bin(
        bin_dir, "flutter",
        'if [ "$1" = "create" ]; then\n'
        '  dir=""; for a in "$@"; do dir="$a"; done\n'
        '  mkdir -p "$dir/lib"; printf \'name: demo\\n\' > "$dir/pubspec.yaml"\n'
        '  printf \'void main() {}\\n\' > "$dir/lib/main.dart"\n'
        '  printf \'generated-outside-workspace\\n\' > "$dir/.dart_tool"\n'
        '  exit 0\n'
        "fi\n"
        'if [ "$1" = "pub" ]; then printf \'%s\\n\' "$*" >> "$FAKE_FLUTTER_LOG"; exit 0; fi\n'
        "exit 1\n",
    )
    clean_env.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "flutter.log"
    clean_env.setenv("FAKE_FLUTTER_LOG", str(log))

    message = scaffold_flutter.invoke(
        {"project_name": "demo", "org": "com.acme", "platforms": "android,ios", "packages": ["http"]},
        config=_config(workspace),
    )

    assert message.startswith("✅"), message
    assert (workspace / "pubspec.yaml").is_file()
    assert (workspace / "lib" / "main.dart").is_file()
    assert (workspace / "_provided" / "brief.md").is_file()
    assert "http" in message
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls[0].startswith("pub get")
    assert calls[1] == "pub add http"  # extras install at the root, not in the temp dir
    # generated temp sibling is gone; nothing nests one level too deep
    assert not any(p.name.startswith("crusor-scaffold-") for p in tmp_path.iterdir())
    assert not (workspace / "workspace").exists()


def test_react_native_happy_path_installs_extras_once_at_the_root(tmp_path, clean_env):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "_provided").mkdir()
    bin_dir = tmp_path / "bin"
    _fake_bin(
        bin_dir, "npx",
        'if [ "$1" = "create-expo-app@latest" ]; then\n'
        '  dir="$2"; mkdir -p "$dir/app"; printf \'{"name":"demo"}\\n\' > "$dir/package.json"\n'
        '  printf \'{"expo":{}}\\n\' > "$dir/app.json"\n'
        '  mkdir -p "$dir/node_modules"; printf \'junk\\n\' > "$dir/node_modules/leftover"\n'
        '  exit 0\n'
        "fi\n"
        "exit 1\n",
    )
    _fake_bin(
        bin_dir, "npm",
        'printf \'%s\\n\' "$*" >> "$FAKE_NPM_LOG"\n'
        "exit 0\n",
    )
    clean_env.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "npm.log"
    clean_env.setenv("FAKE_NPM_LOG", str(log))

    message = scaffold_react_native.invoke(
        {"project_name": "demo", "template": "blank-typescript", "packages": ["axios"]},
        config=_config(workspace),
    )

    assert message.startswith("✅"), message
    assert (workspace / "package.json").is_file()
    assert (workspace / "app.json").is_file()
    # the generator's own node_modules must never be copied into the workspace
    assert not (workspace / "node_modules").exists()
    assert log.read_text(encoding="utf-8").splitlines() == ["install axios --legacy-peer-deps"]


def test_tauri_happy_path_passes_identifier_and_keeps_src_tauri(tmp_path, clean_env):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    _fake_bin(
        bin_dir, "npm",
        'if [ "$1" = "create" ]; then\n'
        '  dir="$3"; shift 3; mkdir -p "$dir/src-tauri"\n'
        '  printf \'{"identifier":"%s"}\\n\' "$(printf \'%s\' "$*" | sed -n \'s/.*--identifier \\([^ ]*\\).*/\\1/p\')" > "$dir/src-tauri/tauri.conf.json"\n'
        '  printf \'{"name":"demo"}\\n\' > "$dir/package.json"\n'
        '  exit 0\n'
        "fi\n"
        'printf \'%s\\n\' "$*" >> "$FAKE_NPM_LOG"\n'
        "exit 0\n",
    )
    clean_env.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "npm.log"
    clean_env.setenv("FAKE_NPM_LOG", str(log))

    message = scaffold_tauri.invoke(
        {"project_name": "demo", "identifier": "io.acme.demo", "frontend": "react-ts"},
        config=_config(workspace),
    )

    assert message.startswith("✅"), message
    conf = (workspace / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    assert "io.acme.demo" in conf
    assert "Rust is not installed" in message  # honest, actionable warning on this host
    assert log.read_text(encoding="utf-8").splitlines() == ["install --legacy-peer-deps"]

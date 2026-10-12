"""Hermetic contracts for the deterministic mobile/desktop scaffolders.

No Flutter SDK, Expo, or Rust installation is needed: happy-path tests stub the
command runner and generated files, so they exercise the scaffold contract on
Windows, macOS, and Linux alike. They cover validation, refusal to merge over an
existing project, generation in a temp sibling, installation at the correct
root, and ``_provided`` preservation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import src.tools.target_scaffold as target_scaffold_module
from src.tools.target_scaffold import (
    TARGET_SCAFFOLD_TOOLS,
    scaffold_flutter,
    scaffold_react_native,
    scaffold_tauri,
)

_ENV_OVERRIDES = ("CRUSORAI_FLUTTER", "CRUSORAI_NPM", "CRUSORAI_CARGO")


def _config(workspace: Path) -> dict:
    return {"configurable": {"workspace": str(workspace)}}


def _stub_tool_runtime(monkeypatch, executables: dict[str, str]) -> None:
    """Make scaffold happy paths hermetic and independent of the host OS/SDKs."""
    monkeypatch.setattr(
        target_scaffold_module,
        "_resolve_tool",
        lambda *tool_ids: next(
            (executables[tool_id] for tool_id in tool_ids if tool_id in executables), ""
        ),
    )

    def which(command: str) -> str | None:
        normalized = command[:-4] if command.lower().endswith(".cmd") else command
        return executables.get(normalized)

    # React Native resolves npx directly rather than through _resolve_tool.
    monkeypatch.setattr(target_scaffold_module.shutil, "which", which)


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
    _stub_tool_runtime(clean_env, {"flutter": "fake-flutter"})
    calls: list[tuple[list[str], Path]] = []

    def fake_run(argv, *, cwd, timeout):
        calls.append((argv[1:], Path(cwd)))
        if argv[1] == "create":
            generated = Path(argv[-1])
            (generated / "lib").mkdir(parents=True)
            (generated / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            (generated / "lib" / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            (generated / ".dart_tool").mkdir()
            return 0, ""
        if argv[1] == "pub":
            return 0, ""
        raise AssertionError(f"Unexpected fake Flutter command: {argv}")

    clean_env.setattr(target_scaffold_module, "_run", fake_run)
    message = scaffold_flutter.invoke(
        {"project_name": "demo", "org": "com.acme", "platforms": "android,ios", "packages": ["http"]},
        config=_config(workspace),
    )

    assert message.startswith("✅"), message
    assert (workspace / "pubspec.yaml").is_file()
    assert (workspace / "lib" / "main.dart").is_file()
    assert not (workspace / ".dart_tool").exists()
    assert (workspace / "_provided" / "brief.md").is_file()
    assert "http" in message
    assert [args for args, _ in calls[1:]] == [["pub", "get"], ["pub", "add", "http"]]
    assert all(cwd == workspace for _, cwd in calls[1:])
    # generated temp sibling is gone; nothing nests one level too deep
    assert not any(p.name.startswith("crusor-scaffold-") for p in tmp_path.iterdir())
    assert not (workspace / "workspace").exists()


def test_react_native_happy_path_installs_extras_once_at_the_root(tmp_path, clean_env):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "_provided").mkdir()
    _stub_tool_runtime(clean_env, {"npx": "fake-npx", "npm": "fake-npm"})
    calls: list[tuple[list[str], Path]] = []

    def fake_run(argv, *, cwd, timeout):
        if argv[0] == "fake-npx" and argv[1] == "create-expo-app@latest":
            generated = Path(argv[2])
            (generated / "app").mkdir(parents=True)
            (generated / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
            (generated / "app.json").write_text('{"expo":{}}\n', encoding="utf-8")
            (generated / "node_modules").mkdir()
            (generated / "node_modules" / "leftover").write_text("junk\n", encoding="utf-8")
            return 0, ""
        if argv[0] == "fake-npm" and argv[1] == "install":
            calls.append((argv[1:], Path(cwd)))
            return 0, ""
        raise AssertionError(f"Unexpected fake React Native command: {argv}")

    clean_env.setattr(target_scaffold_module, "_run", fake_run)
    message = scaffold_react_native.invoke(
        {"project_name": "demo", "template": "blank-typescript", "packages": ["axios"]},
        config=_config(workspace),
    )

    assert message.startswith("✅"), message
    assert (workspace / "package.json").is_file()
    assert (workspace / "app.json").is_file()
    # the generator's own node_modules must never be copied into the workspace
    assert not (workspace / "node_modules").exists()
    assert [args for args, _ in calls] == [["install", "axios", "--legacy-peer-deps"]]
    assert calls[0][1] == workspace


def test_tauri_happy_path_passes_identifier_and_keeps_src_tauri(tmp_path, clean_env):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _stub_tool_runtime(clean_env, {"npm": "fake-npm"})
    calls: list[tuple[list[str], Path]] = []

    def fake_run(argv, *, cwd, timeout):
        if argv[0] == "fake-npm" and argv[1] == "create":
            generated = Path(argv[3])
            src_tauri = generated / "src-tauri"
            src_tauri.mkdir(parents=True)
            identifier = argv[argv.index("--identifier") + 1]
            (src_tauri / "tauri.conf.json").write_text(
                f'{{"identifier":"{identifier}"}}\n', encoding="utf-8"
            )
            (generated / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
            return 0, ""
        if argv[0] == "fake-npm" and argv[1] == "install":
            calls.append((argv[1:], Path(cwd)))
            return 0, ""
        raise AssertionError(f"Unexpected fake Tauri command: {argv}")

    clean_env.setattr(target_scaffold_module, "_run", fake_run)
    message = scaffold_tauri.invoke(
        {"project_name": "demo", "identifier": "io.acme.demo", "frontend": "react-ts"},
        config=_config(workspace),
    )

    assert message.startswith("✅"), message
    conf = (workspace / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    assert "io.acme.demo" in conf
    assert "Rust is not installed" in message  # honest, actionable warning on this host
    assert [args for args, _ in calls] == [["install", "--legacy-peer-deps"]]
    assert calls[0][1] == workspace

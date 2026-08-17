"""Pins for the PulseAI overlay applied in place inside the canonical fork (desktop/vscode)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
FORK = DESKTOP / "vscode"
CONTRIB = FORK / "src" / "vs" / "workbench" / "contrib" / "pulseai"
MAIN = FORK / "src" / "vs" / "workbench" / "workbench.common.main.ts"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked(rel: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_product_brand_is_pulseai_ide():
    product = json.loads((FORK / "product.json").read_text(encoding="utf-8"))
    assert product["nameShort"] == "PulseAI"
    assert product["nameLong"] == "PulseAI IDE"
    assert product["applicationName"] == "pulseai"
    assert product["dataFolderName"] == ".pulseai-ide"
    assert product["serverApplicationName"] == "pulseai-server"
    assert product["win32DirName"] == "PulseAI IDE"
    assert product["win32AppUserModelId"] == "PulseAI.IDE"
    assert product["darwinBundleIdentifier"] == "com.pulseai.ide"
    assert product["linuxIconName"] == "pulseai"
    assert product["urlProtocol"] == "pulseai"


def test_pulse_is_registered_once_as_a_workbench_contribution():
    text = MAIN.read_text(encoding="utf-8")
    registration = "import './contrib/pulseai/browser/pulseAI.contribution.js';"
    assert text.count(registration) == 1
    contrib_files = list(CONTRIB.rglob("*.ts"))
    assert contrib_files
    assert any(path.name == "pulseAI.contribution.ts" for path in contrib_files)
    assert not (FORK / "extensions" / "pulseai").exists()


def test_pulse_menu_and_view_commands_are_declared():
    text = (CONTRIB / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "MenuId.MenubarMainMenu" in text
    assert "MenubarPulseAI" in text
    for command in (
        "NewSession", "OpenManager", "ReviewChanges", "OpenCheckpoints",
        "StopActiveRun", "OpenSettings",
    ):
        assert f"PulseAICommandId.{command}" in text
    assert "ViewContainerLocation.AuxiliaryBar" in text
    assert "new SyncDescriptor(PulseAIViewPane)" in text
    assert "registerEditorPane" in text
    assert "PulseAIManagerEditor" in text
    assert "PulseAIManagerInputSerializer" in text
    assert "openEditor(input, { pinned: true })" in text


def test_selective_manifest_matches_overlay_files():
    manifest = json.loads((DESKTOP / "SELECTIVE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["upstream_commit"] == (DESKTOP / "UPSTREAM_PIN").read_text().strip()
    for rel, receipt in manifest["files"].items():
        assert _sha(FORK / rel) == receipt["overlay_sha256"]
        assert receipt["modified"] is True
    for rel, receipt in manifest["brand_assets"].items():
        assert _sha(FORK / rel) == receipt["overlay_sha256"]
        assert receipt["generated_from"] == "branding/pulseai-mark.svg"


def test_canonical_fork_holds_the_overlay_without_runtime_artifacts():
    assert (FORK / "package.json").exists()
    assert (FORK / "build" / "buildfile.ts").exists()
    assert (FORK / "resources" / "pulseai" / "pulseai-mark.svg").exists()
    assert not (FORK / ".git").exists()
    assert not (DESKTOP / "product.json").exists()
    assert not (DESKTOP / "resources").exists()
    assert not _tracked("desktop/vscode/node_modules/**"), "node_modules must never be committed"
    assert not _tracked("desktop/vscode/.vscode/**"), ".vscode dirs must never be committed"
    tracked_build = _tracked("desktop/vscode/build/**")
    assert tracked_build == [
        "desktop/vscode/build/buildfile.ts",
        "desktop/vscode/build/next/index.ts",
    ]
    tracked_ext_builds = _tracked("desktop/vscode/extensions/**/build/**")
    assert not tracked_ext_builds, "extension build outputs must never be committed"
    # Only the approved build overlays are visible; hydrated siblings stay ignored.
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "desktop/vscode/build/next/nls-plugin.ts"],
        cwd=ROOT,
        capture_output=True,
    )
    assert ignored.returncode == 0, "unrelated hydrated build/next sources must stay ignored"

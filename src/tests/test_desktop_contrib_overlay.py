"""Static pins for the selective first-party PulseAI Code OSS overlay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
CONTRIB = DESKTOP / "src" / "vs" / "workbench" / "contrib" / "pulseai"
MAIN = DESKTOP / "src" / "vs" / "workbench" / "workbench.common.main.ts"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_product_brand_is_pulseai_ide():
    product = json.loads((DESKTOP / "product.json").read_text(encoding="utf-8"))
    assert product["nameShort"] == "PulseAI"
    assert product["nameLong"] == "PulseAI IDE"
    assert product["applicationName"] == "pulseai"
    assert product["dataFolderName"] == ".pulseai-ide"


def test_pulse_is_registered_once_as_a_workbench_contribution():
    text = MAIN.read_text(encoding="utf-8")
    registration = "import './contrib/pulseai/browser/pulseAI.contribution.js';"
    assert text.count(registration) == 1
    contrib_files = list(CONTRIB.rglob("*.ts"))
    assert contrib_files
    assert any(path.name == "pulseAI.contribution.ts" for path in contrib_files)
    assert not (DESKTOP / "extensions" / "pulseai").exists()


def test_pulse_menu_and_view_commands_are_declared():
    text = (CONTRIB / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "MenuId.MenubarMainMenu" in text
    assert "MenubarPulseAI" in text
    for command in (
        "NewSession", "OpenManager", "ReviewChanges", "OpenCheckpoints",
        "StopActiveRun", "OpenSettings",
    ):
        assert f"PulseAICommandId.{command}" in text
    assert "ViewContainerLocation.Sidebar" in text
    assert "new SyncDescriptor(PulseAIViewPane)" in text
    assert "registerEditorPane" in text
    assert "PulseAIManagerEditor" in text
    assert "PulseAIManagerInputSerializer" in text
    assert "openEditor(input, { pinned: true })" in text


def test_selective_manifest_matches_overlay_files():
    manifest = json.loads((DESKTOP / "SELECTIVE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["upstream_commit"] == (DESKTOP / "UPSTREAM_PIN").read_text().strip()
    for rel, receipt in manifest["files"].items():
        assert _sha(DESKTOP / rel) == receipt["overlay_sha256"]
        assert receipt["modified"] is True


def test_selective_desktop_has_no_full_checkout_artifacts():
    assert not (DESKTOP / ".git").exists()
    assert not (DESKTOP / "node_modules").exists()
    assert not (DESKTOP / "extensions").exists()
    build_files = [path.relative_to(DESKTOP).as_posix() for path in (DESKTOP / "build").rglob("*") if path.is_file()]
    assert build_files == ["build/buildfile.ts"]
    size = sum(path.stat().st_size for path in DESKTOP.rglob("*") if path.is_file())
    assert size < 1_000_000, f"selective desktop unexpectedly grew to {size:,} bytes"

"""Pins for PulseAI IDE identity, platform assets, and theme-aware chrome."""
from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
BRANDING = ROOT / "branding"
PULSE = DESKTOP / "src" / "vs" / "workbench" / "contrib" / "pulseai"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_canonical_mark_and_generated_platform_assets_exist():
    mark = (BRANDING / "pulseai-mark.svg").read_text(encoding="utf-8")
    assert "PulseAI IDE mark" in mark
    assert "#22D3EE" in mark
    assert "#9B8CFF" in mark
    assert "M164 536H292L372 306L486 746L584 382L672 552H860" in mark

    assert _png_size(DESKTOP / "resources" / "linux" / "code.png") == (512, 512)
    assert _png_size(DESKTOP / "resources" / "server" / "code-192.png") == (192, 192)
    assert _png_size(DESKTOP / "resources" / "server" / "code-512.png") == (512, 512)
    assert _png_size(DESKTOP / "resources" / "win32" / "code_150x150.png") == (150, 150)
    assert _png_size(DESKTOP / "resources" / "win32" / "code_70x70.png") == (70, 70)
    assert (DESKTOP / "resources" / "win32" / "code.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert (DESKTOP / "resources" / "darwin" / "code.icns").read_bytes()[:4] == b"icns"


def test_brand_asset_manifest_is_complete():
    manifest = json.loads((DESKTOP / "SELECTIVE_MANIFEST.json").read_text(encoding="utf-8"))
    assert set(manifest["brand_assets"]) == {
        "resources/darwin/code.icns",
        "resources/linux/code.png",
        "resources/server/code-192.png",
        "resources/server/code-512.png",
        "resources/server/favicon.ico",
        "resources/win32/code.ico",
        "resources/win32/code_150x150.png",
        "resources/win32/code_70x70.png",
        "resources/pulseai/pulseai-mark.svg",
    }
    replaced = [value for value in manifest["brand_assets"].values() if value["replaces_upstream"]]
    assert len(replaced) == 8


def test_pulse_chrome_is_a_theme_aware_default_not_forced_global_css():
    branding = (PULSE / "browser" / "pulseAIBranding.ts").read_text(encoding="utf-8")
    contribution = (PULSE / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "registerDefaultConfigurations" in branding
    assert "'workbench.colorCustomizations'" in branding
    assert "'[Dark 2026]'" in branding
    assert "'[Light 2026]'" in branding
    assert "'activityBar.activeBorder': '#22D3EE'" in branding
    assert "'statusBar.background': '#0B3942'" in branding
    assert "High Contrast" not in branding
    assert "import './pulseAIBranding.js';" in contribution


def test_product_identifiers_no_longer_ship_as_code_oss():
    product = json.loads((DESKTOP / "product.json").read_text(encoding="utf-8"))
    for key in (
        "serverApplicationName", "serverDataFolderName", "tunnelApplicationName",
        "win32DirName", "win32NameVersion", "win32RegValueName",
        "win32AppUserModelId", "win32ShellNameShort", "darwinBundleIdentifier",
        "linuxIconName", "urlProtocol", "agentsTelemetryAppName",
    ):
        assert "code-oss" not in product[key].lower()
        assert "microsoft code oss" not in product[key].lower()

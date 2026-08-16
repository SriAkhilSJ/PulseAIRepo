"""Pins for PulseAI IDE identity, platform assets, and native-neutral chrome.

Approved direction: the IDE chrome stays VS Code Dark 2026 native-neutral;
Pulse contributes semantic colors only (never global workbench chrome).
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
FORK = DESKTOP / "vscode"
BRANDING = ROOT / "branding"
PULSE = FORK / "src" / "vs" / "workbench" / "contrib" / "pulseai"


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

    assert _png_size(FORK / "resources" / "linux" / "code.png") == (512, 512)
    assert _png_size(FORK / "resources" / "server" / "code-192.png") == (192, 192)
    assert _png_size(FORK / "resources" / "server" / "code-512.png") == (512, 512)
    assert _png_size(FORK / "resources" / "win32" / "code_150x150.png") == (150, 150)
    assert _png_size(FORK / "resources" / "win32" / "code_70x70.png") == (70, 70)
    assert (FORK / "resources" / "win32" / "code.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert (FORK / "resources" / "darwin" / "code.icns").read_bytes()[:4] == b"icns"


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


def test_no_global_workbench_chrome_recoloring():
    """The global cyan/navy workbench theme is removed; chrome is native Dark 2026."""
    contribution = (PULSE / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    # The branding module is deleted and must not be imported.
    assert not (PULSE / "browser" / "pulseAIBranding.ts").exists()
    assert "import './pulseAIBranding.js';" not in contribution

    # No workbench color defaults may be registered anywhere in the contribution.
    for source in (PULSE / "browser").rglob("*.ts"):
        text = source.read_text(encoding="utf-8")
        assert "registerDefaultConfigurations" not in text, source
        assert "workbench.colorCustomizations" not in text, source

    # No global chrome overrides: title bar, Activity Bar, status bar, editor.
    css = (PULSE / "browser" / "media" / "pulseAI.css").read_text(encoding="utf-8")
    for global_selector in (".monaco-workbench", "titleBar", "activityBar", "statusBar"):
        assert global_selector not in css, f"global chrome override leaked: {global_selector}"


def test_pulse_semantic_colors_remain_but_never_as_large_chrome():
    tokens = (PULSE / "browser" / "media" / "pulseAI-tokens.css").read_text(encoding="utf-8")
    for semantic in ("#22d3ee", "#9b8cff", "#49d190", "#efb75c", "#ed727c"):
        assert semantic in tokens
    # The tokens file may only carry Pulse semantic variables, never workbench chrome.
    for chrome_key in ("titleBar", "activityBar", "statusBar", "sideBar.background"):
        assert chrome_key not in tokens

    # High-contrast and user themes stay authoritative: no hardcoded overrides.
    assert "High Contrast" not in tokens


def test_product_identifiers_no_longer_ship_as_code_oss():
    product = json.loads((FORK / "product.json").read_text(encoding="utf-8"))
    for key in (
        "serverApplicationName", "serverDataFolderName", "tunnelApplicationName",
        "win32DirName", "win32NameVersion", "win32RegValueName",
        "win32AppUserModelId", "win32ShellNameShort", "darwinBundleIdentifier",
        "linuxIconName", "urlProtocol", "agentsTelemetryAppName",
    ):
        assert "code-oss" not in product[key].lower()
        assert "microsoft code oss" not in product[key].lower()
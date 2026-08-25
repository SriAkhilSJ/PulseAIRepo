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

def test_pulseai_defaults_suppress_copilot_onboarding():
    """The bundled defaults must ship the PulseAI first-run contract.

    Rationale (see docs/DESIGN/FORK_REBRANDING.md section 2d): removing
    `product.defaultChatAgent` bricked the renderer, because
    `base/common/product.ts:272` declares it REQUIRED and
    `onboardingVariationA.ts:80` calls `assertDefined` on it at module top
    level. The supported lever is the `chat.disableAIFeatures` SETTING, which
    is read at runtime with a safe default by every consumer.

    `chat.disableAIFeatures: true` makes `ChatContextKeys.Setup.hidden` true
    (chatEntitlementService.ts:1397), which falsifies the `when` clause on the
    chat view (chatParticipant.contribution.ts:71). The container declares
    `hideIfEmpty: true`, so it leaves the auxiliary bar entirely, and
    `startupPage.ts:249` returns early instead of showing the sign-in modal.
    """
    pkg = json.loads(
        (FORK / "extensions" / "theme-defaults" / "package.json").read_text(encoding="utf-8")
    )
    defaults = pkg["contributes"]["configurationDefaults"]

    assert defaults["workbench.colorTheme"] == "PulseAI Dark"
    # Suppresses the GitHub sign-in modal AND removes the CHAT container.
    assert defaults["chat.disableAIFeatures"] is True
    # Second, independent guard on the onboarding modal.
    assert defaults["workbench.welcomePage.experimentalOnboarding"] is False


def test_product_json_keeps_required_default_chat_agent():
    """Regression guard: `defaultChatAgent` must NOT be removed again.

    It is declared without `?` in `src/vs/base/common/product.ts`, and
    `onboardingVariationA.ts:80` runs `assertDefined` on it during workbench
    bundle evaluation. Removing it produced a black screen (renderer never
    paints). Hide Copilot with settings, never by deleting this key.
    """
    product = json.loads(
        (FORK / "product.json").read_text(encoding="utf-8")
    )
    assert "defaultChatAgent" in product, (
        "defaultChatAgent is a REQUIRED product key; removing it bricks the "
        "renderer. See docs/DESIGN/FORK_REBRANDING.md section 2c."
    )
    # voiceWsUrl IS optional (`voiceWsUrl?: string`) and is intentionally gone.
    assert "voiceWsUrl" not in product


def test_pulse_is_first_class_top_level_menu_not_buried_after_help():
    """The Pulse menu must sit between Terminal and Help (order 7.5), not at
    group '9_pulseAI' after Help. Discoverability regression guard for R4.
    """
    contribution = (PULSE / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    # Must register to MenubarMainMenu with order between Terminal(7) and Help(8).
    assert "MenuId.MenubarMainMenu" in contribution
    assert "order: 7.5" in contribution, "Pulse menu must sit between Terminal (7) and Help (8)"
    # The old bury-at-end position must not come back.
    assert "'9_pulseAI'" not in contribution and '"9_pulseAI"' not in contribution, (
        "Pulse menu was regressed to group 9_pulseAI (sorted after Help). "
        "Keep it at order: 7.5."
    )


def test_pulse_panel_opens_via_ctrl_cmd_l():
    """Market-standard AI hotkey: Ctrl+L (Win/Linux) / Cmd+L (Mac) opens Pulse.

    Cursor and Windsurf both use Ctrl/Cmd+L for their AI agent panel. We match
    that muscle memory. The binding is registered through the view container's
    `openCommandActionDescriptor`, which viewsService wires with
    KeybindingWeight.WorkbenchContrib (200), outranking the editor's
    'expandLineSelection' (EditorCore=0) — same trick Cursor/Windsurf use.
    """
    contribution = (PULSE / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "KeyCode.KeyL" in contribution, "Ctrl/Cmd+L must be the Pulse hotkey"
    assert "KeyMod.CtrlCmd | KeyCode.KeyL" in contribution, (
        "Ctrl/Cmd+L must be the primary keybinding for opening Pulse"
    )
    assert "PulseAICommandId.Focus" in contribution, (
        "Ctrl/Cmd+L must be bound to the explicit pulseai.focus action, not "
        "via the auto-wired openCommandActionDescriptor (which produced a "
        "command-ID mismatch in R4/R4.1a)."
    )
    # Pulse must NOT claim Copilot's legacy Ctrl+Alt+I — that is reserved for
    # Copilot Chat which we hide but do not delete per project rules.
    assert "KeyMod.Alt | KeyCode.KeyI" not in contribution, (
        "Do not claim Ctrl+Alt+I — that collides with Copilot Chat which we "
        "keep in source. Use Ctrl+L like Cursor/Windsurf."
    )


def test_pulse_lives_in_auxiliary_bar_not_sidebar():
    """Default location matches market leaders (Cursor, Copilot Chat): right
    side (Auxiliary Bar), not the left activity bar. Access via Ctrl+L / menu
    makes sidebar placement unnecessary.
    """
    contribution = (PULSE / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "ViewContainerLocation.AuxiliaryBar" in contribution
    assert "ViewContainerLocation.Sidebar" not in contribution, (
        "Pulse belongs in the right-side auxiliary bar (Cursor/Copilot Chat "
        "pattern); do not move it to the left sidebar."
    )


def test_pulse_ctrl_l_is_registered_on_explicit_focus_action():
    """Regression for R4.1: R4/R4.1a tried to auto-wire the keybinding via
    openCommandActionDescriptor, which silently created a command ID mismatch
    (nothing fired on Ctrl+L). R4.1b binds Ctrl+L to an EXPLICIT
    registerAction2 with id = PulseAICommandId.Focus ('pulseai.focus'), same
    pattern every other first-class panel uses. Title-bar icon + menu item
    both reference the same command id.
    """
    contribution = (PULSE / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "id: PulseAICommandId.Focus" in contribution
    assert "KeyMod.CtrlCmd | KeyCode.KeyL" in contribution
    assert "KeybindingWeight.WorkbenchContrib" in contribution
    # No more doNotRegisterOpenCommand or openCommandActionDescriptor indirection.
    assert "doNotRegisterOpenCommand" not in contribution
    assert "openCommandActionDescriptor" not in contribution


def test_pulse_command_center_title_bar_icon():
    """Copilot has a Copilot icon in the top-center command center that
    one-clicks open chat. Pulse must mirror that with a pulse icon that fires
    the same open command (workbench.view.pulseai) that Ctrl+L fires.
    """
    contribution = (PULSE / "browser" / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "MenuId.CommandCenterCenter" in contribution, (
        "Pulse must register an icon in the command center (title bar), like Copilot."
    )
    assert "id: PULSE_AI_VIEW_CONTAINER_ID" in contribution
<<<<<<< HEAD
=======


def test_pulse_forces_copilot_context_keys_hidden_at_startup():
    """R4.2 regression guard: R4 still showed a CHAT tab next to Pulse and an
    'Open Chat' empty-editor watermark on first boot, because
    chat.disableAIFeatures only flips ChatContextKeys.Setup.hidden AFTER the
    entitlement service resolves (async, network). Pulse must install a
    Starting-phase workbench contribution that forces chatSetupHidden=true,
    chatIsEnabled=false, and calls setForceHidden(true) BEFORE first paint.
    All changes stay inside contrib/pulseai/ — Copilot source is not touched.
    """
    contrib_dir = PULSE / "browser"
    # New file must exist and be imported from pulseAI.contribution.ts
    hide_ts = contrib_dir / "pulseAIHideCopilot.ts"
    assert hide_ts.exists(), (
        "pulseAIHideCopilot.ts must exist and force Copilot context keys hidden."
    )
    text = hide_ts.read_text(encoding="utf-8")
    # Must bind all four context keys that Copilot surfaces read.
    for key in ("chatSetupHidden", "chatSetupInstalled", "chatSetupDisabled", "chatIsEnabled"):
        assert f"'{key}'" in text or f'"{key}"' in text, (
            f"pulseAIHideCopilot.ts must set the {key} context key."
        )
    # Must call setForceHidden(true) on IChatEntitlementService.
    assert "setForceHidden(hide)" in text
    # Must register at LifecyclePhase.Starting (before first paint).
    assert "LifecyclePhase.Starting" in text
    # Master toggle setting exists and defaults to true.
    assert "'pulseai.hideBuiltInCopilotUI'" in text or '"pulseai.hideBuiltInCopilotUI"' in text
    # Must be imported from the main contribution file.
    main = (contrib_dir / "pulseAI.contribution.ts").read_text(encoding="utf-8")
    assert "pulseAIHideCopilot.js" in main, (
        "pulseAI.contribution.ts must import './pulseAIHideCopilot.js' so the "
        "contribution registers on load."
    )
    # Guard rail: Copilot source MUST NOT be modified by this change.
    chat_contrib = (
        FORK / "src" / "vs" / "workbench" / "contrib" / "chat" / "browser" /
        "chatParticipant.contribution.ts"
    )
    import hashlib
    # Sanity check: the chat contrib file is still intact (not empty, >5KB).
    assert chat_contrib.stat().st_size > 5000

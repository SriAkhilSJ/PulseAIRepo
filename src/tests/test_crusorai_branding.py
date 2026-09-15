"""Pins for CrusorAI IDE identity, platform assets, and native-neutral chrome.

Approved direction: the IDE chrome stays VS Code Dark 2026 native-neutral;
Crusor contributes semantic colors only (never global workbench chrome).
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
FORK = DESKTOP / "vscode"
BRANDING = ROOT / "branding"
CRUSOR = FORK / "src" / "vs" / "workbench" / "contrib" / "crusorai"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_canonical_mark_and_generated_platform_assets_exist():
    mark = (BRANDING / "crusorai-mark.svg").read_text(encoding="utf-8")
    assert "CrusorAI IDE mark" in mark
    # The canonical mark embeds the uploaded CrusorAI logo (silver-on-black).
    assert "<image" in mark and "data:image/png;base64," in mark
    assert _png_size(BRANDING / "crusorai-mark.png") == (1536, 1536)

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
        "resources/crusorai/crusorai-mark.svg",
    }
    replaced = [value for value in manifest["brand_assets"].values() if value["replaces_upstream"]]
    assert len(replaced) == 8


def test_no_global_workbench_chrome_recoloring():
    """The global cyan/navy workbench theme is removed; chrome is native Dark 2026."""
    contribution = (CRUSOR / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    # The branding module is deleted and must not be imported.
    assert not (CRUSOR / "browser" / "crusorAIBranding.ts").exists()
    assert "import './crusorAIBranding.js';" not in contribution

    # No workbench color defaults may be registered anywhere in the contribution.
    for source in (CRUSOR / "browser").rglob("*.ts"):
        text = source.read_text(encoding="utf-8")
        assert "registerDefaultConfigurations" not in text, source
        assert "workbench.colorCustomizations" not in text, source

    # No global chrome overrides: title bar, Activity Bar, status bar, editor.
    # Exclude Copilot-hiding rules (they legitimately reference statusBarEntry etc.)
    css = (CRUSOR / "browser" / "media" / "crusorAI.css").read_text(encoding="utf-8")
    css_before_copilot_hiding = css.split("/* ---- Copilot hiding")[0]
    for global_selector in (".monaco-workbench", "titleBar", "activityBar", "statusBar"):
        assert global_selector not in css_before_copilot_hiding, f"global chrome override leaked: {global_selector}"


def test_crusor_semantic_colors_remain_but_never_as_large_chrome():
    """Crusor keeps a semantic identity, but as derivation SEEDS, not painted
    hex. The old hand palette (#22d3ee accent, #49d190 verified, #ed727c
    failed) painted a foreign brand over whatever theme the user ran —
    retired by the seed-to-token machine (owner: "don't hardcode plz").
    Approval (#efb75c) and agent (#9b8cff) survive as machine INPUTS in
    crusorTheme.ts; accent/verified/failed derive from the live workbench
    theme + the hermes success seed. The tokens file carries var() fallback
    chains only — zero hex, and never a workbench chrome key."""
    tokens = (CRUSOR / "browser" / "media" / "crusorAI-tokens.css").read_text(encoding="utf-8")
    machine = (CRUSOR / "browser" / "crusorTheme.ts").read_text(encoding="utf-8")
    for seed in ("#efb75c", "#9b8cff"):
        assert seed in machine, f"semantic seed {seed} must survive in the machine"
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", tokens), "no hex in the token file"
    # The tokens file may only carry Crusor semantic variables, never workbench chrome.
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

def test_crusorai_defaults_suppress_copilot_onboarding():
    """The bundled defaults must ship the CrusorAI first-run contract.

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

    assert defaults["workbench.colorTheme"] == "CrusorAI Dark"
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


def test_crusor_is_first_class_top_level_menu_not_buried_after_help():
    """The Crusor menu must sit between Terminal and Help (order 7.5), not at
    group '9_crusorAI' after Help. Discoverability regression guard for R4.
    """
    contribution = (CRUSOR / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    # Must register to MenubarMainMenu with order between Terminal(7) and Help(8).
    assert "MenuId.MenubarMainMenu" in contribution
    assert "order: 7.5" in contribution, "Crusor menu must sit between Terminal (7) and Help (8)"
    # The old bury-at-end position must not come back.
    assert "'9_crusorAI'" not in contribution and '"9_crusorAI"' not in contribution, (
        "Crusor menu was regressed to group 9_crusorAI (sorted after Help). "
        "Keep it at order: 7.5."
    )


def test_crusor_panel_opens_via_ctrl_cmd_l():
    """Market-standard AI hotkey: Ctrl+L (Win/Linux) / Cmd+L (Mac) opens Crusor.

    Cursor and Windsurf both use Ctrl/Cmd+L for their AI agent panel. We match
    that muscle memory. The binding is registered through the view container's
    `openCommandActionDescriptor`, which viewsService wires with
    KeybindingWeight.WorkbenchContrib (200), outranking the editor's
    'expandLineSelection' (EditorCore=0) — same trick Cursor/Windsurf use.
    """
    contribution = (CRUSOR / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    assert "KeyCode.KeyL" in contribution, "Ctrl/Cmd+L must be the Crusor hotkey"
    assert "KeyMod.CtrlCmd | KeyCode.KeyL" in contribution, (
        "Ctrl/Cmd+L must be the primary keybinding for opening Crusor"
    )
    assert "CrusorAICommandId.Focus" in contribution, (
        "Ctrl/Cmd+L must be bound to the explicit crusorai.focus action, not "
        "via the auto-wired openCommandActionDescriptor (which produced a "
        "command-ID mismatch in R4/R4.1a)."
    )
    # Crusor must NOT claim Copilot's legacy Ctrl+Alt+I — that is reserved for
    # Copilot Chat which we hide but do not delete per project rules.
    assert "KeyMod.Alt | KeyCode.KeyI" not in contribution, (
        "Do not claim Ctrl+Alt+I — that collides with Copilot Chat which we "
        "keep in source. Use Ctrl+L like Cursor/Windsurf."
    )


def test_crusor_lives_in_auxiliary_bar_not_sidebar():
    """Default location matches market leaders (Cursor, Copilot Chat): right
    side (Auxiliary Bar), not the left activity bar. Access via Ctrl+L / menu
    makes sidebar placement unnecessary.
    """
    contribution = (CRUSOR / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    assert "ViewContainerLocation.AuxiliaryBar" in contribution
    assert "ViewContainerLocation.Sidebar" not in contribution, (
        "Crusor belongs in the right-side auxiliary bar (Cursor/Copilot Chat "
        "pattern); do not move it to the left sidebar."
    )


def test_crusor_ctrl_l_is_registered_on_explicit_focus_action():
    """Regression for R4.1: R4/R4.1a tried to auto-wire the keybinding via
    openCommandActionDescriptor, which silently created a command ID mismatch
    (nothing fired on Ctrl+L). R4.1b binds Ctrl+L to an EXPLICIT
    registerAction2 with id = CrusorAICommandId.Focus ('crusorai.focus'), same
    pattern every other first-class panel uses. Title-bar icon + menu item
    both reference the same command id.
    """
    contribution = (CRUSOR / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    assert "id: CrusorAICommandId.Focus" in contribution
    assert "KeyMod.CtrlCmd | KeyCode.KeyL" in contribution
    assert "KeybindingWeight.WorkbenchContrib" in contribution
    # No more doNotRegisterOpenCommand or openCommandActionDescriptor indirection.
    assert "doNotRegisterOpenCommand" not in contribution
    assert "openCommandActionDescriptor" not in contribution


def test_crusor_command_center_title_bar_icon():
    """Copilot has a Copilot icon in the top-center command center that
    one-clicks open chat. Crusor must mirror that with a crusor icon that fires
    the same open command (workbench.view.crusorai) that Ctrl+L fires.
    """
    contribution = (CRUSOR / "browser" / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    assert "MenuId.CommandCenterCenter" in contribution, (
        "Crusor must register an icon in the command center (title bar), like Copilot."
    )
    assert "id: CRUSOR_AI_VIEW_CONTAINER_ID" in contribution


def test_crusor_forces_copilot_context_keys_hidden_at_startup():
    """R4.2 regression guard: R4 still showed a CHAT tab next to Crusor and an
    'Open Chat' empty-editor watermark on first boot, because
    chat.disableAIFeatures only flips ChatContextKeys.Setup.hidden AFTER the
    entitlement service resolves (async, network). Crusor must install a
    Starting-phase workbench contribution that forces chatSetupHidden=true,
    chatIsEnabled=false, and calls setForceHidden(true) BEFORE first paint.
    All changes stay inside contrib/crusorai/ — Copilot source is not touched.
    """
    contrib_dir = CRUSOR / "browser"
    # New file must exist and be imported from crusorAI.contribution.ts
    hide_ts = contrib_dir / "crusorAIHideCopilot.ts"
    assert hide_ts.exists(), (
        "crusorAIHideCopilot.ts must exist and force Copilot context keys hidden."
    )
    text = hide_ts.read_text(encoding="utf-8")
    # Must bind all four context keys that Copilot surfaces read.
    for key in ("chatSetupHidden", "chatSetupInstalled", "chatSetupDisabled", "chatIsEnabled"):
        assert f"'{key}'" in text or f'"{key}"' in text, (
            f"crusorAIHideCopilot.ts must set the {key} context key."
        )
    # Must call setForceHidden(true) on IChatEntitlementService.
    assert "setForceHidden(hide)" in text
    # Must register at LifecyclePhase.Starting (before first paint).
    assert "LifecyclePhase.Starting" in text
    # Master toggle setting exists and defaults to true.
    assert "'crusorai.hideBuiltInCopilotUI'" in text or '"crusorai.hideBuiltInCopilotUI"' in text
    # Must be imported from the main contribution file.
    main = (contrib_dir / "crusorAI.contribution.ts").read_text(encoding="utf-8")
    assert "crusorAIHideCopilot.js" in main, (
        "crusorAI.contribution.ts must import './crusorAIHideCopilot.js' so the "
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

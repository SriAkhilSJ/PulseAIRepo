"""Structural pins for the shared native Pulse Agent / Manager renderer."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PULSE = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "pulseai"
UI = ROOT / "ui" / "src"


def _text(*parts: str) -> str:
    return PULSE.joinpath(*parts).read_text(encoding="utf-8")


def _catalog_names(text: str) -> set[str]:
    return set(re.findall(r"^\s*([a-z_]+): tool\(", text, re.MULTILINE))


def test_agent_and_manager_mount_one_shared_renderer_service():
    view = _text("browser", "pulseAIViewPane.ts")
    manager = _text("browser", "pulseAIManagerEditor.ts")
    registration = _text("browser", "pulseAI.contribution.ts")
    assert "pulseAIRendererService.mount(root, 'agent')" in view
    assert "pulseAIRendererService.mount(this.root, 'manager')" in manager
    assert "registerSingleton(IPulseAIRendererService, PulseAIRendererService" in registration
    assert "boot-status" not in view
    assert "boot-main" not in manager


def test_renderer_boundary_is_browser_safe_and_text_only():
    renderer = _text("browser", "pulseAIRenderer.ts")
    service = _text("browser", "pulseAIRendererService.ts")
    for source in (renderer, service):
        assert "node:" not in source
        assert "electron-browser/" not in source
        assert ".innerHTML" not in source
    assert "IPulseAIEngineService" in service
    assert "IPulseAIWorkbenchService" in service
    assert "onDidReceiveFrame" in service
    assert "PulseClientMethod" in service
    assert "openNativeDiff" in service
    assert "openInlineDiff" in service
    assert "old_text" in service and "new_text" in service
    assert "session_resume" in service
    assert "events_replay" in service
    assert "rememberEvent" in service
    assert "cancelRequested" in service
    assert "frame.cancel_requested" in service
    assert "Stopping." in renderer
    assert "Run cancelled" in renderer
    assert "frame.completed ? 'completed' : 'cancelled'" in service
    assert "scheduleRestart" in service
    assert "restartAttempts >= 3" in service
    assert "requestAnimationFrame" in service
    assert "preventScroll: true" in renderer
    assert "wasNearBottom" in renderer
    assert "Review change" in renderer


def test_web_fallback_and_desktop_override_share_the_engine_contract():
    common = _text("browser", "pulseAI.contribution.ts")
    fallback = _text("browser", "pulseAIUnavailableEngineService.ts")
    desktop = _text("electron-browser", "pulseAI.desktop.contribution.ts")
    assert "registerSingleton(IPulseAIEngineService, PulseAIUnavailableEngineService" in common
    assert "registerSingleton(IPulseAIEngineService, PulseAIEngineService" in desktop
    assert "child_process" not in fallback
    assert "PulseAIEngineState.Degraded" in fallback


def test_native_and_lab_catalogs_cover_the_same_36_tools():
    native = _catalog_names(_text("common", "pulseAIToolCatalog.ts"))
    lab = _catalog_names((UI / "runtime" / "toolCatalog.ts").read_text(encoding="utf-8"))
    assert len(native) == 36
    assert native == lab


def test_renderer_gates_sessions_on_an_open_project_folder():
    service = _text("browser", "pulseAIRendererService.ts")
    assert "Open a folder to start a Pulse session." in service
    assert "if (!workspace) {" in service
    assert "session_create', workspace" in service
    assert "start(workspace).then" in service
    assert "Open a workspace or configure pulseai.engineRoot" not in service


def test_terminal_disclosure_has_bounded_output_and_completion_evidence():
    renderer = _text("browser", "pulseAIRenderer.ts")
    for receipt in (
        "function boundedText", "earlier characters omitted", "terminal-command",
        "terminal-output", "exitCode", "duration", "Copy command", "Reveal location",
    ):
        assert receipt in renderer


def test_agent_layout_keeps_progressive_disclosure_and_stable_docks_native():
    renderer = _text("browser", "pulseAIRenderer.ts")
    css = _text("browser", "media", "pulseAI.css")
    for behavior in (
        "function planStrip", "function workingDock", "function emptyState",
        "pulseai-section-heading", "host.submitPrompt(prompt)", "planOpen",
    ):
        assert behavior in renderer
    assert "openManager(): void" in renderer
    assert "executeCommand(PulseAICommandId.OpenManager)" in _text("browser", "pulseAIRendererService.ts")
    for style in (
        ".pulseai-starter-grid", ".pulseai-working-dock", ".pulseai-plan-strip",
        "prefers-reduced-motion", "@media (max-width: 420px)",
        "var(--vscode-focusBorder)", "var(--vscode-sideBar-background)",
    ):
        assert style in css
    assert "kilocode" not in renderer.lower()
    assert "kilocode" not in css.lower()

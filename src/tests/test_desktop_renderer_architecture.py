"""Structural pins for the shared native Pulse Agent / Manager renderer."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PULSE = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "pulseai"
UI = ROOT / "ui" / "src"   # not tracked in this repo; see the skip in the catalog pin


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
    if not UI.is_dir():
        pytest.skip(
            f"{UI.relative_to(ROOT)} is not present in this checkout: the lab catalog this "
            "compares against lives in a tree the repo does not track. Skip is honest; a "
            "silent pass would mean the pin compared nothing."
        )
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
    # Manager's popup-vs-tab routing is a deferred owner decision, so that assertion lives
    # in its own strict-xfail test at the bottom of this file: the Agent-UI lane must not
    # be blocked by a choice the owner has not made, and the choice cannot be made quietly.
    # Activity runs, not a flat list: both transcript branches fold through the shared rule.
    assert "toolSection(" in renderer
    assert renderer.count("lane.append(toolSection(") == 2, "both transcript branches group; none stays a flat list"
    assert "dataset.component = 'tool-run'" in renderer and "dataset.runKey = key" in renderer
    assert "runLive = live && runTools.some(tool => tool.state === 'running'" in renderer, \
        "a settled turn must not narrate in the present tense"
    for style in (
        ".pulseai-starter-grid", ".pulseai-working-dock", ".pulseai-plan-strip",
        "prefers-reduced-motion", "@media (max-width: 420px)",
        "container-name: pulseai-manager-editor", "@container pulseai-manager-editor (max-width: 610px)",
        "var(--vscode-focusBorder)", "var(--vscode-sideBar-background)",
    ):
        assert style in css
    assert "kilocode" not in renderer.lower()
    assert "kilocode" not in css.lower()


def test_execution_mode_picker_is_functional_and_theme_driven():
    renderer = _text("browser", "pulseAIRenderer.ts")
    service = _text("browser", "pulseAIRendererService.ts")
    protocol = _text("common", "pulseAIProtocol.ts")
    generated = _text("common", "pulseAIProtocol.generated.ts")
    css = _text("browser", "media", "pulseAI.css")
    for mode in ("agent", "plan", "debug", "ask"):
        assert f"id: '{mode}'" in renderer
        assert f"'{mode}'" in generated
    assert "setMode(mode: PulseExecutionMode)" in renderer
    assert "readonly mode?: PulseExecutionMode" in protocol
    assert "mode: this.mode" in service
    assert "this.send({ type: 'prompt'" in service
    assert ".pulseai-mode-menu" in css
    for token in ("--vscode-menu-background", "--vscode-menu-foreground", "--vscode-focusBorder"):
        assert token in css
    assert "#071118" not in css
    assert "#061115" not in css


def test_copilot_webview_host_is_a_setting_and_fails_loudly():
    """The CopilotKit iframe used to hardcode `http://localhost:5173` at a fixed 50%.

    That is only reachable when someone happens to have `npm run dev` open on that
    port: a packaged build, a remote window (where `localhost` is the client), a
    taken port, or just forgetting the dev server all render an empty frame with no
    explanation -- and the native renderer above it still surrenders half the pane.
    So: URL/enabled/height are settings, and an unreachable URL says so in the pane.
    """
    view = _text("browser", "pulseAIViewPane.ts")
    contribution = _text("browser", "pulseAI.contribution.ts")
    for key in ("pulseai.copilotWebview.enabled", "pulseai.copilotWebview.url", "pulseai.copilotWebview.height"):
        assert key in view, f"{key} must be read by the pane"
        assert f"'{key}'" in contribution, f"{key} must be declared, not merely read"
    # The default may exist only as a named constant -- never inline on the element,
    # which is what made it unconfigurable in the first place.
    assert "setAttribute('src', 'http://localhost:5173')" not in view
    assert "const DEFAULT_COPILOT_WEBVIEW_URL = 'http://localhost:5173'" in view
    assert "frame.setAttribute('src', url)" in view
    # Off means off: the iframe must not be built at all, so the native renderer
    # gets the whole pane instead of 50% of it.
    disabled_guard = view.index("copilotWebview.enabled') === false")
    assert "return;" in view[disabled_guard:disabled_guard + 200]
    # And a dead URL is a message, not a blank rectangle.
    assert "pulseai-copilot-unreachable" in view
    assert "npm run dev" in view
    # The load event is the only honest success signal, so the watchdog is cancelled
    # on dispose rather than left to fire into torn-down DOM.
    assert "watchdog.cancel()" in view


def test_approval_dock_offers_every_scope_the_protocol_carries():
    """`always_allow` was plumbed end to end and unreachable from the UI.

    `PulseAIRenderHost.replyToSafety(toolId, approved, alwaysAllow?)` ->
    `safety_reply { always_allow }` -> `src/bridge/__main__.py:552` ->
    `EventBus.resolve_approval(..., always_allow)`. The dock sent only true/false,
    so every ordinary write re-prompted for the rest of the session even though a
    session grant existed. The third argument must be used, and the two grants must
    be labelled as different things.
    """
    renderer = _text("browser", "pulseAIRenderer.ts")
    css = _text("browser", "media", "pulseAI.css")
    assert "host.replyToSafety(approval.toolId, true, true)" in renderer
    assert "'Allow for session'" in renderer
    assert "'Allow once'" in renderer
    assert "'Deny'" in renderer
    # Every decision carries an icon and a hint: a bare word on a button is how
    # "Allow" and "Allow always" get clicked by mistake.
    assert ".pulseai-button-allow" in css and ".pulseai-button-deny" in css
    assert "control.title = hint" in renderer
    # Green/red are token-derived, never literals, so both product themes stay legible.
    assert "--vscode-testing-iconPassed" in css
    assert "--vscode-testing-iconFailed" in css
    assert "--vscode-diffEditor-insertedTextBackground" in css
    assert "--vscode-diffEditor-removedTextBackground" in css


def test_file_write_rows_report_counted_values_not_placeholders():
    """Two rows in the file-write card were invented: `+12 −4` and "syntax valid".

    A number the user cannot distinguish from a real measurement is worse than a
    blank, because it teaches them to skim the card. Line counts are now counted from
    the diff that arrived, and the receipt row only appears when the tool reported
    one.
    """
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "'+12 −4'" not in renderer
    assert "['Receipt', 'syntax valid']" not in renderer
    assert "export function diffStats" in renderer
    assert "stats ? `+${stats.added} −${stats.removed}`" in renderer
    # Diff lines are per-line nodes so green/red can exist at all -- the old
    # single <pre> could only be tinted as one block -- and the clamp is bounded for
    # paint while saying what it hid.
    assert "pulseai-diff-line" in renderer
    assert "is-truncated" in renderer
    css = _text("browser", "media", "pulseAI.css")
    assert ".pulseai-diff-line.is-added" in css
    assert ".pulseai-diff-line.is-removed" in css


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFERRED BY OWNER (2026-09-02: 'don't touch manager UI / for / now'). The in-pane "
        "Manager button reaches PulseAIRendererService via host.openManager() "
        "(pulseAIRenderer.ts:657 -> pulseAIRendererService.ts:129), which calls "
        "openManagerWindow() (:325) and hand-builds an auxiliary-window root classed "
        "`pulseai-manager-editor`; the pulseai.openManager command instead opens the registered "
        "PulseAIManagerEditor, whose DOM carries `.pulseai-manager-shell` -- the selector "
        "scripts/validate_pulse_ui_cdp.js:218-239 waits for. Un-mark this test when the button is "
        "routed through the command; strict=True means fixing it without saying so fails here."
    ),
)
def test_manager_opens_through_one_path_pending_owner_decision():
    service = _text("browser", "pulseAIRendererService.ts")
    assert "executeCommand(PulseAICommandId.OpenManager)" in service

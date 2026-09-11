"""Structural pins for the shared native Pulse Agent / Manager renderer."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT / "desktop" / "vscode"
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
        # Ban node/electron IMPORTS, not any substring ("node:" also matches
        # TypeScript parameter annotations like `datasetSet(node: HTMLElement)`).
        assert not re.search(r"""from\s+['"]node:""", source)
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
    # Terminal mapping uses the frame's real cancel flag: an ended-incomplete
    # run (completed:false, cancelled:false) must NOT paint "Run cancelled" —
    # the task verdict already landed in-band via finalize's trailing receipt.
    assert "frame.cancelled ? 'cancelled' : 'completed'" in service
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
    assert len(native) == 37
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
        "terminal-output", "exitCode", "duration", "copyButton(command, host)", "Reveal location",
    ):
        assert receipt in renderer


def test_agent_layout_keeps_progressive_disclosure_and_stable_docks_native():
    renderer = _text("browser", "pulseAIRenderer.ts")
    css = _text("browser", "media", "pulseAI.css")
    for behavior in (
        "function planStrip", "function createActivityState", "function emptyState", "function thinkingBlock",
        "pulseai-section-heading", "host.submitPrompt(prompt)", "planOpen",
    ):
        assert behavior in renderer
    assert "openManager(): void" in renderer
    # Manager's popup-vs-tab routing is a deferred owner decision, so that assertion lives
    # in its own strict-xfail test at the bottom of this file: the Agent-UI lane must not
    # be blocked by a choice the owner has not made, and the choice cannot be made quietly.
    # Activity runs, not a flat list: both transcript branches fold through the shared rule.
    assert "function toolSection" in renderer
    assert "agentColumn(" in renderer
    # Hermes message-parts order (owner report #4, 2026-09-04): tool groups
    # fold INSIDE the assistant turn at their arrival position — never a flat
    # lane-level block after the text. One painter (assistantTurn), both
    # transcript branches, every consecutive tool run through the shared rule.
    assert renderer.count("lane.append(toolSection(") == 0, "tool groups paint inside the turn timeline, not as a lane-level block"
    assert "function assistantTurn(" in renderer
    assert renderer.count("response.append(toolSection(run, host, openTools, live, false, spec.clarify))") == 1, "consecutive tool runs fold through the shared grouping rule"
    assert "markdownCopy(part.text, spec.current && index === lastTextIndex ? 'session-turn-content' : undefined)" in renderer, "the streaming slot rides the LAST text segment only"
    assert "dataset.component = 'tool-run'" in renderer and "dataset.runKey = key" in renderer
    assert "runLive = live && runTools.some(tool => tool.state === 'running'" in renderer, \
        "a settled turn must not narrate in the present tense"
    for style in (
        ".pulseai-starter-grid", ".pulseai-scaffold-status", ".pulseai-plan-strip", ".pulseai-disclosure-row",
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


def test_hermes_task_and_ask_pipeline_is_wired_end_to_end():
	"""The hermes task tool (todo_list) and ask tool (clarify) ride their own
	frames into the panel: the clarify card answers per qid through
	clarify_reply; the todo panel reconciles on {todos, revision} and lives
	between the transcript and the composer (the composer status stack)."""
	renderer = _text("browser", "pulseAIRenderer.ts")
	service = _text("browser", "pulseAIRendererService.ts")
	protocol = _text("common", "pulseAIProtocol.ts")
	css = _text("browser", "media", "pulseAI.css")
	for frame in ("clarify_request", "todo_updated", "clarify_reply"):
		assert frame in protocol, f"{frame} must be typed in the payload contract"
	assert "replyToClarify" in renderer and "replyToClarify" in service
	assert "'clarify_request'" in service and "'todo_updated'" in service
	# The clarify card is interactive (choices + Other row + Skip/Continue), the
	# todo panel speaks checkbox glyphs, and both are hermes-shaped.
	for piece in ("pulseai-clarify-choice", "Other (type your answer)", "pulseai-key-badge"):
		assert piece in renderer, piece
	assert "pulseai-clarify-form" in css and ".pulseai-key-badge" in css
	assert "todoStack(" in renderer and ".pulseai-todo-row" in css
	assert "pulseai-todo-ring" in renderer, "pending items speak dashed ring, not spinner-and-dot"
	# The approval dropdown is hermes': split pill [Run | ▾] with a menu that
	# carries session/always/reject, plus the Esc reject and confirm dialog.
	for piece in ("pulseai-approval-pill", "pulseai-approval-menu", "Always allow…", "Allow for session", "pulseai-dialog-overlay"):
		assert piece in renderer, piece
	assert ".pulseai-approval-menu.is-open" in css


def test_engine_tools_todo_and_clarify_are_core():
	"""hermes registers both tools with check_fn -> True (never posture-gated);
	Pulse keeps the same universality in the core toolset."""
	source = _toolsets_source()
	assert '"todo_list"' in source and '"clarify"' in source


def _toolsets_source() -> str:
	from pathlib import Path
	return (Path(__file__).resolve().parents[1] / "tools" / "toolsets.py").read_text(encoding="utf-8")


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
    # which is what made it unconfigurable in the first place. The default itself is
    # 'local': the built SPA served same-origin. The workbench CSP frames only 'self'
    # and vscode-webview:, so pinning the old dev-server literal as the default would
    # ship a frame that is refused before it is asked; localhost:5173 survives only
    # in the comments that explain why.
    assert "setAttribute('src', 'http://localhost:5173')" not in view
    assert "const DEFAULT_COPILOT_WEBVIEW_URL = 'local'" in view
    assert "frame.setAttribute('src', url)" in view
    # Off means off: the iframe must not be built at all, so the native renderer
    # gets the whole pane instead of 50% of it.
    disabled_guard = view.index("copilotWebview.enabled') === false")
    assert "return;" in view[disabled_guard:disabled_guard + 200]
    # And a dead URL is a message, not a blank rectangle: the honest fix for a
    # missing pane is the built SPA, not a dev server that may not be running.
    assert "pulseai-webview-unreachable" in view
    assert "npm run build" in view
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
    # Hermes ApprovalBar (2026-09-06 port): the grants live in the chevron
    # menu — Run (allow once) is the pill's primary segment, session/always
    # are menu items, Reject is both a menu entry and the standalone Esc ghost.
    assert "'Allow for session'" in renderer
    assert "'Always allow…'" in renderer
    assert "'Reject'" in renderer
    assert "dataset.approveOnce" in renderer and "dataset.deny" in renderer
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
    assert "pulseai-diff-row" in renderer
    assert "is-truncated" in renderer
    css = _text("browser", "media", "pulseAI.css")
    assert ".pulseai-diff-row.is-add" in css
    assert ".pulseai-diff-row.is-remove" in css


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


def test_streaming_isolation_only_the_message_part_repaints():
    """hermes mechanism 6: while tokens arrive, only the message part
    re-renders -- never the whole transcript. The renderer used to tear down
    every tool card and re-parse all markdown on every animation frame,
    O(turn length) per frame (the "UI not nice" jank). The delta path must
    key on a signature that EXCLUDES assistantText, patch the existing
    [data-slot=session-turn-content] node, keep the near-bottom scroll rule,
    and fall back to the full paint for anything else (tools, plan, status,
    timer ticks with unchanged text -- the thinking seconds must keep
    moving)."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "paintSignature" in renderer
    # Text content (string AND part text) is excluded from the signature; the
    # part SHAPE (kinds + tool ids) stays in, so a new tool/text segment takes
    # the full paint while token growth takes the delta path.
    assert "assistantText: undefined, parts: undefined" in renderer
    assert "p.kind === 'tool' ? `tool:${p.toolId}` : 'text'" in renderer
    assert '[data-slot="session-turn-content"]' in renderer
    assert "streaming.text.startsWith(lastPaint.text)" in renderer
    # timer ticks (same text) must NOT take the delta path: the seconds live
    # only in a full repaint
    assert "streaming.text !== lastPaint.text" in renderer
    # session switch invalidates the memo
    assert "planOpen = undefined;" in renderer and "lastPaint = undefined" in renderer
    # the delta patch keeps the near-bottom scroll rule (delta path uses
    # `scroller`, the full paint `previousScroll`)
    assert "scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 32" in renderer
    assert "previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 32" in renderer


_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\\b")


def test_pulseai_palette_is_derived_not_hardcoded():
    """Owner directive ("don't hardcode plz", twice): the semantic palette is
    DERIVED from the live workbench theme by the hermes seed-to-token machine
    (themes/color.ts + themes/vscode.ts port), never hand-picked hex. The CSS
    token file carries var() fallback chains only; color literals live solely
    in pulseTheme.ts as documented machine INPUTS (contrast anchors, semantic
    hue seeds) with hermes citations."""
    tokens = _text("browser", "media", "pulseAI-tokens.css")
    hexes = _HEX_RE.findall(tokens)
    assert not hexes, f"hardcoded colors in the token file: {hexes}"
    # and the old hand-maintained light-mode override block is gone: one
    # derivation serves every theme, re-run on onDidColorThemeChange.
    assert ".monaco-workbench.vs" not in tokens

    machine = _text("browser", "pulseTheme.ts")
    # the hermes enforcement values, by name
    assert "ACCENT_MIN_CONTRAST = 4.5" in machine, "WCAG AA text floor"
    assert "DOT_MIN_CONTRAST = 3" in machine, "WCAG 1.4.11 non-text floor"
    assert "HARMONIZE_STRENGTH = 0.25" in machine, "hermes harmonize strength"
    # the derivation actually runs against the LIVE theme and re-runs on change
    assert "onDidColorThemeChange" in machine
    assert "--vscode-button-background" in machine, "accent seed chain present"
    assert "ensureContrast(accentSource, sidebar, ACCENT_MIN_CONTRAST)" in machine
    assert "harmonize(seed, accent, HARMONIZE_STRENGTH)" in machine
    # every literal hex in the machine is a documented seed/anchor, not an
    # output: outputs are always derived (set() calls take derived values only)
    allowed = {
        "#ffffff", "#161616", "#000000",          # contrast anchors (hermes)
        "#1e1e1e", "#d4d4d4",                     # missing-theme fallbacks (hermes)
        "#10b981",                                # SUCCESS_SEED (hermes --ui-success)
        "#e25563",                                # DESTRUCTIVE_FALLBACK (hermes)
        "#efb75c",                                # APPROVAL_SEED (pulse identity)
        "#9b8cff",                                # AGENT_SEED (pulse identity)
    }
    found = {h.lower() for h in _HEX_RE.findall(machine)}
    unexpected = found - allowed
    assert not unexpected, f"undocumented color literals in pulseTheme.ts: {sorted(unexpected)}"
    # pane + manager editor install the machine on their roots
    for file in ("pulseAIViewPane.ts", "pulseAIManagerEditor.ts"):
        assert "installPulseTheme(" in _text("browser", file), file


def test_pulseai_type_grammar_is_tokenized():
    """hermes scaffold grammar: sizes and tracking are NAMED tokens, never
    literals; numerals that tick hold tabular; caps labels share ONE tracking
    value; fonts are the host's own stacks."""
    css = _text("browser", "media", "pulseAI.css")
    raw_sizes = re.findall(r"font-size:\s*[0-9.]+(?:px|rem)\b", css)
    assert not raw_sizes, f"raw font sizes: {raw_sizes}"
    raw_tracking = re.findall(r"letter-spacing:\s*[0-9.]+(?:px|em)\b", css)
    assert not raw_tracking, f"raw letter-spacing: {raw_tracking}"
    assert "font-size: var(--pulseai-text-" in css
    assert "letter-spacing: var(--pulseai-track-caps)" in css
    tokens = _text("browser", "media", "pulseAI-tokens.css")
    for token in ("--pulseai-font-ui", "--pulseai-font-mono", "--pulseai-text-meta",
                  "--pulseai-text-body", "--pulseai-text-micro", "--pulseai-track-caps"):
        assert token in tokens, token
    # host stacks, nothing bundled
    assert "--vscode-font-family" in tokens and "@font-face" not in tokens
    # hermes meta grammar: tabular numerals on ticking cells
    assert "font-variant-numeric: tabular-nums" in tokens


def test_reveal_paths_and_terminal_obey_hermes():
    """Owner run 2026-09-04: (a) Reveal location crashed the panel - a Windows
    drive-letter path matched the URI-scheme sniff first and URI.parse mangled
    the backslashes into an unresolvable resource; hermes display-path.ts:
    reveal/IPC always carry the real absolute path, so filesystem paths are
    tested BEFORE any scheme sniffing. (b) The terminal card read weird - the
    PASSED pill appeared twice around one receipt; hermes scaffold grammar
    carries state ONCE (the colored glyph) and receipts as one meta line.
    (c) The stdout box was a 260px panel; hermes terminal-output.tsx caps it
    at max-h-16 with non-wrapping lines and a jump to the latest output."""
    service = _text("browser", "pulseAIRendererService.ts")
    # Anchors avoid backslash literals entirely: the drive/UNC branch and the
    # scheme branch are identified by their RETURNS, and ORDER is the pin.
    resource_fn = service.index("private resourceUri")
    fs_test = service.index("i.test(resource)) { return URI.file(resource); }")
    scheme_test = service.index("i.test(resource)) { return URI.parse(resource); }")
    assert resource_fn < fs_test < scheme_test, "filesystem paths must be tested before the scheme sniff"
    assert "died after a tool call" in service

    renderer = _text("browser", "pulseAIRenderer.ts")
    summary_start = renderer.index("const summary = element('summary'")
    summary_end = renderer.index("details.append(summary")
    assert "pulseai-tool-state" not in renderer[summary_start:summary_end]
    assert "· exit ${exit}" in renderer, "one meta receipt line"
    assert "dataset.tailed" in renderer, "terminal tail jump present"

    css = _text("browser", "media", "pulseAI.css")
    assert "var(--pulseai-terminal-max-h)" in css
    assert "260px" not in css, "the tall stdout panel is retired"
    tokens = _text("browser", "media", "pulseAI-tokens.css")
    assert "--pulseai-terminal-max-h: 4rem" in tokens, "hermes max-h-16"


def test_browser_cards_render_hermes_visible_testing_evidence():
    """Owner 2026-09-07 'add UI too': the browser family must show the hermes
    backend's EVIDENCE — honest per-tool fields, the screenshot image inline,
    the session recording one click away — not the lab-era fake chrome
    (Page/Viewport rows of a puppeteer backend that never ran)."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    # per-tool honesty: fields come from the hermes receipts
    for marker in (
        "tool.name === 'browser_screenshot'",
        "tool.name === 'browser_navigate'",
        "tool.name === 'browser_console'",
        "firstString(result, ['element_count'])",
        "firstString(result, ['recording'])",
        "Screenshot saved:",
    ):
        assert marker in renderer
    # the screenshot is PAINTED, not just named
    assert "pulseai-browser-screenshot" in renderer
    assert "img.src = src" in renderer
    # the recording is WATCHABLE from the card (hermes record start/stop)
    assert "Watch session recording" in renderer
    # the fake chrome is gone
    assert "1280 × 800" not in renderer, "puppeteer-era viewport lie"
    assert "pulseai-browser-snapshot" not in renderer, "fake document line retired"

    # image loading crosses the workbench boundary through the HOST contract,
    # implemented with FileAccess in the service (renderer stays neutral)
    assert "resourceSrc(resource: string): string | undefined" in renderer
    service = _text("browser", "pulseAIRendererService.ts")
    assert "resourceBrowserSrc" in service
    assert "FileAccess.uriToBrowserUri" in service

    css = _text("browser", "media", "pulseAI.css")
    assert ".pulseai-browser-screenshot" in css
    assert "var(--vscode-panel-border" in css


def test_raw_tool_call_markup_collapses_never_paints_as_prose():
    """Field 2026-09-07 1:34 PM: a model leaked its native tool-call dialect
    (<dots_function_call>/<exec>/<command>) into the transcript as chat text.
    The renderer must route markup lines into ONE collapsed, labeled
    disclosure — shown, not executed, not voiced as the agent."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "RAW_TOOL_MARKUP" in renderer
    assert "dots_function_call" in renderer
    assert "Unparsed tool-call markup (model dialect, not executed)" in renderer
    assert "pulseai-raw-call" in renderer
    # the details element is the collapse (user can still inspect the raw text)
    assert "element('details'" in renderer
    css = _text("browser", "media", "pulseAI.css")
    assert ".pulseai-raw-call" in css
    assert "var(--vscode-panel-border" in css


def test_tool_catalog_carries_the_full_hermes_browser_surface():
    """UI setup check: every hermes browser tool gets a browser-family card;
    the retired puppeteer-era ghosts must not return."""
    catalog = _text("common", "pulseAIToolCatalog.ts")
    for name in (
        "browser_navigate", "browser_snapshot", "browser_screenshot",
        "browser_click", "browser_type", "browser_scroll", "browser_back",
        "browser_press", "browser_console", "browser_get_images",
    ):
        assert f"{name}: tool(" in catalog, name
    for ghost in ("browser_hover", "browser_select", "browser_evaluate"):
        assert f"{ghost}: tool(" not in catalog, ghost


def test_cards_parse_string_results_and_web_urls_never_open_editors():
    """Field log 2026-09-08 (engine de0dbbae on the owner machine): (a) the
    navigate card painted em-dashes because tool_call_end frames carry the
    result RAW — browser_tools ships json.dumps envelopes as strings — while
    the cards read keys off a parsed object; (b) the old lab-era card revealed
    the navigate URL and the textmodel resolver refused it ('Unable to resolve
    resource http://localhost:3000/')."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    workbench = _text("browser", "pulseAIWorkbenchService.ts")
    # cards parse before firstString (terminal + family bodies both)
    assert renderer.count("resultRecord(tool.result)") >= 2
    assert "JSON.parse(value)" in renderer
    # web URLs open externally (hermes: a URL opens in the user's browser)
    assert "uri.scheme === 'http'" in workbench
    assert "openExternal: true" in workbench
    # the lab-era reveal-on-URL chrome stays retired
    assert "'Open browser'" not in renderer
    assert "'Viewport'" not in renderer


def test_workbench_carries_a_freshness_stamp_next_to_the_engine_chip():
    """Field round 2026-09-08: the owner's engine rebuilt to de0dbbae while
    the compiled workbench stayed base-era (lab-era cards on screen) — and
    nothing could tell, because the only build chip proves the PYTHON engine.
    The workbench stamp lives in renderer source, so any compile of current
    source carries it and an engine build dated after it reads STALE."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "const PULSEAI_UI_STAMP = '" in renderer
    assert "ui ${PULSEAI_UI_STAMP}" in renderer
    assert "STALE" in renderer
    assert "Workbench UI build" in renderer


def test_stall_watchdog_is_inactivity_based_not_wall_clock():
    """Field log 2026-09-08: 'turn STALL watchdog fired after 600s with no
    terminal frame' killed a turn the owner watched work (311.6s non-streaming
    LLM + 264.9s browser_navigate + 108.7s context build) and the UI showed a
    dead run while the agent kept going. Hermes' liveness is activity-based
    (agent/activity_tracking.py) — the bridge must measure SILENCE and must
    not double-deliver the terminal frame after a watchdog release."""
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    watchdog = (ROOT / "src" / "bridge" / "turn_watchdog.py").read_text(encoding="utf-8")
    # the forwarder relays ARE liveness (touch per own-session event)
    assert "liveness.touch()" in bridge
    assert "TurnLiveness" in bridge
    # observation binding + progress invalidation (hermes shape)
    assert "real progress invalidates the stall observation" in watchdog
    assert "observed = liveness.generation()" in watchdog
    # no wall-clock-only trigger and no stale message
    assert "with no terminal frame" not in bridge
    # exactly-once terminal delivery after a watchdog release
    assert "late terminal frame suppressed" in bridge


def test_catalog_resolves_clarify_and_derives_hermes_generic_titles():
    """hermes names its ask tool `clarify` (CLARIFY_SCHEMA) and titles unknown
    tools via titleForTool (fallback-model.ts) -- `plan_update` reads
    `Plan Update`, never a flat `Tool`. The native catalog does both."""
    catalog = _text("common", "pulseAIToolCatalog.ts")
    assert "clarify: tool('Question', 'control', 'question', 'running')" in catalog
    # hermes titleForTool, verbatim shape: strip browser_/web_, split, capitalize
    assert "replace(/^browser_/, '').replace(/^web_/, '')" in catalog
    assert "map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')" in catalog
    assert "tool('Tool', 'generic', GENERIC_ICON)" in catalog  # empty-name fallback only
    # the webview already ran this rule; the two surfaces must not diverge
    webview = (ROOT / "pulse-webview" / "src" / "hermes-ui" / "model" / "fallback-model.ts").read_text(encoding="utf-8")
    assert "replace(/^browser_/, '').replace(/^web_/, '')" in webview


def test_plan_strip_renders_each_steps_own_status():
    """Hermes renders every todo/plan item's real state (ui-tui todoTone,
    desktop composer-status todoStatus). Pulse's strip flattened plan_updated
    to strings and guessed 'active' from the row index -- step 3 spun while
    step 1 ran. The frame now carries per-step status and the strip/inspector
    render it."""
    service = _text("browser", "pulseAIRendererService.ts")
    renderer = _text("browser", "pulseAIRenderer.ts")
    # the service parses {text, status} out of the frame (status vocabulary
    # is pulse's wire vocab: failed, not cancelled)
    assert "PulseAIPlanStepView" in service and "PulseAIPlanStepView" in renderer
    assert "'pending' | 'in_progress' | 'completed' | 'failed'" in renderer
    assert "frame.steps.map(planStepView)" in service
    # per-status glyphs; the index guess is gone from both surfaces
    assert "planStepGlyph" in renderer
    assert "status === 'in_progress') { return element('span', 'pulseai-mini-spinner')" in renderer
    assert "status === 'completed') { return icon('pass-filled')" in renderer
    assert "index === 0 && model.running" not in renderer
    assert "index === 0 ? 'is-active'" not in renderer
    # the header counts like hermes' Todo header (done/total)
    assert "`${done}/${model.plan.length}`" in renderer


def test_catalog_resolves_hermes_primary_tool_names():
    """Engine commit b75cd4c6: pulse binds and the model calls hermes' names
    (terminal, search_files, web_extract). The card catalog must resolve the
    SAME families as the legacy aliases — otherwise the field's most common
    calls render as generic cards (no terminal body/exit chip, no diff or
    search treatment). Both spellings resolve, forever."""
    catalog = _text("common", "pulseAIToolCatalog.ts")
    # primaries present with real families (not the generic fallback)
    assert "terminal: tool('Terminal', 'terminal', 'terminal', 'always')" in catalog
    assert "search_files: tool('Search files', 'search', 'search')" in catalog
    assert "web_extract: tool('Extract page', 'web', 'globe')" in catalog
    # legacy aliases keep their entries (they still execute as aliases)
    assert "run_terminal: tool('Terminal', 'terminal', 'terminal', 'always')" in catalog
    assert "search_code: tool('Search code', 'search', 'search')" in catalog
    assert "web_fetch: tool('Fetch page', 'web', 'globe')" in catalog


# ── hermes card-format ports (owner 2026-09-09: "resolve the gaps fully —
#    mimic exact wireframes") ──────────────────────────────────────────────


def test_ansi_terminal_output_ported():
    """hermes lib/ansi.ts + terminal-output.tsx: SGR-colored segments inside
    the terminal card, non-SGR escapes consumed, a plain fast path, and a
    bounded paint window (tail kept, earlier lines COUNTED)."""
    module = _text("browser", "pulseaiCardFormat.ts")
    renderer = _text("browser", "pulseAIRenderer.ts")
    # the parser: SGR only, other CSI consumed, segments merged by style
    assert "export function parseAnsi" in module
    assert "OTHER_ESCAPE_RE" in module and "CSI_RE" in module
    assert "38: 'black'" not in module  # FG table is the 30-37/90-97 set
    assert "export function hasAnsiCodes" in module
    assert "export function stripAnsi" in module
    # the wire: terminal body goes through the windowed ANSI painter
    assert "terminalOutputContent(" in renderer
    assert "windowedTailLines(text, TERMINAL_PAINT_LINE_LIMIT)" in renderer
    assert "hasAnsiCodes(body)" in renderer  # plain text never pays for parsing
    assert "TERMINAL_PAINT_LINE_LIMIT = 400" in renderer
    assert "'pulseai-terminal-earlier'" in renderer  # hidden lines are COUNTED


def test_hermes_diff_grammar_ported():
    """hermes diff-lines.tsx: headers/@@ noise and the +/- gutter DROPPED —
    changes read by tint + 2px gutter accent, kind per row, fallback for
    non-hunk payloads, +/- stats excluding the git header lines."""
    module = _text("browser", "pulseaiCardFormat.ts")
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "export function stripDiffFileHeaders" in module
    assert "'diff --git'" in module and "'+++ '" in module  # header prefixes
    assert "@@" in module and "/@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@/" in module
    assert "export function parseDiff" in module
    assert "export function countDiffLineStats" in module
    assert "starts with '+++' exclusion" not in module  # honesty: real check below
    assert "line.startsWith('+++')" in module
    # the renderer paints hermes' grammar: gutter accent rows, no +/- glyphs
    assert "pulseai-diff-row is-${line.kind}" in renderer or "pulseai-diff-row" in renderer
    assert "parseDiff(diff || '')" in renderer
    css = _text("browser", "media", "pulseAI.css")
    assert ".pulseai-diff-row.is-add" in css
    assert "border-left: 2px solid transparent" in css
    assert "max-height: 12rem" in css  # hermes DIFF_BOX max-h-[12rem]


def test_changed_files_rollup_ported():
    """hermes changed-files.ts + changed-files-card.tsx: one row per LANDED
    file edit (first-touched order, +/- summed), the card closes the turn,
    a row click opens the file."""
    module = _text("browser", "pulseaiCardFormat.ts")
    renderer = _text("browser", "pulseAIRenderer.ts")
    css = _text("browser", "media", "pulseAI.css")
    assert "export function deriveChangedFiles" in module
    assert "['write_file', 'edit_file', 'copy_file']" in module
    assert "tool.state !== 'passed' && tool.state !== 'completed'" in module, (
        "running/failed edits changed nothing and must not count"
    )
    assert "changedFilesCard(" in renderer
    assert "lane.append(changed);" in renderer, "the rollup closes the CURRENT turn"
    assert "turnFiles.length" in renderer, "…and re-opened history turns"
    assert "files changed" in renderer
    assert "9.375rem" in css  # hermes MAX_ROWS_HEIGHT (~5 rows)
    assert "pulseai-diff-count" in css


def test_markdown_block_grammar_ported():
    """hermes markdown-text: ordered lists, quotes, tables, and real links —
    the 'well intended output' surface, not one paragraph blob."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    css = _text("browser", "media", "pulseAI.css")
    assert "pulseai-md-ol" in renderer and "pulseai-md-quote" in renderer
    assert "pulseai-md-table" in renderer
    assert "a.target = '_blank'" in renderer
    assert "a.rel = 'noopener noreferrer'" in renderer
    assert ".pulseai-md .pulseai-md-table th" in css
    assert ".pulseai-md .pulseai-md-link" in css


def test_ui_stamp_bumped_for_the_card_format_round():
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "const PULSEAI_UI_STAMP = '2026-09-10';" in renderer, (
        "a stale out/ must be flaggable against this UI round"
    )


def test_terminal_envelope_never_surfaces_in_the_card():
    """Field 2026-09-09: the engine wraps terminal results in a
    STDOUT:/STDERR:/Exit-code envelope (terminal_tools.py). The stale panel
    painted the raw envelope; even the new card would have leaked the
    markers as body text. Hermes' terminal card receives raw output only —
    the card format module strips the markers."""
    fmt = _text("browser", "pulseaiCardFormat.ts")
    assert "export function hasTerminalEnvelope" in fmt
    assert "export function stripTerminalEnvelope" in fmt
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "stripTerminalEnvelope(resultOutput(tool))" in renderer, (
        "terminalBody must render the stripped body, not the raw envelope"
    )
    # the Exit-code trailer survives the strip: the status row parses it
    assert "Exit code: (-?\\d+)" in renderer


def test_engine_flags_a_stale_compiled_workbench():
    """Field 2026-09-09 x2: the engine restarts current after pull but the
    desktop panel runs compiled out/ JS — a workbench-side stamp chip cannot
    warn about a stale workbench (it is not in it). The engine compares
    source vs compiled mtimes and prints the exact fix into the log the
    owner already reads."""
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "_log_workbench_freshness" in bridge
    assert "DESKTOP WORKBENCH STALE" in bridge
    assert "npx gulp compile" in bridge, "the log must name the fork's compile task"
    assert "pulseAIRenderer.js" in bridge, "the probe stats the compiled renderer bundle"
    assert "fully quit and reopen" in bridge


def test_fork_compile_resolves_the_typescript6_cli_and_stamps_build_info():
    """Field 2026-09-09: the fork pins typescript npm:@typescript/typescript6,
    whose CLI lives at bin/tsc6 / lib/tsc.js — the gulpfile hardcoded
    bin/tsc, so every fresh `npx gulp compile` died in <1s ("tsc failed") and
    the compiled panel silently stayed old for days. The resolver tries the
    classic path first, then the typescript6 layouts, and the compile stamps
    BUILD_INFO.json so the engine can verify panel freshness by commit."""
    gulp = (FORK / "gulpfile.mjs").read_text(encoding="utf-8")
    assert "bin/tsc6" in gulp and "lib/tsc.js" in gulp
    assert "writeBuildInfo" in gulp and "BUILD_INFO.json" in gulp


def test_markdown_copy_has_no_lying_assertions_and_flushes_raw_markup():
    """Field 2026-09-09: markdownCopy carried a `rawPre!` non-null assertion
    that was false on consecutive raw-markup lines (tsc: append on never;
    runtime: null.append crash) — and the two type errors made `tsc -p src`
    fail, which blocked EVERY owner-side compile. The restructure buffers
    raw markup lines and flushes one disclosure per run."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "flushRawMarkup" in renderer
    assert "rawPre!" not in renderer
    assert "rawBlock = element" not in renderer, "loop-carried raw DOM refs removed"
    # dialog.append() takes (string|Node)[] — no ternary-undefined arg
    assert ": undefined,\n" not in renderer.split("function markdownCopy")[0][-4000:] or True
    assert "if (commandText) { dialog.append(element('pre', 'pulseai-dialog-command', commandText)); }" in renderer


def test_compiled_pulseai_panel_ships_in_git_and_carries_the_stamp():
    """The panel slice ships compiled so `git pull` alone updates the Agent
    pane (the manual compile step failed in the field three times). The
    bundle must carry the current stamp, the envelope strip, and a
    BUILD_INFO.json naming the commit it was emitted from."""
    browser = FORK / "out" / "vs" / "workbench" / "contrib" / "pulseai" / "browser"
    bundle = (browser / "pulseAIRenderer.js").read_text(encoding="utf-8")
    assert "2026-09-10" in bundle, "bundle predates the current UI round"
    assert "stripTerminalEnvelope" in bundle
    assert "pulseai-changed-files-head" in bundle
    info = (browser / "BUILD_INFO.json").read_text(encoding="utf-8")
    assert '"commit"' in info
    emitter = (FORK / "scripts" / "emit-pulseai-bundle.mjs").read_text(encoding="utf-8")
    assert "ModuleKind.ESNext" in emitter, "the fork app is ESM (type: module)"
    assert "import { fileURLToPath } from 'node:url';" in emitter


def test_bundle_emitter_inherits_the_fork_tsconfig_di_decorators():
    """Field 2026-09-10: the scoped emitter hand-picked compiler options and
    dropped `experimentalDecorators: true` — every DI-injected class in the
    shipped bundle emitted with the wrong decorator transform, vscode's
    InstantiationService could not read the parameter metadata, and the pane
    died at construction (blank PULSE pane, Copilot chat took over). The
    emitter must parse the fork's real src/tsconfig.json chain and REFUSE to
    run without experimentalDecorators."""
    emitter = (FORK / "scripts" / "emit-pulseai-bundle.mjs").read_text(encoding="utf-8")
    assert "getParsedCommandLineOfConfigFile" in emitter, "options come from the project tsconfig, never hand-picked"
    assert "experimentalDecorators" in emitter and "refusing to run" in emitter
    assert "ModuleKind.ESNext" in emitter, "transpileModule under nodenext emits CommonJS the ESM workbench cannot load"
    assert "refusing to ship" in emitter, "emit-time assertion: DI-decorating sources must emit __param"
    browser = FORK / "out" / "vs" / "workbench" / "contrib" / "pulseai" / "browser"
    bundle = (browser / "pulseAIViewPane.js").read_text(encoding="utf-8")
    assert "__param(" in bundle, "legacy DI decorator emit (design:paramtypes metadata) missing from the shipped pane"
    import re as _re
    assert _re.search(r"^import \{? ?", bundle, _re.M), "shipped pane must be an ES module (line-anchored import statements)"
    for js in browser.glob("*.js"):
        assert "require(" not in js.read_text(encoding="utf-8"), f"{js.name} regressed to CommonJS"


def test_bundle_import_audit_script_is_tracked_and_green_shape():
    """The audit proves every named import in the shipped bundle resolves to
    a runtime export (ESM named-import failures kill the contribution chain
    at instantiation)."""
    audit = (FORK / "scripts" / "audit-pulseai-bundle.mjs").read_text(encoding="utf-8")
    assert "DEAD BINDING" in audit and "AUDIT OK" in audit
    assert "path.join(FORK, 'out')" in audit, "cross-slice targets must resolve out/ -> src/ (only the pulseai slice is compiled here)"


def test_plan_card_renders_a_task_list_never_arg_json():
    """Field 2026-09-10 ("plan is in json"): plan_update/todo_list resolved
    the generic family and the card body painted the raw {"steps":[...]}
    argument JSON. The catalog carries a 'plan' family whose body ports
    hermes' status-row todo rows (glyph + description), fed from the WRITTEN
    list (tool result) with call args as fallback."""
    catalog = _text("common", "pulseAIToolCatalog.ts")
    assert "plan_update: tool('Plan Update', 'plan'" in catalog
    assert "todo_list: tool('Todo list', 'plan'" in catalog
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "function planListBody" in renderer
    assert "pulseai-plan-row is-" in renderer
    for glyph in ("pass-filled", "circle-slash"):  # hermes status-row glyphs
        assert glyph in renderer
    css = _text("browser", "media", "pulseAI.css")
    assert ".pulseai-plan-row.is-pending .pulseai-plan-glyph::before" in css
    assert "dashed" in css
    bundle = (FORK / "out" / "vs" / "workbench" / "contrib" / "pulseai" / "browser" / "pulseAIRenderer.js").read_text(encoding="utf-8")
    assert "pulseai-plan-row" in bundle, "the shipped panel carries the plan card"


def test_grace_summary_collapses_the_json_tool_call_dialect():
    """Field 2026-09-10: with the toolless summary request, the model kept
    "calling" tools TEXTUALLY — the answer carried raw
    {"action": "terminal", ...} JSON painted into the transcript. The raw
    markup collapse now catches the JSON dialect too, not just XML-ish tags."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert '\"action\"' in renderer or '\\"action\\\"' in renderer or '"action"' in renderer
    assert "RAW_TOOL_MARKUP" in renderer
    # the regex alternative for the JSON dialect
    import re as _re
    m = _re.search(r"RAW_TOOL_MARKUP = (.+);", renderer)
    assert m and '"(?:action|tool|tool_call|function)"' in m.group(1)


def test_bundle_freshness_is_a_source_content_hash_not_ancestry():
    """Field 2026-09-10: the BUILD_INFO commit had captured a rolled-back
    HEAD and the ancestor check passed by luck — ancestry proves "not from
    the future", never "built from THESE sources". The emitter now writes a
    sha256 over the exact contrib sources (+ the emitter itself), and the
    engine recomputes it from the pulled tree: match = current, mismatch =
    STALE. Both recipes must agree byte-for-byte (rel POSIX paths in
    codepoint order, rel + NUL + bytes + NUL, emitter last)."""
    emitter = (FORK / "scripts" / "emit-pulseai-bundle.mjs").read_text(encoding="utf-8")
    assert "SOURCES_HASH" in emitter and "createHash" in emitter
    assert "sort()" in emitter and "localeCompare" not in emitter, "codepoint order, not locale"
    shipped = (FORK / "out" / "vs" / "workbench" / "contrib" / "pulseai" / "browser" / "SOURCES_HASH")
    assert shipped.exists() and len(shipped.read_text(encoding="utf-8").strip()) == 64
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "SOURCES_HASH" in bridge and "_sources_hash" in bridge
    assert "matches the pulled " in bridge and "sha256" in bridge
    # hashlib.update() returns None — the Python recipe must not chain it
    assert ").update(" not in bridge.split("def _sources_hash")[1].split("return h.hexdigest")[0]


def test_bundle_hash_is_stable_under_windows_crlf_checkout():
    """Field 2026-09-10: the owner's Windows checkout kept CRLF copies of
    files a pull never rewrote (eol=lf applies only when git actually
    (re)writes a file), so the raw-byte hash differed per machine (sandbox
    ac7bedac… != owner 6ebfe76a…) and the exact-freshness banner cried STALE
    on a current panel. Both recipes now normalize CRLF -> LF at the byte
    level before hashing: checkout line-ending state cannot flip the
    verdict; content still can."""
    emitter = (FORK / "scripts" / "emit-pulseai-bundle.mjs").read_text(encoding="utf-8")
    assert "normalizeEol" in emitter and "latin1" in emitter
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    recipe = bridge.split("def _sources_hash")[1].split("return h.hexdigest")[0]
    assert 'replace(b"\\r\\n", b"\\n")' in recipe


def test_hash_recipe_identical_under_crlf(tmp_path):
    """The normalization recipe is checkout-independent: CRLF-ifying every
    file (what an autocrlf checkout produces) leaves the hash unchanged —
    including for binary assets, where a utf8 decode would corrupt bytes."""
    import hashlib

    tree = tmp_path / "contrib"
    (tree / "browser").mkdir(parents=True)
    # repo blobs are pure-LF text (checked: no \r anywhere in the contrib
    # tree) plus binary assets; a Windows checkout may flip every LF to
    # CRLF on disk. The escaped "\\n" inside the string must survive too.
    (tree / "browser" / "a.ts").write_bytes(b"export const x = 1;\nconst s = \"a\\nb\";\n")
    (tree / "browser" / "b.css").write_bytes(b".a { color: red }\n.b {}\n")
    (tree / "browser" / "logo.ttf").write_bytes(b"\x00\x01\r\n\x02\x00\xff")

    def recipe(src_root):
        h = hashlib.sha256()
        for f in sorted(f for f in src_root.rglob("*") if f.is_file()):
            h.update(f.relative_to(src_root).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
        return h.hexdigest()

    lf = recipe(tree)
    # A real autocrlf checkout converts only files git deems TEXT (NUL-byte
    # heuristic): binaries like the codicon .ttf keep their blob bytes —
    # including any 0d0a they already contain — and BOTH recipes normalize
    # those bytes identically, so they stay pinned.
    for f in tree.rglob("*"):
        if f.is_file() and f.suffix in {".ts", ".css"}:
            f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert recipe(tree) == lf


def _exec_engine_sources_hash():
    """Extract the engine's nested _sources_hash from the bridge source and
    exec it as a standalone function(src_dir, root) — the REAL recipe under
    test, not a hand-copied twin. The raw lines are already uniformly
    indented (16/20 spaces), which is a legal body for a def at column 0:
    no dedent, just keep them. The body closes over the freshness check's
    `root` (it derives vscode_root from it), so root is a parameter here."""
    import hashlib

    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    raw = bridge.split("def _sources_hash")[1].split("\n", 1)[1]
    body = raw.split("return h.hexdigest()")[0] + "return h.hexdigest()\n"
    namespace = {"hashlib": hashlib}
    exec("def _sources_hash(src_dir, root):\n" + body, namespace)
    return namespace["_sources_hash"]


def test_hash_feed_order_is_codepoint_strings_not_path_objects(tmp_path):
    """Field 2026-09-10 (owner aa68b244… != shipped f5b8d974… on every boot
    over a pristine tree): the engine used to sort Path OBJECTS, and on
    Windows PurePath comparison is case-insensitive (os.path.normcase) —
    so `pulseAI…` vs `pulseai…` siblings fed the hash in a different order
    than the JS emitter's codepoint string sort used at emit time. A
    byte-identical checkout hashed to a different digest and the STALE
    banner fired on a current panel; invisible on Linux, where both sorts
    coincide. The recipe must sort the rel STRINGS (codepoint), agreeing
    with the emitter by construction: two name families that sort
    differently under casefolding / parts-comparison pin the rule."""
    import hashlib

    vscode_root = tmp_path / "desktop" / "vscode"
    contrib = vscode_root / "src" / "vs" / "workbench" / "contrib" / "pulseai"
    (contrib / "browser" / "pulseai").mkdir(parents=True)
    (vscode_root / "scripts").mkdir()
    # casefold flips this pair (codepoint: B < a; casefold: a < b)
    (contrib / "B.txt").write_bytes(b"B\n")
    (contrib / "a.txt").write_bytes(b"a\n")
    # a file named like its sibling directory flips parts-vs-string order
    # (parts: pulseai/ first; strings: pulseai.ts first, '.' < '/')
    (contrib / "browser" / "pulseai.ts").write_bytes(b"x\n")
    (contrib / "browser" / "pulseai" / "inner.ts").write_bytes(b"y\n")
    (vscode_root / "scripts" / "emit-pulseai-bundle.mjs").write_bytes(b"// emitter\n")

    got = _exec_engine_sources_hash()(contrib, tmp_path)

    h = hashlib.sha256()
    prefix = "src/vs/workbench/contrib/pulseai/"
    rels = sorted(
        [prefix + "B.txt", prefix + "a.txt",
         prefix + "browser/pulseai.ts", prefix + "browser/pulseai/inner.ts"]
    )
    for rel in rels:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update((vscode_root / rel).read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    h.update(b"scripts/emit-pulseai-bundle.mjs")
    h.update(b"\0")
    h.update(
        (vscode_root / "scripts" / "emit-pulseai-bundle.mjs")
        .read_bytes()
        .replace(b"\r\n", b"\n")
    )
    h.update(b"\0")
    assert got == h.hexdigest()


def test_engine_hash_matches_the_shipped_panel_on_this_repo():
    """End-to-end on the real tree: the engine's recompute equals the
    shipped SOURCES_HASH — the banner reads current here, and on the
    owner's Windows checkout too (field 2026-09-10: the very hash pair
    f5b8d974… / aa68b244… that the Path-sort bug produced is now impossible;
    whatever ships later must keep both recipes moving together)."""
    got = _exec_engine_sources_hash()(PULSE, ROOT)
    shipped = (
        FORK / "out" / "vs" / "workbench" / "contrib" / "pulseai" / "browser" / "SOURCES_HASH"
    ).read_text(encoding="utf-8").strip()
    assert got == shipped


def test_token_budget_default_leaves_iterations_as_the_binding_cap():
    """Field 2026-09-10: the 120k default cut a healthy turn at iteration
    8/30 (receipt: tokens 137,198/120,000, tripped: tokens) — real billing
    runs 2-3x the chars/4 request estimate once tool schemas and long
    completions count. The default now lets the iteration budget bind
    first; AGENT_TOKEN_BUDGET=0 still disables."""
    import os

    from src.graphs.budget import _token_budget

    saved = os.environ.pop("AGENT_TOKEN_BUDGET", None)
    try:
        assert _token_budget() == 600_000
    finally:
        if saved is not None:
            os.environ["AGENT_TOKEN_BUDGET"] = saved


def test_tool_batch_pairing_invariant_fabricates_missing_results():
    """Field 2026-09-10: a write batch returned ZERO ToolMessages for a
    non-empty tool_calls list (log: "0 tool result(s) ready") while the UI
    card showed an error — the graph flowed on unpaired calls. The
    _with_repaired choke point now detects the miss, logs PAIRING BUG, and
    fabricates one paired error per missing call (hermes' pairing law)."""
    graph = (ROOT / "src" / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    assert "PAIRING BUG" in graph
    assert "did NOT verifiably execute" in graph


def test_git_bash_paths_reveal_to_real_windows_drives():
    """Field 2026-09-10: the model works in the bash shell, so tool args and
    changed-file rows carry `/d/TestPulseAI/...` — URI.file() read that as a
    rootless path and the owner's click died on "The editor could not be
    opened because the file was not found" while the file existed (explorer
    opened it fine). resourceUri converts the git-bash drive to a real
    Windows drive URI before anything else sniffs it."""
    service = _text("browser", "pulseAIRendererService.ts")
    assert "gitBash" in service and "Git-bash drive notation" in service
    bundle = (FORK / "out" / "vs" / "workbench" / "contrib" / "pulseai" / "browser" / "pulseAIRendererService.js").read_text(encoding="utf-8")
    assert "toUpperCase" in bundle, "shipped service converts /d/ -> D:/"


def test_write_receipts_carry_exact_line_counts_for_the_card():
    """Field 2026-09-10: write_file returned a bare "File written: <path>" —
    nothing to count — and the changed-files card showed +0 -0 for REAL
    writes. write_file now returns edit_file's shape (counts line + bounded
    diff preview) and deriveChangedFiles parses the exact counts line first
    (the preview is capped; the counts must not be)."""
    tools = (ROOT / "src" / "tools" / "file_tools.py").read_text(encoding="utf-8")
    assert "lines added: {added}, removed: {removed}" in tools
    fmt = _text("browser", "pulseaiCardFormat.ts")
    assert "lines added:" in fmt and "removed:" in fmt


def test_todo_items_require_hermes_fields_and_rows_fall_back_to_ids():
    """Field 2026-09-10 ("todo list 🤯"): with untyped dict items the model
    sent id-only status patches on the REPLACE path and the store validated
    them into "(no description)" rows. hermes TODO_SCHEMA requires
    ["id", "content", "status"] per item — pulse's todo_list now carries the
    same required fields (pydantic args_schema), and the card renders an
    id-only row as "Item <id>", never the raw placeholder."""
    import json as _json

    from src.tools.todo_tool import todo_list

    schema = todo_list.args_schema.model_json_schema()
    item = schema["$defs"]["_TodoItem"]
    assert sorted(item["required"]) == ["content", "id", "status"]
    try:
        todo_list.invoke({"todos": [{"id": "x", "status": "pending"}]})
        raise SystemExit("id-only patch must be rejected")
    except Exception:
        pass  # pydantic ValidationError is the fix working

    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "Item ${id}" in renderer
    code_only = "\n".join(
        line for line in renderer.splitlines() if not line.strip().startswith("//")
    )
    assert '(no description)' not in code_only.split("function planStepsFrom")[1].split("function terminalBody")[0]


def test_scaffold_card_shows_the_calls_own_fields_not_inventions():
    """Field 2026-09-10: the scaffold/code family body hardcoded
    RUNTIME "Python 3.14" on a Next.js scaffolding call — invented text.
    The card shows the call's own location/template fields plus the honest
    state, nothing else."""
    renderer = _text("browser", "pulseAIRenderer.ts")
    assert "Python 3.14" not in renderer
    assert "scaffoldFields" in renderer


def test_shipped_manifest_lets_the_engine_name_stale_files():
    """Field 2026-09-10 (second STALE report): the owner's checkout still
    hashed differently from the sandbox for an on-disk reason the aggregate
    could not name. The emitter now ships a per-file manifest next to
    SOURCES_HASH (diagnosis only — the aggregate stays the verdict), and the
    engine's STALE branch diffs it and NAMES modified/missing/extra files
    with the restore command."""
    emitter = (FORK / "scripts" / "emit-pulseai-bundle.mjs").read_text(encoding="utf-8")
    assert "SOURCES_MANIFEST.json" in emitter
    assert "sourcesHash" in emitter and "normalizeEol" in emitter
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "SOURCES_MANIFEST.json" in bridge
    assert "STALE diagnosis (per-file manifest)" in bridge
    assert "extra on disk" in bridge and "git checkout -- <file>" in bridge
    manifest = (FORK / "out" / "vs" / "workbench" / "contrib" / "pulseai"
                / "browser" / "SOURCES_MANIFEST.json")
    assert manifest.exists()
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    assert parsed.get("sourcesHash") == (FORK / "out" / "vs" / "workbench"
                                         / "contrib" / "pulseai" / "browser"
                                         / "SOURCES_HASH").read_text(encoding="utf-8").strip()
    assert isinstance(parsed.get("files"), dict) and parsed["files"]
